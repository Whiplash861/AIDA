from __future__ import annotations

import pytest

from aida.aegis.models import ProviderHealth, SecuritySnapshot
from aida.aegis.remote.models import (
    RemoteAccessClassification,
    RemoteIntrusionAssessment,
    RemoteSessionEvidence,
)
from aida.aegis.remote.store import RemoteSecurityStore
from aida.aegis.sentry import protocol as sentry_module
from aida.aegis.sentry.models import SentryAttackState
from aida.aegis.sentry.protocol import SentryAttackService


def _snapshot() -> SecuritySnapshot:
    return SecuritySnapshot.create(
        processes=(),
        persistence=(),
        listeners=(),
        provider_health=ProviderHealth(
            available=True,
            active=True,
            healthy=True,
            real_time_protection=True,
            signatures_current=True,
            provider_name="Microsoft Defender",
        ),
    )


def _session() -> RemoteSessionEvidence:
    return RemoteSessionEvidence(
        session_id=9,
        username="unexpected",
        domain="HOST",
        state="active",
        protocol_type=2,
        client_address="192.0.2.77",
        client_name="REMOTE",
    )


def _assessment(*, confirmed: bool) -> RemoteIntrusionAssessment:
    return RemoteIntrusionAssessment.create(
        classification=(
            RemoteAccessClassification.CONFIRMED_INTRUSION
            if confirmed
            else RemoteAccessClassification.LIKELY_INTRUSION
        ),
        intrusion_likelihood=1.0 if confirmed else 0.85,
        confidence=1.0 if confirmed else 0.85,
        urgency=1.0 if confirmed else 0.90,
        active_sessions=(_session(),),
        recent_logons=(),
        remote_tools=(),
        support_match=None,
        provider_detection_count=0,
        baseline_change_count=0,
        learning_anomaly_score=0.0,
        learning_confidence=0.0,
        evidence=(),
        counter_evidence=(),
        degraded_reasons=(),
        recommended_action="prepare_sentry_attack_protocol",
        user_confirmed_attacker=confirmed,
    )


def test_sentry_refuses_to_arm_without_explicit_user_attacker_confirmation(
    tmp_path,
) -> None:
    service = SentryAttackService(
        store=RemoteSecurityStore(tmp_path / "remote.db"),
        snapshot_reader=_snapshot,
    )

    with pytest.raises(RuntimeError):
        service.prepare(_assessment(confirmed=False))


def test_sentry_requires_exact_fresh_phrase_and_verifies_session_removal(
    tmp_path, monkeypatch
) -> None:
    calls = {"enumerate": 0, "logoff": 0}

    def enumerate_sessions():
        calls["enumerate"] += 1
        # prepare -> current, execute revalidation -> current, verify -> absent
        if calls["enumerate"] <= 2:
            return ((_session(),), ())
        return ((), ())

    def logoff(session_id: int) -> bool:
        calls["logoff"] += 1
        return session_id == 9

    monkeypatch.setattr(sentry_module, "enumerate_remote_desktop_sessions", enumerate_sessions)
    monkeypatch.setattr(sentry_module, "logoff_remote_desktop_session", logoff)

    service = SentryAttackService(
        store=RemoteSecurityStore(tmp_path / "remote.db"),
        snapshot_reader=_snapshot,
    )
    plan = service.prepare(_assessment(confirmed=True))

    with pytest.raises(RuntimeError):
        service.execute(plan, confirmation_phrase="yes do it")

    result = service.execute(plan, confirmation_phrase=plan.required_phrase)

    assert result.state is SentryAttackState.COMPLETED
    assert result.session_attempted == 1
    assert result.session_terminated == 1
    assert result.remaining_sessions == 0
    assert calls["logoff"] == 1


def test_sentry_plan_is_durable_and_loadable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        sentry_module,
        "enumerate_remote_desktop_sessions",
        lambda: ((_session(),), ()),
    )
    store = RemoteSecurityStore(tmp_path / "remote.db")
    service = SentryAttackService(store=store, snapshot_reader=_snapshot)

    plan = service.prepare(_assessment(confirmed=True))
    restored = service.load_plan(plan.plan_id)

    assert restored is not None
    assert restored.plan_id == plan.plan_id
    assert restored.required_phrase == plan.required_phrase
    assert restored.state is SentryAttackState.AWAITING_CONFIRMATION
