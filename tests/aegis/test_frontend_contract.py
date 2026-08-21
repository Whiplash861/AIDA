from __future__ import annotations

from pathlib import Path

from aida.frontend.command_router import CommandRouter, CommandType


def test_explicit_intelligent_scan_routes_to_aegis() -> None:
    routed = CommandRouter().route("run intelligent security scan")

    assert routed is not None
    assert routed.command_type is CommandType.SECURITY_INTELLIGENT_SCAN
    assert routed.local_only is True


def test_aegis_has_no_dedicated_frontend_control() -> None:
    window_source = Path("aida/frontend/window.py").read_text(encoding="utf-8")
    widget_source = Path("aida/frontend/widgets.py").read_text(encoding="utf-8")

    assert "aegis_button" not in window_source.lower()
    assert '("AEGIS",' not in widget_source
