from __future__ import annotations

import threading
import time

from aida.aegis.artificer_bridge import AegisArtificerBridge
from aida.aegis.remote.models import RemoteAccessClassification
from aida.aegis.remote.service import AegisRemoteIntrusionService
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService


_ALERT_CLASSES = {
    RemoteAccessClassification.SUPPORT_SESSION_ANOMALOUS,
    RemoteAccessClassification.UNAUTHORIZED_SUSPECTED,
    RemoteAccessClassification.LIKELY_INTRUSION,
    RemoteAccessClassification.CONFIRMED_INTRUSION,
}


class RemoteIntrusionMonitor:
    """Low-cost background watcher for active remote-access indicators."""

    def __init__(
        self,
        *,
        service: AegisRemoteIntrusionService,
        memory: MemoryService,
        bridge: AegisArtificerBridge,
        interval_seconds: int = 30,
        initial_delay_seconds: float = 8.0,
        enabled: bool = True,
    ) -> None:
        self.service = service
        self.memory = memory
        self.bridge = bridge
        self.interval_seconds = max(10, int(interval_seconds))
        self.initial_delay_seconds = max(0.0, float(initial_delay_seconds))
        self.enabled = bool(enabled)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_signature: tuple[str, int, int] | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="AIDA-Aegis-Remote-Intrusion-Monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        self._thread = None

    def _loop(self) -> None:
        if self._stop.wait(self.initial_delay_seconds):
            return
        while not self._stop.is_set():
            try:
                if self.service.activity_hint():
                    started = time.monotonic()
                    assessment = self.service.inspect()
                    signature = (
                        assessment.classification.value,
                        len(assessment.active_sessions),
                        len(assessment.remote_tools),
                    )
                    if signature != self._last_signature:
                        self._record(assessment, (time.monotonic() - started) * 1000)
                        self._last_signature = signature
            except Exception:
                self.bridge.publish(
                    event_type="remote_intrusion_monitor_failed",
                    status="failed",
                    metadata={
                        "remote_monitor_degraded": True,
                    },
                )
            if self._stop.wait(self.interval_seconds):
                return

    def _record(self, assessment, duration_ms: float) -> None:
        alert = assessment.classification in _ALERT_CLASSES
        self.memory.log_event(
            "AEGIS_REMOTE_ACCESS_OBSERVATION",
            "security.aegis.remote",
            (
                f"Aegis classified current remote-access evidence as "
                f"{assessment.classification.value}; likelihood "
                f"{round(assessment.intrusion_likelihood * 100)}%, confidence "
                f"{round(assessment.confidence * 100)}%."
            ),
            payload={
                "classification": assessment.classification.value,
                "intrusion_likelihood": assessment.intrusion_likelihood,
                "confidence": assessment.confidence,
                "urgency": assessment.urgency,
                "active_session_count": len(assessment.active_sessions),
                "remote_tool_count": len(assessment.remote_tools),
                "support_context_present": assessment.support_match is not None,
                "recommended_action": assessment.recommended_action,
            },
            outcome=(
                ProcessOutcome.PARTIAL
                if assessment.degraded_reasons
                else ProcessOutcome.SUCCEEDED
            ),
            confidence=assessment.confidence,
            promote=alert,
        )
        self.bridge.publish(
            event_type=(
                "remote_intrusion_alert" if alert else "remote_access_observed"
            ),
            status=("alert" if alert else "completed"),
            duration_ms=duration_ms,
            metadata={
                "remote_classification": assessment.classification.value,
                "remote_likelihood_band": _band(assessment.intrusion_likelihood),
                "remote_confidence_band": _band(assessment.confidence),
                "remote_urgency_band": _band(assessment.urgency),
                "remote_active_session_count": len(assessment.active_sessions),
                "remote_tool_count": len(assessment.remote_tools),
                "support_context_present": assessment.support_match is not None,
                "remote_monitor_degraded": bool(assessment.degraded_reasons),
            },
        )


def _band(value: float) -> str:
    if value >= 0.80:
        return "high"
    if value >= 0.50:
        return "moderate"
    return "low"
