from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from aida.aegis.models import (
    AegisCaseStatus,
    AegisHypothesis,
    BaselineDelta,
    CoverageVector,
    RiskVector,
    SecurityCase,
    SecuritySnapshot,
    utc_now,
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

    for item in delta.new_persistence:
        target = _extract_existing_target(item.target)
        if target is not None:
            _append_path(candidates, target)

    new_process_keys = {_path_key(value) for value in delta.new_process_paths}
    for process in snapshot.processes:
        if not process.executable:
            continue
        key = _path_key(process.executable)
        if key not in new_process_keys:
            continue
        lowered = process.executable.lower()
        if any(token in lowered for token in _SUSPICIOUS_PATH_TOKENS):
            _append_path(candidates, Path(process.executable))
        elif process.listening_endpoints or process.remote_endpoints:
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
) -> RiskVector:
    likelihood = 0.05
    impact = 0.10
    activity = 0.05
    persistence = 0.05
    exposure = 0.05

    active_detections = [
        item
        for item in detections
        if item.metadata.get("is_active") is not False
    ]
    if active_detections:
        likelihood = max(likelihood, 0.88)
        activity = max(activity, 0.65)
        for detection in active_detections:
            if detection.severity is SecuritySeverity.CRITICAL:
                likelihood = max(likelihood, 0.98)
                impact = max(impact, 1.0)
            elif detection.severity is SecuritySeverity.HIGH:
                likelihood = max(likelihood, 0.96)
                impact = max(impact, 0.86)
            elif detection.severity is SecuritySeverity.MEDIUM:
                impact = max(impact, 0.58)
            else:
                impact = max(impact, 0.32)

    for analysis in analyses:
        likelihood = max(likelihood, _assessment_likelihood(analysis))
        if analysis.process_observations:
            activity = max(activity, 0.75)
        if analysis.persistence_observations:
            persistence = max(persistence, 0.80)
        if any(item.network_endpoints for item in analysis.process_observations):
            exposure = max(exposure, 0.75)
        if analysis.possible_impacts:
            impact = max(impact, _impact_from_analysis(analysis))

    if delta.new_persistence:
        persistence = max(persistence, min(0.85, 0.30 + len(delta.new_persistence) * 0.12))
        likelihood = max(likelihood, 0.22)
    if delta.new_listeners:
        exposure = max(exposure, min(0.75, 0.22 + len(delta.new_listeners) * 0.08))
    if snapshot.provider_health.active is False:
        impact = max(impact, 0.65)
        likelihood = max(likelihood, 0.30)

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
    provider = 1.0 if snapshot.provider_health.available is True else 0.45
    if snapshot.provider_health.active is False:
        provider = 0.25
    processes = 0.45 if "process_snapshot_unavailable" in errors else 1.0
    persistence = (
        0.50 if "registry_persistence_unavailable" in errors else 0.92
    )
    network = 0.45 if "network_snapshot_unavailable" in errors else 0.95
    baseline_score = 1.0 if baseline is not None else 0.25
    if candidate_count == 0:
        file_analysis = 1.0
    else:
        file_analysis = analyzed_count / candidate_count
    return CoverageVector(
        provider=_clamp(provider),
        processes=_clamp(processes),
        persistence=_clamp(persistence),
        network=_clamp(network),
        baseline=_clamp(baseline_score),
        file_analysis=_clamp(file_analysis),
    )


def build_hypotheses(
    *,
    detections: tuple[ProviderDetection, ...],
    analyses: tuple[ThreatAnalysisRecord, ...],
    delta: BaselineDelta,
) -> tuple[AegisHypothesis, ...]:
    output: list[AegisHypothesis] = []
    active = [
        item
        for item in detections
        if item.metadata.get("is_active") is not False
    ]

    if active:
        output.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="Active provider-confirmed threat",
                category="malicious",
                confidence=max(
                    0.92,
                    max(
                        (_severity_confidence(item.severity) for item in active),
                        default=0.92,
                    ),
                ),
                evidence_for=tuple(
                    f"{item.source} reports {item.name} ({item.severity.name})."
                    for item in active[:5]
                ),
                evidence_against=(),
                unresolved_questions=(
                    "Whether related persistence, child processes, or secondary payloads remain outside the provider record.",
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
        output.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="Suspicious local activity without active provider confirmation",
                category="malicious_candidate",
                confidence=max(item.confidence for item in suspicious),
                evidence_for=tuple(
                    f"{item.path.name}: {item.assessment.value.replace('_', ' ')}"
                    for item in suspicious[:5]
                ),
                evidence_against=(
                    "The current provider snapshot does not report an active matching threat.",
                ),
                unresolved_questions=(
                    "Whether a targeted provider scan would confirm or reject the local assessment.",
                ),
            )
        )

    signed_low_concern = [
        item
        for item in analyses
        if item.assessment is ThreatAssessmentLevel.LOW_CONCERN
        and item.identity.signature_state is SignatureState.VALID
    ]
    if signed_low_concern and not active:
        output.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="Legitimate signed software change",
                category="benign_candidate",
                confidence=min(
                    0.92,
                    0.60 + len(signed_low_concern) * 0.06,
                ),
                evidence_for=tuple(
                    f"{item.path.name} has a valid signer and low-concern local assessment."
                    for item in signed_low_concern[:5]
                ),
                evidence_against=tuple(
                    f"{len(delta.new_persistence)} new persistence item(s) remain to be explained."
                    for _ in (0,)
                    if delta.new_persistence
                ),
                unresolved_questions=(
                    "Whether the observed change aligns with a recent installation or update event.",
                ),
            )
        )

    if delta.meaningful_change_count and not output:
        output.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="Unexplained baseline drift",
                category="unknown",
                confidence=min(0.70, 0.30 + delta.meaningful_change_count * 0.03),
                evidence_for=(
                    f"{delta.meaningful_change_count} security-relevant baseline change(s) were observed.",
                ),
                evidence_against=(
                    "No strong malicious evidence has been correlated yet.",
                ),
                unresolved_questions=(
                    "Whether the changes are explained by expected software or operating-system activity.",
                ),
            )
        )

    if not output:
        output.append(
            AegisHypothesis(
                hypothesis_id=uuid4().hex,
                title="No active compromise identified",
                category="benign_current_state",
                confidence=0.82,
                evidence_for=(
                    "No active provider detection or high-confidence local malicious assessment was correlated.",
                ),
                evidence_against=(),
                unresolved_questions=(
                    "Read-only observation cannot prove the absence of behavior that was not observable during this snapshot.",
                ),
            )
        )

    return tuple(output)


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
) -> tuple[str, ...]:
    notes: list[str] = []
    if snapshot.sensor_errors:
        notes.append(
            "One or more read-only security sensors returned incomplete coverage: "
            + ", ".join(snapshot.sensor_errors)
        )
    if coverage.baseline < 0.5:
        notes.append(
            "No established Aegis machine baseline was available for drift comparison."
        )
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
) -> str:
    if detection_count:
        return (
            f"Aegis correlated {detection_count} provider detection(s) with local machine evidence."
        )
    if risk.overall >= 0.50:
        return (
            "Aegis identified elevated security risk from correlated local evidence and baseline drift."
        )
    if delta.meaningful_change_count:
        return (
            f"Aegis reviewed {delta.meaningful_change_count} security-relevant baseline change(s) without confirming an active compromise."
        )
    return (
        f"Aegis found no active compromise in the observable evidence set; coverage confidence is {round(coverage.overall * 100)}%."
    )


def _append_path(output: list[Path], path: Path) -> None:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser().absolute()
    key = _path_key(str(resolved))
    if any(_path_key(str(item)) == key for item in output):
        return
    output.append(resolved)


def _extract_existing_target(raw: str) -> Path | None:
    text = raw.strip().strip('"')
    if not text:
        return None
    candidates = [text]
    if text.startswith('"') and '"' in text[1:]:
        candidates.insert(0, text.split('"', 2)[1])
    for candidate in candidates:
        expanded = os.path.expandvars(candidate).strip().strip('"')
        path = Path(expanded)
        if path.is_file():
            return path
        if " " in expanded:
            parts = expanded.split()
            for index in range(len(parts), 0, -1):
                possible = Path(" ".join(parts[:index]).strip('"'))
                if possible.is_file():
                    return possible
    return None


def _assessment_likelihood(record: ThreatAnalysisRecord) -> float:
    mapping = {
        ThreatAssessmentLevel.INSUFFICIENT_EVIDENCE: 0.15,
        ThreatAssessmentLevel.UNKNOWN: 0.25,
        ThreatAssessmentLevel.LOW_CONCERN: 0.08,
        ThreatAssessmentLevel.SUSPICIOUS: max(0.48, record.confidence * 0.75),
        ThreatAssessmentLevel.LIKELY_MALICIOUS: max(0.75, record.confidence),
        ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS: max(
            0.92, record.confidence
        ),
    }
    return _clamp(mapping[record.assessment])


def _impact_from_analysis(record: ThreatAnalysisRecord) -> float:
    text = " ".join(record.possible_impacts).lower()
    if any(token in text for token in ("ransom", "credential", "remote control")):
        return 0.90
    if any(token in text for token in ("persistence", "secondary payload", "data")):
        return 0.72
    if record.possible_impacts:
        return 0.45
    return 0.20


def _severity_confidence(severity: SecuritySeverity) -> float:
    if severity is SecuritySeverity.CRITICAL:
        return 0.99
    if severity is SecuritySeverity.HIGH:
        return 0.97
    if severity is SecuritySeverity.MEDIUM:
        return 0.94
    return 0.92


def _path_key(value: str) -> str:
    return os.path.normcase(os.path.normpath(value.strip())).lower()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
