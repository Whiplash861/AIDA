from datetime import datetime, timedelta, timezone
from pathlib import Path

from aida.frontend.commands.security import SecurityScanExecutor
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService
from aida.security.continuity import SecurityTaskLedger
from aida.security.models import (
    ProviderCapability,
    ProviderDetection,
    ProviderStatus,
    SecurityScanHandle,
    SecurityScanMode,
    SecurityScanState,
    SecurityScanStatus,
    SecuritySeverity,
)
from aida.security.stand_down import StandDownService, StandDownStatus
from aida.security.windows.discovery import WindowsProviderDiscovery


class Provider:
    provider_id = "microsoft_defender"
    display_name = "Test Defender"
    capabilities = frozenset(
        {
            ProviderCapability.READ_STATUS,
            ProviderCapability.QUICK_SCAN,
            ProviderCapability.CUSTOM_SCAN,
            ProviderCapability.FULL_SCAN,
            ProviderCapability.READ_DETECTIONS,
        }
    )

    def __init__(self, before, after, scan_window=()):
        self.before = tuple(before)
        self.after = tuple(after)
        self.scan_window = tuple(scan_window)
        self.snapshot_calls = 0

    def get_status(self):
        return ProviderStatus(
            provider_id=self.provider_id,
            display_name=self.display_name,
            healthy=True,
            active=True,
            real_time_protection=True,
            signatures_current=True,
        )

    def start_scan(self, request):
        return SecurityScanHandle(
            scan_id="local-scan",
            provider_id=self.provider_id,
            request_id=request.request_id,
            started_at=request.requested_at,
        )

    def get_scan_status(self, handle):
        return SecurityScanStatus(
            SecurityScanState.COMPLETED,
            progress_percent=100.0,
            detail="completed",
        )

    def get_detections(self, handle):
        return list(self.scan_window)

    def get_detection_snapshot(self):
        self.snapshot_calls += 1
        return list(self.before if self.snapshot_calls == 1 else self.after)

    def cancel_scan(self, handle):
        return False


def _discovery(provider):
    return WindowsProviderDiscovery(
        provider=provider,
        products=(),
        detail="test discovery",
    )


def _detection(
    detection_id: str,
    *,
    path: Path | None,
    detected_at: datetime,
    active: bool = True,
):
    return ProviderDetection(
        detection_id=detection_id,
        name="Test threat",
        severity=SecuritySeverity.HIGH,
        source="Test Defender",
        file_path=path,
        metadata={
            "is_active": active,
            "action_success": not active,
            "initial_detection_time": detected_at.isoformat(),
            "last_status_change": detected_at.isoformat(),
        },
    )


def _memory_services(tmp_path):
    database = MemoryDatabase(tmp_path / "memory.db")
    memory = MemoryService(
        database,
        user_id="Austin",
        device_id="Test-PC",
    )
    return (
        memory,
        SecurityTaskLedger(
            database,
            user_id=memory.user_id,
            device_id=memory.device_id,
        ),
        StandDownService(database, memory),
    )


def test_scan_separates_existing_unresolved_detection_from_new_findings(tmp_path):
    detected = datetime.now(timezone.utc) - timedelta(days=1)
    existing = _detection(
        "existing",
        path=tmp_path / "old.exe",
        detected_at=detected,
    )
    provider = Provider((existing,), (existing,), scan_window=())
    memory, ledger, stand_down = _memory_services(tmp_path)
    executor = SecurityScanExecutor(
        SecurityScanMode.SURFACE,
        "test",
        discovery_function=lambda: _discovery(provider),
        sleep_function=lambda _: None,
        poll_interval_seconds=0.05,
        memory_service=memory,
        task_ledger=ledger,
        stand_down_service=stand_down,
    )

    result = executor.execute()

    assert "New or reactivated detections in this scan window: 0" in result.transcript_text
    assert "Pre-existing unresolved detections still reported: 1" in result.transcript_text
    assert "No new detections were attributed" in result.speech_text


def test_new_detection_suspends_stand_down_even_for_explicit_deep_scan(tmp_path):
    target = tmp_path / "trusted.exe"
    target.write_bytes(b"unchanged test material")
    memory, ledger, stand_down = _memory_services(tmp_path)
    trusted = stand_down.create(
        target,
        reason="test trust",
        authorized_by="Austin",
        alarm_count=0,
    )
    detected = datetime.now(timezone.utc) + timedelta(seconds=1)
    new = _detection(
        "new",
        path=target,
        detected_at=detected,
    )
    provider = Provider((), (new,), scan_window=(new,))
    executor = SecurityScanExecutor(
        SecurityScanMode.DEEP,
        "test",
        target_path=str(target),
        discovery_function=lambda: _discovery(provider),
        sleep_function=lambda _: None,
        path_exists=lambda _: True,
        poll_interval_seconds=0.05,
        memory_service=memory,
        task_ledger=ledger,
        stand_down_service=stand_down,
    )

    result = executor.execute()

    assert "Stand Down status: Suspended" in result.transcript_text
    assert "normal threat assessment resumed" in result.transcript_text
    assert stand_down.get(trusted.exception_id).status is StandDownStatus.SUSPENDED
