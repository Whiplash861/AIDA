from __future__ import annotations

from aida.frontend.command_router import CommandRouter, CommandType


def test_router_recognizes_artificer_review() -> None:
    routed = CommandRouter().route("Run an Artificer review")
    assert routed is not None
    assert routed.command_type is CommandType.ARTIFICER_REVIEW


def test_router_recognizes_platform_security_scan() -> None:
    routed = CommandRouter().route("Scan my computer for malware")
    assert routed is not None
    assert routed.command_type is CommandType.SECURITY_SCAN
