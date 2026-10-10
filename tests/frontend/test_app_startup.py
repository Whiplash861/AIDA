"""Exercise production startup wiring with real dialogs and temporary local state."""
from __future__ import annotations

import ast
import inspect
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication


@pytest.mark.parametrize("reproduce_old_wiring", [False, True], ids=["production", "reject-old-wiring"])
def test_production_main_constructs_dialogs_with_shared_task_manager(tmp_path, monkeypatch, reproduce_old_wiring):
    from aida.frontend import app as frontend
    from aida.artificer.engine import ArtificerEngine
    from aida.config import AidaConfig

    qt = QApplication.instance() or QApplication([])
    original_widgets = set(qt.topLevelWidgets())
    original_style, original_palette, original_font = qt.styleSheet(), qt.palette(), qt.font()
    original_quit = qt.quitOnLastWindowClosed()
    created, scheduled = {}, []
    config = AidaConfig(
        app_name="AIDA", app_full_name="AIDA startup fixture", version="test",
        base_dir=str(tmp_path), assets_dir=str(tmp_path / "assets"), sounds_dir=str(tmp_path / "sounds"),
        log_dir=str(tmp_path / "logs"), memory_db_path=str(tmp_path / "memory.db"),
        elevenlabs_api_key=None, elevenlabs_voice_id=None, voice_enabled=False,
        bug_report_outbox_dir=str(tmp_path / "outbox"), artificer_enabled=False,
        artificer_source_root=str(tmp_path), artificer_data_dir=str(tmp_path / "artificer"),
        artificer_ledger_path=str(tmp_path / "artificer" / "ledger.db"),
        artificer_consent_path=str(tmp_path / "artificer" / "consent.json"),
        artificer_developer_registry_path=str(tmp_path / "artificer" / "developers.json"),
        artificer_export_dir=str(tmp_path / "exports"),
    )
    monkeypatch.setattr(frontend, "load_dotenv", lambda: None)
    monkeypatch.setattr(frontend, "get_config", lambda: config)
    monkeypatch.setattr(frontend, "setup_logging", lambda _config: None)
    monkeypatch.setattr(frontend, "build_artificer_engine", lambda config: ArtificerEngine(
        config=config, platform_adapter=SimpleNamespace(name="fixture")))

    # Keep production Qt objects/signals and constructors. Only execution of
    # background/native/cloud work is replaced; no provider or microphone runs.
    def forbid_external(*_args, **_kwargs):
        pytest.fail("Startup construction must not contact cloud/native services")

    monkeypatch.setattr(frontend.WindowsAntivirusDiscovery, "discover", forbid_external)
    monkeypatch.setattr(frontend.AIDABrain, "_get_client", forbid_external)
    monkeypatch.setattr(frontend.SecurityAlertBridge, "start", lambda _self: None)
    monkeypatch.setattr(frontend.TaskManager, "run_task", lambda self, name, function, **kwargs:
                        scheduled.append((name, function, kwargs)) or True)

    class StartupTimers(QTimer):
        def start(self, *_args):
            pass

        @staticmethod
        def singleShot(*_args):
            pass

    # Suppress main()'s deferred host recovery/observation callbacks. Real widget
    # timers and the explicitly bounded test event loop remain ordinary Qt.
    monkeypatch.setattr(frontend, "QTimer", StartupTimers)
    for name in ("AIDAWindow", "TaskManager", "MemoryBankDialog", "BugReportDialog",
                 "ThreatCenterDialog", "TaskCenterDialog", "ArtificerCenterDialog"):
        constructor = getattr(frontend, name)
        def record_constructor(*args, _name=name, _constructor=constructor, **kwargs):
            instance = _constructor(*args, **kwargs)
            created[_name] = instance
            return instance
        monkeypatch.setattr(frontend, name, record_constructor)

    def brief_event_loop():
        # These are actual dialogs constructed by production main(), not mocks
        # that accept arbitrary keywords and conceal a constructor mismatch.
        shared = created["TaskManager"]
        assert created["ThreatCenterDialog"].task_manager is shared
        assert created["ArtificerCenterDialog"].task_manager is shared
        assert created["TaskCenterDialog"].confirmations is not None
        assert created["TaskCenterDialog"].parent() is created["AIDAWindow"]
        assert {"MemoryBankDialog", "BugReportDialog", "TaskCenterDialog", "ThreatCenterDialog"} <= created.keys()
        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()
        return 0

    monkeypatch.setattr(qt, "exec", brief_event_loop)
    launch = frontend.main
    if reproduce_old_wiring:
        # Mutation is confined to a compiled in-memory function. Reproduce the
        # reported call-site mistake without editing production app.py.
        tree = ast.parse(inspect.getsource(frontend.main))
        calls = {node.func.id: node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id in {"ThreatCenterDialog", "TaskCenterDialog"}}
        calls["ThreatCenterDialog"].keywords = [keyword for keyword in calls["ThreatCenterDialog"].keywords
                                                if keyword.arg != "task_manager"]
        calls["TaskCenterDialog"].keywords.append(ast.keyword(arg="task_manager", value=ast.Name(id="task_manager", ctx=ast.Load())))
        namespace = dict(vars(frontend))
        exec(compile(ast.fix_missing_locations(tree), "<old-startup-wiring>", "exec"), namespace)
        launch = namespace["main"]

    try:
        if reproduce_old_wiring:
            with pytest.raises(TypeError, match="unexpected keyword argument 'task_manager'"):
                launch()
        else:
            assert launch() == 0
            assert any(name == "engine_initialization" for name, _, _ in scheduled)
            assert created["ThreatCenterDialog"]._disposed is True
            assert created["TaskManager"]._closing is True
        assert (tmp_path / "memory.db").is_file()
    finally:
        frontend.set_active_artificer(None)
        for widget in set(qt.topLevelWidgets()) - original_widgets:
            widget.close()
            widget.deleteLater()
        qt.processEvents()
        qt.setStyleSheet(original_style)
        qt.setPalette(original_palette)
        qt.setFont(original_font)
        qt.setQuitOnLastWindowClosed(original_quit)
