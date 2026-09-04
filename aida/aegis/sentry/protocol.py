from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import psutil

from aida.aegis.models import ProcessEntity, SecuritySnapshot
from aida.aegis.remote.models import (
    RemoteAccessClassification,
    RemoteIntrusionAssessment,
)
from aida.aegis.remote.store import RemoteSecurityStore
from aida.aegis.remote.tooling import (
    identify_remote_tools,
    is_security_sensitive_child_name,
    match_remote_tool,
)
from aida.aegis.remote.windows_sessions import (
    enumerate_remote_desktop_sessions,
    logoff_remote_desktop_session,
)
from aida.aegis.sentry.models import (
    SentryAttackPlan,
    SentryAttackResult,
    SentryAttackState,
    SentryProcessTarget,
    SentrySessionTarget,
    utc_now,
)


_CRITICAL_PROCESS_NAMES = frozenset(
    {
        "system",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "svchost.exe",
        "dwm.exe",
        "explorer.exe",
    }
)


class SentryAttackService:
    """Guarded active containment for user-confirmed remote intrusion.

    Phase 1 terminates only exact RDP sessions and exact remote-control process
    lineage captured in the plan. It does not disable network adapters, create
    firewall blocks, remove persistence, or delete files. Those require separate
    reversible designs because a remote endpoint may be legitimate relay
    infrastructure and blind isolation can lock out the local user or AIDA.
    """

    def __init__(
        self,
        *,
        store: RemoteSecurityStore,
        snapshot_reader,
    ) -> None:
        self.store = store
        self.snapshot_reader = snapshot_reader

    def prepare(self, assessment: RemoteIntrusionAssessment) -> SentryAttackPlan:
        if (
            assessment.classification is not RemoteAccessClassification.CONFIRMED_INTRUSION
            or not assessment.user_confirmed_attacker
        ):
            raise RuntimeError(
                "Sentry Attack Protocol requires an explicit local-user attacker confirmation."
            )

        current_sessions, _errors = enumerate_remote_desktop_sessions()
        session_targets = tuple(
            SentrySessionTarget(
                session_id=session.session_id,
                username=session.username,
                domain=session.domain,
                client_address=session.client_address,
                protocol_type=session.protocol_type,
            )
            for session in current_sessions
            if session.is_remote_interactive and session.is_active
        )

        snapshot = self.snapshot_reader()
        tools = identify_remote_tools(snapshot)
        by_pid = {process.pid: process for process in snapshot.processes}
        process_targets: list[SentryProcessTarget] = []
        seen: set[int] = set()
        for tool in tools:
            process = by_pid.get(tool.pid)
            if process is not None and tool.pid not in seen:
                seen.add(tool.pid)
                process_targets.append(
                    SentryProcessTarget(
                        pid=process.pid,
                        parent_pid=process.parent_pid,
                        name=process.name,
                        executable=process.executable,
                        create_time=process.create_time,
                        reason="remote_control_process",
                        tool_key=tool.tool_key,
                    )
                )
            for child_pid in tool.child_pids:
                child = by_pid.get(child_pid)
                if child is None or child.pid in seen:
                    continue
                if not is_security_sensitive_child_name(child.name):
                    continue
                seen.add(child.pid)
                process_targets.append(
                    SentryProcessTarget(
                        pid=child.pid,
                        parent_pid=child.parent_pid,
                        name=child.name,
                        executable=child.executable,
                        create_time=child.create_time,
                        reason="remote_tool_security_sensitive_child",
                        tool_key=tool.tool_key,
                    )
                )

        plan = SentryAttackPlan.create(
            assessment_id=assessment.assessment_id,
            session_targets=session_targets,
            process_targets=tuple(process_targets),
            rationale=(
                "The local user explicitly confirmed that the active remote access is unauthorized.",
                "Sentry will revalidate each exact session and process identity immediately before containment.",
                "Process targets are limited to recognized remote-control tooling and security-sensitive children directly captured from that lineage.",
            ),
            limitations=(
                "Phase 1 does not disable network adapters or create firewall block rules.",
                "Phase 1 does not delete files, remove persistence, or alter antivirus settings.",
                "A remote-control service may restart after process termination; verification reports that as remaining risk.",
                "A successful containment result does not prove that no secondary foothold exists; an Aegis security scan remains required afterward.",
            ),
        )
        self.store.store_sentry_plan(plan.to_record())
        return plan

    def load_plan(self, plan_id: str) -> SentryAttackPlan | None:
        record = self.store.get_sentry_plan_record(plan_id)
        if record is None:
            return None
        return _plan_from_record(record)

    def execute(self, plan: SentryAttackPlan, *, confirmation_phrase: str) -> SentryAttackResult:
        if _normalize(confirmation_phrase) != _normalize(plan.required_phrase):
            raise RuntimeError("The Sentry Attack Protocol confirmation phrase did not match.")
        if plan.state is not SentryAttackState.AWAITING_CONFIRMATION:
            raise RuntimeError("This Sentry Attack Protocol plan is not awaiting confirmation.")

        executing = replace(plan, state=SentryAttackState.EXECUTING, updated_at=utc_now())
        self.store.store_sentry_plan(executing.to_record())
        details: list[str] = []

        current_sessions, session_errors = enumerate_remote_desktop_sessions()
        if session_errors:
            details.append("Remote Desktop session revalidation was partially unavailable.")
        current_by_id = {session.session_id: session for session in current_sessions}
        session_attempted = 0
        session_terminated = 0
        for target in plan.session_targets:
            current = current_by_id.get(target.session_id)
            if current is None:
                details.append(f"RDP session {target.session_id} was already absent.")
                continue
            if not _session_matches(target, current):
                details.append(
                    f"RDP session {target.session_id} changed identity and was not terminated."
                )
                continue
            session_attempted += 1
            if logoff_remote_desktop_session(target.session_id):
                session_terminated += 1
            else:
                details.append(
                    f"Windows did not permit Sentry to log off RDP session {target.session_id}."
                )

        process_attempted = 0
        process_terminated = 0
        for target in plan.process_targets:
            process = _revalidate_process(target)
            if process is None:
                details.append(
                    f"Process target {target.pid} was absent or changed identity before containment."
                )
                continue
            process_attempted += 1
            if _terminate_exact_process(process, target):
                process_terminated += 1
            else:
                details.append(
                    f"Process target {target.pid} could not be terminated or failed exact safety checks."
                )

        verifying = replace(executing, state=SentryAttackState.VERIFYING, updated_at=utc_now())
        self.store.store_sentry_plan(verifying.to_record())

        remaining_sessions_rows, _ = enumerate_remote_desktop_sessions()
        remaining_session_ids = {
            session.session_id
            for session in remaining_sessions_rows
            if session.is_remote_interactive and session.is_active
        }
        remaining_sessions = sum(
            1 for target in plan.session_targets if target.session_id in remaining_session_ids
        )
        remaining_process_targets = sum(
            1 for target in plan.process_targets if _revalidate_process(target) is not None
        )

        post_snapshot = self.snapshot_reader()
        remaining_tools = identify_remote_tools(post_snapshot)
        remaining_sensitive = sum(
            1 for tool in remaining_tools if tool.security_sensitive_children
        )
        if remaining_sensitive:
            details.append(
                f"{remaining_sensitive} remote-control process lineage item(s) still have security-sensitive children after containment."
            )

        if remaining_sessions == 0 and remaining_process_targets == 0 and remaining_sensitive == 0:
            state = SentryAttackState.COMPLETED
        elif session_attempted or process_attempted:
            state = SentryAttackState.PARTIAL
        else:
            state = SentryAttackState.FAILED

        final_plan = replace(verifying, state=state, updated_at=utc_now())
        self.store.store_sentry_plan(final_plan.to_record())
        return SentryAttackResult(
            plan_id=plan.plan_id,
            state=state,
            session_attempted=session_attempted,
            session_terminated=session_terminated,
            process_attempted=process_attempted,
            process_terminated=process_terminated,
            remaining_sessions=remaining_sessions,
            remaining_process_targets=remaining_process_targets,
            details=tuple(details),
        )


def render_sentry_plan(plan: SentryAttackPlan) -> str:
    lines = [
        "SENTRY ATTACK PROTOCOL",
        "",
        f"Plan: {plan.plan_id}",
        f"Remote Desktop sessions targeted: {len(plan.session_targets)}",
        f"Exact process targets: {len(plan.process_targets)}",
        "",
        "Containment scope:",
        "- Revalidate and log off exact active RDP sessions captured in this plan.",
        "- Revalidate and terminate exact recognized remote-control process lineage captured in this plan.",
        "- Verify that targeted sessions/processes are no longer active.",
        "",
        "Sentry will NOT:",
        "- disable a network adapter",
        "- create firewall block rules",
        "- delete files",
        "- remove persistence",
        "- disable or reconfigure antivirus",
    ]
    if plan.limitations:
        lines.extend(["", "Limitations:"])
        lines.extend(f"- {item}" for item in plan.limitations)
    lines.extend(
        [
            "",
            "This is an active containment action and requires a fresh exact confirmation.",
            f"Type exactly: {plan.required_phrase}",
        ]
    )
    return "\n".join(lines)


def render_sentry_result(result: SentryAttackResult) -> str:
    lines = [
        "SENTRY ATTACK PROTOCOL RESULT",
        "",
        f"Plan: {result.plan_id}",
        f"State: {result.state.value.upper()}",
        f"RDP session termination: {result.session_terminated}/{result.session_attempted}",
        f"Process termination: {result.process_terminated}/{result.process_attempted}",
        f"Remaining targeted sessions: {result.remaining_sessions}",
        f"Remaining exact process targets: {result.remaining_process_targets}",
    ]
    if result.details:
        lines.extend(["", "Details:"])
        lines.extend(f"- {item}" for item in result.details)
    lines.extend(
        [
            "",
            "Containment does not prove the machine is clean. Run an Aegis Adaptive Security Scan immediately after Sentry containment, and escalate to a Full-System Sweep if Aegis recommends it.",
        ]
    )
    return "\n".join(lines)


def _session_matches(target: SentrySessionTarget, current: object) -> bool:
    if getattr(current, "session_id", None) != target.session_id:
        return False
    if int(getattr(current, "protocol_type", -1)) != 2 or target.protocol_type != 2:
        return False
    if target.username and str(getattr(current, "username", "")).lower() != target.username.lower():
        return False
    if target.domain and str(getattr(current, "domain", "")).lower() != target.domain.lower():
        return False
    if target.client_address:
        if str(getattr(current, "client_address", "")).lower() != target.client_address.lower():
            return False
    return True


def _revalidate_process(target: SentryProcessTarget) -> psutil.Process | None:
    if target.pid <= 4 or target.name.strip().lower() in _CRITICAL_PROCESS_NAMES:
        return None
    try:
        process = psutil.Process(target.pid)
        name = process.name()
        executable = process.exe()
        create_time = process.create_time()
        parent_pid = process.ppid()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return None
    if name.strip().lower() != target.name.strip().lower():
        return None
    if target.executable and _path_key(executable) != _path_key(target.executable):
        return None
    if target.create_time is not None and abs(float(create_time) - float(target.create_time)) > 1.0:
        return None
    if target.parent_pid is not None and parent_pid != target.parent_pid:
        return None

    entity = ProcessEntity(
        pid=target.pid,
        parent_pid=parent_pid,
        name=name,
        executable=executable,
        create_time=create_time,
    )
    if target.reason == "remote_control_process":
        profile = match_remote_tool(entity)
        if profile is None or (target.tool_key and profile.key != target.tool_key):
            return None
    elif target.reason == "remote_tool_security_sensitive_child":
        if not is_security_sensitive_child_name(name):
            return None
    else:
        return None
    return process


def _terminate_exact_process(process: psutil.Process, target: SentryProcessTarget) -> bool:
    if process.pid == os.getpid():
        return False
    try:
        process.terminate()
        try:
            process.wait(timeout=3.0)
            return True
        except psutil.TimeoutExpired:
            # Hard termination remains scoped to the exact PID/create-time/path
            # identity already revalidated above. Revalidate again to prevent
            # killing a recycled PID after the graceful termination request.
            again = _revalidate_process(target)
            if again is None:
                return True
            again.kill()
            again.wait(timeout=2.0)
            return True
    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.TimeoutExpired,
        OSError,
    ):
        return False


def _plan_from_record(record: dict[str, object]) -> SentryAttackPlan:
    return SentryAttackPlan(
        plan_id=str(record["plan_id"]),
        assessment_id=str(record["assessment_id"]),
        state=SentryAttackState(str(record["state"])),
        created_at=_parse(str(record["created_at"])),
        updated_at=_parse(str(record["updated_at"])),
        session_targets=tuple(
            SentrySessionTarget(**dict(item))
            for item in (record.get("session_targets") or ())
        ),
        process_targets=tuple(
            SentryProcessTarget(**dict(item))
            for item in (record.get("process_targets") or ())
        ),
        required_phrase=str(record["required_phrase"]),
        rationale=tuple(record.get("rationale") or ()),
        limitations=tuple(record.get("limitations") or ()),
    )


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _path_key(value: str) -> str:
    return os.path.normcase(os.path.normpath(str(Path(value)))).lower()
