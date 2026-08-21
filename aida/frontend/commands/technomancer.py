from __future__ import annotations

from collections.abc import Callable

from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult
from aida.frontend.engine_state import ENGINE_VISUAL_STATE
from aida.technomancer.engine import TechnomancerEngine
from aida.technomancer.models import TECHNOMANCER_COLOR


class TechnomancerCommandExecutor(CommandExecutor):
    """Runs one local Technomancer operation inside AIDA's normal command path."""

    def __init__(
        self,
        engine: TechnomancerEngine,
        mode: str,
        *,
        autonomy_enabled: Callable[[], bool] | None = None,
    ) -> None:
        self.engine = engine
        self.mode = mode
        self._autonomy_enabled = autonomy_enabled

    @property
    def task_name(self) -> str:
        return f"technomancer_{self.mode}"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.TECHNOMANCER

    @property
    def start_message(self) -> str:
        labels = {
            "health": "Technomancer machine-health analysis initiated.",
            "upgrades": "Technomancer upgrade-worthiness analysis initiated.",
            "inventory": "Technomancer hardware inventory initiated.",
            "advisories": "Technomancer advisory review initiated.",
            "background_on": "Technomancer background-monitoring authorization is being updated.",
            "background_off": "Technomancer background monitoring is being disabled.",
        }
        return labels.get(self.mode, "Technomancer initiated.")

    def execute(self) -> CommandResult:
        ENGINE_VISUAL_STATE.activate(
            "technomancer",
            TECHNOMANCER_COLOR,
            "RUNNING",
        )
        try:
            if self.mode == "health":
                text = self.engine.health_report()
            elif self.mode == "upgrades":
                text = self.engine.upgrade_report()
            elif self.mode == "inventory":
                text = self.engine.inventory_report()
            elif self.mode == "advisories":
                text = self.engine.advisory_report()
            elif self.mode == "background_on":
                self._sync_global_autonomy()
                text = self.engine.set_background_monitoring(True)
            elif self.mode == "background_off":
                text = self.engine.set_background_monitoring(False)
            else:
                text = "Technomancer did not recognize the requested operation."
        except Exception:
            ENGINE_VISUAL_STATE.deactivate("technomancer", "ERROR")
            raise
        else:
            ENGINE_VISUAL_STATE.deactivate("technomancer", "IDLE")

        first_line = next(
            (line.strip() for line in text.splitlines() if line.strip()),
            "Technomancer operation complete.",
        )
        return CommandResult(
            transcript_text=text,
            speech_text=first_line,
        )

    def _sync_global_autonomy(self) -> None:
        if self._autonomy_enabled is None:
            return
        self.engine.permissions.set_autonomy(bool(self._autonomy_enabled()))
