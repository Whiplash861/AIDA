from aida.frontend.command_router import CommandRouter, CommandType


def test_threat_navigation_and_assistance_intents_route_locally():
    router = CommandRouter()
    path = r'C:\Users\Austin\Downloads\sample.exe'

    assert router.route(f'analyze threat "{path}"').command_type is CommandType.THREAT_ANALYZE
    assert router.route(f'locate threat file "{path}"').command_type is CommandType.EVIDENCE_LOCATE
    assert router.route(f'open containing folder "{path}"').command_type is CommandType.EVIDENCE_OPEN_FOLDER
    assert router.route(f'prepare threat response "{path}"').command_type is CommandType.THREAT_RESPONSE_PLAN
    assert router.route(f'delete suspicious file "{path}"').command_type is CommandType.THREAT_DELETE_BLOCKED


def test_exact_remediation_confirmation_outranks_request_aliases():
    command = CommandRouter().route("confirm defender remediation")
    assert command.command_type is CommandType.THREAT_REMEDIATE_CONFIRM
    assert command.local_only is True
