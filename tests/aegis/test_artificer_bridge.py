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
        event_type="intelligent_scan_completed",
        status="completed",
        metadata={
            "state": "observing",
            "provider_detection_count": 1,
            "risk_band": "high",
            "coverage_band": "high",
            "path": r"C:\Users\Private\secret.exe",
            "sha256": "a" * 64,
            "network_endpoint": "203.0.113.20:443",
        },
    )

    assert len(bus.events) == 1
    metadata = dict(bus.events[0].metadata)
    assert metadata["state"] == "observing"
    assert metadata["provider_detection_count"] == 1
    assert metadata["risk_band"] == "high"
    assert "path" not in metadata
    assert "sha256" not in metadata
    assert "network_endpoint" not in metadata
    assert "secret.exe" not in repr(metadata)
