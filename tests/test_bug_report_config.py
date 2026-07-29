from pathlib import Path

from aida.config import DEFAULT_BUG_REPORT_RECIPIENT, get_config


def test_default_bug_report_mailbox_is_registered(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("AIDA_BUG_REPORT_RECIPIENT", raising=False)
    monkeypatch.delenv("AIDA_MICROSOFT_GRAPH_CLIENT_ID", raising=False)

    config = get_config()

    assert config.bug_report_recipient == "AIDAdeveloper@outlook.com"
    assert config.bug_report_recipient == DEFAULT_BUG_REPORT_RECIPIENT
    assert config.microsoft_graph_client_id is None
    assert Path(config.bug_report_outbox_dir).name == "bug_reports"
    assert Path(config.microsoft_token_cache_path).name.endswith(".bin")


def test_bug_report_client_id_is_loaded_without_a_secret(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("AIDA_MICROSOFT_GRAPH_CLIENT_ID", "public-client-id")

    config = get_config()

    assert config.microsoft_graph_client_id == "public-client-id"
    assert not hasattr(config, "microsoft_graph_client_secret")
