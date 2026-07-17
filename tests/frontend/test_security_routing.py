from aida.frontend.command_router import CommandRouter, CommandType


def test_routes_security_status() -> None:
    command = CommandRouter().route("Check antivirus status")
    assert command is not None
    assert command.command_type is CommandType.SECURITY_STATUS
    assert command.local_only is True


def test_routes_surface_security_scan_separately_from_quickscan() -> None:
    command = CommandRouter().route("Run a surface-level security scan")
    assert command is not None
    assert command.command_type is CommandType.SECURITY_SURFACE_SCAN


def test_routes_deep_scan_and_preserves_target_case() -> None:
    command = CommandRouter().route(
        'Deep scan "C:\\Users\\Austin\\Downloads"'
    )
    assert command is not None
    assert command.command_type is CommandType.SECURITY_DEEP_SCAN
    assert command.target_path == r"C:\Users\Austin\Downloads"
    assert command.local_only is True


def test_deep_scan_placeholder_requires_explicit_path() -> None:
    command = CommandRouter().route("Deep scan this folder")
    assert command is not None
    assert command.command_type is CommandType.SECURITY_DEEP_SCAN
    assert command.target_path is None


def test_routes_full_sweep_only_from_explicit_phrase() -> None:
    command = CommandRouter().route("Perform a full-system sweep")
    assert command is not None
    assert command.command_type is CommandType.SECURITY_FULL_SWEEP


def test_legacy_quickscan_stays_diagnostic() -> None:
    command = CommandRouter().route("quick scan")
    assert command is not None
    assert command.command_type is CommandType.QUICKSCAN
    assert command.local_only is False
