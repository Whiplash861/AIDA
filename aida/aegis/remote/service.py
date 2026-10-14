from __future__ import annotations

from aida.reporting import render_report

from collections.abc import Callable, Iterable

import psutil
import time

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
from aida.aegis.remote.tooling import (
    identify_remote_tools,
    is_security_sensitive_child_name,
    remote_tool_name_hint,
)
from aida.aegis.remote.windows_sessions import (
    enumerate_remote_desktop_sessions,
    read_recent_remote_logons,
)
from aida.aegis.store import AegisStore
from aida.security.models import ProviderDetection
from aida.security.detection_intelligence import _is_unresolved


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
        investigations=None,
        logon_reader=None,
        event_collector=None,
    ) -> None:
        self.store = store
        self.aegis_store = aegis_store
        self.support = support
        self.snapshot_reader = snapshot_reader
        self.detection_reader = detection_reader
        self.learning = learning
        self.investigations = investigations
        self.logon_reader = logon_reader
        self.event_collector = event_collector
        self._last_periodic_probe = 0.0

    def activity_hint(self) -> bool:
        """Cheap background trigger before running the full remote assessment.

        Active RDP is a direct trigger. Resident remote-support services alone
        are not: many legitimate tools remain connected to a relay continuously.
        Third-party tooling triggers the heavier assessment when it spawns a
        security-sensitive child such as PowerShell, cmd, schtasks, or reg.exe.
        """

        # Even a quiet machine gets a bounded logon/evidence review, so failed
        # logons and sensor failures are not invisible to the cheap trigger.
        now = time.monotonic()
        if now - self._last_periodic_probe >= 300:
            self._last_periodic_probe = now
            return True
        sessions, _errors = enumerate_remote_desktop_sessions()
        if _errors:
            return True
        if any(session.is_active for session in sessions):
            return True
        try:
            rows = list(psutil.process_iter(["pid", "ppid", "name"]))
        except (psutil.Error, OSError):
            return False
        remote_pids = {
            int(process.info.get("pid") or process.pid)
            for process in rows
            if remote_tool_name_hint(str(process.info.get("name") or ""))
        }
        if not remote_pids:
            return False
        return any(
            process.info.get("ppid") in remote_pids
            and is_security_sensitive_child_name(
                str(process.info.get("name") or "")
            )
            for process in rows
        )

    def inspect(
        self,
        *,
        unexpected_claim: bool = False,
        user_confirmed_attacker: bool = False,
        cancel_check=None,
    ) -> RemoteIntrusionAssessment:
        snapshot = self.snapshot_reader()
        baseline = self.aegis_store.load_baseline()
        delta = compare_snapshots(baseline, snapshot)
        detection_errors = ()
        try:
            rows = self.detection_reader()
            if rows is None:
                raise RuntimeError("Provider findings unavailable")
            detections = tuple(item for item in rows if _is_unresolved(item))
        except (OSError, RuntimeError, ValueError):
            detections = ()
            detection_errors = ("provider_detections_unavailable",)

        sessions, session_errors = enumerate_remote_desktop_sessions()
        logons, logon_errors = (self.event_collector.recent_remote_logons(cancel_check=cancel_check)
            if self.event_collector is not None else (self.logon_reader or read_recent_remote_logons)())
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
            if support_match.fully_matched and not strong_malicious_context and not detection_errors:
                score -= min(0.30, 0.10 + support_match.confidence * 0.20)
            elif strong_malicious_context:
                evidence.append(
                    "A support authorization exists, but strong security evidence prevents Aegis from treating the session as ordinary support."
                )

        score = _clamp(score)
        confidence = _confidence(
            sessions=sessions,
            logon_error_count=len(logon_errors),
            session_error_count=len(session_errors) + len(detection_errors),
            process_sensor_error_count=len(snapshot.sensor_errors),
            learning_confidence=learned.confidence,
        )

        # A successful historical logon is useful evidence, but it is not a
        # current containment target. Active RDP sessions and recognized
        # remote-control process instances are the current Phase 1 targets.
        active_containment_target = bool(active_sessions or tools)
        remote_activity = bool(active_containment_target or successful_remote_logons)
        effective_user_confirmation = bool(
            user_confirmed_attacker and active_containment_target
        )

        if effective_user_confirmation:
            classification = RemoteAccessClassification.CONFIRMED_INTRUSION
            score = 1.0
            # User intent is confirmed; sensor confidence still reflects coverage.
            urgency = 1.0
            evidence.append(
                "The local user explicitly confirmed that the currently observable remote access is unauthorized."
            )
            recommended = "prepare_sentry_attack_protocol"
        elif user_confirmed_attacker and not active_containment_target:
            classification = (
                RemoteAccessClassification.UNAUTHORIZED_SUSPECTED
                if remote_activity
                else RemoteAccessClassification.NO_REMOTE_ACTIVITY
            )
            score = max(score, 0.45 if remote_activity else 0.20)
            urgency = max(urgency, 0.65)
            evidence.append(
                "The local user reported an attacker, but Aegis could not resolve a currently active RDP session or recognized remote-control process target."
            )
            recommended = "preserve_evidence_and_run_aegis_scan"
        elif support_match is not None and remote_activity and strong_malicious_context:
            classification = RemoteAccessClassification.SUPPORT_SESSION_ANOMALOUS
            score = max(score, 0.62)
            urgency = max(urgency, 0.80)
            recommended = "interrupt_and_verify_support_session"
        elif support_match is not None and remote_activity and support_match.fully_matched and not detection_errors and score < 0.55:
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
        elif session_errors or logon_errors or snapshot.sensor_errors or detection_errors:
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
                + detection_errors
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
            user_confirmed_attacker=effective_user_confirmation,
        )
        if cancel_check and cancel_check():
            return assessment
        self.store.store_assessment(assessment)
        if self.investigations is not None:
            self.investigations.record_remote(assessment)
        return assessment


def render_remote_intrusion_assessment(assessment: RemoteIntrusionAssessment) -> str:
    from aida.aegis.explanations import explain_sensor_limitations

    classification = assessment.classification
    interpretations = {
        RemoteAccessClassification.NO_REMOTE_ACTIVITY: "AIDA did not identify an active Remote Desktop session or a recognized remote-control program in the information it could read. This does not rule out every kind of remote access.",
        RemoteAccessClassification.AUTHORIZED_SUPPORT: "Recorded activity matches the details of a support session you authorized. A match is context for review, not proof that every action is safe.",
        RemoteAccessClassification.SUPPORT_SESSION_ANOMALOUS: "There is a support authorization, but other security evidence needs attention before treating the activity as expected support.",
        RemoteAccessClassification.REMOTE_ACCESS_OBSERVED: "Remote-access activity or repeated sign-in attempts were recorded. This alone does not establish unauthorized control.",
        RemoteAccessClassification.UNAUTHORIZED_SUSPECTED: "Recorded remote-access activity needs your review because AIDA could not sufficiently explain it as expected access.",
        RemoteAccessClassification.LIKELY_INTRUSION: "The combination of recorded activity and security indicators warrants urgent review. The assessment alone does not identify an attacker.",
        RemoteAccessClassification.CONFIRMED_INTRUSION: "You reported that the recorded remote access is unauthorized. AIDA also identified a current session or remote-control program that can be reviewed for containment.",
        RemoteAccessClassification.DEGRADED: "Some checks could not be completed. AIDA cannot give a complete account of remote access from this check.",
    }
    found = [
        f"Active Remote Desktop sessions recorded: {len(assessment.active_sessions)}.",
        f"Recognized remote-control programs recorded: {len(assessment.remote_tools)}.",
        f"Antivirus findings included in this check: {assessment.provider_detection_count}.",
        *(_plain_remote_evidence(item) for item in assessment.evidence[:12]),
    ]
    if assessment.support_match is not None:
        found.append(f"Support authorization considered: {assessment.support_match.vendor_label}.")
    found.append("This check did not end sessions, stop programs, or change network or antivirus settings.")
    unknown = [
        *explain_sensor_limitations(assessment.degraded_reasons),
        "A session or program name does not establish who is operating it or whether every action is authorized.",
    ]
    actions = {
        "prepare_sentry_attack_protocol": "Review the exact sessions and programs in the Sentry containment plan. Nothing is stopped until you give its fresh, exact confirmation.",
        "confirm_attacker_and_prepare_sentry": "Check whether you recognize the remote access. If you know it is unauthorized, tell AIDA so it can prepare a specific containment plan for your review.",
        "interrupt_and_verify_support_session": "Verify the session with the support company using a contact method you already trust. If you know the access is unauthorized, request a containment plan.",
        "monitor_authorized_support": "Check that the support session is still expected. Revoke its authorization when the work is finished; revoking the authorization does not disconnect it.",
        "ask_user_to_verify_remote_access": "Confirm whether you recognize the recorded remote access before deciding on a response.",
        "verify_remote_access_context": "Check whether the recorded activity matches support or remote access you requested.",
        "monitor_remote_logon_attempts": "Review whether you expected the sign-in attempts. Repeat this check if attempts continue or new access appears.",
        "restore_remote_intrusion_visibility": "Review the checks that could not finish. Check Windows Security and repeat the remote-access check when those sources are available.",
        "preserve_evidence_and_run_aegis_scan": "Keep this report and request an Aegis security scan. A current session or program must be identified before Sentry can prepare containment.",
        "observe": "If you still see unexpected remote activity, run another remote-access check while it is happening and review Windows Security.",
    }
    details = [
        f"Assessment: {assessment.assessment_id}; recorded at: {assessment.created_at.isoformat()}",
        f"Classification code: {classification.value}",
        f"Intrusion indicator: {round(assessment.intrusion_likelihood * 100)}%; evidence confidence: {round(assessment.confidence * 100)}%; urgency: {round(assessment.urgency * 100)}%. These scores are not calibrated probabilities.",
        f"Changes against saved comparison: {assessment.baseline_change_count}; learned anomaly: {round(assessment.learning_anomaly_score * 100)}%",
        *(f"Session {item.session_id}: {item.account}; client {item.client_address or 'unknown'}; logon identity {item.logon_time}" for item in assessment.active_sessions),
        *(f"Process {item.pid}: {item.display_name}; {item.executable}; created {item.create_time}" for item in assessment.remote_tools),
        *assessment.counter_evidence,
        *assessment.degraded_reasons,
    ]
    urgent = classification in {RemoteAccessClassification.LIKELY_INTRUSION, RemoteAccessClassification.CONFIRMED_INTRUSION, RemoteAccessClassification.SUPPORT_SESSION_ANOMALOUS}
    return render_report("Urgent remote-access review" if urgent else "Remote-access review",
                         found=found, unknown=unknown,
                         next_steps=(actions.get(assessment.recommended_action, "Review the recorded activity before choosing another check or a response."),),
                         interpretation=interpretations[classification], details=details)


def _plain_remote_evidence(value: str) -> str:
    if value.startswith("Current machine behavior is anomalous relative to Aegis's learned baseline"):
        return "The behavior comparison flagged activity for review against earlier observations. This does not by itself establish harmful behavior."
    return (value.replace("active RDP/Remote Desktop session(s) are present", "active Remote Desktop session(s) were recorded")
        .replace("remote-interactive logon", "Remote Desktop sign-in")
        .replace("Windows network logon event(s)", "Windows network sign-in event(s)")
        .replace("these are weaker evidence than RemoteInteractive sessions", "these do not by themselves show that someone controlled the desktop")
        .replace("remote-support/control process instance(s) are present", "remote-support or remote-control program(s) were running")
        .replace("Remote-control tooling has spawned security-sensitive child process(es)", "Remote-control software started programs that can change important system settings")
        .replace("new persistence item(s) differ from the established Aegis baseline", "new ways for programs to start automatically differ from the saved comparison of this computer")
        .replace("new listening endpoint(s) differ from baseline", "new network addresses where programs accept connections differ from the saved comparison")
        .replace("unresolved antivirus-provider detection(s) are active in the same assessment window", "unresolved antivirus finding(s) were reported during this check")
        .replace("Endpoint protection", "Antivirus protection")
        .replace("currently observable remote access", "remote access recorded in this check")
        .replace("currently active RDP session or recognized remote-control process target", "active Remote Desktop session or recognized remote-control program"))


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
