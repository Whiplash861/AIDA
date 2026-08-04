from datetime import datetime, timezone

from aida.autonomy.controller import AutonomyController
from aida.autonomy.models import PolicyDisposition
from aida.autonomy.observation import (
    AutonomyObservationService,
    SecurityObservation,
)
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.detection_intelligence import DetectionReconciler
from aida.security.models import (
    ProviderDetection,
    SecuritySeverity,
)


def _controller(tmp_path) -> AutonomyController:
    memory = MemoryService(
        MemoryDatabase(tmp_path / "memory.db"),
        user_id="Austin",
        device_id="Test-PC",
    )
    return AutonomyController(memory)


def _active_detection() -> ProviderDetection:
    now = datetime.now(timezone.utc).isoformat()
    return ProviderDetection(
        detection_id="active-threat",
        name="Test active threat",
        severity=SecuritySeverity.HIGH,
        source="Test provider",
        metadata={
            "is_active": True,
            "action_success": False,
            "initial_detection_time": now,
            "last_status_change": now,
        },
    )


def _assessment():
    reconciler = DetectionReconciler()
    detection = _active_detection()
    snapshot = reconciler.snapshot((detection,))
    return reconciler.reconcile(snapshot, snapshot).assessments


def test_observation_mode_reports_and_routes_operational_response_to_user(
    tmp_path,
) -> None:
    controller = _controller(tmp_path)
    controller.set_enabled(True, changed_by="Austin")
    service = AutonomyObservationService(controller)

    outcome = service.evaluate(
        SecurityObservation(
            provider_name="Test provider",
            provider_active=True,
            provider_healthy=True,
            real_time_protection=True,
            signatures_current=True,
            active_scan_description=None,
            detections=_assessment(),
            active_stand_down_count=0,
        )
    )

    assert len(outcome.reports) == 2
    assert outcome.reports[0].decision.disposition is PolicyDisposition.ALLOW
    assert (
        outcome.reports[1].decision.disposition
        is PolicyDisposition.REQUIRE_USER
    )
    assert "No operational action taken" in outcome.reports[1].action_taken
    assert outcome.user_action_required is True


def test_manual_control_also_routes_operational_response_to_user(tmp_path) -> None:
    controller = _controller(tmp_path)
    service = AutonomyObservationService(controller)

    outcome = service.evaluate(
        SecurityObservation(
            provider_name="Test provider",
            provider_active=True,
            provider_healthy=True,
            real_time_protection=True,
            signatures_current=True,
            active_scan_description=None,
            detections=_assessment(),
            active_stand_down_count=0,
        )
    )

    assert outcome.user_action_required is True
    assert all(
        report.action_taken != "Operational action executed"
        for report in outcome.reports
    )


def test_healthy_observation_only_records_read_only_report(tmp_path) -> None:
    controller = _controller(tmp_path)
    controller.set_enabled(True, changed_by="Austin")
    service = AutonomyObservationService(controller)

    outcome = service.evaluate(
        SecurityObservation(
            provider_name="Test provider",
            provider_active=True,
            provider_healthy=True,
            real_time_protection=True,
            signatures_current=True,
            active_scan_description=None,
            detections=(),
            active_stand_down_count=1,
        )
    )

    assert len(outcome.reports) == 1
    assert outcome.reports[0].decision.disposition is PolicyDisposition.ALLOW
    assert outcome.user_action_required is False
    assert "No operational action" in outcome.summary
