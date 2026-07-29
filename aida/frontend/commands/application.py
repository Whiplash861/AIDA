
from __future__ import annotations

from aida.applications.monitor import (
    ApplicationHealthMonitor,
    render_application_health,
)
from aida.applications.models import (
    ApplicationHealthAssessment,
    ApplicationHealthState,
    RepairAction,
)
from aida.applications.repair import (
    ApplicationRepairPlanner,
    render_repair_plan,
)
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)


class ApplicationHealthExecutor(CommandExecutor):
    def __init__(
        self,
        monitor: ApplicationHealthMonitor,
        application_name: str,
        memory: MemoryService | None = None,
    ) -> None:
        self.monitor = monitor
        self.application_name = application_name
        self.memory = memory

    @property
    def task_name(self) -> str:
        return "application_health"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.APPLICATION

    @property
    def start_message(self) -> str:
        return f"Inspecting {self.application_name} without changing the application."

    def execute(self) -> CommandResult:
        assessment = self.monitor.inspect(self.application_name)
        if self.memory is not None:
            self.memory.log_event(
                "APPLICATION_HEALTH_INSPECTED",
                "application.health",
                assessment.summary,
                payload={
                    "application_name": assessment.application_name,
                    "state": assessment.state.value,
                    "evidence": list(assessment.evidence),
                    "recommendations": list(assessment.recommendations),
                    "process_count": len(assessment.observations),
                },
                outcome=(
                    ProcessOutcome.SUCCEEDED
                    if assessment.state.value == "healthy"
                    else ProcessOutcome.PARTIAL
                ),
                confidence=assessment.confidence,
                promote=assessment.state.value != "healthy",
            )
        return CommandResult(
            transcript_text=render_application_health(assessment),
            speech_text=assessment.summary,
        )


class ApplicationRecoveryPlanExecutor(CommandExecutor):
    """Builds a deterministic recovery plan without executing it."""

    def __init__(
        self,
        planner: ApplicationRepairPlanner,
        application_name: str,
        action: RepairAction,
        memory: MemoryService | None = None,
    ) -> None:
        self.planner = planner
        self.application_name = application_name
        self.action = action
        self.memory = memory

    @property
    def task_name(self) -> str:
        return f"application_plan_{self.action.value}"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.APPLICATION

    @property
    def start_message(self) -> str:
        return (
            f"Preparing a local {self.action.value.replace('_', ' ')} plan "
            f"for {self.application_name}. No repair action will run yet."
        )

    def execute(self) -> CommandResult:
        assessment = ApplicationHealthAssessment(
            application_name=self.application_name,
            state=ApplicationHealthState.UNKNOWN,
            confidence=0.35,
            summary=(
                "A repair plan was requested before a complete health "
                "assessment was available."
            ),
            observations=(),
            evidence=("Direct user request for a recovery plan.",),
            recommendations=(),
        )
        plan = self.planner.propose(
            assessment,
            requested_action=self.action,
        )
        if self.memory is not None:
            self.memory.log_event(
                "APPLICATION_REPAIR_PLANNED",
                "application.recovery",
                plan.summary,
                payload={
                    "application_name": plan.application_name,
                    "action": plan.action.value,
                    "supported": plan.supported,
                    "requires_confirmation": plan.requires_confirmation,
                    "requires_elevation": plan.requires_elevation,
                    "destructive": plan.destructive,
                    "reason_unavailable": plan.reason_unavailable,
                },
                confidence=1.0,
                promote=True,
            )
        return CommandResult(
            transcript_text=render_repair_plan(plan),
            speech_text=(
                f"The {plan.action.value.replace('_', ' ')} plan is ready. "
                "No repair action was executed."
            ),
        )
