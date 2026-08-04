from datetime import datetime, timedelta, timezone

from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.stand_down import StandDownService, StandDownStatus


def setup_service(tmp_path):
    database = MemoryDatabase(tmp_path / "m.db")
    memory = MemoryService(database, user_id="Austin", device_id="PC")
    return StandDownService(database, memory)


def test_stand_down_is_hash_bound_and_explicit_scan_overrides(tmp_path):
    service = setup_service(tmp_path)
    target = tmp_path / "program.exe"
    target.write_bytes(b"original")
    service.create(
        target,
        reason="User accepts risk",
        authorized_by="Austin",
    )

    assert service.evaluate(target).suppress_aida_recommendation is True
    explicit = service.evaluate(target, explicit_scan=True)
    assert explicit.suppress_aida_recommendation is False
    assert explicit.status is StandDownStatus.ACTIVE
    assert service.find_active(target) is not None

    target.write_bytes(b"changed")
    result = service.evaluate(target)
    assert result.suppress_aida_recommendation is False
    assert result.status is StandDownStatus.SUSPENDED
    assert service.find_active(target) is None


def test_new_alarm_suspends_exception_even_during_explicit_scan(tmp_path):
    service = setup_service(tmp_path)
    target = tmp_path / "program.exe"
    target.write_bytes(b"x")
    record = service.create(
        target,
        reason="User accepts risk",
        authorized_by="Austin",
        alarm_count=1,
    )

    result = service.evaluate(
        target,
        explicit_scan=True,
        current_alarm_count=2,
    )

    assert result.status is StandDownStatus.SUSPENDED
    assert result.suppress_aida_recommendation is False
    assert service.get(record.exception_id).status is StandDownStatus.SUSPENDED


def test_new_exception_supersedes_existing_active_record(tmp_path):
    service = setup_service(tmp_path)
    target = tmp_path / "program.exe"
    target.write_bytes(b"x")
    first = service.create(
        target,
        reason="First decision",
        authorized_by="Austin",
    )
    second = service.create(
        target,
        reason="Updated decision",
        authorized_by="Austin",
    )

    assert service.get(first.exception_id).status is StandDownStatus.REVOKED
    assert service.find_active(target).exception_id == second.exception_id
    assert len(service.list_active()) == 1


def test_revoke_restores_normal_assessment(tmp_path):
    service = setup_service(tmp_path)
    target = tmp_path / "program.exe"
    target.write_bytes(b"x")
    record = service.create(
        target,
        reason="Temporary trust",
        authorized_by="Austin",
    )

    revoked = service.revoke(record.exception_id, revoked_by="Austin")

    assert revoked.status is StandDownStatus.REVOKED
    assert service.find_active(target) is None
    assert service.evaluate(target).suppress_aida_recommendation is False


def test_expired_exception_is_removed_from_active_list(tmp_path):
    service = setup_service(tmp_path)
    target = tmp_path / "program.exe"
    target.write_bytes(b"x")
    record = service.create(
        target,
        reason="Short trust",
        authorized_by="Austin",
        expires_in_days=1,
    )
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    with service.database.transaction() as connection:
        connection.execute(
            "UPDATE stand_down_items SET expires_at = ? WHERE exception_id = ?",
            (past.isoformat(), record.exception_id),
        )

    assert service.list_active() == []
    assert service.get(record.exception_id).status is StandDownStatus.EXPIRED
