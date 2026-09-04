from __future__ import annotations

from aida.aegis.learning.service import AegisLearningService
from aida.aegis.learning.store import AegisLearningStore
from aida.aegis.models import ProcessEntity, ProviderHealth, SecuritySnapshot
from aida.aegis.remote import service as remote_service_module
from aida.aegis.remote.models import (
    RemoteAccessClassification,
    RemoteSessionEvidence,
)
from aida.aegis.remote.service import AegisRemoteIntrusionService
from aida.aegis.remote.store import RemoteSecurityStore
from aida.aegis.remote.support import RemoteSupportService
from aida.aegis.store import AegisStore
from aida.security.models import ProviderDetection, SecuritySeverity


def _health() -> ProviderHealth:
    return ProviderHealth(
        available=True,
        active=True,
        healthy=True,
        real_time_protection=True,
        signatures_current=True,
        provider_name="Microsoft Defender",
    )


def _snapshot(*, remote_tool: bool = False) -> SecuritySnapshot:
    processes = ()
    if remote_tool:
        processes = (
            ProcessEntity(
                pid=4400,
                parent_pid=100,
                name="ScreenConnect.ClientService.exe",
                executable=r"C:\Program Files\ScreenConnect\ScreenConnect.ClientService.exe",
                create_time=1000.0,
                remote_endpoints=("203.0.113.50:443",),
            ),
        )
    return SecuritySnapshot.create(
        processes=processes,
        persistence=(),
        listeners=(),
        provider_health=_health(),
    )


def _rdp_session() -> RemoteSessionEvidence:
    return RemoteSessionEvidence(
        session_id=3,
        username="supportuser",
        domain="CLUB",
        state="active",
        protocol_type=2,
        client_address="192.0.2.44",
        client_name="SUPPORT-LAPTOP",
    )


def _service(tmp_path, *, snapshot=None, detections=()):
    aegis_store = AegisStore(tmp_path / "aegis.db")
    remote_store = RemoteSecurityStore(tmp_path / "remote.db")
    support = RemoteSupportService(remote_store)
    learning = AegisLearningService(
        AegisLearningStore(tmp_path / "learning.json"),
        minimum_samples=3,
    )
    current = snapshot or _snapshot()
    return (
        AegisRemoteIntrusionService(
            store=remote_store,
            aegis_store=aegis_store,
            support=support,
            snapshot_reader=lambda: current,
            detection_reader=lambda: tuple(detections),
            learning=learning,
        ),
        support,
    )


def test_no_remote_activity_is_not_called_an_intrusion(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        remote_service_module,
        "enumerate_remote_desktop_sessions",
        lambda: ((), ()),
    )
    monkeypatch.setattr(
        remote_service_module,
        "read_recent_remote_logons",
        lambda: ((), ()),
    )
    service, _support = _service(tmp_path)

    assessment = service.inspect()

    assert assessment.classification is RemoteAccessClassification.NO_REMOTE_ACTIVITY
    assert assessment.user_confirmed_attacker is False


def test_unexpected_active_rdp_is_suspected_not_automatically_confirmed(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        remote_service_module,
        "enumerate_remote_desktop_sessions",
        lambda: ((_rdp_session(),), ()),
    )
    monkeypatch.setattr(
        remote_service_module,
        "read_recent_remote_logons",
        lambda: ((), ()),
    )
    service, _support = _service(tmp_path)

    assessment = service.inspect(unexpected_claim=True)

    assert assessment.classification is RemoteAccessClassification.UNAUTHORIZED_SUSPECTED
    assert assessment.user_confirmed_attacker is False
    assert assessment.intrusion_likelihood < 1.0


def test_active_support_window_explains_ordinary_remote_session(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        remote_service_module,
        "enumerate_remote_desktop_sessions",
        lambda: ((_rdp_session(),), ()),
    )
    monkeypatch.setattr(
        remote_service_module,
        "read_recent_remote_logons",
        lambda: ((), ()),
    )
    service, support = _service(tmp_path, snapshot=_snapshot(remote_tool=True))
    support.authorize("Northstar", duration_minutes=120)

    assessment = service.inspect()

    assert assessment.classification is RemoteAccessClassification.AUTHORIZED_SUPPORT
    assert assessment.support_match is not None
    assert assessment.support_match.vendor_label == "Northstar"


def test_support_context_cannot_suppress_provider_confirmed_threat(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        remote_service_module,
        "enumerate_remote_desktop_sessions",
        lambda: ((_rdp_session(),), ()),
    )
    monkeypatch.setattr(
        remote_service_module,
        "read_recent_remote_logons",
        lambda: ((), ()),
    )
    detection = ProviderDetection(
        detection_id="det-remote",
        name="Trojan:Test/Remote",
        severity=SecuritySeverity.HIGH,
        source="Microsoft Defender",
        file_path=None,
        metadata={"is_active": True},
    )
    service, support = _service(
        tmp_path,
        snapshot=_snapshot(remote_tool=True),
        detections=(detection,),
    )
    support.authorize("Northstar", duration_minutes=120)

    assessment = service.inspect()

    assert assessment.classification is RemoteAccessClassification.SUPPORT_SESSION_ANOMALOUS
    assert assessment.intrusion_likelihood >= 0.62


def test_user_confirmation_requires_a_current_containment_target(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        remote_service_module,
        "enumerate_remote_desktop_sessions",
        lambda: ((), ()),
    )
    monkeypatch.setattr(
        remote_service_module,
        "read_recent_remote_logons",
        lambda: ((), ()),
    )
    service, _support = _service(tmp_path)

    assessment = service.inspect(
        unexpected_claim=True,
        user_confirmed_attacker=True,
    )

    assert assessment.classification is RemoteAccessClassification.NO_REMOTE_ACTIVITY
    assert assessment.user_confirmed_attacker is False


def test_user_can_confirm_current_active_remote_access_as_attacker(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        remote_service_module,
        "enumerate_remote_desktop_sessions",
        lambda: ((_rdp_session(),), ()),
    )
    monkeypatch.setattr(
        remote_service_module,
        "read_recent_remote_logons",
        lambda: ((), ()),
    )
    service, _support = _service(tmp_path)

    assessment = service.inspect(
        unexpected_claim=True,
        user_confirmed_attacker=True,
    )

    assert assessment.classification is RemoteAccessClassification.CONFIRMED_INTRUSION
    assert assessment.user_confirmed_attacker is True
    assert assessment.intrusion_likelihood == 1.0
