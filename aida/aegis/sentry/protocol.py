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

        if (utc_now() - assessment.created_at).total_seconds() > 120:
            raise RuntimeError("The remote assessment expired; inspect and confirm current targets again")
        current_sessions, session_errors = enumerate_remote_desktop_sessions()
        session_targets = tuple(
            SentrySessionTarget(
                session_id=session.session_id,
                username=session.username,
                domain=session.domain,
                client_address=session.client_address,
                protocol_type=session.protocol_type,
                logon_time=session.logon_time,
            )
            for session in current_sessions
            if session.is_remote_interactive and session.is_active and session.logon_time is not None
            and session.username and session.domain and session.client_address
            and any(_session_matches(SentrySessionTarget(
                prior.session_id, prior.username, prior.domain, prior.client_address,
                prior.protocol_type, prior.logon_time), session) for prior in assessment.active_sessions)
        )

        snapshot = self.snapshot_reader()
        tools = identify_remote_tools(snapshot)
        by_pid = {process.pid: process for process in snapshot.processes}
        process_targets: list[SentryProcessTarget] = []
        seen: set[int] = set()
        assessed_tools = {(tool.pid, tool.create_time, _path_key(tool.executable)) for tool in assessment.remote_tools if tool.executable and tool.create_time is not None}
        for tool in tools:
            if (tool.pid, tool.create_time, _path_key(tool.executable)) not in assessed_tools:
                continue
            process = by_pid.get(tool.pid)
            if process is not None and process.executable and process.create_time is not None and tool.pid not in seen:
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
                if child is None or not child.executable or child.create_time is None or child.pid in seen:
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

        if not session_targets and not process_targets:
            raise RuntimeError("No unchanged, fully identified containment target could be prepared")
        if len(session_targets) + len(process_targets) > 32:
            raise RuntimeError("Containment exceeds the 32-target safety bound; a narrower reviewed scope is required")
        plan = SentryAttackPlan.create(
            assessment_id=assessment.assessment_id,
            session_targets=session_targets,
            process_targets=tuple(sorted(process_targets, key=lambda target: target.reason == "remote_control_process")),
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
            ) + tuple(session_errors) + tuple(snapshot.sensor_errors),
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
        executing = _plan_from_record(self.store.claim_sentry_plan(plan.to_record(), now=utc_now()))
        try:
            result = self._execute_claimed(executing)
        except Exception as exc:
            # Never make an interrupted/failed plan executable again. Individual
            # outcomes already recorded remain available for review.
            latest = self.load_plan(plan.plan_id) or executing
            self.store.store_sentry_plan(replace(latest, state=SentryAttackState.FAILED,
                updated_at=utc_now(), limitations=latest.limitations + (f"Execution interrupted: {type(exc).__name__}",)).to_record())
            investigations = getattr(self, "investigations", None)
            if investigations is not None:
                try:
                    investigations.record_sentry_interruption(plan)
                except Exception:
                    pass  # The consumed plan and partial outcomes remain in the native ledger.
            raise
        investigations = getattr(self, "investigations", None)
        if investigations is not None:
            try:
                investigations.record_sentry(plan, result)
            except Exception:
                # The native outcome and consumed authorization remain in the
                # authoritative Sentry ledger if the secondary journal fails.
                result = replace(result, details=result.details + ("The investigation journal is unavailable; the Sentry result remains in its execution ledger.",))
        return result

    def _execute_claimed(self, plan: SentryAttackPlan) -> SentryAttackResult:
        details: list[str] = []
        outcomes: list[dict[str, object]] = []
        incomplete = False
        session_attempted = session_terminated = process_attempted = process_terminated = 0

        def record(kind: str, identity: int, status: str) -> None:
            outcomes.append({"kind": kind, "identity": identity, "status": status,
                "at": utc_now().isoformat()})
            self.store.store_sentry_plan(replace(plan, updated_at=utc_now(), target_outcomes=tuple(outcomes)).to_record())

        for target in plan.session_targets:
            rows, errors = enumerate_remote_desktop_sessions()
            if errors:
                incomplete = True
                record("session", target.session_id, "identity_unavailable")
                continue
            current = next((row for row in rows if row.session_id == target.session_id), None)
            if current is None:
                record("session", target.session_id, "already_absent")
                continue
            if not _session_matches(target, current):
                incomplete = True
                record("session", target.session_id, "identity_changed_not_terminated")
                continue
            record("session", target.session_id, "logoff_requested")
            session_attempted += 1
            accepted = logoff_remote_desktop_session(target.session_id)
            session_terminated += int(accepted)
            incomplete = incomplete or not accepted
            record("session", target.session_id, "logoff_accepted" if accepted else "logoff_denied")

        for target in plan.process_targets:
            try:
                process = _revalidate_process(target)
            except (RuntimeError, psutil.Error, OSError):
                incomplete = True
                record("process", target.pid, "identity_unavailable_or_changed")
                continue
            if process is None:
                record("process", target.pid, "already_absent")
                continue
            record("process", target.pid, "termination_requested")
            process_attempted += 1
            stopped = _terminate_exact_process(process, target)
            process_terminated += int(stopped)
            incomplete = incomplete or not stopped
            record("process", target.pid, "terminated" if stopped else "termination_not_verified")

        verifying = replace(plan, state=SentryAttackState.VERIFYING, updated_at=utc_now(), target_outcomes=tuple(outcomes))
        self.store.store_sentry_plan(verifying.to_record())
        rows, errors = enumerate_remote_desktop_sessions()
        if errors:
            incomplete = True
            details.append("Final Remote Desktop visibility was unavailable or incomplete; absence is unverified.")
        remaining_sessions = sum(1 for row in rows if row.is_remote_interactive and row.is_active)
        for target in plan.session_targets:
            current = next((row for row in rows if row.session_id == target.session_id), None)
            outcomes.append({"kind": "session", "identity": target.session_id,
                "status": "verification_unavailable" if errors else "verified_absent" if current is None else "still_present_or_reused",
                "at": utc_now().isoformat()})
        remaining_process_targets = 0
        for target in plan.process_targets:
            try:
                present = _revalidate_process(target) is not None
                if present:
                    remaining_process_targets += 1
                outcomes.append({"kind": "process", "identity": target.pid,
                    "status": "still_present" if present else "verified_absent", "at": utc_now().isoformat()})
            except (RuntimeError, psutil.Error, OSError):
                incomplete = True
                remaining_process_targets += 1
                details.append(f"Process {target.pid} could not be verified absent with its approved identity.")
                outcomes.append({"kind": "process", "identity": target.pid,
                    "status": "verification_unavailable_or_reused", "at": utc_now().isoformat()})
        remaining_tools = ()
        try:
            snapshot = self.snapshot_reader()
            if snapshot.sensor_errors:
                incomplete = True
                details.append("Post-containment process evidence has visibility limitations.")
            targeted_tools = {target.tool_key for target in plan.process_targets if target.tool_key}
            remaining_tools = tuple(tool for tool in identify_remote_tools(snapshot) if tool.tool_key in targeted_tools)
            if remaining_tools:
                details.append(f"{len(remaining_tools)} targeted remote-tool instance(s) remain or restarted; no new process was automatically terminated.")
        except (RuntimeError, OSError, ValueError):
            incomplete = True
            details.append("Post-containment process collection failed.")
        completed = not incomplete and not remaining_sessions and not remaining_process_targets and not remaining_tools
        state = SentryAttackState.COMPLETED if completed else SentryAttackState.PARTIAL if session_attempted or process_attempted else SentryAttackState.FAILED
        details.extend(f"{item['kind']} {item['identity']}: {item['status']}" for item in outcomes)
        self.store.store_sentry_plan(replace(verifying, state=state, updated_at=utc_now(), target_outcomes=tuple(outcomes)).to_record())
        return SentryAttackResult(plan.plan_id, state, session_attempted, session_terminated,
            process_attempted, process_terminated, remaining_sessions, remaining_process_targets,
            tuple(details), verification_complete=not incomplete)


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
    lines.extend(["", "Exact targets requiring approval:"])
    for target in plan.session_targets:
        lines.append(f"- RDP {target.session_id}: {target.domain}\\{target.username}; client {target.client_address}; logon identity {target.logon_time}")
    for target in plan.process_targets:
        lines.append(f"- Process {target.pid}: {target.name}; {target.executable}; created {target.create_time}; parent {target.parent_pid}; {target.reason}")
    lines.append("Plan validity: two minutes from preparation; single use.")
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
        f"Verification complete: {'yes' if result.verification_complete else 'no; inspect visibility limitations'}",
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
    return bool(target.username and target.domain and target.client_address and target.logon_time
        and target.protocol_type == 2 and getattr(current, "protocol_type", None) == 2
        and getattr(current, "is_active", False)
        and getattr(current, "session_id", None) == target.session_id
        and str(getattr(current, "username", "")).casefold() == target.username.casefold()
        and str(getattr(current, "domain", "")).casefold() == target.domain.casefold()
        and str(getattr(current, "client_address", "")).casefold() == target.client_address.casefold()
        and getattr(current, "logon_time", None) == target.logon_time)


def _revalidate_process(target: SentryProcessTarget) -> psutil.Process | None:
    if target.pid <= 4 or target.name.strip().lower() in _CRITICAL_PROCESS_NAMES:
        raise RuntimeError("Process identity does not match the approved target")
    if not target.executable or target.create_time is None or target.parent_pid is None:
        raise RuntimeError("Process target identity is incomplete")
    try:
        process = psutil.Process(target.pid)
        name = process.name()
        executable = process.exe()
        create_time = process.create_time()
        parent_pid = process.ppid()
    except psutil.NoSuchProcess:
        return None
    if name.strip().lower() != target.name.strip().lower():
        raise RuntimeError("Process identity does not match the approved target")
    if target.executable and _path_key(executable) != _path_key(target.executable):
        raise RuntimeError("Process identity does not match the approved target")
    if float(create_time) != float(target.create_time):
        raise RuntimeError("Process identity does not match the approved target")
    if target.parent_pid is not None and parent_pid != target.parent_pid:
        raise RuntimeError("Process identity does not match the approved target")

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
            raise RuntimeError("Process identity does not match the approved target")
    elif target.reason == "remote_tool_security_sensitive_child":
        if not is_security_sensitive_child_name(name):
            raise RuntimeError("Process identity does not match the approved target")
    else:
        raise RuntimeError("Process identity does not match the approved target")
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
        RuntimeError,
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
        target_outcomes=tuple(record.get("target_outcomes") or ()),
        owner_process_id=record.get("owner_process_id"),
        owner_create_time=record.get("owner_create_time"),
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
