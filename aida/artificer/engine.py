from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aida.artificer.appraiser import Appraiser
from aida.artificer.architect import Architect
from aida.artificer.codewright import Codewright
from aida.artificer.consent import ConsentManager
from aida.artificer.developer_registry import DeveloperRegistry
from aida.artificer.dispatch import (
    ArtificerDispatch,
    DisabledTransport,
    HTTPSDispatchTransport,
    LocalExportTransport,
)
from aida.artificer.event_bus import EventBus
from aida.artificer.events import make_event
from aida.artificer.forge import Forge
from aida.artificer.ledger import ArtificerLedger
from aida.artificer.liaison import Liaison
from aida.artificer.models import (
    ArtificerFinding,
    ArtificerSnapshot,
    ArtificerStatus,
    PlatformProfile,
    TelemetryLevel,
    UpgradeProposal,
    utc_now,
)
from aida.artificer.policy import ArtificerPolicy
from aida.artificer.rollback import RollbackManager
from aida.artificer.sanitizer import PayloadSanitizer
from aida.artificer.scheduler import ArtificerScheduler
from aida.artificer.validator import Validator
from aida.artificer.warden import Warden
from aida.artificer.watchtower import Watchtower
from aida.platform.base import PlatformAdapter
from aida.platform.detector import detect_platform_adapter

SnapshotListener = Callable[[ArtificerSnapshot], None]


class ArtificerEngine:
    """AIDA's governed self-observation, compatibility, and improvement engine."""

    def __init__(
        self,
        *,
        config: Any,
        event_bus: EventBus | None = None,
        platform_adapter: PlatformAdapter | None = None,
    ) -> None:
        self.config = config
        self.enabled = bool(getattr(config, "artificer_enabled", True))
        self.version = str(getattr(config, "version", "1.0.0"))
        self.source_root = Path(
            getattr(config, "artificer_source_root", getattr(config, "base_dir", "."))
        ).resolve()
        data_dir = Path(
            getattr(config, "artificer_data_dir", self.source_root / "memory" / "artificer")
        )
        data_dir.mkdir(parents=True, exist_ok=True)
        self.event_bus = event_bus or EventBus()
        self.ledger = ArtificerLedger(
            getattr(config, "artificer_ledger_path", data_dir / "artificer.db")
        )
        self.sanitizer = PayloadSanitizer()
        self.watchtower = Watchtower(self.ledger, self.sanitizer)
        self.event_bus.subscribe(self.watchtower.observe)
        self.platform_adapter = platform_adapter or detect_platform_adapter()
        self.liaison = Liaison(self.platform_adapter)
        self.codewright = Codewright(self.source_root)
        self.appraiser = Appraiser(self.ledger)
        self.architect = Architect()
        self.policy = ArtificerPolicy(self.source_root)
        self.warden = Warden(self.policy)
        self.validator = Validator()
        self.rollback = RollbackManager(data_dir / "rollback")
        self.forge = Forge(
            source_root=self.source_root,
            ledger=self.ledger,
            policy=self.policy,
            warden=self.warden,
            validator=self.validator,
            rollback=self.rollback,
        )
        self.consent = ConsentManager(
            getattr(config, "artificer_consent_path", data_dir / "consent.json")
        )
        configured_level = getattr(config, "artificer_telemetry_level", None)
        if configured_level:
            try:
                desired_level = TelemetryLevel(str(configured_level))
                if self.consent.state.telemetry_level != desired_level:
                    self.consent.set_level(desired_level)
            except ValueError:
                pass
        self.developers = DeveloperRegistry(
            getattr(
                config,
                "artificer_developer_registry_path",
                data_dir / "developers.json",
            )
        )
        endpoint = str(getattr(config, "artificer_dispatch_endpoint", "") or "").strip()
        export_dir = getattr(config, "artificer_export_dir", data_dir / "exports")
        if endpoint:
            transport = HTTPSDispatchTransport(endpoint)
        elif bool(getattr(config, "artificer_local_export_enabled", True)):
            transport = LocalExportTransport(export_dir)
        else:
            transport = DisabledTransport()
        self.dispatch = ArtificerDispatch(
            ledger=self.ledger,
            sanitizer=self.sanitizer,
            consent=self.consent,
            developers=self.developers,
            transport=transport,
        )
        interval = int(getattr(config, "artificer_review_interval_seconds", 21600))
        self.scheduler = ArtificerScheduler(self.run_review, interval)
        self._status = ArtificerStatus.DISABLED if not self.enabled else ArtificerStatus.READY
        self._last_review_utc: str | None = None
        self._platform_profile: PlatformProfile | None = None
        self._listeners: list[SnapshotListener] = []
        self._lock = threading.RLock()

    @property
    def status(self) -> ArtificerStatus:
        return self._status

    @property
    def platform_profile(self) -> PlatformProfile | None:
        return self._platform_profile

    def start(self, *, run_startup_review: bool = True) -> None:
        if not self.enabled:
            self._set_status(ArtificerStatus.DISABLED)
            return
        self._platform_profile = self.liaison.capture_profile()
        self.ledger.store_platform_profile(self._platform_profile)
        self.ledger.append_capability_results(
            self.liaison.verify_capabilities(self._platform_profile)
        )
        self.event_bus.publish(
            make_event(
                source="artificer.engine",
                event_type="engine_started",
                status="completed",
                aida_version=self.version,
                platform_profile_id=self._platform_profile.profile_id,
                metadata={"mode": str(getattr(self.config, "artificer_mode", "early_alpha"))},
            )
        )
        self._set_status(ArtificerStatus.OBSERVING)
        self.scheduler.start()
        if run_startup_review:
            self.run_review()
        else:
            self._set_status(ArtificerStatus.READY)

    def stop(self) -> None:
        self.scheduler.stop()
        self.event_bus.publish(
            make_event(
                source="artificer.engine",
                event_type="engine_stopped",
                status="completed",
                aida_version=self.version,
                platform_profile_id=(
                    self._platform_profile.profile_id if self._platform_profile else "unknown"
                ),
            )
        )
        self._set_status(ArtificerStatus.READY if self.enabled else ArtificerStatus.DISABLED)

    def run_review(self) -> ArtificerSnapshot:
        if not self.enabled:
            return self.snapshot()
        with self._lock:
            self._set_status(ArtificerStatus.REVIEWING)
            operation_id = str(uuid.uuid4())
            self.event_bus.publish(
                make_event(
                    source="artificer.engine",
                    event_type="review_started",
                    status="started",
                    aida_version=self.version,
                    platform_profile_id=(
                        self._platform_profile.profile_id if self._platform_profile else "unknown"
                    ),
                    operation_id=operation_id,
                )
            )
            try:
                profile = self.liaison.capture_profile()
                self._platform_profile = profile
                self.ledger.store_platform_profile(profile)
                capability_results = self.liaison.verify_capabilities(profile)
                self.ledger.append_capability_results(capability_results)
                findings = self.codewright.inspect()
                findings.extend(self._compatibility_findings(profile))
                findings.extend(self.appraiser.review())
                stored = [self.ledger.upsert_finding(finding) for finding in findings]
                self._last_review_utc = utc_now().isoformat()
                self.event_bus.publish(
                    make_event(
                        source="artificer.engine",
                        event_type="review_finished",
                        status="completed",
                        aida_version=self.version,
                        platform_profile_id=profile.profile_id,
                        operation_id=operation_id,
                        metadata={"findings_returned": len(stored)},
                    )
                )
                self._set_status(
                    ArtificerStatus.FINDINGS if self.ledger.list_findings() else ArtificerStatus.READY
                )
            except Exception as exc:
                self.event_bus.publish(
                    make_event(
                        source="artificer.engine",
                        event_type="review_failed",
                        status="failed",
                        aida_version=self.version,
                        platform_profile_id=(
                            self._platform_profile.profile_id if self._platform_profile else "unknown"
                        ),
                        operation_id=operation_id,
                        error_category=type(exc).__name__,
                        metadata={"error": str(exc)},
                    )
                )
                self._set_status(ArtificerStatus.ERROR)
                raise
            return self.snapshot()

    def create_proposal(self, finding_id: str) -> UpgradeProposal:
        findings = {finding.finding_id: finding for finding in self.ledger.list_findings(status=None)}
        finding = findings.get(finding_id)
        if finding is None:
            raise KeyError(finding_id)
        proposal = self.architect.propose(finding, current_version=self.version)
        self.ledger.store_proposal(proposal)
        self._set_status(ArtificerStatus.PROPOSAL)
        return proposal

    def decide_proposal(
        self,
        proposal_id: str,
        decision: str,
        *,
        developer_id: str = "owner",
        reason: str = "",
    ) -> None:
        active = {record.developer_id: record for record in self.developers.list_active()}
        developer = active.get(developer_id)
        if developer is None or developer.role not in {"owner", "lead_developer"}:
            raise PermissionError("Only an authorized owner or lead developer may decide proposals")
        self.ledger.record_proposal_decision(
            proposal_id=proposal_id,
            decision=decision,
            developer_id=developer_id,
            reason=reason,
        )
        self._set_status(ArtificerStatus.PROPOSAL if self.ledger.list_proposals() else ArtificerStatus.READY)

    def set_telemetry_level(
        self,
        level: TelemetryLevel,
        *,
        allow_crash_reports: bool = False,
        allow_compatibility_reports: bool = False,
        allow_raw_diagnostic_bundles: bool = False,
    ) -> None:
        self.consent.set_level(
            level,
            allow_crash_reports=allow_crash_reports,
            allow_compatibility_reports=allow_compatibility_reports,
            allow_raw_diagnostic_bundles=allow_raw_diagnostic_bundles,
        )
        self._set_status(self._status)

    def clear_unsent_dispatches(self) -> int:
        count = self.ledger.clear_unsent_dispatches()
        self._set_status(self._status)
        return count

    def snapshot(self) -> ArtificerSnapshot:
        profile = self._platform_profile
        findings = tuple(self.ledger.list_findings(limit=100))
        proposals = tuple(self.ledger.list_proposals())
        return ArtificerSnapshot(
            status=self._status.value,
            last_review_utc=self._last_review_utc,
            platform_summary=(
                f"{profile.os_family} {profile.os_release} ({profile.architecture})"
                if profile
                else "Platform profile unavailable"
            ),
            compatibility_summary=(dict(profile.capabilities) if profile else {}),
            open_findings=findings,
            pending_proposals=proposals,
            dispatch_queue_depth=self.ledger.dispatch_queue_depth(),
            telemetry_level=self.consent.state.telemetry_level.value,
        )

    def subscribe(self, listener: SnapshotListener) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)
        listener(self.snapshot())

    def unsubscribe(self, listener: SnapshotListener) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def export_report(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else Path(
            getattr(self.config, "artificer_export_dir", self.source_root / "memory" / "artificer" / "exports")
        ) / f"artificer_report_{utc_now().strftime('%Y%m%dT%H%M%SZ')}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        snapshot = self.snapshot()
        payload = {
            "generated_at_utc": utc_now().isoformat(),
            "aida_version": self.version,
            "status": snapshot.status,
            "last_review_utc": snapshot.last_review_utc,
            "platform": snapshot.platform_summary,
            "compatibility": dict(snapshot.compatibility_summary),
            "findings": [finding.to_record() for finding in snapshot.open_findings],
            "proposals": [proposal.to_record() for proposal in snapshot.pending_proposals],
            "dispatch_queue_depth": snapshot.dispatch_queue_depth,
            "telemetry_level": snapshot.telemetry_level,
            "ledger_integrity": self.ledger.verify_integrity(),
        }
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
        return target

    def record_diagnostic_run(
        self,
        *,
        scan_type: str,
        status: str,
        findings_count: int,
        duration_ms: float | None = None,
        provider: str | None = None,
        error: str | None = None,
    ) -> None:
        self.event_bus.publish(
            make_event(
                source="diagnostics",
                event_type="diagnostic_run",
                status=status,
                aida_version=self.version,
                platform_profile_id=(
                    self._platform_profile.profile_id if self._platform_profile else "unknown"
                ),
                duration_ms=duration_ms,
                error_category="DiagnosticError" if error else None,
                metadata={
                    "scan_type": scan_type,
                    "findings_count": findings_count,
                    "provider": provider,
                    "error": error,
                },
            )
        )

    def _set_status(self, status: ArtificerStatus) -> None:
        self._status = status
        snapshot = self.snapshot()
        for listener in tuple(self._listeners):
            try:
                listener(snapshot)
            except Exception:
                continue

    def _compatibility_findings(self, profile: PlatformProfile) -> list[ArtificerFinding]:
        findings: list[ArtificerFinding] = []
        for capability, status in profile.capabilities.items():
            if status not in {"blocked", "unsupported", "degraded", "unverified"}:
                continue
            severity = "moderate" if status in {"blocked", "unsupported"} else "minor"
            now = utc_now()
            findings.append(
                ArtificerFinding(
                    finding_id=f"AE-OS-{uuid.uuid4().hex[:10].upper()}",
                    category="platform_compatibility",
                    title=f"Capability {status}: {capability}",
                    severity=severity,
                    confidence=0.99,
                    evidence_quality=0.95,
                    affected_components=(capability, self.platform_adapter.name),
                    first_seen_utc=now,
                    last_seen_utc=now,
                    observation_count=1,
                    finding=f"{capability} is {status} on the current operating platform.",
                    evidence_summary=(
                        f"The {self.platform_adapter.name} adapter reported {status} during a live capability probe."
                    ),
                    reasoning_summary="AIDA cannot assume a capability works when the active platform adapter cannot verify native or compatible behavior.",
                    recommended_change="Implement or improve the platform adapter while retaining explicit fallback behavior.",
                    expected_outcomes=("Clear platform behavior", "Reduced unsupported command failures"),
                    implementation_risk=0.35,
                    regression_risk=0.30,
                    authority_required="recommend",
                    fingerprint=f"capability:{profile.os_family}:{capability}:{status}",
                )
            )
        return findings
