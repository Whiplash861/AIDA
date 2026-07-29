from __future__ import annotations

import json
from pathlib import Path

import pytest

from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.support.models import (
    BugCategory,
    BugDeliveryStatus,
    BugReport,
    BugReportDraft,
    BugSeverity,
)
from aida.support.reporting import (
    BugReportDeliveryError,
    BugReportOutbox,
    BugReportService,
    MicrosoftGraphBugReportTransport,
    MicrosoftGraphMailConfig,
)


class _TransportConfig:
    recipient_address = "AIDAdeveloper@outlook.com"


class _SuccessfulTransport:
    configured = True

    def __init__(self) -> None:
        self.reports: list[BugReport] = []
        self.config = _TransportConfig()

    def send(self, report: BugReport, *, authentication_prompt=None) -> None:
        del authentication_prompt
        self.reports.append(report)


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


class _FakeApp:
    def __init__(self, result: dict) -> None:
        self.result = result

    def get_accounts(self, username: str):
        return [{"username": username}]

    def acquire_token_silent(self, scopes: list[str], account: dict):
        del scopes, account
        return self.result


class _TestGraphTransport(MicrosoftGraphBugReportTransport):
    def __init__(self, *args, app: _FakeApp, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.app = app

    def _build_client(self):
        return self.app


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


def test_unconfigured_delivery_preserves_report_in_local_outbox(tmp_path: Path) -> None:
    service = _service(tmp_path, transport=None)

    result = service.submit(_draft())

    assert result.status is BugDeliveryStatus.QUEUED
    record = Path(result.local_record_path)
    assert record.exists()
    payload = json.loads(record.read_text(encoding="utf-8"))
    assert payload["report"]["title"] == "Report button failure"
    assert payload["delivery_status"] == "queued"


def test_successful_delivery_moves_report_to_sent_outbox(tmp_path: Path) -> None:
    transport = _SuccessfulTransport()
    service = _service(tmp_path, transport=transport)

    result = service.submit(_draft())

    assert result.status is BugDeliveryStatus.SENT
    assert len(transport.reports) == 1
    assert Path(result.local_record_path).parent.name == "sent"
    assert not list((tmp_path / "outbox" / "pending").glob("*.json"))


def test_report_redacts_inline_secrets_before_persistence(tmp_path: Path) -> None:
    service = _service(tmp_path, transport=None)

    result = service.submit(
        _draft("A failure displayed password=super-secret-value in the console.")
    )

    content = Path(result.local_record_path).read_text(encoding="utf-8")
    assert "super-secret-value" not in content
    assert "[REDACTED]" in content


def test_graph_transport_sends_to_registered_developer_mailbox() -> None:
    mailbox = "AIDAdeveloper@outlook.com"
    session = _FakeSession(_FakeResponse(202))
    app = _FakeApp(
        {
            "access_token": "not-a-real-token",
            "id_token_claims": {"preferred_username": mailbox},
        }
    )
    transport = _TestGraphTransport(
        MicrosoftGraphMailConfig(
            client_id="test-client-id",
            recipient_address=mailbox,
            expected_account=mailbox,
            token_cache_path="unused-in-test",
        ),
        session=session,
        app=app,
    )
    report = BugReport(
        title="Example failure",
        category=BugCategory.FRONTEND,
        severity=BugSeverity.LOW,
        description="A harmless test report.",
        expected_behavior="The test should send.",
        reproduction_steps="Run the unit test.",
        reporter_contact="",
    )

    transport.send(report)

    assert session.calls[0]["url"].endswith("/me/sendMail")
    recipients = session.calls[0]["json"]["message"]["toRecipients"]
    assert recipients[0]["emailAddress"]["address"] == mailbox


def test_graph_transport_rejects_wrong_connected_account() -> None:
    mailbox = "AIDAdeveloper@outlook.com"
    app = _FakeApp(
        {
            "access_token": "not-a-real-token",
            "id_token_claims": {"preferred_username": "someone@example.com"},
        }
    )
    transport = _TestGraphTransport(
        MicrosoftGraphMailConfig(
            client_id="test-client-id",
            recipient_address=mailbox,
            expected_account=mailbox,
            token_cache_path="unused-in-test",
        ),
        session=_FakeSession(_FakeResponse(202)),
        app=app,
    )
    report = BugReport(
        title="Example failure",
        category=BugCategory.FRONTEND,
        severity=BugSeverity.LOW,
        description="A harmless test report.",
        expected_behavior="The test should send.",
        reproduction_steps="Run the unit test.",
        reporter_contact="",
    )

    with pytest.raises(BugReportDeliveryError):
        transport.send(report)
