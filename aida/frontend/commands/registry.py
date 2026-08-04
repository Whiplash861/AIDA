from __future__ import annotations

from collections.abc import Callable

from aida.applications.monitor import ApplicationHealthMonitor
from aida.applications.models import RepairAction
from aida.applications.repair import ApplicationRepairPlanner
from aida.authorization.confirmation import ConfirmationService
from aida.autonomy.controller import AutonomyController
from aida.autonomy.observation import AutonomyObservationService
from aida.config import AidaConfig
from aida.frontend.command_router import CommandType, RoutedCommand
from aida.frontend.commands.application import (
    ApplicationHealthExecutor,
    ApplicationRecoveryPlanExecutor,
)
from aida.frontend.commands.autonomy import (
    AutonomyCommandExecutor,
    AutonomyOperation,
)
from aida.frontend.commands.autonomy_observation import (
    SecurityObservationExecutor,
)
from aida.frontend.commands.base import CommandExecutor
from aida.frontend.commands.memory import (
    MemoryCommandExecutor,
    MemoryOperation,
)
from aida.frontend.commands.performance import PerformanceScanExecutor
from aida.frontend.commands.quickscan import QuickscanExecutor
from aida.frontend.commands.security import (
    SecurityScanExecutor,
    SecurityStatusExecutor,
)
from aida.frontend.commands.security_control import (
    SecurityControlExecutor,
    SecurityControlOperation,
)
from aida.frontend.commands.system import StaticResponseExecutor
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.continuity import SecurityTaskLedger
from aida.security.models import SecurityScanMode
from aida.security.stand_down import StandDownService
from aida.security.windows.defender_cancel import DefenderCancellationService


CommandFactory = Callable[[RoutedCommand], CommandExecutor]


class CommandRegistry:
    """Maps resolved local intents to fresh executor instances."""

    def __init__(
        self,
        config: AidaConfig,
        *,
        memory_service: MemoryService | None = None,
        autonomy_controller: AutonomyController | None = None,
        confirmation_service: ConfirmationService | None = None,
        cancellation_service: DefenderCancellationService | None = None,
        stand_down_service: StandDownService | None = None,
        task_ledger: SecurityTaskLedger | None = None,
        application_monitor: ApplicationHealthMonitor | None = None,
        application_repair_planner: ApplicationRepairPlanner | None = None,
    ) -> None:
        if memory_service is None:
            database = MemoryDatabase(config.memory_db_path)
            self.memory = MemoryService(database)
        else:
            self.memory = memory_service
            database = self.memory.database
        self.autonomy = autonomy_controller or AutonomyController(self.memory)
        self.observation = AutonomyObservationService(self.autonomy)
        self.confirmations = confirmation_service or ConfirmationService()
        self.cancellation = (
            cancellation_service or DefenderCancellationService()
        )
        self.stand_down = (
            stand_down_service
            or StandDownService(database, self.memory)
        )
        self.task_ledger = task_ledger or SecurityTaskLedger(
            database,
            user_id=self.memory.user_id,
            device_id=self.memory.device_id,
        )
        self.application_monitor = (
            application_monitor or ApplicationHealthMonitor()
        )
        self.application_repair_planner = (
            application_repair_planner or ApplicationRepairPlanner()
        )

        self._factories: dict[CommandType, CommandFactory] = {
            CommandType.QUICKSCAN: (
                lambda command: QuickscanExecutor(config=config)
            ),
            CommandType.PERFORMANCE_SCAN: (
                lambda command: PerformanceScanExecutor()
            ),
            CommandType.SECURITY_STATUS: (
                lambda command: SecurityStatusExecutor()
            ),
            CommandType.SECURITY_SURFACE_SCAN: (
                lambda command: self._security_scan(
                    SecurityScanMode.SURFACE,
                    command,
                )
            ),
            CommandType.SECURITY_DEEP_SCAN: (
                lambda command: self._security_scan(
                    SecurityScanMode.DEEP,
                    command,
                )
            ),
            CommandType.SECURITY_FULL_SWEEP: (
                lambda command: self._security_scan(
                    SecurityScanMode.FULL_SWEEP,
                    command,
                )
            ),
            CommandType.SECURITY_CANCEL_REQUEST: (
                lambda command: self._security_control(
                    SecurityControlOperation.CANCEL_REQUEST,
                    command,
                )
            ),
            CommandType.SECURITY_CANCEL_CONFIRM: (
                lambda command: self._security_control(
                    SecurityControlOperation.CANCEL_CONFIRM,
                    command,
                )
            ),
            CommandType.STAND_DOWN_REQUEST: (
                lambda command: self._security_control(
                    SecurityControlOperation.STAND_DOWN_REQUEST,
                    command,
                )
            ),
            CommandType.STAND_DOWN_CONFIRM: (
                lambda command: self._security_control(
                    SecurityControlOperation.STAND_DOWN_CONFIRM,
                    command,
                )
            ),
            CommandType.STAND_DOWN_REVOKE_REQUEST: (
                lambda command: self._security_control(
                    SecurityControlOperation.STAND_DOWN_REVOKE_REQUEST,
                    command,
                )
            ),
            CommandType.STAND_DOWN_REVOKE_CONFIRM: (
                lambda command: self._security_control(
                    SecurityControlOperation.STAND_DOWN_REVOKE_CONFIRM,
                    command,
                )
            ),
            CommandType.STAND_DOWN_LIST: (
                lambda command: self._security_control(
                    SecurityControlOperation.STAND_DOWN_LIST,
                    command,
                )
            ),
            CommandType.AUTONOMY_ENABLE: (
                lambda command: AutonomyCommandExecutor(
                    self.autonomy,
                    AutonomyOperation.ENABLE,
                )
            ),
            CommandType.AUTONOMY_DISABLE: (
                lambda command: AutonomyCommandExecutor(
                    self.autonomy,
                    AutonomyOperation.DISABLE,
                )
            ),
            CommandType.AUTONOMY_STATUS: (
                lambda command: AutonomyCommandExecutor(
                    self.autonomy,
                    AutonomyOperation.STATUS,
                )
            ),
            CommandType.AUTONOMY_OBSERVE_SECURITY: (
                lambda command: SecurityObservationExecutor(
                    self.observation,
                    memory=self.memory,
                    stand_down=self.stand_down,
                    cancellation=self.cancellation,
                    announce=command.user_initiated,
                )
            ),
            CommandType.MEMORY_SHOW: (
                lambda command: MemoryCommandExecutor(
                    self.memory,
                    MemoryOperation.SHOW,
                    slots=command.slots,
                )
            ),
            CommandType.MEMORY_SEARCH: (
                lambda command: MemoryCommandExecutor(
                    self.memory,
                    MemoryOperation.SEARCH,
                    slots=command.slots,
                )
            ),
            CommandType.MEMORY_ADD: (
                lambda command: MemoryCommandExecutor(
                    self.memory,
                    MemoryOperation.ADD,
                    slots=command.slots,
                )
            ),
            CommandType.MEMORY_DELETE: (
                lambda command: MemoryCommandExecutor(
                    self.memory,
                    MemoryOperation.DELETE,
                    slots=command.slots,
                )
            ),
            CommandType.MEMORY_REVISE: (
                lambda command: MemoryCommandExecutor(
                    self.memory,
                    MemoryOperation.REVISE,
                    slots=command.slots,
                )
            ),
            CommandType.APPLICATION_HEALTH: (
                lambda command: ApplicationHealthExecutor(
                    self.application_monitor,
                    str(command.slots.get("application_name") or ""),
                    memory=self.memory,
                )
            ),
            CommandType.APPLICATION_REPAIR_PLAN: (
                lambda command: ApplicationRecoveryPlanExecutor(
                    self.application_repair_planner,
                    str(command.slots.get("application_name") or ""),
                    RepairAction.APP_REPAIR,
                    memory=self.memory,
                )
            ),
            CommandType.APPLICATION_CACHE_PLAN: (
                lambda command: ApplicationRecoveryPlanExecutor(
                    self.application_repair_planner,
                    str(command.slots.get("application_name") or ""),
                    RepairAction.CACHE_CLEAR,
                    memory=self.memory,
                )
            ),
            CommandType.APPLICATION_RESTART_PLAN: (
                lambda command: ApplicationRecoveryPlanExecutor(
                    self.application_repair_planner,
                    str(command.slots.get("application_name") or ""),
                    RepairAction.GRACEFUL_RESTART,
                    memory=self.memory,
                )
            ),
            CommandType.INTENT_CLARIFICATION: (
                lambda command: StaticResponseExecutor(
                    command.clarification_text
                    or "Please clarify the requested operation.",
                    local_only=command.local_only,
                )
            ),
        }

    def _security_scan(
        self,
        mode: SecurityScanMode,
        command: RoutedCommand,
    ) -> SecurityScanExecutor:
        return SecurityScanExecutor(
            mode=mode,
            authorization_reason=command.original_text,
            target_path=(
                command.target_path
                if mode is SecurityScanMode.DEEP
                else None
            ),
            memory_service=self.memory,
            task_ledger=self.task_ledger,
            stand_down_service=self.stand_down,
            recovery_task_id=(
                str(command.slots.get("recovery_task_id"))
                if command.slots.get("recovery_task_id")
                else None
            ),
        )

    def _security_control(
        self,
        operation: SecurityControlOperation,
        command: RoutedCommand,
    ) -> SecurityControlExecutor:
        return SecurityControlExecutor(
            operation,
            confirmation_service=self.confirmations,
            memory=self.memory,
            cancellation_service=self.cancellation,
            stand_down_service=self.stand_down,
            task_ledger=self.task_ledger,
            original_text=command.original_text,
            target_path=command.target_path,
        )

    def resolve(
        self,
        command: RoutedCommand,
    ) -> CommandExecutor | None:
        factory = self._factories.get(command.command_type)
        return None if factory is None else factory(command)

    def get(
        self,
        command_type: CommandType,
    ) -> CommandExecutor | None:
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
