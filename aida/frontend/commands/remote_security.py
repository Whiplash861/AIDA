from __future__ import annotations

from aida.reporting import render_report

from enum import StrEnum

from aida.aegis.engine import AegisEngine
from aida.aegis.remote.models import RemoteAccessClassification
from aida.aegis.remote.service import render_remote_intrusion_assessment
from aida.aegis.sentry.protocol import render_sentry_plan, render_sentry_result
from aida.authorization.confirmation import ConfirmationService
from aida.frontend.commands.base import CommandCategory, CommandExecutor, CommandResult


class RemoteSecurityOperation(StrEnum):
    INSPECT = "inspect"
    AUTHORIZE_SUPPORT = "authorize_support"
    LIST_SUPPORT = "list_support"
    REVOKE_SUPPORT = "revoke_support"
    CONFIRM_ATTACKER = "confirm_attacker"
    CONFIRM_SENTRY = "confirm_sentry"


class AegisRemoteSecurityExecutor(CommandExecutor):
    """Local command surface for Aegis remote intrusion and Sentry containment."""

    def __init__(
        self,
        engine: AegisEngine,
        operation: RemoteSecurityOperation,
        *,
        confirmations: ConfirmationService,
        slots: dict[str, object] | None = None,
        original_text: str = "",
    ) -> None:
        self.engine = engine
        self.operation = operation
        self.confirmations = confirmations
        self.slots = dict(slots or {})
        self.original_text = original_text

    @property
    def task_name(self) -> str:
        return f"aegis_remote_{self.operation.value}"

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SECURITY

    @property
    def start_message(self) -> str:
        return {
            RemoteSecurityOperation.INSPECT: (
                "Aegis is checking current remote-access sessions, security events, remote-control process lineage, baseline drift, provider evidence, and learned behavior."
            ),
            RemoteSecurityOperation.AUTHORIZE_SUPPORT: (
                "Aegis is creating a local, time-bounded remote-support authorization context."
            ),
            RemoteSecurityOperation.LIST_SUPPORT: (
                "Aegis is reading active remote-support authorizations."
            ),
            RemoteSecurityOperation.REVOKE_SUPPORT: (
                "Aegis is revoking the requested remote-support authorization context."
            ),
            RemoteSecurityOperation.CONFIRM_ATTACKER: (
                "Aegis is revalidating current remote-access evidence before preparing Sentry containment."
            ),
            RemoteSecurityOperation.CONFIRM_SENTRY: (
                "Sentry is revalidating the exact prepared containment plan."
            ),
        }[self.operation]

    @property
    def locks_input(self) -> bool:
        return False

    @property
    def can_run_during_active(self) -> bool:
        return self.operation in {
            RemoteSecurityOperation.INSPECT,
            RemoteSecurityOperation.CONFIRM_ATTACKER,
            RemoteSecurityOperation.CONFIRM_SENTRY,
        }

    def execute(self) -> CommandResult:
        if self.operation is RemoteSecurityOperation.INSPECT:
            return self._inspect()
        if self.operation is RemoteSecurityOperation.AUTHORIZE_SUPPORT:
            return self._authorize_support()
        if self.operation is RemoteSecurityOperation.LIST_SUPPORT:
            return self._list_support()
        if self.operation is RemoteSecurityOperation.REVOKE_SUPPORT:
            return self._revoke_support()
        if self.operation is RemoteSecurityOperation.CONFIRM_ATTACKER:
            return self._confirm_attacker()
        if self.operation is RemoteSecurityOperation.CONFIRM_SENTRY:
            return self._confirm_sentry()
        raise RuntimeError("Unknown remote security operation")

    def _inspect(self) -> CommandResult:
        service = getattr(self.engine, "remote_intrusion", None)
        if service is None:
            return _unavailable()
        assessment = service.inspect(
            unexpected_claim=bool(self.slots.get("unexpected_remote_access")),
        )
        text = render_remote_intrusion_assessment(assessment)
        if assessment.classification is RemoteAccessClassification.AUTHORIZED_SUPPORT:
            speech = (
                "Aegis found remote-access activity that matches an active support authorization. This does not prove every action is safe; stronger security evidence still needs review."
            )
        elif assessment.classification in {
            RemoteAccessClassification.SUPPORT_SESSION_ANOMALOUS,
            RemoteAccessClassification.LIKELY_INTRUSION,
        }:
            speech = (
                "Aegis found high-concern remote-access evidence. Review the assessment and verify whether the current access is authorized."
            )
        elif assessment.classification is RemoteAccessClassification.UNAUTHORIZED_SUSPECTED:
            speech = (
                "Aegis found remote-access evidence that does not currently have a sufficient authorized explanation. Verify whether you recognize the session."
            )
        elif assessment.classification is RemoteAccessClassification.NO_REMOTE_ACTIVITY:
            speech = "Aegis did not identify an active Remote Desktop session or recognized remote-control program in the information it could read. Review any incomplete checks."
        else:
            speech = "Aegis remote-access assessment complete. Review the local evidence and visibility notes."
        return CommandResult(transcript_text=text, speech_text=speech)

    def _authorize_support(self) -> CommandResult:
        support = getattr(self.engine, "remote_support", None)
        if support is None:
            return _unavailable()
        vendor = str(self.slots.get("support_vendor") or "").strip()
        if not vendor:
            return CommandResult(
                transcript_text="Remote support authorization was not created. Provide the company or support-session label.",
                speech_text="Tell me which company or support session you are authorizing.",
            )
        duration = int(self.slots.get("duration_minutes") or 120)
        expected_tools = _slot_values(self.slots.get("expected_tools"))
        authorization = support.authorize(
            vendor,
            duration_minutes=duration,
            expected_tools=expected_tools,
            expected_accounts=_slot_values(self.slots.get("expected_accounts")),
            expected_source_addresses=_slot_values(self.slots.get("expected_source_addresses")),
            note="Explicit local user authorization through AIDA.",
        )
        tools = (
            ", ".join(authorization.expected_tools)
            if authorization.expected_tools
            else "not specified"
        )
        transcript = render_report("Remote support authorization recorded",
            found=(f"Support label: {authorization.vendor_label}.",
                   f"Starts: {authorization.starts_at.isoformat()}; expires: {authorization.expires_at.isoformat()}.",
                   f"Expected programs: {tools}.",
                   f"Expected accounts: {', '.join(authorization.expected_accounts) or 'not specified'}.",
                   f"Expected client addresses: {', '.join(authorization.expected_source_addresses) or 'not specified'}."),
            unknown=("The authorization records what you expect. A company label or matching program name does not verify a particular session or operator.",
                     "Recording this authorization does not establish whether background monitoring is currently running."),
            next_steps=("Check that these details match the support you requested. Revoke the authorization when the work ends.",
                        "Use a remote-access check to review current activity. Stronger security evidence can still raise an alert during authorized support."),
            details=(f"Authorization ID: {authorization.authorization_id}",
                     "No antivirus exclusion, firewall exception, permanent trust decision, or training label was created."))
        return CommandResult(
            transcript_text=transcript,
            speech_text=(
                f"Remote support for {authorization.vendor_label} is recorded as expected for {duration} minutes. This does not verify the operator or disable security checks."
            ),
        )

    def _list_support(self) -> CommandResult:
        support = getattr(self.engine, "remote_support", None)
        if support is None:
            return _unavailable()
        active = support.active_authorizations()
        if not active:
            return CommandResult(
                transcript_text="AEGIS REMOTE SUPPORT AUTHORIZATIONS\n\nNo active remote-support authorization windows.",
                speech_text="There are no active remote support authorizations.",
            )
        lines = ["AEGIS REMOTE SUPPORT AUTHORIZATIONS", ""]
        for item in active:
            lines.extend(
                [
                    f"- {item.vendor_label}",
                    f"  ID: {item.authorization_id}",
                    f"  Expires: {item.expires_at.isoformat()}",
                    f"  Expected tools: {', '.join(item.expected_tools) if item.expected_tools else 'not specified'}",
                ]
            )
        return CommandResult(
            transcript_text=render_report("Active remote support authorizations",
                found=(f"{len(active)} support authorization window(s) are active.",),
                unknown=("An authorization records your expectation; it does not prove that an observed session belongs to the intended operator.",),
                next_steps=("Review the labels and expiry times below. Revoke a window when support finishes; revoking it does not disconnect the session.",),
                details=lines[2:]),
            speech_text=f"Aegis has {len(active)} active remote support authorization window{'s' if len(active) != 1 else ''}.",
        )

    def _revoke_support(self) -> CommandResult:
        support = getattr(self.engine, "remote_support", None)
        if support is None:
            return _unavailable()
        vendor = str(self.slots.get("support_vendor") or "").strip()
        try:
            revoked = support.revoke(vendor)
        except RuntimeError as exc:
            return CommandResult(
                transcript_text=f"Remote support authorization was not revoked.\n\n{exc}",
                speech_text="A unique active support authorization could not be resolved.",
            )
        return CommandResult(
            transcript_text=(
                "AEGIS REMOTE SUPPORT AUTHORIZATION REVOKED\n\n"
                f"Vendor / support label: {revoked.vendor_label}\n"
                f"Authorization ID: {revoked.authorization_id}\n\n"
                "Normal Aegis remote-access assessment now applies without that support context."
            ),
            speech_text=f"Remote support authorization for {revoked.vendor_label} has been revoked.",
        )

    def _confirm_attacker(self) -> CommandResult:
        service = getattr(self.engine, "remote_intrusion", None)
        sentry = getattr(self.engine, "sentry", None)
        if service is None or sentry is None:
            return _unavailable()
        assessment = service.inspect(
            unexpected_claim=True,
            user_confirmed_attacker=True,
        )
        assessment_text = render_remote_intrusion_assessment(assessment)
        if (
            assessment.classification is not RemoteAccessClassification.CONFIRMED_INTRUSION
            or not assessment.user_confirmed_attacker
        ):
            return CommandResult(
                transcript_text=(
                    assessment_text
                    + "\n\nSentry Attack Protocol was not prepared because Aegis could not revalidate a currently active RDP session or recognized remote-control process target. No containment action was taken."
                ),
                speech_text=(
                    "I recorded your report, but Aegis could not revalidate an active containment target. Sentry was not armed."
                ),
            )

        plan = sentry.prepare(assessment)
        scope = _sentry_scope(plan)
        action_id = _sentry_action_id(plan.plan_id)
        self.confirmations.create(
            action_id=action_id,
            summary="Execute Sentry Attack Protocol against the exact revalidated remote-session and process targets in this plan.",
            scope=scope,
            requested_by="local_user",
            required_phrase=plan.required_phrase,
            risk="high_impact_active_containment",
            ttl_seconds=120,
        )
        self.engine.bridge.publish(
            event_type="sentry_attack_plan_prepared",
            status="awaiting_confirmation",
            metadata={
                "sentry_plan_state": plan.state.value,
                "sentry_session_target_count": len(plan.session_targets),
                "sentry_process_target_count": len(plan.process_targets),
            },
        )
        return CommandResult(
            transcript_text=assessment_text + "\n\n" + render_sentry_plan(plan),
            speech_text=(
                "You reported unauthorized remote access, and Aegis identified current targets for a Sentry plan. Review the exact targets and confirmation phrase before approving containment."
            ),
        )

    def _confirm_sentry(self) -> CommandResult:
        sentry = getattr(self.engine, "sentry", None)
        if sentry is None:
            return _unavailable()
        plan_id = str(self.slots.get("sentry_plan_id") or "").strip()
        if not plan_id:
            return CommandResult(
                transcript_text="Sentry containment was not executed. No plan ID was supplied in the exact confirmation phrase.",
                speech_text="Sentry containment was not executed because the plan ID is missing.",
            )
        plan = sentry.load_plan(plan_id)
        if plan is None:
            return CommandResult(
                transcript_text=f"Sentry containment was not executed. Plan {plan_id} could not be loaded.",
                speech_text="Sentry could not load that containment plan.",
            )
        action_id = _sentry_action_id(plan.plan_id)
        scope = _sentry_scope(plan)
        try:
            confirmed = self.confirmations.confirm(
                action_id=action_id,
                phrase=self.original_text,
            )
            self.confirmations.consume(
                confirmed.confirmation_id,
                action_id=action_id,
                expected_scope=scope,
            )
        except RuntimeError as exc:
            return CommandResult(
                transcript_text=f"Sentry containment was not executed.\n\n{exc}",
                speech_text="The Sentry confirmation was invalid, expired, or no longer matched the prepared scope.",
            )

        try:
            result = sentry.execute(plan, confirmation_phrase=self.original_text)
        except RuntimeError as exc:
            return CommandResult(transcript_text=f"Sentry containment was not verified.\n\n{exc}",
                speech_text="Sentry containment was not verified. Review the local result.")
        self.engine.bridge.publish(
            event_type="sentry_attack_protocol_completed",
            status=result.state.value,
            metadata={
                "sentry_plan_state": result.state.value,
                "sentry_session_target_count": len(plan.session_targets),
                "sentry_process_target_count": len(plan.process_targets),
            },
        )
        return CommandResult(
            transcript_text=render_sentry_result(result),
            speech_text=(
                f"Sentry containment result: {result.state.value}. Review remaining activity and visibility limitations before running a follow-up Aegis scan."
            ),
        )


def _sentry_action_id(plan_id: str) -> str:
    return f"security.sentry.attack.{plan_id.lower()}"


def _sentry_scope(plan) -> dict[str, object]:
    return {
        "plan_id": plan.plan_id,
        "assessment_id": plan.assessment_id,
        "session_targets": [
            {
                "session_id": target.session_id,
                "username": target.username,
                "domain": target.domain,
                "client_address": target.client_address,
                "protocol_type": target.protocol_type,
                "logon_time": target.logon_time,
            }
            for target in plan.session_targets
        ],
        "process_targets": [
            {
                "pid": target.pid,
                "parent_pid": target.parent_pid,
                "name": target.name,
                "executable": target.executable,
                "create_time": target.create_time,
                "reason": target.reason,
                "tool_key": target.tool_key,
            }
            for target in plan.process_targets
        ],
    }


def _unavailable() -> CommandResult:
    return CommandResult(
        transcript_text=render_report("Remote-access check unavailable",
            found=("AIDA could not use its remote-access checking service in this session.",),
            unknown=("Current remote activity was not checked by this request.",),
            next_steps=("Review Windows Security and any remote-support programs you recognize. Restart AIDA and retry the check if the service should be available.",)),
        speech_text="Remote intrusion intelligence is not available in the current runtime.",
    )


def _slot_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (tuple, list)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()
