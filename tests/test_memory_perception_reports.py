from dataclasses import replace
from datetime import timedelta
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from aida.memory.database import MemoryDatabase
from aida.memory.models import JournalEvent, MemoryItem, MemoryStatus, ProcessOutcome, utc_now
from aida.memory.renderer import render_event, render_memory
from aida.memory.service import MemoryService
from aida.perception.models import EvidenceSource
from aida.perception.ocr import TextExtraction
from aida.perception.service import PerceptionService


def assert_report(text):
    for heading in ("What AIDA found", "What remains unknown", "What to do next"):
        assert heading in text


def test_memory_report_distinguishes_user_correction_from_verified_fact():
    item = MemoryItem("repair", "Startup", "The repair did not help.", "user", "device",
        status=MemoryStatus.DISPUTED, source="user_correction", facts={"private": "Do not dump raw facts"})
    text = render_memory(item)
    assert_report(text)
    assert "Saved wording: The repair did not help." in text
    assert "excluded from factual recall" in text
    assert "Editing the wording alone does not reconcile" in text
    assert "not independent verification" in text
    assert item.memory_id in text
    assert "Do not dump raw facts" not in text
    assert item.status is MemoryStatus.DISPUTED


def test_expired_memory_is_not_presented_as_available_for_future_answers():
    item = MemoryItem("note", "Old note", "Earlier information.", "user", "device",
        expires_at=utc_now() - timedelta(days=1))
    text = render_memory(item)
    assert "expiry date passed; excluded from current recall" in text
    assert "available as saved background information" not in text
    assert "No explanation was saved" in text


@pytest.mark.parametrize("outcome", [None, ProcessOutcome.SUCCEEDED, ProcessOutcome.PARTIAL])
def test_event_report_keeps_recorded_outcome_distinct_from_fix_verification(outcome):
    event = JournalEvent("PROCESS_RESULT", "repair", "Repair attempt was recorded.", "user", "device", outcome=outcome)
    text = render_event(event)
    assert_report(text)
    if outcome is None:
        assert "No completion outcome was recorded" in text
        assert "do not assume the operation completed" in text
    elif outcome is ProcessOutcome.SUCCEEDED:
        assert "Recorded outcome: Successful" in text
        assert "does not by itself prove" in text
    else:
        assert "Partially completed" in text
        assert "before deciding whether to retry" in text


def test_memory_commands_report_missing_results_and_unreconciled_corrections(tmp_path):
    from aida.frontend.commands.memory import MemoryCommandExecutor, MemoryOperation
    service = MemoryService(MemoryDatabase(tmp_path / "memory.db"), user_id="user", device_id="device")
    empty = MemoryCommandExecutor(service, MemoryOperation.SEARCH, slots={"query": "Outlook"}).execute()
    assert_report(empty.transcript_text)
    assert "does not establish that the event never happened" in empty.transcript_text
    item = service.add_memory(category="repair", title="Repair", summary="Worked", facts={"outcome": "succeeded"})
    revised = MemoryCommandExecutor(service, MemoryOperation.REVISE,
        slots={"memory_id": item.memory_id, "revision_text": "It failed."}).execute()
    assert "excluded from factual recall" in revised.transcript_text
    assert "saved facts still need review" in revised.speech_text
    assert service.retrieve_context("Repair") == []


def test_memory_dialog_uses_plain_text_and_clears_previous_details_on_empty_search(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QScrollArea
    from aida.frontend.memory_dialog import MemoryBankDialog
    app = QApplication.instance() or QApplication([])
    service = MemoryService(MemoryDatabase(tmp_path / "memory.db"), user_id="user", device_id="device")
    item = service.add_memory(category="user.note", title="<b>literal title</b>", summary="<b>literal note</b>")
    dialog = MemoryBankDialog(service)
    try:
        dialog._select_id(item.memory_id)
        assert dialog.detail_label.textFormat() == Qt.TextFormat.PlainText
        assert "<b>literal note</b>" in dialog.detail_label.text()
        assert len(dialog.findChildren(QScrollArea)) == 2
        dialog.search_box.setText("no-match-token")
        dialog.search()
        assert "No matching memories" in dialog.detail_label.text()
        assert "literal note" not in dialog.detail_label.text()
        assert dialog._selected_memory_id is None
        assert dialog.summary_box.toPlainText() == ""
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("size", [(900, 620), (720, 480)])
def test_memory_dialog_long_record_is_readable_and_scrolls_without_overlapping_controls(tmp_path, size):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFont, QPalette
    from PySide6.QtWidgets import QApplication, QScrollArea
    from aida.frontend.memory_dialog import MemoryBankDialog
    from aida.frontend.theme import apply_theme
    app = QApplication.instance() or QApplication([])
    previous_style, previous_font = app.styleSheet(), app.font()
    dialog = None
    try:
        app.setFont(QFont("Segoe UI", 10))
        apply_theme(app)
        service = MemoryService(MemoryDatabase(tmp_path / "memory.db"), user_id="qa", device_id="qa")
        item = service.add_memory(category="user.note", title="Long synthetic memory",
            summary="Earlier startup was slow, but the cause was not verified. " * 20)
        dialog = MemoryBankDialog(service)
        dialog._select_id(item.memory_id)
        dialog.resize(*size)
        dialog.show()
        app.processEvents()
        scroll = next(widget for widget in dialog.findChildren(QScrollArea) if widget.widget() is dialog.detail_label)
        assert scroll.verticalScrollBar().maximum() > 0
        area = scroll.rect().translated(scroll.mapTo(dialog, QPoint(0, 0)))
        for button in (dialog.new_button, dialog.save_button, dialog.delete_button, dialog.close_button,
                       dialog.search_button, dialog.refresh_button):
            bounds = button.rect().translated(button.mapTo(dialog, QPoint(0, 0)))
            assert button.isVisible() and dialog.rect().contains(bounds)
            assert not bounds.intersects(area)
        assert dialog.palette().color(QPalette.ColorRole.Window).lightness() < 80
        assert dialog.detail_label.palette().color(QPalette.ColorRole.WindowText).lightness() > 180
    finally:
        if dialog:
            dialog.close()
            dialog.deleteLater()
        app.setStyleSheet(previous_style)
        app.setFont(previous_font)
        app.processEvents()


@pytest.fixture
def image_path(tmp_path):
    from PySide6.QtGui import QImage
    image = QImage(3, 2, QImage.Format.Format_RGB32)
    image.fill(0)
    path = tmp_path / "screenshot.png"
    assert image.save(str(path))
    return path


class Extractor:
    def __init__(self, result):
        self.result = result

    def extract(self, _content):
        return self.result


@pytest.mark.parametrize("status,expected", [
    ("empty", "does not mean the image is blank"),
    ("unavailable", "unavailable text reading is not a clean result"),
    ("timeout", "unavailable text reading is not a clean result"),
])
def test_perception_distinguishes_no_text_from_unavailable_text(image_path, status, expected):
    service = PerceptionService(extractor=Extractor(TextExtraction(status)))
    evidence = service.observe_image(image_path, source=EvidenceSource.FILE_PICKER)
    text = service.review((evidence,))
    assert_report(text)
    assert "3 by 2 pixels" in text
    assert expected in text
    assert "does not interpret the whole scene" in text
    assert evidence.inferred == ()
    assert "capture confidence" not in evidence.compact_summary()


def test_perception_quotes_ocr_warning_without_presenting_it_as_a_diagnosis(image_path):
    service = PerceptionService(extractor=Extractor(TextExtraction("available", text="WARNING: Virus found\nOpen https://example.invalid now")))
    evidence = service.observe_image(image_path, source=EvidenceSource.FILE_PICKER)
    text = service.review((evidence,))
    assert_report(text)
    assert "> WARNING: Virus found" in text
    assert "UNTRUSTED REFERENCE ONLY" in text
    assert "does not establish that the stated condition is true" in text
    assert "URLs and paths were not opened" in text
    assert "Compare the extracted text with the image" in text


def test_perception_missing_or_invalid_evidence_has_no_fabricated_findings(image_path):
    service = PerceptionService(extractor=Extractor(TextExtraction("empty")))
    empty = service.review(())
    assert_report(empty)
    assert "No image evidence was supplied" in empty
    evidence = service.observe_image(image_path, source=EvidenceSource.FILE_PICKER)
    invalid = service.review((replace(evidence, content=b"changed"),))
    assert_report(invalid)
    assert "This image could not be reviewed" in invalid
    assert "No image interpretation or diagnostic result" in invalid
    assert "Decoded image" not in invalid
