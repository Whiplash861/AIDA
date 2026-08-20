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


def test_backend_is_connected_through_explicit_frontend_lifecycle() -> None:
    source = Path("aida/frontend/app.py").read_text(encoding="utf-8")

    assert "build_artificer_engine(config)" in source
    assert "set_active_artificer(artificer_engine)" in source
    assert "ArtificerOperationalBridge(artificer_engine)" in source
    assert "ArtificerQtBridge(artificer_engine" in source
    assert "ArtificerCenterDialog(artificer_engine" in source
    assert "artificer_engine.start(run_startup_review=False)" in source
    assert "artificer_engine.run_review" in source
    assert "artificer_engine.export_report" in source
    assert "artificer_engine.stop()" in source
    assert "set_active_artificer(None)" in source


def test_perception_and_voice_are_connected_without_content_capture() -> None:
    source = Path("aida/frontend/app.py").read_text(encoding="utf-8")
    bridge = Path("aida/artificer/integration.py").read_text(encoding="utf-8")

    assert "perception_evidence_attached.connect" in source
    assert "record_perception_evidence" in source
    assert "record_voice_state" in source
    assert "record_voice_transcript" in source
    assert "record_voice_error" in source

    assert '"content_recorded": False' in bridge
    assert '"detail_recorded": False' in bridge
    assert "local_path" not in bridge
    assert "evidence.sha256" in bridge
    assert "bool(evidence.sha256)" in bridge
