
from __future__ import annotations

import getpass
from enum import StrEnum

from aida.authorization.confirmation import ConfirmationService
from aida.frontend.commands.base import (
    CommandCategory,
    CommandExecutor,
    CommandResult,
)
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService
from aida.security.stand_down import StandDownService
from aida.security.windows.defender_cancel import DefenderCancellationService


class SecurityControlOperation(StrEnum):
    CANCEL_REQUEST = "cancel_request"
    CANCEL_CONFIRM = "cancel_confirm"
    STAND_DOWN_REQUEST = "stand_down_request"
    STAND_DOWN_CONFIRM = "stand_down_confirm"
    STAND_DOWN_LIST = "stand_down_list"


_CANCEL_ACTION = "security.scan.cancel"
_STAND_DOWN_ACTION = "security.stand_down.create"


class SecurityControlExecutor(CommandExecutor):
    def __init__(
        self,
        operation: SecurityControlOperation,
        *,
        confirmation_service: ConfirmationService,
        memory: MemoryService,
        cancellation_service: DefenderCancellationService,
        stand_down_service: StandDownService,
        original_text: str = "",
        target_path: str | None = None,
    ) -> None:
        self.operation = operation
        self.confirmations = confirmation_service
        self.memory = memory
        self.cancellation = cancellation_service
        self.stand_down = stand_down_service
        self.original_text = original_text
        self.target_path = target_path

    @property
    def task_name(self) -> str:
        return f"security_{self.operation.value}"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def start_message(self) -> str:
        return {
            SecurityControlOperation.CANCEL_REQUEST: (
                "Checking for an active Microsoft Defender scan that can be cancelled."
            ),
            SecurityControlOperation.CANCEL_CONFIRM: (
                "Validating the scan-cancellation confirmation."
            ),
            SecurityControlOperation.STAND_DOWN_REQUEST: (
                "Preparing a local Stand Down trust exception."
            ),
            SecurityControlOperation.STAND_DOWN_CONFIRM: (
                "Validating the Stand Down confirmation."
            ),
            SecurityControlOperation.STAND_DOWN_LIST: (
                "Reading active Stand Down exceptions."
            ),
        }[self.operation]

    @property
    def can_run_during_active(self) -> bool:
        return self.operation in {
            SecurityControlOperation.CANCEL_REQUEST,
            SecurityControlOperation.CANCEL_CONFIRM,
        }

    @property
    def locks_input(self) -> bool:
        return False

    def execute(self) -> CommandResult:
        if self.operation is SecurityControlOperation.CANCEL_REQUEST:
            return self._cancel_request()
        if self.operation is SecurityControlOperation.CANCEL_CONFIRM:
            return self._cancel_confirm()
        if self.operation is SecurityControlOperation.STAND_DOWN_REQUEST:
            return self._stand_down_request()
        if self.operation is SecurityControlOperation.STAND_DOWN_CONFIRM:
            return self._stand_down_confirm()
        return self._stand_down_list()

    def _cancel_request(self) -> CommandResult:
        scan = self.cancellation.active_cancelable_scan()
        if scan is None:
            return CommandResult(
                transcript_text=(
                    "No active Microsoft Defender Quick or Full Scan was found. "
                    "Targeted Custom Scans are not cancelled by this protocol."
                ),
                speech_text="No cancellable Defender scan was found.",
            )
        request = self.confirmations.create(
            action_id=_CANCEL_ACTION,
            summary=(
                f"Cancel the active Microsoft Defender {scan.mode.value.title()} Scan."
            ),
            scope={
                "scan_id": scan.scan_id,
                "mode": scan.mode.value,
                "started_at": scan.started_at,
            },
            requested_by=_user(),
            required_phrase="confirm scan cancellation",
            risk="high",
            ttl_seconds=120,
        )
        return CommandResult(
            transcript_text=(
                f"A Microsoft Defender {scan.mode.value.title()} Scan is active.\n\n"
                f"Provider Scan ID: {scan.scan_id}\n"
                f"Provider started: {scan.started_at or 'unknown'}\n\n"
                "Canceling will stop the scan before completion. "
                'Say "confirm scan cancellation" within two minutes to proceed.\n\n'
                f"Confirmation ID: {request.confirmation_id}"
            ),
            speech_text=(
                f"A Defender {scan.mode.value} scan is active. "
                "Say confirm scan cancellation to stop it before completion."
            ),
        )

    def _cancel_confirm(self) -> CommandResult:
        confirmed = self.confirmations.confirm(
            action_id=_CANCEL_ACTION,
            phrase=self.original_text,
        )
        consumed = self.confirmations.consume(
            confirmed.confirmation_id,
            action_id=_CANCEL_ACTION,
            expected_scope=confirmed.scope,
        )
        self.memory.record_authorization(
            action_id=_CANCEL_ACTION,
            scope=consumed.scope,
            granted_by=_user(),
            reason="Direct scan-cancellation confirmation",
            one_time=True,
        )
        current = self.cancellation.active_cancelable_scan()
        if current is None:
            return CommandResult(
                transcript_text=(
                    "Cancellation was not sent because no active cancellable scan remains. "
                    "The scan may have completed before confirmation."
                ),
                speech_text="The scan is no longer active.",
            )
        if current.scan_id != str(consumed.scope.get("scan_id")):
            return CommandResult(
                transcript_text=(
                    "Cancellation was blocked because the active provider Scan ID changed. "
                    "Request cancellation again for the current scan."
                ),
                speech_text="The active scan changed. Cancellation was blocked.",
            )
        result = self.cancellation.request_cancel(current)
        self.memory.log_event(
            "SCAN_CANCELLATION_REQUESTED",
            "security.scan",
            result.detail,
            payload={
                "scan_id": current.scan_id,
                "mode": current.mode.value,
                "requested": result.requested,
                "confirmed": result.confirmed,
                "exit_code": result.exit_code,
            },
            outcome=(
                ProcessOutcome.CANCELLED
                if result.confirmed
                else ProcessOutcome.PARTIAL
                if result.requested
                else ProcessOutcome.FAILED
            ),
            promote=True,
        )
        return CommandResult(
            transcript_text=(
                "SCAN CANCELLATION RESULT\n\n"
                f"Requested: {'yes' if result.requested else 'no'}\n"
                f"Provider-confirmed cancellation: {'yes' if result.confirmed else 'no'}\n"
                f"Detail: {result.detail}"
            ),
            speech_text=(
                "Microsoft Defender confirmed the scan was cancelled."
                if result.confirmed
                else "Cancellation was not confirmed. Review the transcript."
            ),
        )

    def _stand_down_request(self) -> CommandResult:
        if not self.target_path:
            return CommandResult(
                transcript_text=(
                    "Stand Down was not prepared. Provide one explicit local file path."
                ),
                speech_text="Provide the exact file path for Stand Down.",
            )
        request = self.confirmations.create(
            action_id=_STAND_DOWN_ACTION,
            summary=(
                "Create an AIDA-local user trust exception. This does not change "
                "Microsoft Defender settings or prove the file safe."
            ),
            scope={"target_path": self.target_path},
            requested_by=_user(),
            required_phrase="confirm stand down",
            risk="high",
            ttl_seconds=120,
        )
        return CommandResult(
            transcript_text=(
                "STAND DOWN — USER TRUST EXCEPTION\n\n"
                f"Target: {self.target_path}\n\n"
                "This will suppress repeated AIDA recommendations only while the exact "
                "file identity remains unchanged. It will not create a Defender exclusion, "
                "allow the item in Windows Security, or certify it as harmless.\n\n"
                'Say "confirm stand down" within two minutes to proceed.\n'
                f"Confirmation ID: {request.confirmation_id}"
            ),
            speech_text=(
                "Stand Down is ready. Say confirm stand down to create the local trust exception."
            ),
        )

    def _stand_down_confirm(self) -> CommandResult:
        confirmed = self.confirmations.confirm(
            action_id=_STAND_DOWN_ACTION,
            phrase=self.original_text,
        )
        consumed = self.confirmations.consume(
            confirmed.confirmation_id,
            action_id=_STAND_DOWN_ACTION,
            expected_scope=confirmed.scope,
        )
        target = str(consumed.scope["target_path"])
        self.memory.record_authorization(
            action_id=_STAND_DOWN_ACTION,
            scope=consumed.scope,
            granted_by=_user(),
            reason="Direct Stand Down confirmation",
            one_time=True,
        )
        record = self.stand_down.create(
            target,
            reason="Direct user override from the AIDA frontend",
            authorized_by=_user(),
        )
        return CommandResult(
            transcript_text=(
                "Stand Down exception recorded.\n\n"
                f"File: {record.path}\n"
                f"SHA-256: {record.sha256}\n"
                f"Status: User-trusted; not verified safe\n"
                f"Expires: {record.expires_at or 'no automatic expiration'}\n\n"
                "AIDA will resume assessment if the file identity changes, a new alarm "
                "appears, the exception expires, or the user explicitly scans the item."
            ),
            speech_text=(
                "Stand Down recorded. The item is user trusted, not verified safe."
            ),
        )

    def _stand_down_list(self) -> CommandResult:
        records = self.stand_down.list_active()
        if not records:
            return CommandResult(
                transcript_text="No active Stand Down exceptions are in effect.",
                speech_text="No active Stand Down exceptions are in effect.",
            )
        lines = ["ACTIVE STAND DOWN EXCEPTIONS", ""]
        for index, record in enumerate(records, start=1):
            lines.extend(
                [
                    f"{index}. {record.path.name}",
                    f"   Path: {record.path}",
                    f"   SHA-256: {record.sha256}",
                    f"   Authorized by: {record.authorized_by}",
                    f"   Expires: {record.expires_at or 'never'}",
                    "   Status: User-trusted; not verified safe",
                ]
            )
        return CommandResult(
            transcript_text="\n".join(lines),
            speech_text=f"{len(records)} Stand Down exceptions are active.",
        )


def _user() -> str:
    try:
        return getpass.getuser() or "local user"
    except (ImportError, KeyError, OSError):
        return "local user"
