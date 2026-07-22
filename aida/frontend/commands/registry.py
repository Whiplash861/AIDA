from __future__ import annotations

from collections.abc import Callable

from aida.config import AidaConfig
from aida.frontend.command_router import (
    CommandType,
    RoutedCommand,
)
from aida.frontend.commands.base import CommandExecutor
from aida.frontend.commands.performance import (
    PerformanceScanExecutor,
)
from aida.frontend.commands.quickscan import (
    QuickscanExecutor,
)
from aida.frontend.commands.security import (
    SecurityScanExecutor,
    SecurityStatusExecutor,
)
from aida.security.models import SecurityScanMode


CommandFactory = Callable[[RoutedCommand], CommandExecutor]


class CommandRegistry:
    """
    Maps recognized commands to fresh executor instances.
    """

    def __init__(self, config: AidaConfig) -> None:
        self._factories: dict[
            CommandType,
            CommandFactory,
        ] = {
            CommandType.QUICKSCAN: (
                lambda command: QuickscanExecutor(
                    config=config
                )
            ),
            CommandType.PERFORMANCE_SCAN: (
                lambda command: PerformanceScanExecutor()
            ),
            CommandType.SECURITY_STATUS: (
                lambda command: SecurityStatusExecutor()
            ),
            CommandType.SECURITY_SURFACE_SCAN: (
                lambda command: SecurityScanExecutor(
                    mode=SecurityScanMode.SURFACE,
                    authorization_reason=command.original_text,
                )
            ),
            CommandType.SECURITY_DEEP_SCAN: (
                lambda command: SecurityScanExecutor(
                    mode=SecurityScanMode.DEEP,
                    authorization_reason=command.original_text,
                    target_path=command.target_path,
                )
            ),
            CommandType.SECURITY_FULL_SWEEP: (
                lambda command: SecurityScanExecutor(
                    mode=SecurityScanMode.FULL_SWEEP,
                    authorization_reason=command.original_text,
                )
            ),
        }

    def resolve(
        self,
        command: RoutedCommand,
    ) -> CommandExecutor | None:
        factory = self._factories.get(
            command.command_type
        )
        if factory is None:
            return None
        return factory(command)

    def get(
        self,
        command_type: CommandType,
    ) -> CommandExecutor | None:
        """
        Backwards-compatible lookup for callers that do not have a
        routed command. Targeted commands should use resolve().
        """

        return self.resolve(
            RoutedCommand(
                command_type=command_type,
                original_text="",
            )
        )

    def register(
        self,
        command_type: CommandType,
        executor: CommandExecutor,
    ) -> None:
        self._factories[command_type] = (
            lambda command, registered=executor: registered
        )

    def register_factory(
        self,
        command_type: CommandType,
        factory: CommandFactory,
    ) -> None:
        self._factories[command_type] = factory
