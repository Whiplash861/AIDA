from __future__ import annotations

from typing import Any

from aida.artificer.engine import ArtificerEngine
from aida.artificer.events import make_event
from aida.perception.models import PerceptionEvidence


class ArtificerOperationalBridge:
    """Translates live AIDA activity into privacy-minimized Artificer events."""

    def __init__(self, engine: ArtificerEngine) -> None:
        self.engine = engine

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
        self._publish(
            source="frontend.task_manager",
            event_type="task_started",
            status="started",
            task_name=task_name,
        )

    def record_task_finished(self, task_name: str) -> None:
        self._publish(
            source="frontend.task_manager",
            event_type="task_finished",
            status="completed",
            task_name=task_name,
        )

    def record_task_failed(self, task_name: str, message: str) -> None:
        self._publish(
            source="frontend.task_manager",
            event_type="task_failed",
            status="failed",
            task_name=task_name,
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

    def _publish(
        self,
        *,
        source: str,
        event_type: str,
        status: str,
        task_name: str | None = None,
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
                error_category=error_category,
                metadata=metadata or {},
            )
        )


def _safe_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
