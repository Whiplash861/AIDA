from types import SimpleNamespace

from aida.engines.observation_runtime import ObservationRuntime
from aida.autonomy.models import AutonomyLevel


def test_disabled_consent_does_not_construct_engines_and_revocation_stops_both():
    calls = []
    engine = SimpleNamespace(start=lambda: calls.append("start"), stop=lambda **kw: calls.append("stop"),
                             remote_monitor=SimpleNamespace(start=lambda: calls.append("remote-start"), stop=lambda **kw: calls.append("remote-stop")))
    def factory():
        calls.append("build")
        return engine
    runtime = ObservationRuntime(factory)
    disabled = SimpleNamespace(enabled=False, kill_switch_engaged=False, level=AutonomyLevel.MANUAL)
    enabled = SimpleNamespace(enabled=True, kill_switch_engaged=False, level=AutonomyLevel.OBSERVE)
    runtime.apply(disabled)
    assert calls == []
    runtime.apply(enabled)
    assert calls == ["build", "start", "remote-start"]
    runtime.apply(disabled)
    assert calls[-2:] == ["stop", "remote-stop"]
    runtime.close()
    closed_calls = list(calls)
    runtime.apply(enabled)
    assert calls == closed_calls


def test_malformed_autonomy_boolean_is_not_consent():
    from aida.autonomy.controller import AutonomyController
    memory = SimpleNamespace(get_preference=lambda *args: {"enabled": "false", "level": 1})
    assert AutonomyController(memory).settings.enabled is False


class DrainingObserver:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.running = False
        self.stopping = False
        self.starts = 0
        self.stops = 0

    def start(self):
        if self.enabled and not self.running:
            self.starts += 1
            self.running = True
            self.stopping = False

    def stop(self, timeout=0):
        self.stops += 1
        self.stopping = True

    def drain(self):
        self.running = False


def _settings(enabled=True, kill=False):
    return SimpleNamespace(enabled=enabled, kill_switch_engaged=kill,
                           level=AutonomyLevel.OBSERVE if enabled else AutonomyLevel.MANUAL)


def _engine(enabled=True):
    engine = DrainingObserver(enabled)
    engine.remote_monitor = DrainingObserver()
    return engine


def test_rapid_reenable_retries_only_after_previous_threads_drain():
    engine = _engine()
    constructions = []
    runtime = ObservationRuntime(lambda: constructions.append(True) or engine)
    runtime.apply(_settings())
    runtime.apply(_settings(False))
    assert engine.stopping and engine.remote_monitor.stopping
    runtime.apply(_settings())
    runtime.reconcile()
    assert engine.starts == engine.remote_monitor.starts == 1
    engine.drain()
    engine.remote_monitor.drain()
    runtime.reconcile()
    assert engine.starts == engine.remote_monitor.starts == 2
    assert constructions == [True]
    runtime.reconcile()
    assert engine.starts == engine.remote_monitor.starts == 2


def test_disabled_parent_or_kill_switch_stops_remote_monitor_too():
    engine = _engine(enabled=False)
    runtime = ObservationRuntime(lambda: engine)
    runtime.apply(_settings())
    assert engine.starts == engine.remote_monitor.starts == 0
    engine.enabled = True
    runtime.reconcile()
    assert engine.starts == engine.remote_monitor.starts == 1
    engine.enabled = False
    runtime.reconcile()
    assert engine.stopping and engine.remote_monitor.stopping
    engine.drain()
    engine.remote_monitor.drain()
    engine.enabled = True
    runtime.apply(_settings(kill=True))
    runtime.reconcile()
    assert engine.starts == engine.remote_monitor.starts == 1


def test_construction_failure_is_not_retried_by_timer_or_same_enabled_state():
    import pytest
    attempts = []
    def factory():
        attempts.append(True)
        raise RuntimeError("Corrupt learning state")
    runtime = ObservationRuntime(factory)
    with pytest.raises(RuntimeError):
        runtime.apply(_settings())
    for _ in range(3):
        runtime.reconcile()
        runtime.apply(_settings())
    assert len(attempts) == 1
    runtime.apply(_settings(False))
    with pytest.raises(RuntimeError):
        runtime.apply(_settings())
    assert len(attempts) == 2


def test_disable_and_close_revoke_during_pending_factory_without_waiting():
    from threading import Event, Thread
    for close in (False, True):
        entered, release = Event(), Event()
        engine = _engine()
        def factory():
            entered.set()
            assert release.wait(3)
            return engine
        runtime = ObservationRuntime(factory)
        worker = Thread(target=lambda: runtime.apply(_settings()))
        worker.start()
        assert entered.wait(1)
        if close:
            runtime.close()
        else:
            runtime.apply(_settings(False))
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert engine.starts == engine.remote_monitor.starts == 0
        runtime.reconcile()
        assert engine.starts == engine.remote_monitor.starts == 0
        if close:
            runtime.apply(_settings())
            assert engine.starts == engine.remote_monitor.starts == 0


def test_repeated_disabled_reconcile_does_not_emit_repeated_stopped_events():
    engine = _engine()
    runtime = ObservationRuntime(lambda: engine)
    runtime.apply(_settings())
    runtime.apply(_settings(False))
    for _ in range(3):
        runtime.reconcile()
    assert engine.stops == engine.remote_monitor.stops == 1
    engine.drain()
    engine.remote_monitor.drain()
    runtime.reconcile()
    for _ in range(3):
        runtime.reconcile()
    assert engine.stops == engine.remote_monitor.stops == 2



def test_canonical_disable_can_revoke_while_enable_listener_initializes(tmp_path):
    from threading import Event, Thread
    from aida.autonomy.controller import AutonomyController
    from aida.memory.service import MemoryService
    entered, release = Event(), Event()
    engine = _engine()
    def factory():
        entered.set()
        assert release.wait(3)
        return engine
    runtime = ObservationRuntime(factory)
    control = AutonomyController(MemoryService(tmp_path / "m.db", user_id="owner", device_id="host"))
    control.subscribe(runtime.apply)
    worker = Thread(target=lambda: control.set_enabled(True, changed_by="owner"))
    worker.start()
    assert entered.wait(1)
    try:
        control.set_enabled(False, changed_by="owner")
        assert control.settings.enabled is False
        assert not release.is_set()
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert engine.starts == engine.remote_monitor.starts == 0


def test_shutdown_failure_for_one_observer_still_stops_the_other():
    engine = _engine()
    runtime = ObservationRuntime(lambda: engine)
    runtime.apply(_settings())
    def failure(timeout=0):
        raise RuntimeError("Engine shutdown failed")
    engine.stop = failure
    runtime.close()
    assert engine.remote_monitor.stopping
    starts = engine.remote_monitor.starts
    runtime.reconcile()
    assert engine.remote_monitor.starts == starts
