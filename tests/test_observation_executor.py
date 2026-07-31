from aida.autonomy.controller import AutonomyController
from aida.autonomy.observation import AutonomyObservationService
from aida.frontend.commands.autonomy_observation import (
    SecurityObservationExecutor,
)
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.models import ProviderStatus
from aida.security.stand_down import StandDownService
from aida.security.windows.discovery import WindowsProviderDiscovery


class Provider:
    provider_id = "microsoft_defender"
    display_name = "Test Defender"

    def get_status(self):
        return ProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            healthy=True,
            active=True,
            real_time_protection=True,
            signatures_current=True,
        )

    def get_detection_snapshot(self):
        return []


class Cancellation:
    def active_cancelable_scan(self):
        return None


def _executor(tmp_path, *, announce: bool):
    database = MemoryDatabase(tmp_path / "memory.db")
    memory = MemoryService(
        database,
        user_id="Austin",
        device_id="Test-PC",
    )
    controller = AutonomyController(memory)
    controller.set_enabled(True, changed_by="Austin")
    observation = AutonomyObservationService(controller)
    provider = Provider()
    discovery = WindowsProviderDiscovery(
        provider=provider,
        products=(),
        selected_product=None,
        detail="test",
    )
    return SecurityObservationExecutor(
        observation,
        memory=memory,
        stand_down=StandDownService(database, memory),
        cancellation=Cancellation(),
        discovery_function=lambda: discovery,
        announce=announce,
    )


def test_healthy_scheduled_observation_is_silent_but_recorded(tmp_path):
    result = _executor(tmp_path, announce=False).execute()

    assert result.speech_text == ""
    assert "No operational action was executed" in result.transcript_text


def test_explicit_observation_announces_result(tmp_path):
    result = _executor(tmp_path, announce=True).execute()

    assert result.speech_text
    assert "No operational action" in result.speech_text
