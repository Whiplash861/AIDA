from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aida.aegis.models import ProcessEntity, SecuritySnapshot
from aida.aegis.remote.models import RemoteToolEvidence


@dataclass(frozen=True, slots=True)
class RemoteToolProfile:
    key: str
    display_name: str
    process_hints: tuple[str, ...]


# Presence of one of these processes means "remote-support tooling may be
# available", not "an attacker is present". Many products keep a service or
# relay connection active even when nobody is controlling the machine.
_REMOTE_TOOL_PROFILES = (
    RemoteToolProfile(
        key="microsoft_quick_assist",
        display_name="Microsoft Quick Assist",
        process_hints=("quickassist.exe", "quickassist"),
    ),
    RemoteToolProfile(
        key="remote_assistance",
        display_name="Windows Remote Assistance",
        process_hints=("msra.exe",),
    ),
    RemoteToolProfile(
        key="teamviewer",
        display_name="TeamViewer",
        process_hints=("teamviewer.exe", "teamviewer_service.exe"),
    ),
    RemoteToolProfile(
        key="anydesk",
        display_name="AnyDesk",
        process_hints=("anydesk.exe",),
    ),
    RemoteToolProfile(
        key="screenconnect",
        display_name="ConnectWise Control / ScreenConnect",
        process_hints=(
            "screenconnect.clientservice.exe",
            "screenconnect.windowsclient.exe",
            "connectwisecontrol.client.exe",
        ),
    ),
    RemoteToolProfile(
        key="splashtop",
        display_name="Splashtop",
        process_hints=(
            "splashtopstreamer.exe",
            "srmanager.exe",
            "srservice.exe",
        ),
    ),
    RemoteToolProfile(
        key="logmein",
        display_name="LogMeIn",
        process_hints=("logmein.exe", "logmeinremoteusermodule.exe"),
    ),
    RemoteToolProfile(
        key="gotoassist",
        display_name="GoTo Resolve / GoToAssist",
        process_hints=("gotoassist.exe", "gotoassist_customer.exe"),
    ),
    RemoteToolProfile(
        key="beyondtrust",
        display_name="BeyondTrust Remote Support",
        process_hints=("bomgar-scc.exe", "bomgar-rep.exe", "beyondtrust.exe"),
    ),
    RemoteToolProfile(
        key="rustdesk",
        display_name="RustDesk",
        process_hints=("rustdesk.exe",),
    ),
)

_SECURITY_SENSITIVE_CHILDREN = frozenset(
    {
        "cmd.exe",
        "powershell.exe",
        "pwsh.exe",
        "wscript.exe",
        "cscript.exe",
        "mshta.exe",
        "rundll32.exe",
        "regsvr32.exe",
        "schtasks.exe",
        "sc.exe",
        "reg.exe",
        "net.exe",
        "net1.exe",
    }
)


def identify_remote_tools(snapshot: SecuritySnapshot) -> tuple[RemoteToolEvidence, ...]:
    by_pid = {process.pid: process for process in snapshot.processes}
    children: dict[int, list[ProcessEntity]] = {}
    for process in snapshot.processes:
        if process.parent_pid is not None:
            children.setdefault(process.parent_pid, []).append(process)

    output: list[RemoteToolEvidence] = []
    for process in snapshot.processes:
        profile = match_remote_tool(process)
        if profile is None:
            continue
        child_rows = tuple(children.get(process.pid, ()))
        sensitive = tuple(
            sorted(
                {
                    child.name.lower()
                    for child in child_rows
                    if child.name.lower() in _SECURITY_SENSITIVE_CHILDREN
                }
            )
        )
        output.append(
            RemoteToolEvidence(
                tool_key=profile.key,
                display_name=profile.display_name,
                pid=process.pid,
                parent_pid=process.parent_pid,
                name=process.name,
                executable=process.executable,
                create_time=process.create_time,
                remote_endpoints=process.remote_endpoints,
                listening_endpoints=process.listening_endpoints,
                child_pids=tuple(sorted(child.pid for child in child_rows)),
                security_sensitive_children=sensitive,
            )
        )
    return tuple(sorted(output, key=lambda item: (item.tool_key, item.pid)))


def match_remote_tool(process: ProcessEntity) -> RemoteToolProfile | None:
    candidates = {
        process.name.strip().lower(),
        Path(process.executable).name.strip().lower() if process.executable else "",
    }
    for profile in _REMOTE_TOOL_PROFILES:
        if any(hint in candidates for hint in profile.process_hints):
            return profile
    return None


def known_remote_tool_keys() -> tuple[str, ...]:
    return tuple(profile.key for profile in _REMOTE_TOOL_PROFILES)


def is_security_sensitive_child_name(name: str) -> bool:
    return name.strip().lower() in _SECURITY_SENSITIVE_CHILDREN
