from __future__ import annotations

from aida.artificer.events import make_event
from aida.artificer.ledger import ArtificerLedger
from aida.artificer.models import ArtificerFinding, utc_now


def test_ledger_persists_events_and_verifies_chain(tmp_path) -> None:
    ledger = ArtificerLedger(tmp_path / "artificer.db")
    event = make_event(
        source="diagnostics",
        event_type="scan",
        status="completed",
        aida_version="1.0",
        metadata={"findings": 2},
    )
    ledger.append_event(event)
    records = ledger.recent_events()
    assert records[0]["event_id"] == event.event_id
    assert records[0]["metadata"]["findings"] == 2
    assert ledger.verify_integrity() is True


def test_deterministic_finding_count_reflects_current_review(
    tmp_path,
) -> None:
    ledger = ArtificerLedger(tmp_path / "artificer.db")
    fingerprint = "platform-leak:aida/ui/navigation.py"

    legacy = ledger.upsert_finding(_finding(fingerprint, count=6))
    current = ledger.upsert_finding(_finding(fingerprint, count=1))
    repeated = ledger.upsert_finding(_finding(fingerprint, count=1))

    assert legacy.observation_count == 6
    assert current.observation_count == 1
    assert repeated.observation_count == 1
    assert ledger.list_findings()[0].observation_count == 1


def test_operational_finding_retains_highest_measured_count(
    tmp_path,
) -> None:
    ledger = ArtificerLedger(tmp_path / "artificer.db")
    fingerprint = "failures:interaction.voice"

    first = ledger.upsert_finding(_finding(fingerprint, count=4))
    lower_window = ledger.upsert_finding(_finding(fingerprint, count=2))
    higher_window = ledger.upsert_finding(_finding(fingerprint, count=7))

    assert first.observation_count == 4
    assert lower_window.observation_count == 4
    assert higher_window.observation_count == 7


def test_absent_deterministic_findings_resolve_and_reopen(
    tmp_path,
) -> None:
    ledger = ArtificerLedger(tmp_path / "artificer.db")
    fingerprint = "empty:aida/frontend/events.py"
    stored = ledger.upsert_finding(_finding(fingerprint, count=1))

    resolved = ledger.resolve_absent_findings(
        active_fingerprints=set(),
        fingerprint_prefixes=("empty:", "platform-leak:"),
    )

    assert resolved == 1
    assert ledger.list_findings() == []
    historical = ledger.list_findings(status=None)
    assert historical[0].finding_id == stored.finding_id
    assert historical[0].status == "resolved"

    reopened = ledger.upsert_finding(_finding(fingerprint, count=1))
    assert reopened.finding_id == stored.finding_id
    assert reopened.status == "open"
    assert reopened.observation_count == 1


def _finding(fingerprint: str, *, count: int) -> ArtificerFinding:
    now = utc_now()
    return ArtificerFinding(
        finding_id="AE-TEST-001",
        category="source_health",
        title="Deterministic test finding",
        severity="minor",
        confidence=0.98,
        evidence_quality=0.96,
        affected_components=("aida/example.py",),
        first_seen_utc=now,
        last_seen_utc=now,
        observation_count=count,
        finding="A deterministic condition exists.",
        evidence_summary="The condition was found by a repeatable source check.",
        reasoning_summary="Deterministic test reasoning.",
        recommended_change="Correct the source condition.",
        expected_outcomes=("Improved precision",),
        implementation_risk=0.1,
        regression_risk=0.2,
        authority_required="recommend",
        fingerprint=fingerprint,
    )
