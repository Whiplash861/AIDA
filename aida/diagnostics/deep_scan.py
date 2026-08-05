from __future__ import annotations

import time

from aida.artificer.runtime import get_active_artificer
from aida.diagnostics.base import Finding
from aida.diagnostics.system_scan import run_file_scan, run_full_diagnostics
from aida.logging_utils import get_logger

log = get_logger(__name__)


def run_deep_diagnostics(config, *, include_security_scan: bool = True) -> list[Finding]:
    """Run broad non-destructive diagnostics and an optional provider security scan."""
    started = time.monotonic()
    findings: list[Finding] = []
    status = "completed"
    error: str | None = None
    try:
        findings.extend(run_full_diagnostics(config))
        if include_security_scan:
            findings.extend(run_file_scan(config))
    except Exception as exc:
        status = "failed"
        error = str(exc)
        log.exception("Deep diagnostics failed: %s", exc)
        findings.append(
            Finding(
                id="deep.error",
                title="Deep diagnostics error",
                severity="high",
                detail="Deep diagnostics encountered an unexpected error.",
                evidence=str(exc),
                recommended_next="Review AIDA logs and rerun the requested checks separately.",
            )
        )
    engine = get_active_artificer()
    if engine is not None:
        engine.record_diagnostic_run(
            scan_type="deep_diagnostics",
            status=status,
            findings_count=len(findings),
            duration_ms=(time.monotonic() - started) * 1000.0,
            error=error,
        )
    return findings
