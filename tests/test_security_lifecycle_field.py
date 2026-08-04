from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from aida.autonomy.controller import AutonomyController
from aida.autonomy.observation import AutonomyObservationService, SecurityObservation
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.continuity import (
    ProviderTaskState,
    SecurityTaskLedger,
    SecurityTaskRecord,
    TrackingState,
)
from aida.security.detection_intelligence import (
    DetectionDisposition,
    DetectionReconciler,
)
from aida.security.models import ProviderDetection, SecuritySeverity
from aida.security.stand_down import StandDownService, StandDownStatus
from aida.security.startup_recovery import SecurityStartupReconciler
from aida.security.threat_intelligence import (
    AttributionConfidence,
    ThreatIntelligenceBuilder,
)
from aida.security.windows.defender_cancel import (
    ActiveDefenderScan,
    DefenderCancelableScan,
    DefenderProviderScanState,
    DefenderScanStateResult,
)


class TerminalDefender:
    def __init__(self, state: DefenderProviderScanState):
        self.state = state

    def active_cancelable_scan(self):
        return None

    def scan_state(self, scan_id: str):
        return DefenderScanStateResult(
            scan_id=scan_id,
            state=self.state,
            event_id=(
                1001
                if self.state is DefenderProviderScanState.COMPLETED
                else 1002
                if self.state is DefenderProviderScanState.CANCELLED
                else None
            ),
        )


class ActiveDefender:
    def __init__(self, scan_id: str, started_at: datetime):
        self.scan_id = scan_id
        self.started_at = started_at

    def active_cancelable_scan(self):
        return ActiveDefenderScan(
            scan_id=self.scan_id,
            mode=DefenderCancelableScan.QUICK,
            started_at=self.started_at.isoformat(),
            parameters="Quick Scan",
        )

    def scan_state(self, scan_id: str):
        return DefenderScanStateResult(
            scan_id=scan_id,
            state=DefenderProviderScanState.RUNNING,
            event_id=1000,
        )


def _memory(tmp_path: Path):
    database = MemoryDatabase(tmp_path / "memory.db")
    memory = MemoryService(
        database,
        user_id="Austin",
        device_id="AIDA-TEST-PC",
    )
    return database, memory


def _detection(
    detection_id: str,
    *,
    active: bool | None,
    severity: SecuritySeverity = SecuritySeverity.HIGH,
    initial_detection_time: str = "",
    action_success: bool | None = None,
    path: Path | None = None,
) -> ProviderDetection:
    return ProviderDetection(
        detection_id=detection_id,
        name="Test:CredentialStealer",
        severity=severity,
        source="Microsoft Defender",
        file_path=path,
        metadata={
            "is_active": active,
            "action_success": action_success,
            "initial_detection_time": initial_detection_time,
        },
    )


def test_restart_recovery_reattaches_to_matching_active_scan(tmp_path: Path):
    database, memory = _memory(tmp_path)
    ledger = SecurityTaskLedger(database, user_id="Austin", device_id="AIDA-TEST-PC")
    started = datetime.now(timezone.utc) - timedelta(minutes=3)
    task = ledger.create(
        SecurityTaskRecord(
            request_id="surface-request",
            provider_id="microsoft_defender",
            provider_scan_id="{SURFACE}",
            mode="SURFACE",
            authorized_by="Austin",
            authorization_reason="manual field test",
            provider_started_at=started,
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )

    candidate = SecurityStartupReconciler(
        ledger,
        ActiveDefender("{SURFACE}", started),
        memory,
    ).reconcile()

    assert candidate is not None
    assert candidate.task.task_id == task.task_id
    assert candidate.task.tracking_state is TrackingState.RECOVERING
    assert candidate.task.recovery_count == 1
    assert candidate.provider_elapsed_seconds is not None
    assert candidate.provider_elapsed_seconds >= 150


def test_restart_recovery_closes_scan_completed_while_aida_was_closed(tmp_path: Path):
    database, memory = _memory(tmp_path)
    ledger = SecurityTaskLedger(database, user_id="Austin", device_id="AIDA-TEST-PC")
    task = ledger.create(
        SecurityTaskRecord(
            request_id="completed-request",
            provider_id="microsoft_defender",
            provider_scan_id="{COMPLETED}",
            mode="SURFACE",
            authorized_by="Austin",
            authorization_reason="manual field test",
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )

    candidate = SecurityStartupReconciler(
        ledger,
        TerminalDefender(DefenderProviderScanState.COMPLETED),
        memory,
    ).reconcile()

    assert candidate is None
    record = ledger.get(task.task_id)
    assert record is not None
    assert record.provider_state is ProviderTaskState.COMPLETED
    assert record.tracking_state is TrackingState.TERMINAL
    assert "1001" in record.detail
    assert any(
        event.event_type == "PROCESS_SUCCEEDED"
        and event.payload.get("provider_scan_id") == "{COMPLETED}"
        for event in memory.list_events()
    )


def test_restart_recovery_closes_scan_cancelled_while_aida_was_closed(tmp_path: Path):
    database, memory = _memory(tmp_path)
    ledger = SecurityTaskLedger(database, user_id="Austin", device_id="AIDA-TEST-PC")
    task = ledger.create(
        SecurityTaskRecord(
            request_id="cancelled-request",
            provider_id="microsoft_defender",
            provider_scan_id="{CANCELLED}",
            mode="FULL_SWEEP",
            authorized_by="Austin",
            authorization_reason="manual field test",
            provider_state=ProviderTaskState.RUNNING,
            tracking_state=TrackingState.MONITORING,
        )
    )

    SecurityStartupReconciler(
        ledger,
        TerminalDefender(DefenderProviderScanState.CANCELLED),
        memory,
    ).reconcile()

    record = ledger.get(task.task_id)
    assert record is not None
    assert record.provider_state is ProviderTaskState.CANCELLED
    assert record.tracking_state is TrackingState.TERMINAL
    assert record.cancellation_confirmed_at is not None
    assert "1002" in record.detail
    assert any(
        event.event_type == "PROCESS_CANCELLED"
        and event.payload.get("provider_scan_id") == "{CANCELLED}"
        for event in memory.list_events()
    )


def test_stand_down_is_local_identity_bound_and_explicit_scan_overrides(tmp_path: Path):
    database, memory = _memory(tmp_path)
    service = StandDownService(database, memory)
    target = tmp_path / "trusted-test.bin"
    target.write_bytes(b"first identity")
    record = service.create(
        target,
        reason="Harmless lifecycle test artifact",
        authorized_by="Austin",
        expires_in_days=1,
    )

    normal = service.evaluate(target)
    assert normal.suppress_aida_recommendation is True
    assert normal.status is StandDownStatus.ACTIVE

    explicit = service.evaluate(target, explicit_scan=True)
    assert explicit.suppress_aida_recommendation is False
    assert explicit.status is StandDownStatus.ACTIVE

    target.write_bytes(b"changed identity")
    changed = service.evaluate(target)
    assert changed.suppress_aida_recommendation is False
    assert changed.status is StandDownStatus.SUSPENDED
    assert "identity changed" in changed.reason.lower()
    stored = service.get(record.exception_id)
    assert stored is not None
    assert stored.status is StandDownStatus.SUSPENDED


def test_stand_down_new_provider_alarm_suspends_trust(tmp_path: Path):
    database, memory = _memory(tmp_path)
    service = StandDownService(database, memory)
    target = tmp_path / "alarm-test.bin"
    target.write_bytes(b"same identity")
    record = service.create(
        target,
        reason="Alarm invalidation test",
        authorized_by="Austin",
        alarm_count=2,
    )

    evaluation = service.evaluate(target, current_alarm_count=3)

    assert evaluation.status is StandDownStatus.SUSPENDED
    assert evaluation.suppress_aida_recommendation is False
    stored = service.get(record.exception_id)
    assert stored is not None
    assert stored.status is StandDownStatus.SUSPENDED


def test_detection_reconciliation_separates_new_existing_and_resolved(tmp_path: Path):
    now = datetime.now(timezone.utc)
    reconciler = DetectionReconciler()
    before = reconciler.snapshot(
        (
            _detection("existing", active=True),
            _detection("resolved", active=True),
        ),
        captured_at=now - timedelta(minutes=2),
    )
    after = reconciler.snapshot(
        (
            _detection("existing", active=True),
            _detection("resolved", active=False, action_success=True),
            _detection(
                "new",
                active=True,
                initial_detection_time=(now + timedelta(seconds=5)).isoformat(),
            ),
        ),
        captured_at=now + timedelta(minutes=1),
    )

    result = reconciler.reconcile(before, after, scan_started_at=now)

    assert [item.detection.detection_id for item in result.new_detections] == ["new"]
    assert [item.detection.detection_id for item in result.unresolved_existing] == [
        "existing"
    ]
    assert [item.detection.detection_id for item in result.resolved] == ["resolved"]
    assert next(
        item for item in result.assessments if item.detection.detection_id == "new"
    ).disposition is DetectionDisposition.NEW


def test_threat_report_does_not_invent_actor_or_physical_location(tmp_path: Path):
    detection = _detection(
        "threat-report",
        active=True,
        path=tmp_path / "artifact.bin",
    )

    report = ThreatIntelligenceBuilder().build(detection)

    assert report.actor_confidence is AttributionConfidence.UNKNOWN
    assert report.threat_actor.startswith("Unknown")
    assert report.actor_location == "Unknown"
    assert report.classification_confidence < 1.0
    assert any("credentials" in impact.lower() for impact in report.possible_impacts)


def test_observation_mode_records_operational_proposal_but_executes_nothing(tmp_path: Path):
    _, memory = _memory(tmp_path)
    controller = AutonomyController(memory)
    controller.set_enabled(True, changed_by="Austin")
    reconciler = DetectionReconciler()
    snapshot = reconciler.snapshot((_detection("active-threat", active=True),))
    assessments = reconciler.reconcile(snapshot, snapshot).assessments
    observation = SecurityObservation(
        provider_name="Microsoft Defender",
        provider_active=True,
        provider_healthy=True,
        real_time_protection=True,
        signatures_current=True,
        active_scan_description=None,
        detections=assessments,
        active_stand_down_count=0,
    )

    outcome = AutonomyObservationService(controller).evaluate(observation)

    assert outcome.user_action_required is True
    assert len(outcome.reports) == 2
    operational = outcome.reports[1]
    assert "No operational action taken" in operational.action_taken
    assert "No provider mutation requested" == operational.provider_result
    assert "user confirmation required" in operational.authorization_source.lower()
