from __future__ import annotations

from types import SimpleNamespace

from aida.aegis import artificer_bridge as bridge_module
from aida.aegis.artificer_bridge import AegisArtificerBridge


class _Bus:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


def test_artificer_bridge_excludes_security_evidence_contents(monkeypatch) -> None:
    bus = _Bus()
    engine = SimpleNamespace(
        event_bus=bus,
        version="1.0.0",
        platform_profile=None,
    )
    monkeypatch.setattr(
        bridge_module,
        "get_active_artificer",
        lambda: engine,
    )

    AegisArtificerBridge().publish(
        event_type="remote_intrusion_alert",
        status="alert",
        metadata={
            "state": "elevated",
            "provider_detection_count": 1,
            "risk_band": "high",
            "coverage_band": "high",
            "scan_strategy": "adaptive",
            "learning_model_version": 2,
            "learning_feature_schema_version": 2,
            "learning_model_stage": "active",
            "learning_sample_count": 18,
            "learning_ready": True,
            "learning_anomaly_band": "low",
            "engineering_manifest_version": "1.1",
            "shadow_supported": True,
            "rollback_supported": True,
            "remote_classification": "likely_intrusion",
            "remote_likelihood_band": "high",
            "remote_confidence_band": "high",
            "remote_urgency_band": "high",
            "remote_active_session_count": 1,
            "remote_tool_count": 1,
            "support_context_present": True,
            "sentry_plan_state": "awaiting_confirmation",
            "sentry_session_target_count": 1,
            "sentry_process_target_count": 2,
            "path": r"C:\Users\Private\secret.exe",
            "sha256": "a" * 64,
            "network_endpoint": "203.0.113.20:443",
            "support_vendor_label": "Northstar",
            "remote_account": r"CLUB\supportuser",
            "learning_feature_token": "process:private",
        },
    )

    assert len(bus.events) == 1
    metadata = dict(bus.events[0].metadata)
    assert metadata["state"] == "elevated"
    assert metadata["provider_detection_count"] == 1
    assert metadata["remote_classification"] == "likely_intrusion"
    assert metadata["remote_active_session_count"] == 1
    assert metadata["support_context_present"] is True
    assert metadata["sentry_plan_state"] == "awaiting_confirmation"
    assert metadata["learning_feature_schema_version"] == 2
    assert "path" not in metadata
    assert "sha256" not in metadata
    assert "network_endpoint" not in metadata
    assert "support_vendor_label" not in metadata
    assert "remote_account" not in metadata
    assert "learning_feature_token" not in metadata
    assert "Northstar" not in repr(metadata)
    assert "secret.exe" not in repr(metadata)
