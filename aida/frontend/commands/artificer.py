from __future__ import annotations

from aida.artificer.engine import ArtificerEngine
from aida.frontend.command_router import CommandType
from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult


class ArtificerCommandExecutor(CommandExecutor):
    def __init__(self, engine: ArtificerEngine, command_type: CommandType) -> None:
        self.engine = engine
        self.command_type = command_type

    @property
    def task_name(self) -> str:
        return {
            CommandType.ARTIFICER_STATUS: "artificer_status",
            CommandType.ARTIFICER_REVIEW: "artificer_review",
            CommandType.ARTIFICER_FINDINGS: "artificer_findings",
            CommandType.ARTIFICER_COMPATIBILITY: "artificer_compatibility",
            CommandType.ARTIFICER_EXPORT: "artificer_export",
            CommandType.ARTIFICER_OPEN: "artificer_open",
        }[self.command_type]

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.ARTIFICER

    @property
    def start_message(self) -> str:
        return {
            CommandType.ARTIFICER_REVIEW: "Artificer review initiated.",
            CommandType.ARTIFICER_EXPORT: "Artificer report export initiated.",
        }.get(self.command_type, "Artificer query received.")

    def execute(self) -> CommandResult:
        if self.command_type is CommandType.ARTIFICER_REVIEW:
            snapshot = self.engine.run_review()
            return CommandResult(
                transcript_text=self._status_text(snapshot),
                speech_text=(
                    "Artificer review complete. "
                    f"{len(snapshot.open_findings)} open findings recorded."
                ),
            )
        if self.command_type is CommandType.ARTIFICER_FINDINGS:
            findings = self.engine.snapshot().open_findings
            if not findings:
                return CommandResult("Artificer findings.\n\nNo open findings are recorded.")
            lines = ["Artificer findings.", ""]
            for finding in findings[:20]:
                lines.extend(
                    [
                        f"{finding.finding_id} — {finding.title}",
                        f"Severity: {finding.severity.upper()}",
                        f"Affected: {', '.join(finding.affected_components) or 'AIDA'}",
                        f"Finding: {finding.finding}",
                        f"Evidence: {finding.evidence_summary}",
                        f"Recommendation: {finding.recommended_change}",
                        f"Authority: {finding.authority_required.upper()}",
                        "",
                    ]
                )
            return CommandResult("\n".join(lines).strip())
        if self.command_type is CommandType.ARTIFICER_COMPATIBILITY:
            snapshot = self.engine.snapshot()
            lines = [
                "Platform compatibility report.",
                "",
                f"Platform: {snapshot.platform_summary}",
            ]
            lines.extend(
                f"{capability}: {status.upper()}"
                for capability, status in sorted(snapshot.compatibility_summary.items())
            )
            return CommandResult("\n".join(lines))
        if self.command_type is CommandType.ARTIFICER_EXPORT:
            path = self.engine.export_report()
            return CommandResult(
                transcript_text=f"Artificer report exported.\n\nLocation: {path}",
                speech_text="Artificer report export complete.",
            )
        if self.command_type is CommandType.ARTIFICER_OPEN:
            return CommandResult(
                transcript_text="Opening the Artificer Engine panel.",
                ui_action="open_artificer",
            )
        return CommandResult(self._status_text(self.engine.snapshot()))

    @staticmethod
    def _status_text(snapshot) -> str:
        return "\n".join(
            [
                "Artificer Engine status.",
                "",
                f"State: {snapshot.status.upper()}",
                f"Platform: {snapshot.platform_summary}",
                f"Last review: {snapshot.last_review_utc or 'Not completed'}",
                f"Open findings: {len(snapshot.open_findings)}",
                f"Pending proposals: {len(snapshot.pending_proposals)}",
                f"Dispatch queue: {snapshot.dispatch_queue_depth}",
                f"Telemetry: {snapshot.telemetry_level.upper()}",
            ]
        )
