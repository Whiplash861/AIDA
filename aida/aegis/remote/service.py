from __future__ import annotations

from collections.abc import Callable, Iterable

from aida.aegis.baseline import compare_snapshots
from aida.aegis.learning.features import extract_feature_vector
from aida.aegis.learning.service import AegisLearningService
from aida.aegis.models import SecuritySnapshot
from aida.aegis.remote.models import (
    RemoteAccessClassification,
    RemoteIntrusionAssessment,
)
from aida.aegis.remote.store import RemoteSecurityStore
from aida.aegis.remote.support import RemoteSupportService
from aida.aegis.remote.tooling import identify_remote_tools
from aida.aegis.remote.windows_sessions import (
    enumerate_remote_desktop_sessions,
    read_recent_remote_logons,
)
from aida.aegis.store import AegisStore
from aida.security.models import ProviderDetection


SnapshotReader = Callable[[], SecuritySnapshot]
DetectionReader = Callable[[], Iterable[ProviderDetection]]


class AegisRemoteIntrusionService:
    """Correlates remote-session, process, provider, baseline and ML evidence.

    A remote connection is not automatically an attacker. Explicit support
    windows, current session identity, tool lineage, persistence, provider
    evidence and learned machine behavior are considered together. A support
    authorization is context only and never suppresses strong malicious evidence.
    """

    def __init__(
        self,
        *,
        store: RemoteSecurityStore,
        aegis_store: AegisStore,
        support: RemoteSupportService,
        snapshot_reader: SnapshotReader,
        detection_reader: DetectionReader,
        learning: AegisLearningService,
    ) -> None:
        self.store = store
        self.aegis_store = aegis_store
        self.support = support
        self.snapshot_reader = snapshot_reader
        self.detection_reader = detection_reader
        self.learning = learning

    def inspect(
        self,
        *,
        unexpected_claim: bool = False,
        user_confirmed_attacker: bool = False,
    ) -> RemoteIntrusionAssessment:
        snapshot = self.snapshot_reader()
        baseline = self.aegis_store.load_baseline()
        delta = compare_snapshots(baseline, snapshot)
        try:
            detections = tuple(self.detection_reader() or ())
        except Exception:
            detections = ()

        sessions, session_errors = enumerate_remote_desktop_sessions()
        logons, logon_errors = read_recent_remote_logons()
        tools = identify_remote_tools(snapshot)
        support_match = self.support.best_match(sessions=sessions, tools=tools)

        features = extract_feature_vector(
            snapshot=snapshot,
            delta=delta,
            detections=detections,
            analyses=(),
        )
        learned = self.learning.assess(features)

        active_sessions = tuple(session for session in sessions if session.is_active)
        successful_remote_logons = tuple(
            event
            for event in logons
            if event.success and event.logon_type in {10, 12}
        )
        failed_remote_logons = tuple(
            event
            for event in logons
            if not event.success and event.logon_type in {10, 12}
        )
        network_logons = tuple(
            event for event in logons if event.logon_type == 3
        )
        sensitive_tools = tuple(
            tool for tool in tools if tool.security_sensitive_children
        )

        evidence: list[str] = []
        counters: list[str] = []
        score = 0.03
        urgency = 0.05

        if active_sessions:
            score += min(0.28, 0.20 + 0.04 * len(active_sessions))
            urgency = max(urgency, 0.45)
            evidence.append(
                f"{len(active_sessions)} active RDP/Remote Desktop session(s) are present."
            )
        elif successful_remote_logons:
            score += 0.12
            evidence.append(
                f"{len(successful_remote_logons)} recent successful remote-interactive logon event(s) were observed."
            )

        if len(failed_remote_logons) >= 5:
            score += min(0.18, 0.08 + len(failed_remote_logons) * 0.01)
            urgency = max(urgency, 0.35)
            evidence.append(
                f"{len(failed_remote_logons)} recent failed remote-interactive logon attempts were observed."
            )
        if network_logons:
            evidence.append(
                f"{len(network_logons)} recent Windows network logon event(s) were observed; these are weaker evidence than RemoteInteractive sessions."
            )

        if tools:
            score += min(0.10, len(tools) * 0.025)
            evidence.append(
                f"{len(tools)} remote-support/control process instance(s) are present."
            )
        if sensitive_tools:
            score += min(0.32, 0.18 + 0.07 * len(sensitive_tools))
            urgency = max(urgency, 0.72)
            names = sorted(
                {
                    child
                    for tool in sensitive_tools
                    for child in tool.security_sensitive_children
                }
            )
            evidence.append(
                "Remote-control tooling has spawned security-sensitive child process(es): "
                + ", ".join(names[:8])
                + "."
            )

        if delta.new_persistence:
            score += min(0.28, 0.12 + 0.05 * len(delta.new_persistence))
            urgency = max(urgency, 0.65)
            evidence.append(
                f"{len(delta.new_persistence)} new persistence item(s) differ from the established Aegis baseline."
            )
        if delta.new_listeners:
            score += min(0.12, 0.03 * len(delta.new_listeners))
            evidence.append(
                f"{len(delta.new_listeners)} new listening endpoint(s) differ from baseline."
            )
        if detections:
            score += min(0.50, 0.34 + 0.06 * len(detections))
            urgency = max(urgency, 0.90)
            evidence.append(
                f"{len(detections)} unresolved antivirus-provider detection(s) are active in the same assessment window."
            )

        health = snapshot.provider_health
        if health.active is False or health.real_time_protection is False:
            score += 0.20
            urgency = max(urgency, 0.82)
            evidence.append(
                "Endpoint protection is inactive or real-time protection is disabled during the remote-access assessment."
            )

        if not learned.warmup and learned.anomaly_score >= 0.45:
            score += min(0.18, learned.anomaly_score * 0.18)
            evidence.append(
                f"Current machine behavior is anomalous relative to Aegis's learned baseline ({round(learned.anomaly_score * 100)}%)."
            )

        if unexpected_claim:
            score += 0.20
            urgency = max(urgency, 0.70)
            evidence.append(
                "The local user reported that the observed remote access is unexpected."
            )

        strong_malicious_context = bool(
            detections
            or (sensitive_tools and delta.new_persistence)
            or (health.real_time_protection is False and active_sessions)
        )

        if support_match is not None:
            counters.extend(support_match.reasons)
            if support_match.confidence >= 0.45 and not strong_malicious_context:
                score -= min(0.30, 0.10 + support_match.confidence * 0.20)
            elif strong_malicious_context:
                evidence.append(
                    "A support authorization exists, but strong security evidence prevents Aegis from treating the session as ordinary support."
                )

        score = _clamp(score)
        confidence = _confidence(
            sessions=sessions,
            logon_error_count=len(logon_errors),
            session_error_count=len(session_errors),
            process_sensor_error_count=len(snapshot.sensor_errors),
            learning_confidence=learned.confidence,
        )

        remote_activity = bool(active_sessions or successful_remote_logons or tools)
        if user_confirmed_attacker:
            classification = RemoteAccessClassification.CONFIRMED_INTRUSION
            score = 1.0
            confidence = 1.0
            urgency = 1.0
            evidence.append(
                "The local user explicitly confirmed that the active remote access is unauthorized."
            )
            recommended = "prepare_sentry_attack_protocol"
        elif support_match is not None and remote_activity and strong_malicious_context:
            classification = RemoteAccessClassification.SUPPORT_SESSION_ANOMALOUS
            score = max(score, 0.62)
            urgency = max(urgency, 0.80)
            recommended = "interrupt_and_verify_support_session"
        elif support_match is not None and remote_activity and support_match.confidence >= 0.45 and score < 0.55:
            classification = RemoteAccessClassification.AUTHORIZED_SUPPORT
            recommended = "monitor_authorized_support"
        elif remote_activity and score >= 0.72:
            classification = RemoteAccessClassification.LIKELY_INTRUSION
            urgency = max(urgency, 0.85)
            recommended = "confirm_attacker_and_prepare_sentry"
        elif remote_activity and (unexpected_claim or score >= 0.42):
            classification = RemoteAccessClassification.UNAUTHORIZED_SUSPECTED
            recommended = "ask_user_to_verify_remote_access"
        elif remote_activity:
            classification = RemoteAccessClassification.REMOTE_ACCESS_OBSERVED
            recommended = "verify_remote_access_context"
        elif len(failed_remote_logons) >= 5:
            classification = RemoteAccessClassification.REMOTE_ACCESS_OBSERVED
            recommended = "monitor_remote_logon_attempts"
        elif session_errors or logon_errors or snapshot.sensor_errors:
            classification = RemoteAccessClassification.DEGRADED
            recommended = "restore_remote_intrusion_visibility"
        else:
            classification = RemoteAccessClassification.NO_REMOTE_ACTIVITY
            recommended = "observe"
            counters.append("No active RDP session or active remote-control lineage was identified in the observable evidence set.")

        degraded = tuple(
            dict.fromkeys(
                tuple(session_errors)
                + tuple(logon_errors)
                + tuple(snapshot.sensor_errors)
            )
        )
        assessment = RemoteIntrusionAssessment.create(
            classification=classification,
            intrusion_likelihood=_clamp(score),
            confidence=_clamp(confidence),
            urgency=_clamp(urgency),
            active_sessions=active_sessions,
            recent_logons=logons,
            remote_tools=tools,
            support_match=support_match,
            provider_detection_count=len(detections),
            baseline_change_count=delta.meaningful_change_count,
            learning_anomaly_score=learned.anomaly_score,
            learning_confidence=learned.confidence,
            evidence=tuple(evidence),
            counter_evidence=tuple(counters),
            degraded_reasons=degraded,
            recommended_action=recommended,
            user_confirmed_attacker=user_confirmed_attacker,
        )
        self.store.store_assessment(assessment)
        return assessment


def render_remote_intrusion_assessment(assessment: RemoteIntrusionAssessment) -> str:
    lines = [
        "AEGIS REMOTE INTRUSION ASSESSMENT",
        "",
        f"Assessment: {assessment.assessment_id}",
        f"Classification: {assessment.classification.value.replace('_', ' ').title()}",
        f"Intrusion likelihood: {round(assessment.intrusion_likelihood * 100)}%",
        f"Evidence confidence: {round(assessment.confidence * 100)}%",
        f"Urgency: {round(assessment.urgency * 100)}%",
        f"Active RDP sessions: {len(assessment.active_sessions)}",
        f"Remote-control tool processes: {len(assessment.remote_tools)}",
        f"Provider detections: {assessment.provider_detection_count}",
        f"Baseline changes: {assessment.baseline_change_count}",
        f"Learned anomaly: {round(assessment.learning_anomaly_score * 100)}%",
    ]
    if assessment.support_match is not None:
        lines.extend(
            [
                "",
                f"Authorized support context: {assessment.support_match.vendor_label}",
                f"Support-match confidence: {round(assessment.support_match.confidence * 100)}%",
            ]
        )
    if assessment.evidence:
        lines.extend(["", "Evidence:"])
        lines.extend(f"- {item}" for item in assessment.evidence[:12])
    if assessment.counter_evidence:
        lines.extend(["", "Context / counter-evidence:"])
        lines.extend(f"- {item}" for item in assessment.counter_evidence[:8])
    if assessment.degraded_reasons:
        lines.extend(["", "Visibility limitations:"])
        lines.extend(f"- {item}" for item in assessment.degraded_reasons[:8])
    lines.extend(
        [
            "",
            f"Recommended action: {assessment.recommended_action.replace('_', ' ')}",
            "Aegis has not terminated a session, process, network adapter, or security control during this assessment.",
        ]
    )
    return "\n".join(lines)


def _confidence(
    *,
    sessions: tuple[object, ...],
    logon_error_count: int,
    session_error_count: int,
    process_sensor_error_count: int,
    learning_confidence: float,
) -> float:
    value = 0.70
    if sessions:
        value += 0.12
    if learning_confidence > 0.0:
        value += min(0.10, learning_confidence * 0.10)
    value -= min(0.35, (logon_error_count + session_error_count) * 0.12)
    value -= min(0.25, process_sensor_error_count * 0.05)
    return _clamp(value)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
