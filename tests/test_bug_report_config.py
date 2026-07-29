from pathlib import Path

from aida.config import (
    DEFAULT_BUG_REPORT_RECIPIENT,
    get_config,
)


def test_default_bug_report_mailbox_is_registered(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("AIDA_BUG_REPORT_RECIPIENT", raising=False)

    config = get_config()

    assert config.bug_report_recipient == "AIDAdeveloper@outlook.com"
    assert config.bug_report_recipient == DEFAULT_BUG_REPORT_RECIPIENT
    assert Path(config.bug_report_outbox_dir).name == "bug_reports"


def test_bug_report_config_has_no_mailbox_or_service_credentials(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv(
        "AIDA_BUG_REPORT_RECIPIENT",
        "AIDAdeveloper@outlook.com",
    )

    config = get_config()

    assert config.bug_report_recipient == "AIDAdeveloper@outlook.com"
    assert not hasattr(config, "outlook_password")
    assert not hasattr(config, "microsoft_graph_client_secret")
    assert not hasattr(config, "sendgrid_api_key")
    assert not hasattr(config, "bug_report_sender")
