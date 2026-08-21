from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psutil

from aida.technomancer.permissions import PermissionStore, TECHNOMANCER_BACKGROUND_SCOPE


def _pid_path(base_dir: str | Path) -> Path:
    return Path(base_dir) / "memory" / "technomancer.pid"


def background_pid(base_dir: str | Path) -> int | None:
    path = _pid_path(base_dir)
    if not path.exists():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if psutil.pid_exists(pid) else None


def launch_background(base_dir: str | Path, permissions: PermissionStore) -> tuple[bool, str]:
    if not permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE):
        return False, "Technomancer background monitoring requires both global Autonomy and the Technomancer background-monitoring scope."

    existing = background_pid(base_dir)
    if existing:
        return True, f"Technomancer background runtime is already active (PID {existing})."

    kwargs: dict = {
        "cwd": str(base_dir),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen([sys.executable, "-m", "aida.technomancer.runtime"], **kwargs)
    path = _pid_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(process.pid), encoding="utf-8")
    return True, f"Technomancer background runtime started (PID {process.pid})."


def stop_background(base_dir: str | Path) -> tuple[bool, str]:
    pid = background_pid(base_dir)
    path = _pid_path(base_dir)
    if pid is None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return True, "Technomancer background runtime is not active."

    try:
        process = psutil.Process(pid)
        process.terminate()
        try:
            process.wait(timeout=4)
        except psutil.TimeoutExpired:
            process.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return True, "Technomancer background runtime stopped."
