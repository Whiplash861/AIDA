from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
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


class PowerShellRunner(Protocol):
    def run_json(self, script: str, timeout: float = 15.0) -> Any:
        ...

    def start(self, script: str) -> PowerShellCommand:
        ...


class SubprocessPowerShellCommand:
    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        self._result: PowerShellExecution | None = None

    def poll(self) -> int | None:
        if self._result is not None:
            return self._result.return_code
        return self._process.poll()

    def result(self) -> PowerShellExecution:
        if self._result is None:
            stdout, stderr = self._process.communicate()
            self._result = PowerShellExecution(
                return_code=self._process.returncode,
                stdout=stdout or "",
                stderr=stderr or "",
            )
        return self._result


class SubprocessPowerShellRunner:
    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or self._find_executable()

    @property
    def executable(self) -> str:
        return self._executable

    def run_json(self, script: str, timeout: float = 15.0) -> Any:
        completed = subprocess.run(
            self._arguments(script),
            capture_output=True,
            text=True,
            timeout=timeout,
            startupinfo=self._startup_info(),
            creationflags=self._creation_flags(),
            check=False,
        )
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
