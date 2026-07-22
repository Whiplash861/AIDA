from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_provider_probe_can_import_aida_when_run_by_path(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    probe_path = repository_root / "tools" / "security_provider_probe.py"

    result = subprocess.run(
        [sys.executable, str(probe_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    combined_output = f"{result.stdout}\n{result.stderr}"
    assert "No module named 'aida'" not in combined_output
