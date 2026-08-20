from __future__ import annotations

from aida.config import AidaConfig
from aida.frontend.command_router import CommandType
from aida.frontend.commands.base import CommandExecutor
from aida.frontend.commands.performance import PerformanceScanExecutor
from aida.frontend.commands.quickscan import QuickscanExecutor
from aida.frontend.commands.technomancer import TechnomancerCommandExecutor
from aida.technomancer.engine import TechnomancerEngine


class CommandRegistry:
    """Maps recognized command types to their executors."""

    def __init__(self, config: AidaConfig) -> None:
        self.technomancer = TechnomancerEngine.from_config(config)
        self._executors: dict[CommandType, CommandExecutor] = {
            CommandType.QUICKSCAN: QuickscanExecutor(config=config),
            CommandType.PERFORMANCE_SCAN: PerformanceScanExecutor(),
            CommandType.TECHNOMANCER_HEALTH: TechnomancerCommandExecutor(self.technomancer, "health"),
            CommandType.TECHNOMANCER_UPGRADES: TechnomancerCommandExecutor(self.technomancer, "upgrades"),
            CommandType.TECHNOMANCER_INVENTORY: TechnomancerCommandExecutor(self.technomancer, "inventory"),
            CommandType.TECHNOMANCER_ADVISORIES: TechnomancerCommandExecutor(self.technomancer, "advisories"),
            CommandType.TECHNOMANCER_BACKGROUND_ON: TechnomancerCommandExecutor(self.technomancer, "background_on"),
            CommandType.TECHNOMANCER_BACKGROUND_OFF: TechnomancerCommandExecutor(self.technomancer, "background_off"),
            CommandType.AUTONOMY_ON: TechnomancerCommandExecutor(self.technomancer, "autonomy_on"),
            CommandType.AUTONOMY_OFF: TechnomancerCommandExecutor(self.technomancer, "autonomy_off"),
        }

    def get(self, command_type: CommandType) -> CommandExecutor | None:
        return self._executors.get(command_type)

    def register(self, command_type: CommandType, executor: CommandExecutor) -> None:
        self._executors[command_type] = executor
