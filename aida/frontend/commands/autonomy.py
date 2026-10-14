
from __future__ import annotations

import getpass
from enum import StrEnum

from aida.autonomy.controller import AutonomyController
from aida.reporting import render_report
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
                "Enabling automatic monitoring within the saved permissions."
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
            level = settings.level.name.replace('_', ' ').title()
            text = (
                f"Automatic monitoring is enabled at the {level} permission level.\n\n"
                "AIDA may observe and report within its saved permissions. "
                "Enabling monitoring does not itself start a scan or authorize a security response. "
                "Use 'autonomy status' to review the saved permissions."
            )
            return CommandResult(
                transcript_text=text,
                speech_text=(
                    f"Automatic monitoring enabled at the {level} permission level. "
                    "No security response was authorized by this change."
                ),
            )

        if self.operation is AutonomyOperation.DISABLE:
            self.controller.set_enabled(False, changed_by=user)
            return CommandResult(
                transcript_text=(
                    "Autonomy is disabled.\n\n"
                    "Automatic background observation is disabled. You can still request checks manually. "
                    "Disabling autonomy does not cancel an antivirus scan that is already running."
                ),
                speech_text=(
                    "Autonomy disabled. All operational decisions now require you."
                ),
            )

        settings = self.controller.settings
        return CommandResult(
            transcript_text=render_report("Automatic monitoring permissions",
                found=(f"Automatic monitoring is {'enabled' if settings.enabled else 'disabled'}.",
                       f"Permission level: {settings.level.name.replace('_', ' ').title()}.",
                       f"Emergency stop is {'engaged' if settings.kill_switch_engaged else 'not engaged'}.",
                       f"Permission for automatic Surface Scans: {'enabled' if settings.allow_autonomous_surface_scan else 'disabled'}.",
                       "Full-System Sweeps and threat-removal actions still require your authorization."),
                unknown=("These settings describe permission, not proof that each background check is running or that the computer is safe.",),
                next_steps=("Request a security status check to see what AIDA can currently read. Use 'disable autonomy' to turn off automatic background observation.",)),
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
