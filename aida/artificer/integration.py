from __future__ import annotations

import threading
import time
from typing import Any

from aida.artificer.engine import ArtificerEngine
from aida.artificer.events import make_event
from aida.perception.models import PerceptionEvidence


class ArtificerOperationalBridge:
    """Translates live AIDA activity into privacy-minimized Artificer events."""

    def __init__(self, engine: ArtificerEngine) -> None:
        self.engine = engine
        self._lock = threading.RLock()
        self._task_started_ns: dict[str, int] = {}
        self._failed_tasks: set[str] = set()
        self._voice_started_ns: int | None = None

    def record_perception_evidence(self, evidence: PerceptionEvidence) -> None:
        size_bytes = _safe_int(evidence.metadata.get("size_bytes"))
        self._publish(
            source="perception",
            event_type="evidence_attached",
            status="completed",
            metadata={
                "evidence_id": evidence.evidence_id,
                "kind": evidence.kind.value,
                "source": evidence.source.value,
                "media_type": evidence.media_type or "unknown",
                "size_bytes": size_bytes,
                "confidence": round(float(evidence.confidence), 4),
                "digest_available": bool(evidence.sha256),
                "observed_count": len(evidence.observed),
                "extracted_count": len(evidence.extracted),
                "inferred_count": len(evidence.inferred),
                "unknown_count": len(evidence.unknown),
            },
        )

    def record_voice_state(self, state: str) -> None:
        normalized = state.strip().upper() or "UNKNOWN"
        duration_ms: float | None = None
        with self._lock:
            if normalized in {"LISTENING", "CAPTURING"}:
                self._voice_started_ns = time.monotonic_ns()
            elif normalized in {"READY", "ERROR"} and self._voice_started_ns is not None:
                duration_ms = _duration_ms(self._voice_started_ns)
                self._voice_started_ns = None

        if normalized == "ERROR":
            event_status = "failed"
        elif normalized in {"LISTENING", "PROCESSING", "CAPTURING", "EXTRACTING"}:
            event_status = "started"
        else:
            event_status = "completed"
        self._publish(
            source="interaction.voice",
            event_type="state_changed",
            status=event_status,
            duration_ms=duration_ms,
            metadata={"state": normalized},
        )

    def record_voice_transcript(self, transcript: str) -> None:
        clean = transcript.strip()
        self._publish(
            source="interaction.voice",
            event_type="transcript_ready",
            status="completed",
            metadata={
                "character_count": len(clean),
                "word_count": len(clean.split()),
                "content_recorded": False,
            },
        )

    def record_voice_error(self, message: str) -> None:
        self._publish(
            source="interaction.voice",
            event_type="interaction_failed",
            status="failed",
            error_category="VoiceInteractionError",
            metadata={
                "message_length": len(message.strip()),
                "detail_recorded": False,
            },
        )

    def record_task_started(self, task_name: str) -> None:
        with self._lock:
            self._task_started_ns[task_name] = time.monotonic_ns()
            self._failed_tasks.discard(task_name)
        self._publish(
            source="frontend.task_manager",
            event_type="task_started",
            status="started",
            task_name=task_name,
        )

    def record_task_finished(self, task_name: str) -> None:
        with self._lock:
            if task_name in self._failed_tasks:
                self._failed_tasks.discard(task_name)
                self._task_started_ns.pop(task_name, None)
                return
        self._publish(
            source="frontend.task_manager",
            event_type="task_finished",
            status="completed",
            task_name=task_name,
            duration_ms=self._pop_task_duration(task_name),
        )

    def record_task_failed(self, task_name: str, message: str) -> None:
        with self._lock:
            self._failed_tasks.add(task_name)
        self._publish(
            source="frontend.task_manager",
            event_type="task_failed",
            status="failed",
            task_name=task_name,
            duration_ms=self._pop_task_duration(task_name),
            error_category="TaskError",
            metadata={
                "message_length": len(message.strip()),
                "detail_recorded": False,
            },
        )

    def record_autonomy_state(self, enabled: bool) -> None:
        self._publish(
            source="autonomy.frontend",
            event_type="state_changed",
            status="completed",
            metadata={"enabled": bool(enabled)},
        )

    def _pop_task_duration(self, task_name: str) -> float | None:
        with self._lock:
            started_ns = self._task_started_ns.pop(task_name, None)
        return _duration_ms(started_ns) if started_ns is not None else None

    def _publish(
        self,
        *,
        source: str,
        event_type: str,
        status: str,
        task_name: str | None = None,
        duration_ms: float | None = None,
        error_category: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        profile = self.engine.platform_profile
        self.engine.event_bus.publish(
            make_event(
                source=source,
                event_type=event_type,
                status=status,
                aida_version=self.engine.version,
                platform_profile_id=(profile.profile_id if profile else "unknown"),
                task_name=task_name,
                duration_ms=duration_ms,
                error_category=error_category,
                metadata=metadata or {},
            )
        )


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _duration_ms(started_ns: int) -> float:
    return max(0.0, (time.monotonic_ns() - started_ns) / 1_000_000)
