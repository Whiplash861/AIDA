from datetime import datetime, timedelta, timezone

from aida.security.detection_intelligence import (
    DetectionDisposition,
    DetectionReconciler,
    render_detection_reconciliation,
)
from aida.security.models import (
    ProviderDetection,
    SecuritySeverity,
)


def _detection(
    detection_id: str,
    *,
    active: bool,
    action_success: bool,
    detected_at: datetime,
) -> ProviderDetection:
    return ProviderDetection(
        detection_id=detection_id,
        name="Test threat",
        severity=SecuritySeverity.HIGH,
        source="Test provider",
        metadata={
            "threat_id": "42",
            "is_active": active,
            "action_success": action_success,
            "initial_detection_time": detected_at.isoformat(),
            "last_status_change": detected_at.isoformat(),
        },
    )


def test_new_detection_is_attributed_to_current_scan_window() -> None:
    reconciler = DetectionReconciler()
    started = datetime.now(timezone.utc)
    new = _detection(
        "new",
        active=True,
        action_success=False,
        detected_at=started + timedelta(seconds=2),
    )

    result = reconciler.reconcile(
        reconciler.snapshot(()),
        reconciler.snapshot((new,)),
        scan_started_at=started,
    )

    assert len(result.new_detections) == 1
    assert result.new_detections[0].disposition is DetectionDisposition.NEW
    assert result.new_detections[0].unresolved is True


def test_existing_active_detection_is_not_misreported_as_new() -> None:
    reconciler = DetectionReconciler()
    detected = datetime.now(timezone.utc) - timedelta(days=1)
    existing = _detection(
        "existing",
        active=True,
        action_success=False,
        detected_at=detected,
    )
    before = reconciler.snapshot((existing,))
    after = reconciler.snapshot((existing,))

    result = reconciler.reconcile(
        before,
        after,
        scan_started_at=datetime.now(timezone.utc),
    )

    assert result.new_detections == ()
    assert len(result.unresolved_existing) == 1
    assert (
        result.unresolved_existing[0].disposition
        is DetectionDisposition.UNCHANGED_ACTIVE
    )
    rendered = render_detection_reconciliation(result)
    assert "No new provider detection" in rendered
    assert "Pre-existing unresolved detections still reported: 1" in rendered


def test_provider_status_change_records_resolution() -> None:
    reconciler = DetectionReconciler()
    detected = datetime.now(timezone.utc) - timedelta(hours=1)
    before_item = _detection(
        "resolved",
        active=True,
        action_success=False,
        detected_at=detected,
    )
    after_item = _detection(
        "resolved",
        active=False,
        action_success=True,
        detected_at=detected,
    )

    result = reconciler.reconcile(
        reconciler.snapshot((before_item,)),
        reconciler.snapshot((after_item,)),
    )

    assert len(result.resolved) == 1
    assert result.resolved[0].unresolved is False


def test_missing_history_alone_does_not_claim_resolution() -> None:
    reconciler = DetectionReconciler()
    detected = datetime.now(timezone.utc) - timedelta(hours=1)
    existing = _detection(
        "removed",
        active=True,
        action_success=False,
        detected_at=detected,
    )

    result = reconciler.reconcile(
        reconciler.snapshot((existing,)),
        reconciler.snapshot(()),
    )

    assert result.resolved == ()
    assert result.assessments == ()
