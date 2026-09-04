from __future__ import annotations

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
                "Aegis found remote-access activity consistent with an active authorized support window. Monitoring remains active, and the authorization will not suppress stronger security evidence."
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
            speech = "Aegis did not identify a currently active remote-access containment target in the observable evidence set."
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
        expected_tools = tuple(self.slots.get("expected_tools") or ())
        authorization = support.authorize(
            vendor,
            duration_minutes=duration,
            expected_tools=expected_tools,
            note="Explicit local user authorization through AIDA.",
        )
        tools = (
            ", ".join(authorization.expected_tools)
            if authorization.expected_tools
            else "not specified"
        )
        transcript = "\n".join(
            [
                "AEGIS REMOTE SUPPORT AUTHORIZATION",
                "",
                f"Vendor / support label: {authorization.vendor_label}",
                f"Authorization ID: {authorization.authorization_id}",
                f"Starts: {authorization.starts_at.isoformat()}",
                f"Expires: {authorization.expires_at.isoformat()}",
                f"Expected remote tool(s): {tools}",
                "",
                "This authorization gives Aegis context for distinguishing expected support from unexplained remote access.",
                "It does not create an antivirus exclusion, allow rule, firewall exception, or permanent trust decision.",
                "Strong malicious evidence can override the support context and produce an anomalous-support or intrusion alert.",
                "Support authorization is not used as machine-learning ground truth.",
            ]
        )
        return CommandResult(
            transcript_text=transcript,
            speech_text=(
                f"Remote support for {authorization.vendor_label} is authorized for {duration} minutes. Aegis will keep monitoring the session normally."
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
            transcript_text="\n".join(lines),
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
                "Aegis has confirmed your attacker declaration against current remote-access evidence and prepared Sentry containment. Review the plan and use the exact confirmation phrase only if you want Sentry to execute it."
            ),
        )

    def _confirm_sentry(self) -> CommandResult:
        sentry = getattr(self.engine, "sentry", None)
        if sentry is None:
            return _unavailable()
        plan_id = str(self.slots.get("sentry_plan_id") or "").strip().upper()
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

        result = sentry.execute(plan, confirmation_phrase=self.original_text)
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
                "Sentry containment has finished. Aegis should now run an Adaptive Security Scan to search for remaining footholds and determine whether a Full-System Sweep is warranted."
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
        transcript_text="Aegis Remote Intrusion Intelligence is not available in the current runtime.",
        speech_text="Remote intrusion intelligence is not available in the current runtime.",
    )
