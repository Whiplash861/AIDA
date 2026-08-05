from __future__ import annotations

from aida.artificer.engine import ArtificerEngine
from aida.config import AidaConfig
from aida.frontend.command_router import CommandType
from aida.frontend.commands.artificer import ArtificerCommandExecutor
from aida.frontend.commands.base import CommandExecutor
from aida.frontend.commands.performance import PerformanceScanExecutor
from aida.frontend.commands.quickscan import QuickscanExecutor
from aida.frontend.commands.security import SecurityScanExecutor


class CommandRegistry:
    def __init__(self, config: AidaConfig, artificer: ArtificerEngine | None = None) -> None:
        self._executors: dict[CommandType, CommandExecutor] = {
            CommandType.QUICKSCAN: QuickscanExecutor(config=config),
            CommandType.PERFORMANCE_SCAN: PerformanceScanExecutor(artificer=artificer),
            CommandType.SECURITY_SCAN: SecurityScanExecutor(config=config),
        }
        if artificer is None:
            return

        for command_type in (
            CommandType.ARTIFICER_STATUS,
            CommandType.ARTIFICER_REVIEW,
            CommandType.ARTIFICER_FINDINGS,
            CommandType.ARTIFICER_COMPATIBILITY,
            CommandType.ARTIFICER_EXPORT,
            CommandType.ARTIFICER_OPEN,
        ):
            self._executors[command_type] = ArtificerCommandExecutor(
                engine=artificer, command_type=command_type
            )

    def get(self, command_type: CommandType) -> CommandExecutor | None:
        return self._executors.get(command_type)

    def register(self, command_type: CommandType, executor: CommandExecutor) -> None:
        self._executors[command_type] = executor
