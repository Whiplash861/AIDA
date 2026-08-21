from __future__ import annotations

from types import SimpleNamespace

from aida.aegis.engine import AegisEngine
from aida.aegis.models import ProviderHealth, SecuritySnapshot
from aida.aegis.store import AegisStore
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.models import ProviderDetection, SecuritySeverity


class _StaticSensor:
    def __init__(self, snapshot: SecuritySnapshot) -> None:
        self.snapshot = snapshot

    def capture(self) -> SecuritySnapshot:
        return self.snapshot


class _SilentBridge:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, **payload) -> None:
        self.events.append(payload)


def _clean_snapshot() -> SecuritySnapshot:
    return SecuritySnapshot.create(
        processes=(),
        persistence=(),
        listeners=(),
        provider_health=ProviderHealth(
            available=True,
            active=True,
            healthy=True,
            real_time_protection=True,
            signatures_current=True,
            provider_name="Microsoft Defender",
        ),
    )


def _engine(tmp_path, *, detections=()) -> AegisEngine:
    database = MemoryDatabase(tmp_path / "memory.db")
    memory = MemoryService(database)
    bridge = _SilentBridge()
    return AegisEngine(
        store=AegisStore(tmp_path / "aegis.db"),
        memory=memory,
        threat_analysis=SimpleNamespace(
            analyze=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("No file analysis expected in this test")
            )
        ),
        detection_reader=lambda: tuple(detections),
        sensor=_StaticSensor(_clean_snapshot()),
        bridge=bridge,
        observation_interval_seconds=3600,
        initial_observation_delay_seconds=3600,
    )


def test_clean_first_intelligent_scan_establishes_baseline(tmp_path) -> None:
    engine = _engine(tmp_path)

    result = engine.run_intelligent_scan(
        provider_scan_summary="Surface scan completed cleanly."
    )

    assert result.baseline_established is True
    assert engine.store.load_baseline() is not None
    assert result.case.provider_detection_count == 0
    assert result.case.escalation == "no_escalation"
    assert result.case.status.value == "assessed"
    assert engine.store.open_case_count() == 0


def test_active_provider_detection_creates_confirmed_case(tmp_path) -> None:
    detection = ProviderDetection(
        detection_id="det-1",
        name="Trojan:Test/Example",
        severity=SecuritySeverity.CRITICAL,
        source="Microsoft Defender",
        file_path=None,
        metadata={"is_active": True},
    )
    engine = _engine(tmp_path, detections=(detection,))

    result = engine.run_intelligent_scan()

    assert result.baseline_established is False
    assert result.case.status.value == "threat_confirmed"
    assert result.case.escalation == "full_sweep_recommended"
    assert result.case.risk.likelihood >= 0.95
    assert engine.store.get_case(result.case.case_id) is not None
    assert engine.store.open_case_count() == 1
