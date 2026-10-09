from types import SimpleNamespace

import pytest

from aida.frontend.command_router import CommandRouter, CommandType
from aida.frontend.commands.technomancer import TechnomancerCommandExecutor
from aida.frontend.commands.base import CommandCategory
from aida.frontend.controller import AIDAController
from aida.frontend.engine_state import ENGINE_VISUAL_STATE


@pytest.mark.parametrize("phrase, expected", [
    ("Technomancer health", CommandType.TECHNOMANCER_HEALTH),
    ("Technomancer hardware", CommandType.TECHNOMANCER_HARDWARE),
    ("Technomancer upgrades", CommandType.TECHNOMANCER_UPGRADES),
    ("Technomancer advisories", CommandType.TECHNOMANCER_ADVISORIES),
])
def test_routes_local_engine_without_changing_visual_surface(phrase, expected):
    command = CommandRouter().route(phrase)
    assert command.command_type is expected
    assert command.local_only


def test_technomancer_uses_existing_diagnostics_status():
    statuses = []
    controller = AIDAController.__new__(AIDAController)
    controller.window = SimpleNamespace(set_diagnostics_status=statuses.append)
    controller._handle_command_status_changed("TECHNOMANCER", "RUNNING")
    controller._handle_command_status_changed("TECHNOMANCER", "ERROR")
    assert statuses == ["RUNNING", "ERROR"]


def test_engine_returns_through_aida_and_restores_foreground_on_failure():
    def failed():
        raise RuntimeError("test sensor unavailable")
    executor = TechnomancerCommandExecutor(SimpleNamespace(health_report=failed), "health")
    assert executor.category is CommandCategory.TECHNOMANCER
    with pytest.raises(RuntimeError):
        executor.execute()
    assert ENGINE_VISUAL_STATE.snapshot().key is None
    assert ENGINE_VISUAL_STATE.status("technomancer") == "ERROR"
