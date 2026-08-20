from __future__ import annotations

from types import SimpleNamespace

from aida.artificer.engine import ArtificerEngine


def test_engine_profiles_platform_reviews_source_and_exports(tmp_path) -> None:
    source_root = tmp_path / "project"
    package = source_root / "aida"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '1.0.0'\n", encoding="utf-8")
    data_dir = tmp_path / "artificer"
    config = SimpleNamespace(
        artificer_enabled=True,
        version="1.0.0",
        base_dir=str(source_root),
        artificer_source_root=str(source_root),
        artificer_data_dir=str(data_dir),
        artificer_ledger_path=str(data_dir / "ledger.db"),
        artificer_consent_path=str(data_dir / "consent.json"),
        artificer_developer_registry_path=str(data_dir / "developers.json"),
        artificer_export_dir=str(data_dir / "exports"),
        artificer_dispatch_endpoint=None,
        artificer_local_export_enabled=True,
        artificer_review_interval_seconds=3600,
        artificer_telemetry_level="local_only",
        artificer_mode="test",
    )
    engine = ArtificerEngine(config=config)
    engine.start(run_startup_review=False)
    snapshot = engine.run_review()
    assert snapshot.platform_summary
    assert snapshot.last_review_utc is not None
    report = engine.export_report()
    assert report.exists()
    assert engine.ledger.verify_integrity() is True
    engine.stop()
