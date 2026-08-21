from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aida.aegis.models import (
    AegisCaseStatus,
    BaselineDelta,
    CoverageVector,
    IntelligentScanResult,
    RiskVector,
    SecurityCase,
)
from aida.aegis.scan_modes import AegisScanStrategy
from aida.frontend.commands.aegis import AegisSecurityScanExecutor
from aida.frontend.commands.base import CommandResult


class _ProviderExecutor:
    heartbeat_kind = "surface"
    provider_started_at = None

    def execute(self) -> CommandResult:
        return CommandResult(
            transcript_text="Provider scan complete.",
            speech_text="Provider scan complete.",
        )


class _Engine:
    def __init__(self) -> None:
        self.strategies: list[str] = []

    def run_intelligent_scan(self, *, provider_scan_summary: str, scan_strategy: str):
        self.strategies.append(scan_strategy)
        now = datetime.now(timezone.utc)
        case = SecurityCase(
            case_id="CASE-AEGIS-TEST",
            status=AegisCaseStatus.ASSESSED,
            created_at=now,
            updated_at=now,
            summary="No active compromise identified.",
            risk=RiskVector(0.05, 0.10, 0.05, 0.05, 0.05, 0.05),
            coverage=CoverageVector(1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
            baseline_delta=BaselineDelta(baseline_available=True),
            provider_detection_count=0,
            analyzed_file_count=0,
            evidence_nodes=(),
            evidence_edges=(),
            hypotheses=(),
            escalation="no_escalation",
            scan_strategy=scan_strategy,
            learning_model_version=1,
            learning_sample_count=10,
            learning_warmup=False,
        )
        return IntelligentScanResult(
            case=case,
            provider_scan_summary=provider_scan_summary,
            baseline_established=False,
            elapsed_seconds=0.01,
        )


@pytest.mark.parametrize("strategy", list(AegisScanStrategy))
def test_all_security_scan_strategies_receive_aegis_intelligence(strategy) -> None:
    engine = _Engine()
    executor = AegisSecurityScanExecutor(
        engine=engine,
        strategy=strategy,
        provider_scan_factory=_ProviderExecutor,
    )

    result = executor.execute()

    assert engine.strategies == [strategy.value]
    assert "Provider scan complete." in result.transcript_text
    assert "AEGIS" in result.transcript_text
    assert strategy.value.title() in result.transcript_text
