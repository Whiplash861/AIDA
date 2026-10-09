from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from aida.artificer.consent import ConsentManager
from aida.artificer.developer_registry import DeveloperRegistry
from aida.artificer.dispatch import ArtificerDispatch, LocalExportTransport
from aida.artificer.engine import ArtificerEngine
from aida.artificer.events import make_event
from aida.artificer.forge import Forge, ForgeError
from aida.artificer.ledger import ArtificerLedger
from aida.artificer.ledger_core import LedgerIntegrityError
from aida.artificer.models import TelemetryLevel
from aida.artificer.policy import ArtificerPolicy
from aida.artificer.rollback import RollbackManager
from aida.artificer.sanitizer import PayloadSanitizer
from aida.artificer.validator import Validator, ValidationCheck
from aida.artificer.warden import Warden
from tests.artificer.test_governance import _config
from tests.artificer.test_ledger import _finding


def test_concurrent_finding_identity_and_content_integrity(tmp_path):
    a = ArtificerLedger(tmp_path / "ledger.db")
    b = ArtificerLedger(tmp_path / "ledger.db")
    with ThreadPoolExecutor(2) as pool:
        stored = list(pool.map(lambda ledger: ledger.upsert_finding(_finding("test:same", count=1)), (a, b)))
    assert stored[0].finding_id == stored[1].finding_id
    a.set_finding_status(stored[0].finding_id, "resolved")
    assert a.verify_integrity()
    with a._connect() as connection:
        connection.execute("UPDATE artificer_findings SET title='changed'")
    with pytest.raises(LedgerIntegrityError):
        a.verify_integrity()


def test_disabled_ingestion_and_persisted_consent(tmp_path):
    config = _config(tmp_path)
    consent = ConsentManager(config.artificer_consent_path)
    consent.set_level(TelemetryLevel.PSEUDONYMOUS)
    config.artificer_enabled = False
    engine = ArtificerEngine(config=config)
    engine.event_bus.publish(make_event(source="test", event_type="test", status="completed", aida_version="1", platform_profile_id="test"))
    assert engine.ledger.recent_events() == []
    assert engine.consent.state.telemetry_level is TelemetryLevel.PSEUDONYMOUS


def test_dispatch_observes_external_revocation(tmp_path):
    consent = ConsentManager(tmp_path / "consent.json")
    consent.set_level(TelemetryLevel.PSEUDONYMOUS)
    dispatch = ArtificerDispatch(ledger=ArtificerLedger(tmp_path / "ledger.db"),
        sanitizer=PayloadSanitizer(), consent=consent,
        developers=DeveloperRegistry(tmp_path / "developers.json"),
        transport=LocalExportTransport(tmp_path / "exports"))
    dispatch.queue("operational_summary", {"status": "ok"})
    ConsentManager(consent.path).set_level(TelemetryLevel.LOCAL_ONLY)
    assert dispatch.flush()[0].status == "blocked"
    assert list((tmp_path / "exports").iterdir()) == []
    assert dispatch.ledger.verify_integrity()


def _forge(tmp_path, validator=None):
    root = tmp_path / "source"
    (root / "aida").mkdir(parents=True)
    (root / "aida" / "example.py").write_text("value=1\n")
    policy = ArtificerPolicy(root)
    return Forge(source_root=root, ledger=ArtificerLedger(tmp_path / "ledger.db"),
                 policy=policy, warden=Warden(policy), validator=validator or Validator(),
                 rollback=RollbackManager(tmp_path / "rollback"))


def test_forge_protected_alias_has_no_content_copy(tmp_path):
    forge = _forge(tmp_path)
    protected = forge.source_root / "aida/artificer/policy.py"
    protected.parent.mkdir()
    protected.write_text("private = 'test secret'\n")
    with pytest.raises(ForgeError):
        forge.apply_text_replacement(relative_path="aida/other/../artificer/policy.py", new_content="",
            rule_id="python.format_only", confidence=1, evidence_quality=1, implementation_risk=0)
    assert list(forge.rollback.rollback_root.iterdir()) == []


def test_forge_tests_candidate_and_refuses_source_race(tmp_path):
    class Check(Validator):
        def run_tests(self, source_root, *, test_paths=()):
            assert Path(source_root) != forge.source_root
            assert (Path(source_root) / "aida/example.py").read_text() == "value = 1\n"
            (forge.source_root / "aida/example.py").write_text("value=2\n")
            return ValidationCheck("pytest", True, "fixture")
    forge = _forge(tmp_path, Check())
    attempt = forge.apply_text_replacement(relative_path="aida/example.py", new_content="value = 1\n",
        rule_id="python.format_only", confidence=1, evidence_quality=1, implementation_risk=0,
        test_paths=("tests/test_example.py",))
    assert attempt.status == "source_changed"
    assert (forge.source_root / "aida/example.py").read_text() == "value=2\n"


def test_forge_governed_rollback_and_nonfinite_scores(tmp_path):
    forge = _forge(tmp_path)
    attempt = forge.apply_text_replacement(relative_path="aida/example.py", new_content="value = 1\n",
        rule_id="python.format_only", confidence=1, evidence_quality=1, implementation_risk=0)
    with pytest.raises(ForgeError):
        forge.rollback_attempt(replace(attempt, path="aida/other.py"))
    forge.rollback_attempt(attempt)
    assert (forge.source_root / "aida/example.py").read_text() == "value=1\n"
    assert forge.ledger.verify_integrity()
    assert not forge.warden.authorize(path="aida/example.py", rule_id="python.format_only",
        confidence=float("nan"), evidence_quality=1, implementation_risk=0,
        rollback_ready=True, changed_lines=1).allowed


def test_forge_failed_commit_restores_original_and_keeps_audit(tmp_path, monkeypatch):
    forge = _forge(tmp_path)
    append = forge.ledger.append_modification_attempt
    def fail_applied(attempt):
        if attempt.status == "applied_restart_required":
            raise OSError("Simulated database failure")
        append(attempt)
    monkeypatch.setattr(forge.ledger, "append_modification_attempt", fail_applied)
    with pytest.raises(OSError):
        forge.apply_text_replacement(relative_path="aida/example.py", new_content="value = 1\n",
            rule_id="python.format_only", confidence=1, evidence_quality=1, implementation_risk=0)
    assert (forge.source_root / "aida/example.py").read_text() == "value=1\n"
    assert forge.ledger.verify_integrity()


def test_owner_approval_is_bound_and_single_use(tmp_path):
    policy = ArtificerPolicy(tmp_path)
    warden = Warden(policy, approval_authorizer=lambda actor: actor == "owner")
    token = warden.issue_approval(developer_id="owner", path="aida/example.py", rule_id="python.syntax_repair",
                                 original_sha256="a" * 64, proposed_sha256="b" * 64)
    scope = dict(path="aida/example.py", rule_id="python.syntax_repair", original_sha256="a" * 64, proposed_sha256="b" * 64)
    assert warden.consume_approval(token, **scope)
    assert not warden.consume_approval(token, **scope)


def test_retention_checkpoints_bound_events_and_keep_verified_current_records(tmp_path):
    ledger = ArtificerLedger(tmp_path / "ledger.db", event_limit=3, audit_history_limit=3)
    finding = ledger.upsert_finding(_finding("test:retained", count=1))
    for _ in range(10):
        ledger.append_event(make_event(source="test", event_type="observed", status="completed", aida_version="1", platform_profile_id="test"))
    assert len(ledger.recent_events()) <= 3
    assert ledger.get_finding(finding.finding_id) is not None
    assert ledger.verify_integrity()
    assert ledger.retention_status()["history_complete"] is False
    assert ledger.retention_status()["retired_audit_entries"] > 0
    with ledger._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_chain").fetchone()[0] <= 8
        connection.execute("UPDATE artificer_findings SET title='tampered'")
    with pytest.raises(LedgerIntegrityError):
        ledger.verify_integrity()


def test_retention_never_checkpoints_tampered_data(tmp_path):
    ledger = ArtificerLedger(tmp_path / "ledger.db", event_limit=1)
    for _ in range(1):
        ledger.append_event(make_event(source="test", event_type="observed", status="completed", aida_version="1", platform_profile_id="test"))
    with ledger._connect() as connection:
        connection.execute("UPDATE operational_events SET status='tampered'")
    with pytest.raises(LedgerIntegrityError):
        ledger.append_event(make_event(source="test", event_type="observed", status="completed", aida_version="1", platform_profile_id="test"))
    assert ledger.retention_status()["history_complete"] is True
