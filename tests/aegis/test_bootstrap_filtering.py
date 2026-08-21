from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from aida.aegis.bootstrap import build_aegis_engine
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.models import ProviderDetection, SecuritySeverity


def _detection(detection_id: str, *, active, action_success):
    return ProviderDetection(
        detection_id=detection_id,
        name="Test threat",
        severity=SecuritySeverity.MODERATE,
        source="Microsoft Defender",
        file_path=Path(r"C:\Temp\test.exe"),
        metadata={"is_active": active, "action_success": action_success},
    )


def test_runtime_reader_excludes_provider_confirmed_resolved_history(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("AIDA_AEGIS_ENABLED", "false")
    database = MemoryDatabase(tmp_path / "memory" / "aida_memory.db")
    memory = MemoryService(database)
    config = SimpleNamespace(memory_db_path=str(database.path))
    rows = (
        _detection("active", active=True, action_success=False),
        _detection("resolved", active=False, action_success=True),
        _detection("ambiguous", active=None, action_success=False),
    )
    engine = build_aegis_engine(
        config,
        memory=memory,
        threat_analysis=SimpleNamespace(),
        detection_reader=lambda: rows,
    )

    filtered = tuple(engine.detection_reader())

    assert {item.detection_id for item in filtered} == {"active", "ambiguous"}
