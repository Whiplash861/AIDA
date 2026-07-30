from __future__ import annotations

from email import policy
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aida.frontend.bug_report_review_dialog import (
    PreparedEmailDraft,
    browser_handoff_body,
    build_gmail_compose_url,
    build_outlook_compose_url,
    read_prepared_email_draft,
)


def test_read_prepared_email_draft(tmp_path: Path) -> None:
    path = tmp_path / "report.eml"
    message = EmailMessage(policy=policy.default)
    message["To"] = "AIDAdeveloper@outlook.com"
    message["Subject"] = "AIDA test report"
    message["X-Unsent"] = "1"
    message.set_content("Complete report body")
    path.write_bytes(message.as_bytes(policy=policy.default))

    draft = read_prepared_email_draft(path)

    assert draft.path == path
    assert draft.recipient == "AIDAdeveloper@outlook.com"
    assert draft.subject == "AIDA test report"
    assert draft.body.strip() == "Complete report body"


def test_gmail_compose_url_contains_destination_subject_and_body() -> None:
    draft = PreparedEmailDraft(
        path=Path("report.eml"),
        recipient="AIDAdeveloper@outlook.com",
        subject="Frontend issue",
        body="The button failed.",
    )

    url = build_gmail_compose_url(draft)
    query = parse_qs(urlparse(url).query)

    assert query["to"] == ["AIDAdeveloper@outlook.com"]
    assert query["su"] == ["Frontend issue"]
    assert query["body"] == ["The button failed."]
    assert "%20" in url
    assert "Frontend+issue" not in url
    assert "The+button+failed" not in url


def test_outlook_compose_url_contains_destination_subject_and_body() -> None:
    draft = PreparedEmailDraft(
        path=Path("report.eml"),
        recipient="AIDAdeveloper@outlook.com",
        subject="Memory issue",
        body="The revision was not displayed.",
    )

    url = build_outlook_compose_url(draft)
    query = parse_qs(urlparse(url).query)

    assert query["to"] == ["AIDAdeveloper@outlook.com"]
    assert query["subject"] == ["Memory issue"]
    assert query["body"] == ["The revision was not displayed."]
    assert "%20" in url
    assert "Memory+issue" not in url
    assert "The+revision+was+not+displayed" not in url


def test_webmail_urls_percent_encode_line_breaks_and_literal_plus_signs() -> None:
    draft = PreparedEmailDraft(
        path=Path("report.eml"),
        recipient="AIDAdeveloper@outlook.com",
        subject="AIDA + report",
        body="First line\nSecond + line",
    )

    gmail_url = build_gmail_compose_url(draft)
    outlook_url = build_outlook_compose_url(draft)

    for url in (gmail_url, outlook_url):
        assert "%20" in url
        assert "%0A" in url
        assert "%2B" in url
        assert "+" not in url


def test_browser_handoff_truncates_large_body_with_clear_notice() -> None:
    body = "A" * 20_000

    prepared = browser_handoff_body(body)

    assert len(prepared) <= 6_000
    assert "complete report to the clipboard" in prepared
