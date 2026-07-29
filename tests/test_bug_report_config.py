from pathlib import Path

from aida.config import (
    DEFAULT_BUG_REPORT_RECIPIENT,
    DEFAULT_BUG_REPORT_SENDER,
    get_config,
)


def test_default_bug_report_mailbox_is_registered(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("AIDA_BUG_REPORT_RECIPIENT", raising=False)
    monkeypatch.delenv("AIDA_BUG_REPORT_SENDER", raising=False)
    monkeypatch.delenv("AIDA_SENDGRID_API_KEY", raising=False)

    config = get_config()

    assert config.bug_report_recipient == "AIDAdeveloper@outlook.com"
    assert config.bug_report_recipient == DEFAULT_BUG_REPORT_RECIPIENT
    assert config.bug_report_sender == DEFAULT_BUG_REPORT_SENDER
    assert config.sendgrid_api_key is None
    assert Path(config.bug_report_outbox_dir).name == "bug_reports"


def test_sendgrid_api_key_is_loaded_without_mailbox_password(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("AIDA_SENDGRID_API_KEY", "SG.local-test-key")

    config = get_config()

    assert config.sendgrid_api_key == "SG.local-test-key"
    assert not hasattr(config, "outlook_password")
    assert not hasattr(config, "microsoft_graph_client_secret")
