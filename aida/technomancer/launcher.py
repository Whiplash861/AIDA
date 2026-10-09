from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psutil
from aida.artificer.state_file import locked_state, write_json
from aida.technomancer.permissions import PermissionStore, TECHNOMANCER_BACKGROUND_SCOPE


def data_directory() -> Path:
    from aida.config import _user_data_root
    return _user_data_root() / "technomancer"


def _pid_path(base_dir: str | Path, *, data_dir=None) -> Path:
    return Path(data_dir or data_directory()) / "runtime.json"


def _verified_process(path: Path):
    marker = json.loads(path.read_text(encoding="utf-8"))
    process = psutil.Process(int(marker["pid"]))
    arguments = process.cmdline()
    index = arguments.index("-m")
    if (process.create_time() != marker["create_time"]
            or os.path.normcase(str(Path(process.exe()).resolve())) != os.path.normcase(str(Path(marker["executable"]).resolve()))
            or arguments[index + 1] != "aida.technomancer.runtime"
            or "--data-dir" not in arguments
            or Path(arguments[arguments.index("--data-dir") + 1]).resolve() != path.parent.resolve()):
        raise ValueError("Runtime process identity no longer matches")
    return process


def background_pid(base_dir: str | Path, *, data_dir=None) -> int | None:
    try:
        return _verified_process(_pid_path(base_dir, data_dir=data_dir)).pid
    except (OSError, ValueError, KeyError, IndexError, TypeError, psutil.Error):
        return None


def write_runtime_marker(path: Path, pid: int) -> None:
    process = psutil.Process(pid)
    write_json(path, {"pid": pid, "create_time": process.create_time(), "executable": process.exe()})


def launch_background(base_dir, permissions: PermissionStore, *, data_dir=None):
    if not permissions.permitted(TECHNOMANCER_BACKGROUND_SCOPE):
        return False, "Technomancer background monitoring requires global Autonomy and its monitoring scope."
    path = _pid_path(base_dir, data_dir=data_dir)
    with locked_state(path):
        existing = background_pid(base_dir, data_dir=path.parent)
        if existing:
            return True, f"Technomancer runtime is active (PID {existing})."
        if path.exists():
            try:
                marker = json.loads(path.read_text(encoding="utf-8"))
                psutil.Process(int(marker["pid"]))
            except psutil.NoSuchProcess:
                path.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError, TypeError, psutil.Error):
                return False, "Runtime identity is unavailable; review the marker before starting another process."
            else:
                return False, "An unverified live process is associated with the runtime marker; no process was changed."
        kwargs = dict(cwd=str(base_dir), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, close_fds=True)
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen([sys.executable, "-B", "-m", "aida.technomancer.runtime", "--data-dir", str(path.parent.resolve())], **kwargs)
        write_runtime_marker(path, process.pid)
    return True, f"Technomancer runtime started (PID {process.pid}); observation health is reported separately."


def stop_background(base_dir, *, data_dir=None):
    path = _pid_path(base_dir, data_dir=data_dir)
    with locked_state(path):
        if not path.exists():
            return True, "Technomancer runtime is not active."
        try:
            process = _verified_process(path)
            process.terminate()
            try:
                process.wait(timeout=4)
            except psutil.TimeoutExpired:
                process = _verified_process(path)
                process.kill()
                process.wait(timeout=4)
        except psutil.NoSuchProcess:
            pass
        except (OSError, ValueError, KeyError, IndexError, TypeError, psutil.Error):
            return False, "Technomancer stop could not be verified; no unrelated process was targeted."
        path.unlink(missing_ok=True)
    return True, "Technomancer runtime stopped."
