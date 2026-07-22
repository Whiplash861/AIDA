from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Protocol


class PowerShellInvocationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PowerShellExecution:
    return_code: int
    stdout: str = ""
    stderr: str = ""


class PowerShellCommand(Protocol):
    def poll(self) -> int | None:
        ...

    def result(self) -> PowerShellExecution:
        ...

    def terminate(self) -> None:
        ...


class PowerShellRunner(Protocol):
    def run_json(self, script: str, timeout: float = 15.0) -> Any:
        ...

    def start(self, script: str) -> PowerShellCommand:
        ...


class SubprocessPowerShellCommand:
    """Owns a long-running PowerShell process and drains its output.

    stdout and stderr must be consumed while Defender is scanning. Waiting to
    call ``communicate`` only after process exit can fill an OS pipe buffer and
    block the PowerShell host even after the provider operation has advanced.
    A daemon collector therefore starts immediately and stores the terminal
    result for later polling.
    """

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        self._result: PowerShellExecution | None = None
        self._result_lock = threading.Lock()
        self._result_ready = threading.Event()
        self._collector = threading.Thread(
            target=self._collect_output,
            name="aida-powershell-output",
            daemon=True,
        )
        self._collector.start()

    def poll(self) -> int | None:
        with self._result_lock:
            if self._result is not None:
                return self._result.return_code
        return self._process.poll()

    def result(self) -> PowerShellExecution:
        self._result_ready.wait()
        with self._result_lock:
            if self._result is None:
                raise PowerShellInvocationError(
                    "PowerShell process ended without a captured result"
                )
            return self._result

    def terminate(self) -> None:
        """Stops only the host after provider-confirmed completion."""

        if self._process.poll() is not None:
            self._result_ready.wait(timeout=2.0)
            return

        self._process.terminate()
        if self._result_ready.wait(timeout=2.0):
            return

        self._process.kill()
        self._result_ready.wait(timeout=2.0)

    def _collect_output(self) -> None:
        try:
            stdout, stderr = self._process.communicate()
            return_code = self._process.returncode
            execution = PowerShellExecution(
                return_code=-1 if return_code is None else return_code,
                stdout=stdout or "",
                stderr=stderr or "",
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            return_code = self._process.poll()
            execution = PowerShellExecution(
                return_code=-1 if return_code is None else return_code,
                stderr=(
                    "PowerShell output collection failed: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )

        with self._result_lock:
            self._result = execution
        self._result_ready.set()


class SubprocessPowerShellRunner:
    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or self._find_executable()

    @property
    def executable(self) -> str:
        return self._executable

    def run_json(self, script: str, timeout: float = 15.0) -> Any:
        try:
            completed = subprocess.run(
                self._arguments(script),
                capture_output=True,
                text=True,
                timeout=timeout,
                startupinfo=self._startup_info(),
                creationflags=self._creation_flags(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PowerShellInvocationError(
                "PowerShell JSON command timed out after "
                f"{timeout:.1f} seconds"
            ) from exc

        if completed.returncode != 0:
            raise PowerShellInvocationError(
                self._format_error(completed.returncode, completed.stderr)
            )

        output = (completed.stdout or "").strip()
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise PowerShellInvocationError(
                "PowerShell returned invalid JSON output"
            ) from exc

    def start(self, script: str) -> PowerShellCommand:
        process = subprocess.Popen(
            self._arguments(script),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=self._startup_info(),
            creationflags=self._creation_flags(),
        )
        return SubprocessPowerShellCommand(process)

    def _arguments(self, script: str) -> list[str]:
        encoded = base64.b64encode(
            script.encode("utf-16-le")
        ).decode("ascii")
        return [
            self._executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        ]

    @staticmethod
    def _find_executable() -> str:
        candidates: list[str] = []
        system_root = os.environ.get("SystemRoot")
        if system_root:
            candidates.append(
                os.path.join(
                    system_root,
                    "System32",
                    "WindowsPowerShell",
                    "v1.0",
                    "powershell.exe",
                )
            )
        candidates.extend(["powershell.exe", "pwsh.exe", "pwsh"])

        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
            if os.path.isabs(candidate) and os.path.exists(candidate):
                return candidate

        raise PowerShellInvocationError(
            "No supported PowerShell executable was found"
        )

    @staticmethod
    def _startup_info() -> subprocess.STARTUPINFO | None:
        if os.name != "nt":
            return None
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return info

    @staticmethod
    def _creation_flags() -> int:
        if os.name != "nt":
            return 0
        return subprocess.CREATE_NO_WINDOW

    @staticmethod
    def _format_error(return_code: int, stderr: str | None) -> str:
        detail = (stderr or "").strip()
        if detail:
            return f"PowerShell failed with exit code {return_code}: {detail}"
        return f"PowerShell failed with exit code {return_code}"
