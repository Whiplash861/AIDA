from __future__ import annotations

import subprocess
import threading

import pytest

from aida.security.windows.powershell import (
    PowerShellInvocationError,
    SubprocessPowerShellCommand,
    SubprocessPowerShellRunner,
)


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.communicate_started = threading.Event()
        self.release_communicate = threading.Event()

    def communicate(self) -> tuple[str, str]:
        self.communicate_started.set()
        self.release_communicate.wait(timeout=1.0)
        return ("provider output", "provider progress")

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15
        self.release_communicate.set()

    def kill(self) -> None:
        self.returncode = -9
        self.release_communicate.set()


def test_long_running_command_drains_output_before_process_exit() -> None:
    process = FakeProcess()
    command = SubprocessPowerShellCommand(process)  # type: ignore[arg-type]

    assert process.communicate_started.wait(timeout=0.5)
    assert command.poll() is None

    process.returncode = 0
    process.release_communicate.set()
    result = command.result()

    assert result.return_code == 0
    assert result.stdout == "provider output"
    assert result.stderr == "provider progress"


def test_terminate_releases_output_collector() -> None:
    process = FakeProcess()
    command = SubprocessPowerShellCommand(process)  # type: ignore[arg-type]

    assert process.communicate_started.wait(timeout=0.5)
    command.terminate()
    result = command.result()

    assert result.return_code == -15


def test_run_json_converts_timeout_to_provider_error(monkeypatch) -> None:
    def timeout_run(*args, **kwargs):
        del args
        raise subprocess.TimeoutExpired(
            cmd="powershell.exe",
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr(
        "aida.security.windows.powershell.subprocess.run",
        timeout_run,
    )
    runner = SubprocessPowerShellRunner(executable="powershell.exe")

    with pytest.raises(
        PowerShellInvocationError,
        match=r"timed out after 15\.0 seconds",
    ):
        runner.run_json("$null")
