from __future__ import annotations

from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult
from aida.technomancer.engine import TechnomancerEngine


class TechnomancerCommandExecutor(CommandExecutor):
    def __init__(self, engine: TechnomancerEngine, mode: str) -> None:
        self.engine = engine
        self.mode = mode

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
            "autonomy_on": "AIDA Autonomy is being enabled.",
            "autonomy_off": "AIDA Autonomy is being disabled.",
        }
        return labels.get(self.mode, "Technomancer initiated.")

    def execute(self) -> CommandResult:
        if self.mode == "health":
            text = self.engine.health_report()
        elif self.mode == "upgrades":
            text = self.engine.upgrade_report()
        elif self.mode == "inventory":
            text = self.engine.inventory_report()
        elif self.mode == "advisories":
            text = self.engine.advisory_report()
        elif self.mode == "background_on":
            text = self.engine.set_background_monitoring(True)
        elif self.mode == "background_off":
            text = self.engine.set_background_monitoring(False)
        elif self.mode == "autonomy_on":
            text = self.engine.set_autonomy(True)
        elif self.mode == "autonomy_off":
            text = self.engine.set_autonomy(False)
        else:
            text = "Technomancer did not recognize the requested operation."

        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "Technomancer operation complete.")
        return CommandResult(transcript_text=text, speech_text=first_line)
