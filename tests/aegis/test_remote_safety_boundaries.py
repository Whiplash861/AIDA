from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import psutil
import pytest

from aida.aegis.models import ProcessEntity, ProviderHealth, SecuritySnapshot
from aida.aegis.remote.models import RemoteSessionEvidence, RemoteAccessClassification, RemoteIntrusionAssessment, utc_now
from aida.aegis.remote.store import RemoteSecurityStore
from aida.aegis.remote.support import RemoteSupportService
from aida.aegis.remote.tooling import identify_remote_tools
from aida.aegis.remote.monitor import RemoteIntrusionMonitor, _assessment_signature
from aida.aegis.sentry import protocol
from aida.aegis.sentry.models import SentryAttackPlan, SentryAttackState, SentryProcessTarget


def snapshot(processes=()):
    return SecuritySnapshot.create(processes=processes, persistence=(), listeners=(),
        provider_health=ProviderHealth(True, True, True, True, True, "fake"))


def session(**kwargs):
    return replace(RemoteSessionEvidence(9, "support", "HOST", "active", 2,
        "192.0.2.1", logon_time=12345), **kwargs)


def assessment(sessions=(), tools=()):
    return RemoteIntrusionAssessment.create(classification=RemoteAccessClassification.CONFIRMED_INTRUSION,
        intrusion_likelihood=1, confidence=.8, urgency=1, active_sessions=sessions,
        recent_logons=(), remote_tools=tools, support_match=None, provider_detection_count=0,
        baseline_change_count=0, learning_anomaly_score=0, learning_confidence=0,
        user_confirmed_attacker=True)


def saved_plan(store):
    plan = SentryAttackPlan.create(assessment_id="assessment", session_targets=(), process_targets=(),
        rationale=("test",), limitations=())
    store.store_sentry_plan(plan.to_record())
    return plan


def test_sentry_claim_is_atomic_across_store_instances(tmp_path):
    path = tmp_path / "remote.db"
    first, second = RemoteSecurityStore(path), RemoteSecurityStore(path)
    plan = saved_plan(first)

    def claim(store):
        try:
            store.claim_sentry_plan(plan.to_record(), now=utc_now())
            return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, (first, second))) == [False, True]
    with pytest.raises(RuntimeError):
        first.store_sentry_plan(plan.to_record())


def test_expired_plan_is_persistently_nonexecutable(tmp_path):
    store = RemoteSecurityStore(tmp_path / "remote.db")
    plan = saved_plan(store)
    with pytest.raises(RuntimeError, match="expired"):
        store.claim_sentry_plan(plan.to_record(), now=plan.created_at + timedelta(seconds=121))
    assert store.get_sentry_plan_record(plan.plan_id)["state"] == "expired"


def test_caller_cannot_replace_persisted_scope(tmp_path):
    store = RemoteSecurityStore(tmp_path / "remote.db")
    plan = saved_plan(store)
    forged = replace(plan, required_phrase="different phrase")
    with pytest.raises(RuntimeError, match="changed"):
        store.claim_sentry_plan(forged.to_record(), now=utc_now())


def test_second_instance_preserves_live_execution_owner(tmp_path):
    path = tmp_path / "remote.db"
    first = RemoteSecurityStore(path)
    plan = saved_plan(first)
    first.claim_sentry_plan(plan.to_record(), now=utc_now())
    second = RemoteSecurityStore(path)
    assert second.mark_sentry_interrupted() == 0
    assert second.get_sentry_plan_record(plan.plan_id)["state"] == "executing"


def test_missing_session_generation_cannot_arm_sentry(tmp_path, monkeypatch):
    row = session(logon_time=None)
    monkeypatch.setattr(protocol, "enumerate_remote_desktop_sessions", lambda: ((row,), ()))
    service = protocol.SentryAttackService(store=RemoteSecurityStore(tmp_path / "remote.db"), snapshot_reader=snapshot)
    with pytest.raises(RuntimeError, match="fully identified"):
        service.prepare(assessment((row,)))


def test_final_session_access_denial_never_reports_success(tmp_path, monkeypatch):
    reads = iter([((session(),), ()), ((session(),), ()), ((), ("access_denied",))])
    monkeypatch.setattr(protocol, "enumerate_remote_desktop_sessions", lambda: next(reads))
    monkeypatch.setattr(protocol, "logoff_remote_desktop_session", lambda _: True)
    store = RemoteSecurityStore(tmp_path / "remote.db")
    service = protocol.SentryAttackService(store=store, snapshot_reader=snapshot)
    plan = service.prepare(assessment((session(),)))
    result = service.execute(plan, confirmation_phrase=plan.required_phrase)
    assert result.state is SentryAttackState.PARTIAL
    assert not result.verification_complete
    assert any(item["status"] == "verification_unavailable" for item in store.get_sentry_plan_record(plan.plan_id)["target_outcomes"])
    with pytest.raises(RuntimeError):
        service.execute(plan, confirmation_phrase=plan.required_phrase)


def test_reused_session_id_does_not_inherit_approval(tmp_path, monkeypatch):
    reads = iter([((session(),), ()), ((session(logon_time=99999),), ()), ((session(logon_time=99999),), ())])
    monkeypatch.setattr(protocol, "enumerate_remote_desktop_sessions", lambda: next(reads))
    monkeypatch.setattr(protocol, "logoff_remote_desktop_session", lambda _: pytest.fail("Reused session must not be logged off"))
    service = protocol.SentryAttackService(store=RemoteSecurityStore(tmp_path / "remote.db"), snapshot_reader=snapshot)
    plan = service.prepare(assessment((session(),)))
    result = service.execute(plan, confirmation_phrase=plan.required_phrase)
    assert result.state is not SentryAttackState.COMPLETED
    assert result.session_attempted == 0


def test_process_identity_requires_exact_creation_time_and_access(monkeypatch):
    target = SentryProcessTarget(1200, 100, "anydesk.exe", r"C:\AnyDesk\anydesk.exe", 1000.0, "remote_control_process", "anydesk")
    fake = SimpleNamespace(name=lambda: "anydesk.exe", exe=lambda: target.executable,
        create_time=lambda: 1000.01, ppid=lambda: 100)
    monkeypatch.setattr(protocol.psutil, "Process", lambda _: fake)
    with pytest.raises(RuntimeError):
        protocol._revalidate_process(target)
    monkeypatch.setattr(protocol.psutil, "Process", lambda _: (_ for _ in ()).throw(psutil.AccessDenied(1200)))
    with pytest.raises(psutil.AccessDenied):
        protocol._revalidate_process(target)


def test_restarted_remote_tool_blocks_complete_containment(tmp_path, monkeypatch):
    original = ProcessEntity(1200, 100, "anydesk.exe", r"C:\AnyDesk\anydesk.exe", create_time=1000.0)
    current = snapshot((original,))
    restarted = snapshot((replace(original, pid=1201, create_time=1001.0),))
    snapshots = iter([current, restarted])
    monkeypatch.setattr(protocol, "enumerate_remote_desktop_sessions", lambda: ((), ()))
    checks = iter([SimpleNamespace(pid=1200), None])
    monkeypatch.setattr(protocol, "_revalidate_process", lambda _: next(checks))
    monkeypatch.setattr(protocol, "_terminate_exact_process", lambda *_: True)
    service = protocol.SentryAttackService(store=RemoteSecurityStore(tmp_path / "remote.db"), snapshot_reader=lambda: next(snapshots))
    plan = service.prepare(assessment(tools=identify_remote_tools(current)))
    result = service.execute(plan, confirmation_phrase=plan.required_phrase)
    assert result.state is SentryAttackState.PARTIAL
    assert any("restarted" in detail for detail in result.details)


def test_support_does_not_combine_account_and_address_from_different_sessions(tmp_path):
    support = RemoteSupportService(RemoteSecurityStore(tmp_path / "remote.db"))
    support.authorize("help", expected_accounts=(r"HOST\support",), expected_source_addresses=("192.0.2.1",))
    match = support.best_match(sessions=(session(client_address="192.0.2.2"), session(session_id=10, username="other")), tools=())
    assert not match.fully_matched
    assert match.matched_session_ids == ()
    exact = support.best_match(sessions=(session(),), tools=())
    assert exact.fully_matched
    assert exact.matched_session_ids == (9,)


def test_monitor_signature_changes_for_same_count_new_session():
    first = assessment((session(),))
    second = replace(first, active_sessions=(session(logon_time=99999),))
    assert _assessment_signature(first) != _assessment_signature(second)


def test_monitor_resets_episode_after_activity_ends():
    hints = iter([True, False, True])
    waits = iter([False, False, False, True])
    current = assessment((session(),))
    service = SimpleNamespace(activity_hint=lambda: next(hints), inspect=lambda: current)
    monitor = RemoteIntrusionMonitor(service=service, memory=None, bridge=None)
    monitor._stop = SimpleNamespace(is_set=lambda: False, wait=lambda _: next(waits))
    recorded = []
    monitor._record = lambda *args: recorded.append(args)
    monitor._loop()
    assert len(recorded) == 2
