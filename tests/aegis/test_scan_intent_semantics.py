from __future__ import annotations

import pytest

from aida.frontend.command_router import CommandRouter, CommandType


@pytest.mark.parametrize(
    "text",
    [
        "Run an intelligent security scan",
        "run intelligent security scan",
        "Aegis adaptive scan",
        "run Aegis adaptive scan",
        "check my computer for malware",
        "scan my PC for viruses",
        "check for threats",
        "run a security scan",
    ],
)
def test_unqualified_security_requests_route_to_aegis_adaptive(text: str) -> None:
    command = CommandRouter().route(text)
    assert command is not None
    assert command.command_type is CommandType.SECURITY_INTELLIGENT_SCAN
    assert command.local_only is True
    assert command.confidence is not None
    assert command.confidence >= 0.90


def test_exact_screenshot_phrase_resolves_with_perfect_confidence() -> None:
    command = CommandRouter().route("Run an intelligent security scan")
    assert command is not None
    assert command.command_type is CommandType.SECURITY_INTELLIGENT_SCAN
    assert command.confidence == 1.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("run a surface security scan", CommandType.SECURITY_SURFACE_SCAN),
        (r'deep scan "C:\\Temp"', CommandType.SECURITY_DEEP_SCAN),
        ("perform a full system sweep", CommandType.SECURITY_FULL_SWEEP),
        ("quick scan", CommandType.QUICKSCAN),
    ],
)
def test_explicit_scan_depth_still_wins(text: str, expected: CommandType) -> None:
    command = CommandRouter().route(text)
    assert command is not None
    assert command.command_type is expected


def test_pending_clarification_can_be_cancelled_conversationally() -> None:
    router = CommandRouter()
    ambiguous = router.route("scan")
    assert ambiguous is not None
    assert ambiguous.command_type is CommandType.INTENT_CLARIFICATION

    cancelled = router.route("Cancel")
    assert cancelled is not None
    assert cancelled.command_type is CommandType.INTENT_CLARIFICATION
    assert "cancelled" in cancelled.clarification_text.lower()
    assert not router.context.extra.get("clarification_candidates")
