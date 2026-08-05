from __future__ import annotations

from pathlib import Path

from aida.artificer.bootstrap import build_artificer_engine
from aida.config import get_config


def test_artificer_uses_user_data_and_safe_early_alpha_defaults(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("AIDA_ARTIFICER_DISPATCH_ENDPOINT", raising=False)
    monkeypatch.delenv("AIDA_ARTIFICER_TELEMETRY_LEVEL", raising=False)
    monkeypatch.delenv("AIDA_ARTIFICER_AUTO_MAINTENANCE_ENABLED", raising=False)

    config = get_config()
    expected_root = tmp_path / "AIDA" / "artificer"

    assert Path(config.artificer_data_dir) == expected_root
    assert Path(config.artificer_ledger_path) == expected_root / "artificer.db"
    assert config.artificer_telemetry_level == "local_only"
    assert config.artificer_dispatch_endpoint == ""
    assert config.artificer_auto_maintenance_enabled is False

    engine = build_artificer_engine(config)
    try:
        assert engine.enabled is True
        assert engine.source_root == Path(config.base_dir).resolve()
        assert engine.consent.state.telemetry_level.value == "local_only"
    finally:
        engine.stop()


def test_backend_is_not_connected_to_frontend_startup() -> None:
    source = Path("aida/frontend/app.py").read_text(encoding="utf-8")

    assert "ArtificerEngine" not in source
    assert "build_artificer_engine" not in source
    assert "set_active_artificer" not in source
    assert ".run_review(" not in source

    # The existing read-only Artificer dialog remains allowed.
    assert "ArtificerDialog" in source
