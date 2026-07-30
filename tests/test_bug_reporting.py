from __future__ import annotations

import json
from email import policy
from email.parser import BytesParser
from pathlib import Path

from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.support.models import (
    BugCategory,
    BugDeliveryStatus,
    BugReportDraft,
    BugSeverity,
)
from aida.support.reporting import (
    BugReportOutbox,
    BugReportService,
    EmlBugReportTransport,
    EmlDraftConfig,
)


def _service(tmp_path: Path, transport=None) -> BugReportService:
    memory = MemoryService(
        MemoryDatabase(tmp_path / "memory.db"),
        user_id="tester",
        device_id="device",
    )
    return BugReportService(
        version="1.0-test",
        log_dir=tmp_path / "logs",
        outbox=BugReportOutbox(tmp_path / "outbox"),
        memory=memory,
        transport=transport,
    )


def _draft(description: str = "The report button stopped responding.") -> BugReportDraft:
    return BugReportDraft(
        title="Report button failure",
        category=BugCategory.FRONTEND,
        severity=BugSeverity.MEDIUM,
        description=description,
        expected_behavior="The report form should open.",
        reproduction_steps="1. Launch AIDA\n2. Press Report Bug",
        include_system_info=True,
    )


def test_unconfigured_handoff_preserves_report_in_local_outbox(tmp_path: Path) -> None:
    service = _service(tmp_path, transport=None)

    result = service.submit(_draft())

    assert result.status is BugDeliveryStatus.QUEUED
    record = Path(result.local_record_path)
    assert record.exists()
    payload = json.loads(record.read_text(encoding="utf-8"))
    assert payload["report"]["title"] == "Report button failure"
    assert payload["delivery_status"] == "queued"


def test_successful_handoff_creates_editable_eml_and_draft_record(
    tmp_path: Path,
) -> None:
    opened: list[Path] = []
    mailbox = "AIDAdeveloper@outlook.com"
    transport = EmlBugReportTransport(
        EmlDraftConfig(
            recipient_address=mailbox,
            drafts_dir=tmp_path / "mail_drafts",
        ),
        launcher=opened.append,
    )
    service = _service(tmp_path, transport=transport)

    result = service.submit(_draft())

    assert result.status is BugDeliveryStatus.DRAFT_READY
    assert len(opened) == 1
    draft_path = Path(result.draft_path)
    assert draft_path == opened[0]
    assert draft_path.exists()
    assert Path(result.local_record_path).parent.name == "drafts"
    assert not list((tmp_path / "outbox" / "pending").glob("*.json"))

    message = BytesParser(policy=policy.default).parsebytes(draft_path.read_bytes())
    assert message["To"] == mailbox
    assert message["X-Unsent"] == "1"
    assert message["X-AIDA-Report-ID"] == result.report_id
    assert "Report button failure" in message["Subject"]
    assert "The report button stopped responding." in message.get_content()


def test_qt_string_combo_data_is_normalized_before_eml_rendering(
    tmp_path: Path,
) -> None:
    opened: list[Path] = []
    transport = EmlBugReportTransport(
        EmlDraftConfig(
            recipient_address="AIDAdeveloper@outlook.com",
            drafts_dir=tmp_path / "mail_drafts",
        ),
        launcher=opened.append,
    )
    service = _service(tmp_path, transport=transport)
    draft = BugReportDraft(
        title="Qt combo conversion",
        category="frontend",
        severity="low",
        description="Qt returned plain strings for combo-box user data.",
    )

    result = service.submit(draft)

    assert result.status is BugDeliveryStatus.DRAFT_READY
    assert len(opened) == 1
    message = BytesParser(policy=policy.default).parsebytes(opened[0].read_bytes())
    assert message["Subject"].startswith("[LOW]")
    assert "Category: frontend" in message.get_content()
    assert "Severity: low" in message.get_content()


def test_report_redacts_inline_secrets_before_persistence(tmp_path: Path) -> None:
    service = _service(tmp_path, transport=None)

    result = service.submit(
        _draft("A failure displayed password=super-secret-value in the console.")
    )

    content = Path(result.local_record_path).read_text(encoding="utf-8")
    assert "super-secret-value" not in content
    assert "[REDACTED]" in content


def test_draft_open_failure_keeps_report_and_eml_available(tmp_path: Path) -> None:
    def fail_to_open(path: Path) -> None:
        assert path.exists()
        raise OSError("no default mail application")

    transport = EmlBugReportTransport(
        EmlDraftConfig(
            recipient_address="AIDAdeveloper@outlook.com",
            drafts_dir=tmp_path / "mail_drafts",
        ),
        launcher=fail_to_open,
    )
    service = _service(tmp_path, transport=transport)

    result = service.submit(_draft())

    assert result.status is BugDeliveryStatus.QUEUED
    assert Path(result.local_record_path).exists()
    assert Path(result.draft_path).exists()
    assert "could not be opened automatically" in result.message


def test_eml_handoff_is_unconfigured_for_invalid_destination(tmp_path: Path) -> None:
    transport = EmlBugReportTransport(
        EmlDraftConfig(
            recipient_address="not-an-email",
            drafts_dir=tmp_path / "mail_drafts",
        )
    )

    assert transport.configured is False
