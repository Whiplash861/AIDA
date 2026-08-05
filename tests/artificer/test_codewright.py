from __future__ import annotations

import json

from aida.artificer.codewright import Codewright


def test_codewright_detects_syntax_error_and_empty_module(tmp_path) -> None:
    package = tmp_path / "aida"
    package.mkdir()
    (package / "broken.py").write_text(
        "def broken(:\n    pass\n",
        encoding="utf-8",
    )
    (package / "placeholder.py").write_text("", encoding="utf-8")

    findings = Codewright(tmp_path).inspect()
    titles = {finding.title for finding in findings}

    assert "Python syntax failure" in titles
    assert "Empty implementation module" in titles


def test_codewright_ignores_windows_words_without_executable_behavior(
    tmp_path,
) -> None:
    package = tmp_path / "aida" / "intent"
    package.mkdir(parents=True)
    (package / "phrases.py").write_text(
        'POWERSHELL_HELP = "Use PowerShell to inspect the machine."\n'
        'SETTINGS_URI = "ms-settings:bluetooth"\n'
        'EXPLORER_LABEL = "Open Explorer"\n',
        encoding="utf-8",
    )

    findings = Codewright(tmp_path).inspect()

    assert not any(
        finding.fingerprint.startswith("platform-leak:")
        for finding in findings
    )


def test_codewright_detects_actual_windows_execution_outside_adapter(
    tmp_path,
) -> None:
    package = tmp_path / "aida" / "ui"
    package.mkdir(parents=True)
    (package / "navigation.py").write_text(
        "import subprocess\n"
        "def open_settings():\n"
        "    subprocess.run(['powershell', '-Command', "
        "'Start-Process ms-settings:bluetooth'])\n",
        encoding="utf-8",
    )

    findings = Codewright(tmp_path).inspect()
    platform_findings = [
        finding
        for finding in findings
        if finding.fingerprint.startswith("platform-leak:")
    ]

    assert len(platform_findings) == 1
    assert platform_findings[0].title == (
        "Executable platform behavior outside adapter"
    )
    assert "subprocess.run" in platform_findings[0].evidence_summary


def test_codewright_honors_approved_platform_scope(tmp_path) -> None:
    package = tmp_path / "aida" / "security" / "windows"
    package.mkdir(parents=True)
    (package / "powershell.py").write_text(
        "import subprocess\n"
        "def invoke():\n"
        "    subprocess.run(['powershell', '-Command', 'Get-MpComputerStatus'])\n",
        encoding="utf-8",
    )
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "approved_platform_roots": ["aida/security/windows/"],
                "intentional_empty_modules": {},
            }
        ),
        encoding="utf-8",
    )

    findings = Codewright(
        tmp_path,
        expectations_path=expectations,
    ).inspect()

    assert not any(
        finding.fingerprint.startswith("platform-leak:")
        for finding in findings
    )


def test_codewright_honors_intentional_empty_module_manifest(
    tmp_path,
) -> None:
    package = tmp_path / "aida" / "frontend"
    package.mkdir(parents=True)
    placeholder = package / "events.py"
    placeholder.write_text("", encoding="utf-8")
    expectations = tmp_path / "expectations.json"
    expectations.write_text(
        json.dumps(
            {
                "approved_platform_roots": [],
                "intentional_empty_modules": {
                    "aida/frontend/events.py": "Reserved contract module"
                },
            }
        ),
        encoding="utf-8",
    )

    findings = Codewright(
        tmp_path,
        expectations_path=expectations,
    ).inspect()

    assert not any(
        finding.fingerprint == "empty:aida/frontend/events.py"
        for finding in findings
    )
