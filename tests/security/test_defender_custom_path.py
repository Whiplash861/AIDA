from __future__ import annotations

import base64
import re
from pathlib import Path

from aida.security.models import (
    ScanScope,
    SecurityAuthorization,
    SecurityScanMode,
    SecurityScanRequest,
    SecurityScanState,
)
from aida.security.providers.defender_tracked import (
    CompletionAwareMicrosoftDefenderProvider,
)
from aida.security.windows.powershell import PowerShellExecution


class FakeCommand:
    def __init__(
        self,
        return_code: int | None = None,
        stderr: str = "",
    ) -> None:
        self.return_code = return_code
        self.stderr = stderr

    def poll(self) -> int | None:
        return self.return_code

    def result(self) -> PowerShellExecution:
        assert self.return_code is not None
        return PowerShellExecution(
            return_code=self.return_code,
            stderr=self.stderr,
        )

    def terminate(self) -> None:
        self.return_code = 0


class FakeRunner:
    def __init__(self, command: FakeCommand) -> None:
        self.command = command
        self.started_scripts: list[str] = []

    def run_json(self, script: str, timeout: float = 15.0):
        raise AssertionError((script, timeout))

    def start(self, script: str) -> FakeCommand:
        self.started_scripts.append(script)
        return self.command


def deep_request(path: Path) -> SecurityScanRequest:
    return SecurityScanRequest(
        mode=SecurityScanMode.DEEP,
        authorization=SecurityAuthorization(
            granted=True,
            granted_by="Austin",
            reason="Deep scan field test",
        ),
        scope=ScanScope(paths=(path,)),
    )


def test_custom_scan_decodes_target_as_explicit_string() -> None:
    target = Path(r"C:\Users\austi\OneDrive - Marco Island Yacht Club")
    runner = FakeRunner(FakeCommand(return_code=None))
    provider = CompletionAwareMicrosoftDefenderProvider(runner)

    provider.start_scan(deep_request(target))

    script = runner.started_scripts[0]
    match = re.search(r"FromBase64String\('([^']+)'\)", script)
    assert match is not None
    decoded = base64.b64decode(match.group(1)).decode("utf-8")

    assert decoded == str(target)
    assert "[System.String]" in script
    assert "-ScanPath $scanPath0" in script
    assert "ConvertFrom-Json" not in script


def test_custom_scan_failure_strips_clixml_noise() -> None:
    clixml = (
        "#< CLIXML<Objs><S S=\"Error\">"
        "Start-MpScan : Cannot process argument transformation on parameter "
        "'ScanPath'. Cannot convert value to type System.String."
        "_x000D__x000A_At line:7 char:49"
        "</S></Objs>"
    )
    runner = FakeRunner(FakeCommand(return_code=1, stderr=clixml))
    provider = CompletionAwareMicrosoftDefenderProvider(runner)
    handle = provider.start_scan(deep_request(Path(r"C:\Target")))

    status = provider.get_scan_status(handle)

    assert status.state is SecurityScanState.FAILED
    assert "Cannot process argument transformation" in status.detail
    assert "CLIXML" not in status.detail
    assert "At line:" not in status.detail
