from __future__ import annotations

import uuid
from types import SimpleNamespace

from aida.artificer.engine import ArtificerEngine
from aida.artificer.models import ArtificerFinding, TelemetryLevel, utc_now


def _config(tmp_path):
    source_root = tmp_path / "project"
    package = source_root / "aida"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '1.0.0'\n", encoding="utf-8")
    data_dir = tmp_path / "artificer"
    return SimpleNamespace(
        artificer_enabled=True,
        version="1.0.0",
        base_dir=str(source_root),
        artificer_source_root=str(source_root),
        artificer_data_dir=str(data_dir),
        artificer_ledger_path=str(data_dir / "ledger.db"),
        artificer_consent_path=str(data_dir / "consent.json"),
        artificer_developer_registry_path=str(data_dir / "developers.json"),
        artificer_export_dir=str(data_dir / "exports"),
        artificer_dispatch_endpoint=None,
        artificer_local_export_enabled=True,
        artificer_review_interval_seconds=3600,
        artificer_telemetry_level="local_only",
        artificer_mode="test",
    )


def test_owner_can_create_and_decide_proposal(tmp_path) -> None:
    engine = ArtificerEngine(config=_config(tmp_path))
    now = utc_now()
    finding = ArtificerFinding(
        finding_id=f"AE-TEST-{uuid.uuid4().hex[:8]}",
        category="test",
        title="Test improvement",
        severity="moderate",
        confidence=0.99,
        evidence_quality=0.99,
        affected_components=("test_subsystem",),
        first_seen_utc=now,
        last_seen_utc=now,
        observation_count=3,
        finding="A test subsystem needs improvement.",
        evidence_summary="Three deterministic failures.",
        reasoning_summary="Repeated failures justify a proposal.",
        recommended_change="Create a validated v1.1 update.",
        expected_outcomes=("Fewer failures",),
        implementation_risk=0.2,
        regression_risk=0.2,
        authority_required="owner_approval",
        fingerprint="test:proposal",
    )
    engine.ledger.upsert_finding(finding)
    proposal = engine.create_proposal(finding.finding_id)
    assert proposal.status == "pending"
    engine.decide_proposal(proposal.proposal_id, "approved_for_staging")
    assert engine.ledger.list_proposals(status="approved_for_staging")[0].proposal_id == proposal.proposal_id


def test_telemetry_consent_can_be_changed_and_revoked(tmp_path) -> None:
    engine = ArtificerEngine(config=_config(tmp_path))
    engine.set_telemetry_level(
        TelemetryLevel.PSEUDONYMOUS,
        allow_crash_reports=True,
        allow_compatibility_reports=True,
    )
    assert engine.consent.state.telemetry_level is TelemetryLevel.PSEUDONYMOUS
    assert engine.consent.permits("compatibility_regression") is True
    engine.set_telemetry_level(TelemetryLevel.LOCAL_ONLY)
    assert engine.consent.permits("compatibility_regression") is False
