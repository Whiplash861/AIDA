import pytest

from aida.brain.system_prompt import AIDA_SYSTEM_PROMPT
from aida.frontend.command_router import CommandRouter, CommandType


def test_routes_security_status() -> None:
    command = CommandRouter().route("Check antivirus status")
    assert command is not None
    assert command.command_type is CommandType.SECURITY_STATUS
    assert command.local_only is True


@pytest.mark.parametrize(
    "text",
    [
        "Run a surface-level security scan",
        "run a surface level security scan",
        "start surface security scan",
        "initiate a malware scan",
    ],
)
def test_routes_surface_security_scan_separately_from_quickscan(
    text: str,
) -> None:
    command = CommandRouter().route(text)
    assert command is not None
    assert command.command_type is CommandType.SECURITY_SURFACE_SCAN
    assert command.local_only is True


def test_routes_deep_scan_and_preserves_target_case() -> None:
    command = CommandRouter().route(
        r'Deep scan "C:\Users\Austin\Downloads"'
    )
    assert command is not None
    assert command.command_type is CommandType.SECURITY_DEEP_SCAN
    assert command.target_path == r"C:\Users\Austin\Downloads"
    assert command.local_only is True


def test_routes_deep_level_wording() -> None:
    command = CommandRouter().route(
        r'Deep level security scan "C:\Temp"'
    )
    assert command is not None
    assert command.command_type is CommandType.SECURITY_DEEP_SCAN
    assert command.target_path == r"C:\Temp"


def test_deep_scan_placeholder_requires_explicit_path() -> None:
    command = CommandRouter().route("Deep scan this folder")
    assert command is not None
    assert command.command_type is CommandType.SECURITY_DEEP_SCAN
    assert command.target_path is None


@pytest.mark.parametrize(
    "text",
    [
        "Perform a full-system sweep",
        "Perform a full system sweep",
    ],
)
def test_routes_full_sweep_only_from_explicit_phrase(text: str) -> None:
    command = CommandRouter().route(text)
    assert command is not None
    assert command.command_type is CommandType.SECURITY_FULL_SWEEP
    assert command.local_only is True


def test_legacy_quickscan_stays_diagnostic() -> None:
    command = CommandRouter().route("quick scan")
    assert command is not None
    assert command.command_type is CommandType.QUICKSCAN
    assert command.local_only is False


def test_system_prompt_acknowledges_registered_local_scans() -> None:
    assert "user-authorized security scans" in AIDA_SYSTEM_PROMPT
    assert (
        "AIDA may only recommend non-invasive checks and manual user actions."
        not in AIDA_SYSTEM_PROMPT
    )
