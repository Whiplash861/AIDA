from __future__ import annotations

from typing import Any

from aida.artificer.events import make_event
from aida.artificer.runtime import get_active_artificer


class AegisArtificerBridge:
    """One-way privacy-minimized operational link from Aegis to Artificer.

    Artificer already scans AIDA's configured source tree, so Aegis source is
    automatically included in Codewright reviews. This bridge adds runtime
    reliability, performance, and engineering-pattern evidence without exposing
    file paths, hashes, network endpoints, command lines, model feature tokens,
    or Security Case contents.
    """

    def publish(
        self,
        *,
        event_type: str,
        status: str,
        duration_ms: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        engine = get_active_artificer()
        if engine is None:
            return
        profile = engine.platform_profile
        safe_metadata = _safe_metadata(metadata or {})
        engine.event_bus.publish(
            make_event(
                source="aegis.engine",
                event_type=event_type,
                status=status,
                aida_version=engine.version,
                platform_profile_id=(profile.profile_id if profile else "unknown"),
                duration_ms=duration_ms,
                metadata=safe_metadata,
            )
        )


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "state",
        "case_status",
        "provider_detection_count",
        "analyzed_file_count",
        "baseline_change_count",
        "risk_band",
        "coverage_band",
        "escalation",
        "sensor_error_count",
        "baseline_available",
        "scan_strategy",
        "learning_anomaly_band",
        "learning_confidence_band",
        "learning_model_version",
        "learning_model_stage",
        "learning_sample_count",
        "learning_ready",
        "learning_sample_accepted",
        "learning_capability_count",
        "engineering_manifest_version",
        "shadow_supported",
        "rollback_supported",
    }
    output: dict[str, Any] = {}
    for key, value in metadata.items():
        if key not in allowed:
            continue
        if value is None or isinstance(value, (bool, int, float, str)):
            output[key] = value
    return output
