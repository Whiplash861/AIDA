from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette

from aida.artificer.models import ArtificerSnapshot, SourceReviewAnnotation
from aida.artificer.source_review import render_annotation
from aida.frontend.artificer_dialog import ArtificerCenterDialog


class Tasks:
    """Deferred callbacks reproduce TaskManager's finished-before-removal order."""
    def __init__(self):
        self.active = {}
        self.started = []

    def run_task(self, name, function, **callbacks):
        if name in self.active:
            return False
        self.active[name] = (function, callbacks)
        self.started.append(name)
        return True

    def finish(self, name, *, error=None):
        function, callbacks = self.active[name]
        if error:
            callbacks["on_error"](error)
        else:
            callbacks["on_result"](function())
        callbacks["on_finished"]()
        del self.active[name]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def surface(app):
    records = tuple(SourceReviewAnnotation(
        review_id=f"review-{number}", finding_id=f"finding-{number}", path="aida/fixture.py",
        start_line=number + 1, end_line=number + 1, symbol="fixture", source_sha256="abc", span_sha256="def",
        reviewed_code=f"value = {number}\n", proposed_change="Replace duplicated logic.",
        rationale="This definition hides an earlier definition.", evidence="Duplicate fixture symbol.",
        expected_outcomes=("One explicit implementation.",), validation_requirements=("Regression test.",),
    ) for number in range(2))
    snapshot = ArtificerSnapshot(status="ready", last_review_utc=None, platform_summary="FixtureOS",
        compatibility_summary={}, open_findings=(), pending_proposals=(), dispatch_queue_depth=0,
        telemetry_level="local_only", source_reviews=records)
    state = {"state": "current"}
    def inspect(review_id):
        annotation = next(record for record in records if record.review_id == review_id)
        return {"annotation": annotation, "state": state["state"], "text": render_annotation(annotation, state=state["state"])}
    tasks = Tasks()
    engine = SimpleNamespace(snapshot=lambda: snapshot, inspect_source_review=inspect)
    dialog = ArtificerCenterDialog(engine, task_manager=tasks)
    yield dialog, tasks, state
    dialog.close()
    dialog.deleteLater()
    app.processEvents()


def test_source_actions_wait_for_background_identity_check(surface):
    dialog, tasks, _ = surface
    assert tasks.started == ["artificer_source_inspect"]
    assert not dialog.candidate_stage_button.isEnabled()
    assert not dialog.proposal_button.isEnabled()
    tasks.finish("artificer_source_inspect")
    assert dialog.candidate_stage_button.isEnabled()
    assert dialog.proposal_button.isEnabled()
    text = dialog.source_review_text.toPlainText()
    assert "CAPTURED CODE" in text
    assert "PROPOSED ADDITION OR CHANGE" in text
    assert "RATIONALE" in text
    assert "EXPECTED OUTCOMES (not yet verified)" in text
    dialog.source_review_text.ensurePolished()
    palette = dialog.source_review_text.palette()
    assert palette.color(QPalette.ColorRole.Base).lightness() < 80
    assert palette.color(QPalette.ColorRole.Text).lightness() > 180


def test_stale_source_can_be_exported_but_not_staged_or_proposed(surface):
    dialog, tasks, state = surface
    state["state"] = "stale_source"
    tasks.finish("artificer_source_inspect")
    assert "stale_source" in dialog.source_review_text.toPlainText()
    assert dialog.review_export_button.isEnabled()
    assert not dialog.candidate_stage_button.isEnabled()
    assert not dialog.proposal_button.isEnabled()


def test_selection_changed_during_inspection_is_rechecked_after_task_cleanup(surface, app):
    dialog, tasks, _ = surface
    dialog.source_review_picker.setCurrentIndex(1)
    tasks.finish("artificer_source_inspect")
    assert not dialog.candidate_stage_button.isEnabled()
    app.processEvents()
    assert tasks.started == ["artificer_source_inspect", "artificer_source_inspect"]
    tasks.finish("artificer_source_inspect")
    assert "SOURCE REVIEW review-1" in dialog.source_review_text.toPlainText()
    assert dialog.candidate_stage_button.isEnabled()


def test_inspection_failure_does_not_retry_in_a_loop(surface, app):
    dialog, tasks, _ = surface
    tasks.finish("artificer_source_inspect", error="Fixture read failure")
    for _ in range(3):
        app.processEvents()
    assert tasks.active == {}
    assert tasks.started == ["artificer_source_inspect"]
    assert not dialog.candidate_stage_button.isEnabled()
    assert "Fixture read failure" in dialog.status_label.text()
