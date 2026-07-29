
from aida.frontend.command_router import CommandRouter, CommandType

def test_router_understands_surface_synonyms():
    router=CommandRouter()
    assert router.route("perform a surface-level scan").command_type is CommandType.SECURITY_SURFACE_SCAN
    assert router.route("Start a surface scan").command_type is CommandType.SECURITY_SURFACE_SCAN
    assert router.route("Initiate low-level scan").command_type is CommandType.SECURITY_SURFACE_SCAN

def test_router_preserves_diagnostic_quickscan():
    assert CommandRouter().route("quick scan").command_type is CommandType.QUICKSCAN

def test_router_requests_scan_type_clarification():
    command=CommandRouter().route("run a scan")
    assert command.command_type is CommandType.INTENT_CLARIFICATION
    assert "What type of scan" in command.clarification_text

def test_router_extracts_deep_target():
    command=CommandRouter().route(r'deep scan "C:\Users\Austin\Downloads"')
    assert command.command_type is CommandType.SECURITY_DEEP_SCAN
    assert command.target_path==r"C:\Users\Austin\Downloads"

def test_control_command_classification():
    router=CommandRouter()
    assert router.is_control_command(router.route("cancel the scan")) is True
    assert router.is_control_command(router.route("disable autonomy")) is True

def test_router_maps_stand_down_to_registered_request_command():
    command = CommandRouter().route(
        r'stand down on "C:\Program Files\Example\example.exe"'
    )
    assert command.command_type is CommandType.STAND_DOWN_REQUEST
    assert command.target_path == r"C:\Program Files\Example\example.exe"
