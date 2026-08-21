from __future__ import annotations

from pathlib import Path

from aida.aegis.baseline import compare_snapshots
from aida.aegis.intelligence import assess_risk, escalation_for
from aida.aegis.models import (
    CoverageVector,
    PersistenceEntity,
    ProcessEntity,
    ProviderHealth,
    SecuritySnapshot,
)
from aida.security.models import ProviderDetection, SecuritySeverity


def _snapshot(
    *,
    processes=(),
    persistence=(),
    listeners=(),
) -> SecuritySnapshot:
    return SecuritySnapshot.create(
        processes=tuple(processes),
        persistence=tuple(persistence),
        listeners=tuple(listeners),
        provider_health=ProviderHealth(
            available=True,
            active=True,
            healthy=True,
            real_time_protection=True,
            signatures_current=True,
            provider_name="Microsoft Defender",
        ),
    )


def test_baseline_delta_reports_security_relevant_changes() -> None:
    baseline = _snapshot(
        processes=(ProcessEntity(1, None, "known.exe", r"C:\Known\known.exe"),),
        persistence=(PersistenceEntity("hkcu_run", "Known", r"C:\Known\known.exe"),),
        listeners=("127.0.0.1:5000",),
    )
    current = _snapshot(
        processes=(
            ProcessEntity(1, None, "known.exe", r"C:\Known\known.exe"),
            ProcessEntity(2, 1, "new.exe", r"C:\Users\Test\AppData\new.exe"),
        ),
        persistence=(
            PersistenceEntity("hkcu_run", "Known", r"C:\Known\known.exe"),
            PersistenceEntity("hkcu_run", "New", r"C:\Users\Test\AppData\new.exe"),
        ),
        listeners=("127.0.0.1:5000", "0.0.0.0:8123"),
    )

    delta = compare_snapshots(baseline, current)

    assert delta.baseline_available is True
    assert r"C:\Users\Test\AppData\new.exe" in delta.new_process_paths
    assert len(delta.new_persistence) == 1
    assert delta.new_listeners == ("0.0.0.0:8123",)
    assert delta.meaningful_change_count == 3


def test_active_high_provider_detection_drives_full_sweep_recommendation() -> None:
    snapshot = _snapshot()
    detection = ProviderDetection(
        detection_id="det-1",
        name="Trojan:Test/Example",
        severity=SecuritySeverity.HIGH,
        source="Microsoft Defender",
        file_path=Path(r"C:\Temp\example.exe"),
        metadata={"is_active": True},
    )
    delta = compare_snapshots(snapshot, snapshot)

    risk = assess_risk(
        detections=(detection,),
        analyses=(),
        delta=delta,
        snapshot=snapshot,
    )
    coverage = CoverageVector(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

    assert risk.likelihood >= 0.95
    assert risk.impact >= 0.80
    assert escalation_for(risk, coverage) == "full_sweep_recommended"
