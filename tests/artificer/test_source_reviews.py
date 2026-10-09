from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from aida.artificer.codewright import Codewright
from aida.artificer.engine import ArtificerEngine
from aida.artificer.ledger import ArtificerLedger
from aida.artificer.ledger_core import LedgerIntegrityError
from aida.artificer.models import PlatformProfile, utc_now
from aida.artificer.policy import ArtificerPolicy
from aida.artificer.source_review import SourceReviewService, StaleSourceReview, annotations_for_finding, digest, render_annotation
from aida.artificer.validator import Validator


SOURCE = b"# context\r\ndef repeated():\r\n    return 1\r\n\r\ndef repeated():\r\n    return 2\r\n"


@pytest.fixture
def reviewed(tmp_path):
    root = tmp_path / "source"
    target = root / "aida" / "example.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(SOURCE)
    inspector = Codewright(root)
    finding = next(item for item in inspector.inspect() if item.fingerprint.startswith("duplicates:"))
    ledger = ArtificerLedger(tmp_path / "ledger.db")
    finding = ledger.upsert_finding(finding)
    annotations = annotations_for_finding(finding, inspector.review_sources)
    for annotation in annotations:
        ledger.store_source_review(annotation)
    exports = tmp_path / "exports"
    exports.mkdir()
    service = SourceReviewService(root, ledger, policy=ArtificerPolicy(root))
    return SimpleNamespace(root=root, target=target, inspector=inspector, ledger=ledger,
                           finding=finding, annotations=annotations, exports=exports, service=service)


def stage(reviewed, replacement="def repeated():\n    return 3\n", **kwargs):
    annotation = reviewed.annotations[0]
    return reviewed.service.stage(annotation.review_id, replacement,
                                  expected_source_sha256=annotation.source_sha256,
                                  export_dir=reviewed.exports, **kwargs)


def test_annotations_explain_exact_code_change_reason_outcome_and_validation(reviewed):
    first, second = reviewed.annotations
    assert (first.start_line, first.end_line, first.symbol) == (2, 3, "repeated")
    assert (second.start_line, second.end_line) == (5, 6)
    assert first.reviewed_code == "def repeated():\r\n    return 1\r\n"
    assert first.source_sha256 == digest(SOURCE)
    assert first.span_sha256 == digest(first.reviewed_code.encode())
    text = render_annotation(first)
    for required in ("CAPTURED CODE", "2: def repeated():", "PROPOSED ADDITION OR CHANGE",
                     "Consolidate definitions", "RATIONALE", "OBSERVED EVIDENCE",
                     "EXPECTED OUTCOMES (not yet verified)", "REQUIRED VALIDATION"):
        assert required in text
    assert reviewed.ledger.get_source_review(first.review_id) == first
    assert reviewed.ledger.verify_integrity()


def test_annotations_use_inspected_bytes_even_when_file_changes_after_inspection(reviewed):
    reviewed.target.write_text("changed = True\n")
    captured = annotations_for_finding(reviewed.finding, reviewed.inspector.review_sources)
    assert captured[0].source_sha256 == digest(SOURCE)
    assert captured[0].reviewed_code == reviewed.annotations[0].reviewed_code
    assert reviewed.service.inspect(captured[0].review_id)["state"] == "stale_source"
    with pytest.raises(StaleSourceReview):
        stage(reviewed)
    assert list(reviewed.exports.iterdir()) == []


def test_inert_stage_keeps_original_bytes_and_context_and_records_validation(reviewed):
    marker = reviewed.exports / "must_not_execute"
    replacement = f"def reviewed_replacement():\n    return 3\n\n__import__('pathlib').Path({str(marker)!r}).touch()\n"
    manifest = stage(reviewed, replacement)
    folder = Path(manifest["manifest_path"]).parent
    candidate = (folder / manifest["candidate_file"]).read_bytes()
    assert candidate.startswith(b"# context\r\ndef reviewed_replacement():\r\n")
    assert candidate.endswith(b"\r\ndef repeated():\r\n    return 2\r\n")
    assert digest(candidate) == manifest["candidate_sha256"]
    assert manifest["status"] == "static_checks_passed"
    assert manifest["execution_authority"] is False
    assert manifest["behavior_verified"] is False
    assert "--- a/aida/example.py" in (folder / "candidate.diff").read_text()
    assert json.loads((folder / "annotation.json").read_text())["reviewed_code"] == reviewed.annotations[0].reviewed_code
    assert not marker.exists()
    assert reviewed.target.read_bytes() == SOURCE
    assert not list(reviewed.root.rglob("__pycache__"))
    with sqlite3.connect(reviewed.ledger.path) as connection:
        payload = json.loads(connection.execute("SELECT payload_json FROM source_stages").fetchone()[0])
    assert payload["publication"] == "ready"
    assert reviewed.ledger.verify_integrity()


def test_invalid_candidate_is_exported_honestly_without_execution(reviewed):
    manifest = stage(reviewed, "def invalid(:\n")
    assert manifest["status"] == "static_checks_failed"
    assert manifest["validation"][0]["passed"] is False
    assert reviewed.target.read_bytes() == SOURCE


def test_stage_rechecks_source_after_validation_and_cleans_temporary_export(reviewed):
    class MutatingValidator(Validator):
        def validate_python_file(self, path, **kwargs):
            report = super().validate_python_file(path, **kwargs)
            reviewed.target.write_text("external_edit = True\n")
            return report
    reviewed.service.validator = MutatingValidator()
    with pytest.raises(StaleSourceReview):
        stage(reviewed)
    assert list(reviewed.exports.iterdir()) == []
    assert reviewed.target.read_text() == "external_edit = True\n"


def test_finding_closed_during_validation_cannot_publish_candidate(reviewed):
    class ClosingValidator(Validator):
        def validate_python_file(self, path, **kwargs):
            report = super().validate_python_file(path, **kwargs)
            reviewed.ledger.resolve_absent_findings(active_fingerprints=set(), fingerprint_prefixes=("duplicates:",))
            return report
    reviewed.service.validator = ClosingValidator()
    with pytest.raises(StaleSourceReview, match="closed during staging"):
        stage(reviewed)
    assert list(reviewed.exports.iterdir()) == []
    assert reviewed.ledger.verify_integrity()


def test_closed_finding_and_display_hash_mismatch_reject_staging(reviewed):
    annotation = reviewed.annotations[0]
    with pytest.raises(StaleSourceReview):
        reviewed.service.stage(annotation.review_id, "pass\n", expected_source_sha256="different", export_dir=reviewed.exports)
    reviewed.ledger.resolve_absent_findings(active_fingerprints=set(), fingerprint_prefixes=("duplicates:",))
    assert reviewed.service.inspect(annotation.review_id)["state"] == "finding_not_open"
    with pytest.raises(StaleSourceReview):
        stage(reviewed)
    assert list(reviewed.exports.iterdir()) == []


def test_path_escape_rejected_and_stale_annotation_export_is_explicit(reviewed):
    original = reviewed.annotations[0]
    escaped = replace(original, review_id="ESCAPE", path="../outside.py")
    reviewed.ledger.store_source_review(escaped)
    with pytest.raises(ValueError, match="relative Python"):
        reviewed.service.stage(escaped.review_id, "pass", expected_source_sha256=escaped.source_sha256, export_dir=reviewed.exports)
    reviewed.target.write_text("other = True\n")
    exported = reviewed.service.export_review(original.review_id, reviewed.exports)
    payload = json.loads(exported.read_text())
    assert payload["state_at_export"] == "stale_source"
    assert payload["annotation"]["source_sha256"] == digest(SOURCE)


def test_bom_preserved_in_static_candidate(reviewed):
    original = b"\xef\xbb\xbf" + SOURCE
    reviewed.target.write_bytes(original)
    fresh = replace(reviewed.annotations[0], review_id="BOM", source_sha256=digest(original))
    reviewed.ledger.store_source_review(fresh)
    manifest = reviewed.service.stage(fresh.review_id, "def replacement():\n    return 4\n", expected_source_sha256=fresh.source_sha256, export_dir=reviewed.exports)
    candidate = Path(manifest["manifest_path"]).parent / manifest["candidate_file"]
    assert candidate.read_bytes().startswith(b"\xef\xbb\xbf# context\r\n")
    assert manifest["status"] == "static_checks_passed"


def test_schema_upgrade_keeps_verified_history_and_rejects_tampered_rows(reviewed):
    with sqlite3.connect(reviewed.ledger.path) as connection:
        connection.execute("UPDATE schema_meta SET value='2' WHERE key='schema_version'")
    upgraded = ArtificerLedger(reviewed.ledger.path)
    assert upgraded.verify_integrity()
    with sqlite3.connect(reviewed.ledger.path) as connection:
        connection.execute("UPDATE schema_meta SET value='2' WHERE key='schema_version'")
        connection.execute("UPDATE source_reviews SET path='tampered.py'")
    with pytest.raises(LedgerIntegrityError):
        ArtificerLedger(reviewed.ledger.path)


def test_engine_review_links_source_proposal_and_resource_evidence(reviewed, tmp_path):
    config = SimpleNamespace(base_dir=reviewed.root, artificer_data_dir=tmp_path / "engine", version="test")
    engine = ArtificerEngine(config=config, platform_adapter=SimpleNamespace(name="fixture"))
    profile = PlatformProfile("fixture", utc_now(), "FixtureOS", "1", "1", "test", "test", "test", "test", "UTC", 0, "user", None, None)
    engine.liaison = SimpleNamespace(capture_profile=lambda: profile, verify_capabilities=lambda _: ())
    snapshot = engine.run_review()
    assert len(snapshot.source_reviews) == 2
    assert not engine.codewright.review_sources
    proposal = engine.create_proposal(snapshot.source_reviews[0].finding_id)
    assert set(proposal.source_review_ids) == {review.review_id for review in snapshot.source_reviews}
    assert engine.ledger.list_proposals()[0].source_review_ids == proposal.source_review_ids
    reviewed.target.write_text("changed = True\n")
    with pytest.raises(StaleSourceReview):
        engine.create_proposal(snapshot.source_reviews[0].finding_id)
    engine._resource_observer = SimpleNamespace(measure=lambda **_: {"status": "observed", "elapsed_seconds": 1.0, "causal_claim_verified": False})
    record = engine.measure_self_resources(operation_id="investigation-test")
    assert record["causal_claim_verified"] is False
    event = engine.ledger.recent_events()[0]
    assert event["event_type"] == "aida_resource_observed"
    assert event["operation_id"] == "investigation-test"
    assert engine.ledger.verify_integrity()
