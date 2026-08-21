from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import psutil

from aida.aegis.models import (
    PersistenceEntity,
    ProcessEntity,
    ProviderHealth,
    SecuritySnapshot,
)


ProviderHealthReader = Callable[[], ProviderHealth]


class AegisSystemSensor:
    """Bounded read-only machine security snapshot used by Aegis.

    Normal background observation deliberately excludes process command-line
    contents. Aegis only needs process identity, parentage, executable paths,
    and endpoint relationships for its current Early Alpha correlation model.
    More invasive evidence is collected only by existing targeted analysis
    paths when directly relevant to an investigation.
    """

    def __init__(
        self,
        *,
        provider_health_reader: ProviderHealthReader | None = None,
        max_processes: int = 4096,
        max_connections: int = 8192,
    ) -> None:
        self.provider_health_reader = provider_health_reader or (
            lambda: ProviderHealth()
        )
        self.max_processes = max(64, max_processes)
        self.max_connections = max(128, max_connections)

    def capture(self) -> SecuritySnapshot:
        errors: list[str] = []
        processes: list[ProcessEntity] = []
        connection_map: dict[int, dict[str, set[str]]] = {}
        listeners: set[str] = set()

        try:
            for index, connection in enumerate(psutil.net_connections(kind="inet")):
                if index >= self.max_connections:
                    errors.append("network_connection_limit_reached")
                    break
                pid = getattr(connection, "pid", None)
                local = getattr(connection, "laddr", None)
                remote = getattr(connection, "raddr", None)
                status = str(getattr(connection, "status", "") or "").upper()
                local_text = _endpoint(local)
                remote_text = _endpoint(remote)
                if status == "LISTEN" and local_text:
                    listeners.add(local_text)
                if pid is None:
                    continue
                record = connection_map.setdefault(
                    int(pid), {"remote": set(), "listen": set()}
                )
                if remote_text:
                    record["remote"].add(remote_text)
                if status == "LISTEN" and local_text:
                    record["listen"].add(local_text)
        except (psutil.AccessDenied, OSError):
            errors.append("network_snapshot_unavailable")

        try:
            iterator = psutil.process_iter(["pid", "ppid", "name", "exe"])
            for index, process in enumerate(iterator):
                if index >= self.max_processes:
                    errors.append("process_snapshot_limit_reached")
                    break
                try:
                    info = process.info
                    pid = int(info.get("pid") or process.pid)
                    executable = str(info.get("exe") or "")
                    network = connection_map.get(
                        pid, {"remote": set(), "listen": set()}
                    )
                    processes.append(
                        ProcessEntity(
                            pid=pid,
                            parent_pid=(
                                None
                                if info.get("ppid") is None
                                else int(info.get("ppid"))
                            ),
                            name=str(info.get("name") or ""),
                            executable=executable,
                            command_line="",
                            remote_endpoints=tuple(sorted(network["remote"])),
                            listening_endpoints=tuple(sorted(network["listen"])),
                        )
                    )
                except (
                    psutil.AccessDenied,
                    psutil.NoSuchProcess,
                    OSError,
                    TypeError,
                    ValueError,
                ):
                    continue
        except (psutil.Error, OSError):
            errors.append("process_snapshot_unavailable")

        persistence = _read_persistence(errors)
        try:
            health = self.provider_health_reader()
        except Exception:
            health = ProviderHealth()
            errors.append("provider_health_unavailable")

        return SecuritySnapshot.create(
            processes=tuple(processes),
            persistence=persistence,
            listeners=tuple(sorted(listeners)),
            provider_health=health,
            sensor_errors=tuple(dict.fromkeys(errors)),
        )


def _read_persistence(errors: list[str]) -> tuple[PersistenceEntity, ...]:
    if os.name != "nt":
        return ()

    output: list[PersistenceEntity] = []
    startup_dirs = (
        (
            "user_startup",
            Path(os.getenv("APPDATA", ""))
            / "Microsoft/Windows/Start Menu/Programs/Startup",
        ),
        (
            "machine_startup",
            Path(os.getenv("PROGRAMDATA", ""))
            / "Microsoft/Windows/Start Menu/Programs/StartUp",
        ),
    )
    for mechanism, folder in startup_dirs:
        if not str(folder).strip() or not folder.exists():
            continue
        try:
            for child in folder.iterdir():
                output.append(
                    PersistenceEntity(
                        mechanism=mechanism,
                        name=child.name,
                        target=str(child),
                    )
                )
        except OSError:
            errors.append(f"{mechanism}_unavailable")

    try:
        import winreg

        registry_locations = (
            (
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                "hkcu_run",
            ),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                "hklm_run",
            ),
            (
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
                "hkcu_run_once",
            ),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
                "hklm_run_once",
            ),
        )
        for hive, key_path, mechanism in registry_locations:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    index = 0
                    while True:
                        try:
                            name, value, _kind = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        index += 1
                        output.append(
                            PersistenceEntity(
                                mechanism=mechanism,
                                name=str(name),
                                target=str(value),
                            )
                        )
            except OSError:
                continue
    except (ImportError, OSError):
        errors.append("registry_persistence_unavailable")

    unique = {
        (item.mechanism, item.name, item.target): item for item in output
    }
    return tuple(unique[key] for key in sorted(unique))


def _endpoint(value: object) -> str:
    if not value:
        return ""
    host = getattr(value, "ip", None)
    port = getattr(value, "port", None)
    if host is None and isinstance(value, tuple) and value:
        host = value[0]
        port = value[1] if len(value) > 1 else None
    if not host:
        return ""
    return f"{host}:{port}" if port is not None else str(host)
