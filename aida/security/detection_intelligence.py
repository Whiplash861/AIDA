from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable

from aida.security.models import ProviderDetection


class DetectionDisposition(StrEnum):
    NEW = "new"
    REACTIVATED = "reactivated"
    UNCHANGED_ACTIVE = "unchanged_active"
    RESOLVED = "resolved"
    STATUS_CHANGED = "status_changed"
    HISTORICAL = "historical"


@dataclass(frozen=True, slots=True)
class DetectionSnapshot:
    detections: tuple[ProviderDetection, ...]
    captured_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def by_key(self) -> dict[str, ProviderDetection]:
        return {_detection_key(item): item for item in self.detections}


@dataclass(frozen=True, slots=True)
class DetectionAssessment:
    disposition: DetectionDisposition
    detection: ProviderDetection
    previous: ProviderDetection | None
    new_for_scan: bool
    unresolved: bool
    summary: str


@dataclass(frozen=True, slots=True)
class DetectionReconciliation:
    before: DetectionSnapshot
    after: DetectionSnapshot
    assessments: tuple[DetectionAssessment, ...]

    @property
    def new_detections(self) -> tuple[DetectionAssessment, ...]:
        return tuple(item for item in self.assessments if item.new_for_scan)

    @property
    def unresolved_existing(self) -> tuple[DetectionAssessment, ...]:
        return tuple(
            item
            for item in self.assessments
            if item.unresolved and not item.new_for_scan
        )

    @property
    def resolved(self) -> tuple[DetectionAssessment, ...]:
        return tuple(
            item
            for item in self.assessments
            if item.disposition is DetectionDisposition.RESOLVED
        )


class DetectionReconciler:
    """Separates new scan findings from pre-existing Defender history."""

    def snapshot(
        self,
        detections: Iterable[ProviderDetection],
        *,
        captured_at: datetime | None = None,
    ) -> DetectionSnapshot:
        return DetectionSnapshot(
            detections=tuple(detections),
            captured_at=(captured_at or datetime.now(timezone.utc)),
        )

    def reconcile(
        self,
        before: DetectionSnapshot,
        after: DetectionSnapshot,
        *,
        scan_started_at: datetime | None = None,
    ) -> DetectionReconciliation:
        prior = before.by_key
        assessments: list[DetectionAssessment] = []
        for detection in after.detections:
            previous = prior.get(_detection_key(detection))
            disposition = _disposition(previous, detection)
            new_for_scan = _new_for_scan(
                previous,
                detection,
                disposition,
                scan_started_at,
            )
            unresolved = _is_unresolved(detection)
            assessments.append(
                _assessment(
                    disposition,
                    detection,
                    previous,
                    new_for_scan,
                    unresolved,
                )
            )
        # Absence from a later history snapshot is not enough to prove that a
        # detection was neutralized. Resolution is recorded only when the
        # provider explicitly reports an inactive state or successful action.
        return DetectionReconciliation(
            before=before,
            after=after,
            assessments=tuple(assessments),
        )


def render_detection_reconciliation(
    reconciliation: DetectionReconciliation,
) -> str:
    new_count = len(reconciliation.new_detections)
    unresolved_count = len(reconciliation.unresolved_existing)
    resolved_count = len(reconciliation.resolved)
    lines = [
        "DETECTION RECONCILIATION",
        "",
        f"New or reactivated detections in this scan window: {new_count}",
        f"Pre-existing unresolved detections still reported: {unresolved_count}",
        f"Detections with provider-confirmed resolution: {resolved_count}",
    ]
    if not new_count:
        lines.append(
            "Result: No new provider detection was attributed to this scan window."
        )
    if unresolved_count:
        lines.append(
            "Existing unresolved findings are listed separately and were not "
            "misreported as new scan detections."
        )
    return "\n".join(lines)


def _assessment(
    disposition: DetectionDisposition,
    detection: ProviderDetection,
    previous: ProviderDetection | None,
    new_for_scan: bool,
    unresolved: bool,
) -> DetectionAssessment:
    return DetectionAssessment(
        disposition=disposition,
        detection=detection,
        previous=previous,
        new_for_scan=new_for_scan,
        unresolved=unresolved,
        summary=_assessment_summary(
            disposition,
            detection,
            new_for_scan,
            unresolved,
        ),
    )


def _detection_key(detection: ProviderDetection) -> str:
    detection_id = detection.detection_id.strip()
    if detection_id:
        return f"id:{detection_id.lower()}"
    threat_id = str(detection.metadata.get("threat_id") or "unknown").lower()
    path = str(detection.file_path or "").lower()
    initial = str(
        detection.metadata.get("initial_detection_time") or ""
    ).lower()
    return f"fallback:{threat_id}|{path}|{initial}"


def _disposition(
    previous: ProviderDetection | None,
    current: ProviderDetection,
) -> DetectionDisposition:
    current_active = _optional_bool(current.metadata.get("is_active"))
    current_action = _optional_bool(current.metadata.get("action_success"))
    if previous is None:
        return (
            DetectionDisposition.NEW
            if current_active is not False
            else DetectionDisposition.HISTORICAL
        )

    previous_active = _optional_bool(previous.metadata.get("is_active"))
    if previous_active is False and current_active is True:
        return DetectionDisposition.REACTIVATED
    if previous_active is True and current_active is False:
        return DetectionDisposition.RESOLVED
    if current_active is True and previous_active is True:
        return DetectionDisposition.UNCHANGED_ACTIVE
    if (
        current_action is True
        and _optional_bool(previous.metadata.get("action_success")) is not True
    ):
        return DetectionDisposition.RESOLVED
    if _status_signature(previous) != _status_signature(current):
        return DetectionDisposition.STATUS_CHANGED
    return DetectionDisposition.HISTORICAL


def _new_for_scan(
    previous: ProviderDetection | None,
    current: ProviderDetection,
    disposition: DetectionDisposition,
    scan_started_at: datetime | None,
) -> bool:
    if disposition not in {
        DetectionDisposition.NEW,
        DetectionDisposition.REACTIVATED,
    }:
        return False
    if previous is None:
        detected_at = _parse_time(
            current.metadata.get("initial_detection_time")
        )
        if scan_started_at is None or detected_at is None:
            return True
        return detected_at >= scan_started_at.astimezone(timezone.utc)
    return True


def _is_unresolved(detection: ProviderDetection) -> bool:
    active = _optional_bool(detection.metadata.get("is_active"))
    action_success = _optional_bool(
        detection.metadata.get("action_success")
    )
    if active is True:
        return True
    if active is False:
        return False
    return action_success is not True


def _status_signature(detection: ProviderDetection) -> tuple[object, ...]:
    return (
        _optional_bool(detection.metadata.get("is_active")),
        _optional_bool(detection.metadata.get("action_success")),
        str(detection.metadata.get("last_status_change") or ""),
        detection.severity.name,
    )


def _assessment_summary(
    disposition: DetectionDisposition,
    detection: ProviderDetection,
    new_for_scan: bool,
    unresolved: bool,
) -> str:
    label = disposition.value.replace("_", " ")
    window = "new in this scan window" if new_for_scan else "pre-existing"
    state = "unresolved" if unresolved else "not currently active"
    return f"{detection.name}: {label}; {window}; {state}."


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None
