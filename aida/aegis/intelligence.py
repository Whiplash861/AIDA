from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from aida.aegis.explanations import baseline_observations, explain_sensor_limitations

from aida.aegis.learning.models import LearningAssessment
from aida.aegis.models import (
    AegisCaseStatus,
    AegisHypothesis,
    BaselineDelta,
    CoverageVector,
    RiskVector,
    SecuritySnapshot,
)
from aida.security.models import ProviderDetection, SecuritySeverity
from aida.security.threat_analysis import (
    SignatureState,
    ThreatAnalysisRecord,
    ThreatAssessmentLevel,
)


_SUSPICIOUS_PATH_TOKENS = (
    "\\appdata\\local\\temp\\",
    "\\appdata\\roaming\\",
    "\\downloads\\",
    "\\temp\\",
)


def select_candidate_paths(
    *,
    snapshot: SecuritySnapshot,
    delta: BaselineDelta,
    detections: Iterable[ProviderDetection],
    limit: int = 8,
) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for detection in detections:
        if detection.file_path is not None:
            _append_path(candidates, Path(detection.file_path))
    for item in (delta.new_persistence if delta.baseline_available else snapshot.persistence):
        target = _extract_existing_target(item.target)
        if target is not None:
            _append_path(candidates, target)
    new_process_keys = {_path_key(value) for value in delta.new_process_paths}
    for process in snapshot.processes:
        if not process.executable:
            continue
        if delta.baseline_available and _path_key(process.executable) not in new_process_keys:
            continue
        lowered = process.executable.lower()
        if (
            any(token in lowered for token in _SUSPICIOUS_PATH_TOKENS)
            or process.listening_endpoints
            or process.remote_endpoints
        ):
            _append_path(candidates, Path(process.executable))
        if len(candidates) >= limit:
            break
    return tuple(path for path in candidates if path.is_file())[:limit]


def assess_risk(
    *,
    detections: tuple[ProviderDetection, ...],
    analyses: tuple[ThreatAnalysisRecord, ...],
    delta: BaselineDelta,
    snapshot: SecuritySnapshot,
    learning: LearningAssessment | None = None,
) -> RiskVector:
    likelihood, impact = 0.05, 0.10
    activity, persistence, exposure = 0.05, 0.05, 0.05
    active = [
        item for item in detections if item.metadata.get("is_active") is not False
    ]
    if active:
        likelihood = 0.88
        activity = 0.65
        for detection in active:
            if detection.severity is SecuritySeverity.CRITICAL:
                likelihood, impact = max(likelihood, 0.98), max(impact, 1.0)
            elif detection.severity is SecuritySeverity.HIGH:
                likelihood, impact = max(likelihood, 0.96), max(impact, 0.86)
            elif detection.severity is SecuritySeverity.MODERATE:
                impact = max(impact, 0.58)
            elif detection.severity is SecuritySeverity.MINOR:
                impact = max(impact, 0.32)
            else:
                impact = max(impact, 0.20)
    for analysis in analyses:
        likelihood = max(likelihood, _assessment_likelihood(analysis))
        if analysis.process_observations:
            activity = max(activity, 0.75)
        if analysis.persistence_observations:
            persistence = max(persistence, 0.80)
        if any(item.network_endpoints for item in analysis.process_observations):
            exposure = max(exposure, 0.75)
        impact = max(impact, _impact_from_analysis(analysis))
    if delta.new_persistence:
        persistence = max(
            persistence,
            min(0.85, 0.30 + len(delta.new_persistence) * 0.12),
        )
        likelihood = max(likelihood, 0.22)
    if delta.new_listeners:
        exposure = max(
            exposure,
            min(0.75, 0.22 + len(delta.new_listeners) * 0.08),
        )
    if snapshot.provider_health.active is False:
        impact = max(impact, 0.65)
        likelihood = max(likelihood, 0.30)

    # Learned anomaly is deliberately bounded advisory evidence. It can raise
    # investigation priority, but cannot by itself create provider-confirmed or
    # high-confidence malicious status and cannot directly justify remediation.
    if (
        learning is not None
        and not learning.warmup
        and learning.confidence >= 0.35
        and learning.anomaly_score >= 0.55
    ):
        learned_weight = learning.anomaly_score * learning.confidence
        likelihood = max(
            likelihood,
            min(0.42, 0.16 + learned_weight * 0.26),
        )
        activity = max(
            activity,
            min(0.36, 0.12 + learned_weight * 0.22),
        )

    urgency = max(
        likelihood * max(impact, 0.25),
        activity * 0.70,
        persistence * likelihood,
    )
    return RiskVector(
        likelihood=_clamp(likelihood),
        impact=_clamp(impact),
        activity=_clamp(activity),
        persistence=_clamp(persistence),
        exposure=_clamp(exposure),
        urgency=_clamp(urgency),
    )


def assess_coverage(
    *,
    snapshot: SecuritySnapshot,
    baseline: object | None,
    candidate_count: int,
    analyzed_count: int,
) -> CoverageVector:
    errors = set(snapshot.sensor_errors)
    provider = 1.0 if all(value is True for value in (snapshot.provider_health.available, snapshot.provider_health.active, snapshot.provider_health.healthy)) else 0.0
    return CoverageVector(
        provider=_clamp(provider),
        processes=(0.0 if "process_snapshot_unavailable" in errors else 0.5 if any("process" in value for value in errors) else 1.0),
        persistence=(
            0.0 if any("persistence" in value for value in errors) else 0.75
        ),
        network=(0.0 if "network_snapshot_unavailable" in errors else 0.5 if any("network" in value for value in errors) else 0.95),
        baseline=(1.0 if baseline is not None else 0.0),
        file_analysis=(
            0.0
            if candidate_count == 0
            else _clamp(analyzed_count / candidate_count)
        ),
    )


def build_hypotheses(
    *,
    detections: tuple[ProviderDetection, ...],
    analyses: tuple[ThreatAnalysisRecord, ...],
    delta: BaselineDelta,
    learning: LearningAssessment | None = None,
) -> tuple[AegisHypothesis, ...]:
    hypotheses: list[AegisHypothesis] = []
    active = [
        item for item in detections if item.metadata.get("is_active") is not False
    ]
    if active:
        hypotheses.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title=("Antivirus reports an active threat" if any(item.metadata.get("is_active") is True for item in active)
                    else "Antivirus threat finding has unresolved status"),
                category="malicious",
                confidence=max(
                    0.92,
                    max(
                        (_severity_confidence(item.severity) for item in active),
                        default=0.92,
                    ),
                ),
                evidence_for=tuple(
                    f"{item.source} reports {item.name} ({item.severity.name.lower()} severity); "
                    + ("the provider marks it active." if item.metadata.get("is_active") is True else "its current activity is not confirmed in this record.")
                    for item in active[:5]
                ),
                unresolved_questions=(
                    "Whether other affected files, programs or automatic-start entries remain outside this antivirus finding.",
                ),
            )
        )
    suspicious = [
        item
        for item in analyses
        if item.assessment
        in {
            ThreatAssessmentLevel.SUSPICIOUS,
            ThreatAssessmentLevel.LIKELY_MALICIOUS,
            ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS,
        }
    ]
    if suspicious and not active:
        hypotheses.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="File checks need further security review",
                category="malicious_candidate",
                confidence=max(item.confidence for item in suspicious),
                evidence_for=tuple(
                    f"{item.path.name}: {item.assessment.value.replace('_', ' ')}"
                    for item in suspicious[:5]
                ),
                evidence_against=(
                    "These file assessments are separate from a confirmed current antivirus finding; review their recorded facts and uncertainties.",
                ),
                unresolved_questions=(
                    "Whether a current antivirus scan of the affected file supports the local assessment.",
                ),
            )
        )
    signed_low = [
        item
        for item in analyses
        if item.assessment is ThreatAssessmentLevel.LOW_CONCERN
        and item.identity.signature_state is SignatureState.VALID
    ]
    if signed_low and not active:
        hypotheses.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="Signed files with low-concern assessments",
                category="benign_candidate",
                confidence=min(0.92, 0.60 + len(signed_low) * 0.06),
                evidence_for=tuple(
                    f"{item.path.name} has a valid digital signature and a low-concern local assessment."
                    for item in signed_low[:5]
                ),
                evidence_against=(
                    (
                        f"{len(delta.new_persistence)} automatic-start entry or entries differ from the saved comparison and still need explanation."
                    ),
                )
                if delta.new_persistence
                else (),
                unresolved_questions=(
                    "A valid digital signature does not prove that a file is safe; any observed change still needs to be compared with expected software activity.",
                ),
            )
        )

    if (
        learning is not None
        and not learning.warmup
        and learning.confidence >= 0.35
        and learning.anomaly_score >= 0.55
    ):
        hypotheses.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="Activity differs from AIDA's learned pattern",
                category="learned_anomaly",
                confidence=_clamp(
                    learning.anomaly_score * max(0.45, learning.confidence)
                ),
                evidence_for=learning.reasons[:4],
                evidence_against=(
                    "A difference from a learned pattern does not establish malware or authorize any action.",
                ),
                unresolved_questions=(
                    "Whether the antivirus findings, file checks or activity history explain the difference.",
                ),
            )
        )

    if delta.meaningful_change_count and not hypotheses:
        hypotheses.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="Changes from the approved saved comparison need review",
                category="unknown",
                confidence=min(
                    0.70, 0.30 + delta.meaningful_change_count * 0.03
                ),
                evidence_for=baseline_observations(delta),
                evidence_against=(
                    "A difference from a saved comparison does not by itself establish malicious activity.",
                ),
                unresolved_questions=(
                    "Whether the changes are explained by expected software or operating-system activity.",
                ),
            )
        )
    if not hypotheses:
        hypotheses.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="No threat conclusion established from these inputs",
                category="benign_current_state",
                confidence=0.82,
                evidence_for=(
                    "The supplied findings did not establish a current antivirus threat or a suspicious file assessment.",
                ),
                unresolved_questions=(
                    "This does not establish that every check completed or that the computer is free of threats; review the check limitations separately.",
                ),
            )
        )
    return tuple(hypotheses)


def escalation_for(risk: RiskVector, coverage: CoverageVector) -> str:
    if risk.likelihood >= 0.85 or risk.urgency >= 0.82:
        return "full_sweep_recommended"
    if risk.likelihood >= 0.55 and coverage.overall < 0.70:
        return "full_sweep_recommended"
    if risk.likelihood >= 0.35 or risk.persistence >= 0.55:
        return "targeted_investigation_recommended"
    if coverage.overall < 0.55:
        return "additional_evidence_recommended"
    return "no_escalation"


def case_status_for(
    detections: tuple[ProviderDetection, ...],
    risk: RiskVector,
    escalation: str,
) -> AegisCaseStatus:
    if any(item.metadata.get("is_active") is not False for item in detections):
        return AegisCaseStatus.THREAT_CONFIRMED
    if escalation in {
        "full_sweep_recommended",
        "targeted_investigation_recommended",
    }:
        return AegisCaseStatus.ACTION_PENDING
    if risk.overall >= 0.35:
        return AegisCaseStatus.MONITORING
    return AegisCaseStatus.ASSESSED


def remaining_uncertainty(
    *,
    snapshot: SecuritySnapshot,
    coverage: CoverageVector,
    analyses: tuple[ThreatAnalysisRecord, ...],
    candidate_count: int | None = None,
) -> tuple[str, ...]:
    notes: list[str] = []
    notes.extend(explain_sensor_limitations(snapshot.sensor_errors))
    if coverage.baseline < 0.5:
        notes.extend(baseline_observations({"baseline_available": False}))
    if coverage.provider < 1:
        if snapshot.provider_health.active is False:
            notes.append("The antivirus provider reports that it is not active. This is a protection-status finding, not a malware detection.")
        elif snapshot.provider_health.healthy is False:
            notes.append("The antivirus provider reports a problem with its protection status; the cause and effect still need review.")
        else:
            notes.append("The antivirus protection status was not fully verified in this check.")
    if candidate_count is not None and candidate_count > len(analyses):
        notes.append(f"AIDA selected {candidate_count} file(s) for review, but {candidate_count - len(analyses)} did not produce a completed analysis.")
    elif 0 < coverage.file_analysis < 1:
        notes.append("Some selected files could not be fully analyzed, so the file review is incomplete.")
    for analysis in analyses:
        notes.extend(analysis.remaining_uncertainty)
    if not notes:
        notes.append(
            "The assessment describes evidence observable during this scan and does not prove that no hidden threat exists."
        )
    return tuple(dict.fromkeys(notes))


def build_case_summary(
    *,
    risk: RiskVector,
    coverage: CoverageVector,
    detection_count: int,
    delta: BaselineDelta,
    snapshot: SecuritySnapshot | None = None,
    analyses: tuple[ThreatAnalysisRecord, ...] = (),
    detections: tuple[ProviderDetection, ...] | None = None,
    learning: LearningAssessment | None = None,
) -> str:
    observations: list[str] = []
    if detection_count:
        active_count = sum(item.metadata.get("is_active") is True for item in detections or ())
        if active_count:
            observations.append(f"The antivirus provider reports {active_count} active threat finding(s).")
        remaining = max(0, detection_count - active_count)
        if remaining:
            observations.append(f"This assessment also contains {remaining} antivirus threat finding(s) whose current activity needs review." if active_count
                else f"This assessment contains {remaining} antivirus threat finding(s); their current activity needs review.")
        observations.append("Review the affected items and current antivirus status before choosing a response.")
    else:
        flagged = sum(item.assessment in {ThreatAssessmentLevel.SUSPICIOUS, ThreatAssessmentLevel.LIKELY_MALICIOUS,
            ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS} for item in analyses)
        if flagged:
            observations.append(f"The file checks marked {flagged} reviewed file(s) for security review. This summary does not establish a current active antivirus threat.")
        elif risk.overall >= 0.50:
            observations.append("AIDA recommends reviewing the recorded activity; this recommendation alone does not establish a threat.")
        else:
            observations.append("This assessment has not established a confirmed threat. Check the recorded observations and any incomplete checks before drawing a conclusion.")
        associations = []
        for count, label in (
            (sum(bool(item.process_observations) for item in analyses), "with a running program"),
            (sum(any(process.network_endpoints for process in item.process_observations) for item in analyses), "with network connections"),
            (sum(bool(item.persistence_observations) for item in analyses), "with automatic-start entries"),
        ):
            if count:
                associations.append(f"{count} {label}")
        if associations:
            observations.append("Among the reviewed files, AIDA recorded " + ", ".join(associations) + ". Running, connecting to a network and starting automatically can all be normal software behavior.")
        if analyses and not flagged:
            observations.append("These file checks did not classify a reviewed file as suspicious or malicious; that is not a guarantee that it is safe.")
        if risk.overall >= .50 and not associations and not flagged and not (delta.baseline_available and delta.meaningful_change_count):
            observations.append("The risk score alone does not explain which observation caused the recommendation; the underlying records need review.")
    if snapshot is not None and snapshot.provider_health.active is False:
        observations.append("The antivirus provider reports that it is not active.")
    if delta.baseline_available and delta.meaningful_change_count:
        observations.extend(baseline_observations(delta))
    elif not delta.baseline_available:
        observations.extend(baseline_observations(delta))
    if learning is not None and not learning.warmup and learning.confidence >= .35 and learning.anomaly_score >= .55:
        observations.append("The learned activity pattern also differs from prior observations. That comparison does not establish malware.")
    if snapshot is not None and snapshot.sensor_errors:
        observations.append("Some checks did not complete or have incomplete history; see the recorded check limitations.")
    elif coverage.provider < 1 or coverage.processes < 1 or coverage.network < .95 or coverage.persistence < .75:
        observations.append("Some protection, program, network or automatic-start checks were incomplete or could not be verified.")
    return " ".join(observations)


def _append_path(output: list[Path], path: Path) -> None:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser().absolute()
    key = _path_key(str(resolved))
    if not any(_path_key(str(item)) == key for item in output):
        output.append(resolved)


def _extract_existing_target(raw: str) -> Path | None:
    raw_text = raw.strip()
    quoted = None
    if raw_text.startswith('"') and '"' in raw_text[1:]:
        quoted = raw_text.split('"', 2)[1]
    candidates = [item for item in (quoted, raw_text.strip('"')) if item]
    for candidate in candidates:
        expanded = os.path.expandvars(candidate).strip().strip('"')
        direct = Path(expanded)
        if direct.is_file():
            return direct
        parts = expanded.split()
        for index in range(len(parts), 0, -1):
            possible = Path(" ".join(parts[:index]).strip('"'))
            if possible.is_file():
                return possible
    return None


def _assessment_likelihood(record: ThreatAnalysisRecord) -> float:
    return _clamp(
        {
            ThreatAssessmentLevel.INSUFFICIENT_EVIDENCE: 0.15,
            ThreatAssessmentLevel.UNKNOWN: 0.25,
            ThreatAssessmentLevel.LOW_CONCERN: 0.08,
            ThreatAssessmentLevel.SUSPICIOUS: max(
                0.48, record.confidence * 0.75
            ),
            ThreatAssessmentLevel.LIKELY_MALICIOUS: max(
                0.75, record.confidence
            ),
            ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS: max(
                0.92, record.confidence
            ),
        }[record.assessment]
    )


def _impact_from_analysis(record: ThreatAnalysisRecord) -> float:
    text = " ".join(record.possible_impacts).lower()
    if any(token in text for token in ("ransom", "credential", "remote control")):
        return 0.90
    if any(token in text for token in ("persistence", "secondary payload", "data")):
        return 0.72
    return 0.45 if record.possible_impacts else 0.20


def _severity_confidence(severity: SecuritySeverity) -> float:
    if severity is SecuritySeverity.CRITICAL:
        return 0.99
    if severity is SecuritySeverity.HIGH:
        return 0.97
    if severity is SecuritySeverity.MODERATE:
        return 0.94
    return 0.92


def _path_key(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip())).lower()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
