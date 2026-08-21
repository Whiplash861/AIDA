from __future__ import annotations

from collections.abc import Callable
from typing import Iterable

from aida.aegis.engine import AegisEngine
from aida.aegis.runtime import ensure_aegis_engine
from aida.aegis.scan_modes import AegisScanStrategy
from aida.applications.monitor import ApplicationHealthMonitor
from aida.applications.models import RepairAction
from aida.applications.repair import ApplicationRepairPlanner
from aida.assistance.planner import GuidedResponsePlanner
from aida.assistance.store import AssistanceTaskStore
from aida.authorization.confirmation import ConfirmationService
from aida.autonomy.controller import AutonomyController
from aida.autonomy.observation import AutonomyObservationService
from aida.config import AidaConfig
from aida.frontend.command_router import CommandType, RoutedCommand
from aida.frontend.commands.aegis import (
    AegisSecurityScanExecutor,
    AegisSecurityStatusExecutor,
)
from aida.frontend.commands.application import (
    ApplicationHealthExecutor,
    ApplicationRecoveryPlanExecutor,
)
from aida.frontend.commands.autonomy import (
    AutonomyCommandExecutor,
    AutonomyOperation,
)
from aida.frontend.commands.autonomy_observation import SecurityObservationExecutor
from aida.frontend.commands.base import CommandExecutor
from aida.frontend.commands.memory import MemoryCommandExecutor, MemoryOperation
from aida.frontend.commands.performance import PerformanceScanExecutor
from aida.frontend.commands.quickscan import QuickscanExecutor
from aida.frontend.commands.security import SecurityScanExecutor
from aida.frontend.commands.security_control import (
    SecurityControlExecutor,
    SecurityControlOperation,
)
from aida.frontend.commands.system import StaticResponseExecutor
from aida.frontend.commands.technomancer import TechnomancerCommandExecutor
from aida.frontend.commands.threat_assistance import (
    ThreatAssistanceExecutor,
    ThreatAssistanceOperation,
)
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.navigation.service import EvidenceNavigationService
from aida.security.continuity import SecurityTaskLedger
from aida.security.defender_remediation import DefenderRemediationService
from aida.security.models import ProviderDetection, SecurityScanMode
from aida.security.stand_down import StandDownService
from aida.security.threat_analysis import ThreatAnalysisService
from aida.security.windows.defender_cancel import DefenderCancellationService
from aida.security.windows.discovery import WindowsAntivirusDiscovery
from aida.technomancer.engine import TechnomancerEngine


CommandFactory = Callable[[RoutedCommand], CommandExecutor]
DetectionReader = Callable[[], Iterable[ProviderDetection]]


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
        threat_analysis_service: ThreatAnalysisService | None = None,
        navigation_service: EvidenceNavigationService | None = None,
        assistance_task_store: AssistanceTaskStore | None = None,
        response_planner: GuidedResponsePlanner | None = None,
        remediation_service: DefenderRemediationService | None = None,
        detection_reader: DetectionReader | None = None,
        aegis_engine: AegisEngine | None = None,
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
        self.cancellation = cancellation_service or DefenderCancellationService()
        self.threat_analysis = threat_analysis_service or ThreatAnalysisService(
            database,
            self.memory,
        )
        self.stand_down = stand_down_service or StandDownService(
            database,
            self.memory,
            identity_inspector=self.threat_analysis.inspect_identity,
        )
        self.task_ledger = task_ledger or SecurityTaskLedger(
            database,
            user_id=self.memory.user_id,
            device_id=self.memory.device_id,
        )
        self.navigation = navigation_service or EvidenceNavigationService(
            self.memory
        )
        self.assistance_tasks = assistance_task_store or AssistanceTaskStore(
            database,
            user_id=self.memory.user_id,
            device_id=self.memory.device_id,
        )
        self.response_planner = response_planner or GuidedResponsePlanner()
        self._detection_reader = detection_reader or _read_defender_detections
        self.remediation = remediation_service or DefenderRemediationService(
            snapshot_reader=self._detection_reader,
        )
        self.aegis = aegis_engine or ensure_aegis_engine(
            config,
            memory=self.memory,
            threat_analysis=self.threat_analysis,
            detection_reader=self._detection_reader,
        )
        self.application_monitor = application_monitor or ApplicationHealthMonitor()
        self.application_repair_planner = (
            application_repair_planner or ApplicationRepairPlanner()
        )
        self.technomancer = TechnomancerEngine.from_config(config)
        self.technomancer.permissions.set_autonomy(self._autonomy_gate())

        self._factories: dict[CommandType, CommandFactory] = {
            CommandType.QUICKSCAN: lambda command: QuickscanExecutor(config=config),
            CommandType.PERFORMANCE_SCAN: lambda command: PerformanceScanExecutor(),
            CommandType.SECURITY_STATUS: lambda command: AegisSecurityStatusExecutor(
                self.aegis
            ),
            CommandType.SECURITY_INTELLIGENT_SCAN: lambda command: self._aegis_scan(
                AegisScanStrategy.ADAPTIVE, command
            ),
            CommandType.SECURITY_SURFACE_SCAN: lambda command: self._aegis_scan(
                AegisScanStrategy.SURFACE, command
            ),
            CommandType.SECURITY_DEEP_SCAN: lambda command: self._aegis_scan(
                AegisScanStrategy.DEEP, command
            ),
            CommandType.SECURITY_FULL_SWEEP: lambda command: self._aegis_scan(
                AegisScanStrategy.FULL, command
            ),
            CommandType.SECURITY_CANCEL_REQUEST: lambda command: self._security_control(
                SecurityControlOperation.CANCEL_REQUEST, command
            ),
            CommandType.SECURITY_CANCEL_CONFIRM: lambda command: self._security_control(
                SecurityControlOperation.CANCEL_CONFIRM, command
            ),
            CommandType.STAND_DOWN_REQUEST: lambda command: self._security_control(
                SecurityControlOperation.STAND_DOWN_REQUEST, command
            ),
            CommandType.STAND_DOWN_CONFIRM: lambda command: self._security_control(
                SecurityControlOperation.STAND_DOWN_CONFIRM, command
            ),
            CommandType.STAND_DOWN_REVOKE_REQUEST: lambda command: self._security_control(
                SecurityControlOperation.STAND_DOWN_REVOKE_REQUEST, command
            ),
            CommandType.STAND_DOWN_REVOKE_CONFIRM: lambda command: self._security_control(
                SecurityControlOperation.STAND_DOWN_REVOKE_CONFIRM, command
            ),
            CommandType.STAND_DOWN_LIST: lambda command: self._security_control(
                SecurityControlOperation.STAND_DOWN_LIST, command
            ),
            CommandType.AUTONOMY_ENABLE: lambda command: AutonomyCommandExecutor(
                self.autonomy, AutonomyOperation.ENABLE
            ),
            CommandType.AUTONOMY_DISABLE: lambda command: AutonomyCommandExecutor(
                self.autonomy, AutonomyOperation.DISABLE
            ),
            CommandType.AUTONOMY_STATUS: lambda command: AutonomyCommandExecutor(
                self.autonomy, AutonomyOperation.STATUS
            ),
            CommandType.AUTONOMY_OBSERVE_SECURITY: lambda command: SecurityObservationExecutor(
                self.observation,
                memory=self.memory,
                stand_down=self.stand_down,
                cancellation=self.cancellation,
                threat_analysis=self.threat_analysis,
                assistance_tasks=self.assistance_tasks,
                response_planner=self.response_planner,
                announce=command.user_initiated,
            ),
            CommandType.MEMORY_SHOW: lambda command: MemoryCommandExecutor(
                self.memory, MemoryOperation.SHOW, slots=command.slots
            ),
            CommandType.MEMORY_SEARCH: lambda command: MemoryCommandExecutor(
                self.memory, MemoryOperation.SEARCH, slots=command.slots
            ),
            CommandType.MEMORY_ADD: lambda command: MemoryCommandExecutor(
                self.memory, MemoryOperation.ADD, slots=command.slots
            ),
            CommandType.MEMORY_DELETE: lambda command: MemoryCommandExecutor(
                self.memory, MemoryOperation.DELETE, slots=command.slots
            ),
            CommandType.MEMORY_REVISE: lambda command: MemoryCommandExecutor(
                self.memory, MemoryOperation.REVISE, slots=command.slots
            ),
            CommandType.APPLICATION_HEALTH: lambda command: ApplicationHealthExecutor(
                self.application_monitor,
                str(command.slots.get("application_name") or ""),
                memory=self.memory,
            ),
            CommandType.APPLICATION_REPAIR_PLAN: lambda command: ApplicationRecoveryPlanExecutor(
                self.application_repair_planner,
                str(command.slots.get("application_name") or ""),
                RepairAction.APP_REPAIR,
                memory=self.memory,
            ),
            CommandType.APPLICATION_CACHE_PLAN: lambda command: ApplicationRecoveryPlanExecutor(
                self.application_repair_planner,
                str(command.slots.get("application_name") or ""),
                RepairAction.CACHE_CLEAR,
                memory=self.memory,
            ),
            CommandType.APPLICATION_RESTART_PLAN: lambda command: ApplicationRecoveryPlanExecutor(
                self.application_repair_planner,
                str(command.slots.get("application_name") or ""),
                RepairAction.GRACEFUL_RESTART,
                memory=self.memory,
            ),
            CommandType.THREAT_ANALYZE: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.ANALYZE, command
            ),
            CommandType.EVIDENCE_LOCATE: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.LOCATE, command
            ),
            CommandType.EVIDENCE_OPEN_FOLDER: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.OPEN_LOCATION, command
            ),
            CommandType.EVIDENCE_SELECT: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.SELECT_IN_EXPLORER, command
            ),
            CommandType.THREAT_RESPONSE_PLAN: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.RESPONSE_PLAN, command
            ),
            CommandType.THREAT_REMEDIATE_REQUEST: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.REMEDIATION_REQUEST, command
            ),
            CommandType.THREAT_REMEDIATE_CONFIRM: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.REMEDIATION_CONFIRM, command
            ),
            CommandType.THREAT_DELETE_BLOCKED: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.DELETE_BLOCKED, command
            ),
            CommandType.THREAT_CENTER_SHOW: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.THREAT_CENTER_SUMMARY, command
            ),
            CommandType.TASK_CENTER_SHOW: lambda command: self._threat_assistance(
                ThreatAssistanceOperation.TASK_CENTER_SUMMARY, command
            ),
            CommandType.TECHNOMANCER_HEALTH: lambda command: self._technomancer(
                "health"
            ),
            CommandType.TECHNOMANCER_HARDWARE: lambda command: self._technomancer(
                "inventory"
            ),
            CommandType.TECHNOMANCER_UPGRADES: lambda command: self._technomancer(
                "upgrades"
            ),
            CommandType.TECHNOMANCER_ADVISORIES: lambda command: self._technomancer(
                "advisories"
            ),
            CommandType.TECHNOMANCER_BACKGROUND_ENABLE: lambda command: self._technomancer(
                "background_on"
            ),
            CommandType.TECHNOMANCER_BACKGROUND_DISABLE: lambda command: self._technomancer(
                "background_off"
            ),
            CommandType.INTENT_CLARIFICATION: lambda command: StaticResponseExecutor(
                command.clarification_text
                or "Please clarify the requested operation.",
                local_only=command.local_only,
            ),
        }

    def _autonomy_gate(self) -> bool:
        settings = self.autonomy.settings
        return bool(settings.enabled and not settings.kill_switch_engaged)

    def _technomancer(self, mode: str) -> TechnomancerCommandExecutor:
        return TechnomancerCommandExecutor(
            self.technomancer,
            mode,
            autonomy_enabled=self._autonomy_gate,
        )

    def _aegis_scan(
        self,
        strategy: AegisScanStrategy,
        command: RoutedCommand,
    ) -> AegisSecurityScanExecutor:
        return AegisSecurityScanExecutor(
            self.aegis,
            strategy,
            lambda: self._security_scan(strategy.provider_mode, command),
        )

    def _security_scan(
        self, mode: SecurityScanMode, command: RoutedCommand
    ) -> SecurityScanExecutor:
        return SecurityScanExecutor(
            mode=mode,
            authorization_reason=command.original_text,
            target_path=(command.target_path if mode is SecurityScanMode.DEEP else None),
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
        self, operation: SecurityControlOperation, command: RoutedCommand
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

    def _threat_assistance(
        self, operation: ThreatAssistanceOperation, command: RoutedCommand
    ) -> ThreatAssistanceExecutor:
        return ThreatAssistanceExecutor(
            operation,
            analysis=self.threat_analysis,
            navigation=self.navigation,
            planner=self.response_planner,
            tasks=self.assistance_tasks,
            memory=self.memory,
            confirmations=self.confirmations,
            remediation=self.remediation,
            stand_down=self.stand_down,
            detection_reader=self._detection_reader,
            target_path=command.target_path,
            original_text=command.original_text,
        )

    def resolve(self, command: RoutedCommand) -> CommandExecutor | None:
        factory = self._factories.get(command.command_type)
        return None if factory is None else factory(command)

    def get(self, command_type: CommandType) -> CommandExecutor | None:
        return self.resolve(RoutedCommand(command_type=command_type, original_text=""))

    def register(self, command_type: CommandType, executor: CommandExecutor) -> None:
        self._factories[command_type] = (
            lambda command, registered=executor: registered
        )

    def register_factory(
        self, command_type: CommandType, factory: CommandFactory
    ) -> None:
        self._factories[command_type] = factory


def _read_defender_detections() -> tuple[ProviderDetection, ...]:
    discovery = WindowsAntivirusDiscovery().discover()
    getter = getattr(discovery.provider, "get_detection_snapshot", None)
    if not callable(getter):
        return ()
    return tuple(getter() or ())
