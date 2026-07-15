from __future__ import annotations

from aida.config import AidaConfig
from aida.frontend.command_router import CommandType
from aida.frontend.commands.base import CommandExecutor
from aida.frontend.commands.quickscan import QuickscanExecutor


class CommandRegistry:
    """
    Maps recognized command types to their executors.
    """

    def __init__(self, config: AidaConfig) -> None:
        self._executors: dict[
            CommandType,
            CommandExecutor,
        ] = {
            CommandType.QUICKSCAN: QuickscanExecutor(
                config=config
            ),
        }

    def get(
        self,
        command_type: CommandType,
    ) -> CommandExecutor | None:
        return self._executors.get(command_type)

    def register(
        self,
        command_type: CommandType,
        executor: CommandExecutor,
    ) -> None:
        self._executors[command_type] = executor