
from __future__ import annotations

import getpass
from enum import StrEnum

from aida.autonomy.controller import AutonomyController
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)


class AutonomyOperation(StrEnum):
    ENABLE = "enable"
    DISABLE = "disable"
    STATUS = "status"


class AutonomyCommandExecutor(CommandExecutor):
    def __init__(
        self,
        controller: AutonomyController,
        operation: AutonomyOperation,
    ) -> None:
        self.controller = controller
        self.operation = operation

    @property
    def task_name(self) -> str:
        return f"autonomy_{self.operation.value}"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.AUTONOMY

    @property
    def start_message(self) -> str:
        return {
            AutonomyOperation.ENABLE: (
                "Enabling Controlled Autonomy at Observation level."
            ),
            AutonomyOperation.DISABLE: (
                "Disabling autonomy and routing operational decisions to the user."
            ),
            AutonomyOperation.STATUS: "Reading autonomy policy status.",
        }[self.operation]

    @property
    def can_run_during_active(self) -> bool:
        return self.operation in {
            AutonomyOperation.DISABLE,
            AutonomyOperation.STATUS,
        }

    @property
    def locks_input(self) -> bool:
        return False

    def execute(self) -> CommandResult:
        user = _user()
        if self.operation is AutonomyOperation.ENABLE:
            settings = self.controller.set_enabled(True, changed_by=user)
            if not settings.enabled:
                return CommandResult(
                    transcript_text=(
                        "Controlled Autonomy was not enabled.\n\n"
                        "The autonomy kill switch is engaged. Release the kill "
                        "switch before enabling autonomy. Manual control remains active."
                    ),
                    speech_text=(
                        "Controlled Autonomy remains disabled because the kill "
                        "switch is engaged."
                    ),
                )
            text = (
                "Controlled Autonomy is enabled at Observation level.\n\n"
                "AIDA may monitor, report, and recover existing tasks. "
                "Autonomous Surface Scans remain disabled until Limited Triage "
                "is separately configured. Full Sweeps, cancellation, Stand Down, "
                "repairs, resets, cache clearing, and process termination remain manual."
            )
            return CommandResult(
                transcript_text=text,
                speech_text=(
                    "Controlled Autonomy enabled at Observation level. "
                    "Operational changes still require your authorization."
                ),
            )

        if self.operation is AutonomyOperation.DISABLE:
            self.controller.set_enabled(False, changed_by=user)
            return CommandResult(
                transcript_text=(
                    "Autonomy is disabled.\n\n"
                    "AIDA may continue observing and reporting, but every "
                    "operational decision will be routed to the user first, "
                    "regardless of severity."
                ),
                speech_text=(
                    "Autonomy disabled. All operational decisions now require you."
                ),
            )

        settings = self.controller.settings
        return CommandResult(
            transcript_text=(
                "AUTONOMY STATUS\n\n"
                f"Enabled: {'yes' if settings.enabled else 'no'}\n"
                f"Level: {settings.level.name.replace('_', ' ').title()}\n"
                + (
                    "Kill switch: engaged\n"
                    if settings.kill_switch_engaged
                    else "Kill switch: not engaged\n"
                )
                + f"Autonomous Surface Scan permission: "
                f"{'enabled' if settings.allow_autonomous_surface_scan else 'disabled'}\n"
                "Full-System Sweeps and remediation: manual only"
            ),
            speech_text=(
                f"Autonomy is {'enabled' if settings.enabled else 'disabled'} "
                f"at {settings.level.name.lower()} level."
            ),
        )


def _user() -> str:
    try:
        return getpass.getuser() or "local user"
    except (ImportError, KeyError, OSError):
        return "local user"
