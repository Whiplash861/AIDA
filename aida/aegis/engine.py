from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from aida.aegis.artificer_bridge import AegisArtificerBridge
from aida.aegis.baseline import compare_snapshots
from aida.aegis.engineering_manifest import bridge_metadata, build_engineering_manifest
from aida.aegis.evidence_graph import EvidenceGraphBuilder
from aida.aegis.intelligence import (
    assess_coverage,
    assess_risk,
    build_case_summary,
    build_hypotheses,
    case_status_for,
    escalation_for,
    remaining_uncertainty,
    select_candidate_paths,
)
from aida.aegis.learning.features import extract_feature_vector
from aida.aegis.learning.service import AegisLearningService
from aida.aegis.models import (
    AegisCaseStatus,
    AegisSnapshot,
    AegisState,
    IntelligentScanResult,
    ProviderHealth,
    SecurityCase,
    utc_now,
)
from aida.aegis.scan_modes import AegisScanStrategy
from aida.aegis.sensors import AegisSystemSensor
from aida.aegis.store import AegisStore
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService
from aida.security.models import ProviderDetection
from aida.security.threat_analysis import (
    ThreatAnalysisRecord,
    ThreatAnalysisService,
    ThreatAssessmentLevel,
)


DetectionReader = Callable[[], Iterable[ProviderDetection]]


class AegisEngine:
    """AIDA's background defensive intelligence and investigation engine.

    Aegis owns security orchestration and adds deterministic correlation plus a
    local adaptive-learning layer. Learned inference is evidence, never
    execution authority. Provider facts, current identity, authorization, and
    policy remain authoritative.
    """

    def __init__(
        self,
        *,
        store: AegisStore,
        memory: MemoryService,
        threat_analysis: ThreatAnalysisService,
        detection_reader: DetectionReader,
        sensor: AegisSystemSensor,
        learning: AegisLearningService,
        bridge: AegisArtificerBridge | None = None,
        observation_interval_seconds: int = 900,
        initial_observation_delay_seconds: float = 5.0,
        enabled: bool = True,
    ) -> None:
        self.store = store
        self.memory = memory
        self.threat_analysis = threat_analysis
        self.detection_reader = detection_reader
        self.sensor = sensor
        self.learning = learning
        self.bridge = bridge or AegisArtificerBridge()
        self.observation_interval_seconds = max(
            60, int(observation_interval_seconds)
        )
        self.initial_observation_delay_seconds = max(
            0.0, float(initial_observation_delay_seconds)
        )
        self.enabled = bool(enabled)

        self._graph = EvidenceGraphBuilder()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = AegisState.STOPPED
        self._last_observation_at = None
        self._last_intelligent_scan_at = None
        self._degraded_reasons: tuple[str, ...] = ()

    @property
    def state(self) -> AegisState:
        with self._lock:
            return self._state

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def engineering_manifest(self) -> dict[str, Any]:
        return build_engineering_manifest(self.learning)

    def start(self) -> None:
        if not self.enabled or self.running:
            return
        self._stop_event.clear()
        self._set_state(AegisState.OBSERVING)
        self._thread = threading.Thread(
            target=self._observation_loop,
            name="AIDA-Aegis-Observer",
            daemon=True,
        )
        self._thread.start()
        metadata = {
            "state": self.state.value,
            "baseline_available": self.store.load_baseline() is not None,
            **bridge_metadata(self.learning),
        }
        self.bridge.publish(
            event_type="engine_started",
            status="completed",
            metadata=metadata,
        )
        self.bridge.publish(
            event_type="engineering_manifest_available",
            status="completed",
            metadata=bridge_metadata(self.learning),
        )

    def stop(self, timeout: float = 3.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        self._thread = None
        self._set_state(AegisState.STOPPED)
        self.bridge.publish(
            event_type="engine_stopped",
            status="completed",
            metadata={"state": self.state.value, **bridge_metadata(self.learning)},
        )

    def snapshot(self) -> AegisSnapshot:
        learned = self.learning.snapshot()
        return AegisSnapshot(
            state=self.state,
            running=self.running,
            last_observation_at=self._last_observation_at,
            last_intelligent_scan_at=self._last_intelligent_scan_at,
            baseline_available=self.store.load_baseline() is not None,
            open_case_count=self.store.open_case_count(),
            degraded_reasons=self._degraded_reasons,
            learning_model_version=learned.model_version,
            learning_sample_count=learned.sample_count,
            learning_ready=learned.ready,
        )

    def observe_once(self) -> None:
        """Perform a low-cost read-only background observation and safe learning.

        This never starts a provider scan. Learning is allowed only when an
        existing machine baseline is present and no active threat, degraded
        visibility, or material unexplained drift is being normalized.
        """

        started = time.monotonic()
        try:
            snapshot = self.sensor.capture()
            detections = self._read_detections()
            baseline = self.store.load_baseline()
            delta = compare_snapshots(baseline, snapshot)
            active = tuple(
                item
                for item in detections
                if item.metadata.get("is_active") is not False
            )
            self._degraded_reasons = tuple(snapshot.sensor_errors)
            if snapshot.provider_health.available is False:
                self._degraded_reasons = tuple(
                    dict.fromkeys(
                        self._degraded_reasons + ("security_provider_unavailable",)
                    )
                )

            features = extract_feature_vector(
                snapshot=snapshot,
                delta=delta,
                detections=active,
                analyses=(),
            )
            learned = self.learning.assess(features)
            learning_eligible = bool(
                baseline is not None
                and not active
                and not self._degraded_reasons
                and delta.meaningful_change_count <= 2
                and (learned.warmup or learned.anomaly_score < 0.55)
            )
            learning_sample_accepted = self.learning.learn_if_safe(
                features,
                eligible=learning_eligible,
            )

            if active:
                self._set_state(AegisState.THREAT_CONFIRMED)
            elif self._degraded_reasons:
                self._set_state(AegisState.DEGRADED)
            elif (
                delta.meaningful_change_count >= 4
                or (
                    not learned.warmup
                    and learned.confidence >= 0.50
                    and learned.anomaly_score >= 0.75
                )
            ):
                self._set_state(AegisState.ELEVATED)
            else:
                self._set_state(AegisState.OBSERVING)

            should_record = bool(
                active
                or self._degraded_reasons
                or delta.meaningful_change_count >= 4
                or learned.anomaly_score >= 0.65
            )
            if should_record:
                outcome = (
                    ProcessOutcome.PARTIAL
                    if self._degraded_reasons
                    else ProcessOutcome.SUCCEEDED
                )
                self.memory.log_event(
                    "AEGIS_BACKGROUND_OBSERVATION",
                    "security.aegis",
                    (
                        f"Aegis observed {len(active)} active provider detection(s), "
                        f"{delta.meaningful_change_count} baseline change(s), "
                        f"{len(self._degraded_reasons)} visibility degradation(s), "
                        f"and a learned anomaly score of {round(learned.anomaly_score * 100)}%."
                    ),
                    payload={
                        "active_provider_detections": len(active),
                        "baseline_change_count": delta.meaningful_change_count,
                        "degraded_reason_count": len(self._degraded_reasons),
                        "state": self.state.value,
                        "learning_anomaly_score": learned.anomaly_score,
                        "learning_confidence": learned.confidence,
                        "learning_model_version": learned.model_version,
                    },
                    outcome=outcome,
                    confidence=max(0.50, learned.confidence),
                    promote=bool(active),
                )

            self._last_observation_at = utc_now()
            current_model = self.learning.snapshot()
            self.bridge.publish(
                event_type="observation_completed",
                status=("degraded" if self._degraded_reasons else "completed"),
                duration_ms=(time.monotonic() - started) * 1000,
                metadata={
                    "state": self.state.value,
                    "provider_detection_count": len(active),
                    "baseline_change_count": delta.meaningful_change_count,
                    "sensor_error_count": len(self._degraded_reasons),
                    "baseline_available": baseline is not None,
                    "learning_anomaly_band": _band(learned.anomaly_score),
                    "learning_confidence_band": _band(learned.confidence),
                    "learning_model_version": current_model.model_version,
                    "learning_sample_count": current_model.sample_count,
                    "learning_ready": current_model.ready,
                    "learning_sample_accepted": learning_sample_accepted,
                },
            )
        except Exception:
            self._set_state(AegisState.DEGRADED)
            self._degraded_reasons = ("background_observation_failed",)
            self.bridge.publish(
                event_type="observation_failed",
                status="failed",
                duration_ms=(time.monotonic() - started) * 1000,
                metadata={
                    "state": self.state.value,
                    "sensor_error_count": 1,
                },
            )

    def run_intelligent_scan(
        self,
        *,
        provider_scan_summary: str = "",
        scan_strategy: str = "adaptive",
    ) -> IntelligentScanResult:
        """Run Aegis correlation and learning around an authorized scan mode.

        All serviceable security scan modes can call this phase. Adaptive uses
        the Surface provider scan as its economical first stage; explicit
        Surface, Deep, and Full modes retain their requested provider coverage
        while gaining the same Aegis intelligence around the result.
        """

        try:
            strategy = AegisScanStrategy(scan_strategy)
        except ValueError:
            strategy = AegisScanStrategy.ADAPTIVE

        started = time.monotonic()
        self._set_state(AegisState.INVESTIGATING)
        self.bridge.publish(
            event_type="intelligent_scan_started",
            status="started",
            metadata={
                "state": self.state.value,
                "scan_strategy": strategy.value,
            },
        )
        try:
            snapshot = self.sensor.capture()
            detections = self._read_detections()
            baseline = self.store.load_baseline()
            delta = compare_snapshots(baseline, snapshot)
            candidates = select_candidate_paths(
                snapshot=snapshot,
                delta=delta,
                detections=detections,
            )
            analyses = self._analyze_candidates(candidates, detections)
            features = extract_feature_vector(
                snapshot=snapshot,
                delta=delta,
                detections=detections,
                analyses=analyses,
            )
            learned = self.learning.assess(features)
            risk = assess_risk(
                detections=detections,
                analyses=analyses,
                delta=delta,
                snapshot=snapshot,
                learning=learned,
            )
            coverage = assess_coverage(
                snapshot=snapshot,
                baseline=baseline,
                candidate_count=len(candidates),
                analyzed_count=len(analyses),
            )
            hypotheses = build_hypotheses(
                detections=detections,
                analyses=analyses,
                delta=delta,
                learning=learned,
            )
            nodes, edges = self._graph.build(
                snapshot=snapshot,
                delta=delta,
                detections=detections,
                analyses=analyses,
            )
            escalation = escalation_for(risk, coverage)
            status = case_status_for(detections, risk, escalation)
            now = utc_now()
            case = SecurityCase(
                case_id=(
                    f"CASE-AEGIS-{now.strftime('%Y%m%d')}-"
                    f"{now.strftime('%H%M%S')}-{now.microsecond // 1000:03d}"
                ),
                status=status,
                created_at=now,
                updated_at=now,
                summary=build_case_summary(
                    risk=risk,
                    coverage=coverage,
                    detection_count=len(detections),
                    delta=delta,
                ),
                risk=risk,
                coverage=coverage,
                baseline_delta=delta,
                provider_detection_count=len(detections),
                analyzed_file_count=len(analyses),
                evidence_nodes=nodes,
                evidence_edges=edges,
                hypotheses=hypotheses,
                escalation=escalation,
                remaining_uncertainty=remaining_uncertainty(
                    snapshot=snapshot,
                    coverage=coverage,
                    analyses=analyses,
                ),
                scan_strategy=strategy.value,
                learning_anomaly_score=learned.anomaly_score,
                learning_confidence=learned.confidence,
                learning_model_version=learned.model_version,
                learning_sample_count=learned.sample_count,
                learning_warmup=learned.warmup,
            )
            self.store.store_case(case)

            baseline_established = False
            if self._can_establish_initial_baseline(
                baseline=baseline,
                snapshot=snapshot,
                detections=detections,
                risk_overall=risk.overall,
            ):
                self.store.store_baseline(snapshot)
                baseline_established = True

            learning_sample_accepted = self.learning.learn_if_safe(
                features,
                eligible=self._training_eligible(
                    baseline_available=(baseline is not None or baseline_established),
                    snapshot=snapshot,
                    detections=detections,
                    analyses=analyses,
                    risk_overall=risk.overall,
                    learned_anomaly=learned.anomaly_score,
                    learned_warmup=learned.warmup,
                ),
            )

            self._last_intelligent_scan_at = utc_now()
            self._degraded_reasons = tuple(snapshot.sensor_errors)
            self._set_state(_state_for_case(case.status, self._degraded_reasons))
            elapsed = time.monotonic() - started

            self.memory.log_event(
                "AEGIS_INTELLIGENT_SCAN_COMPLETED",
                "security.aegis",
                case.summary,
                payload={
                    "case_id": case.case_id,
                    "case_status": case.status.value,
                    "scan_strategy": strategy.value,
                    "risk": risk.overall,
                    "coverage": coverage.overall,
                    "provider_detection_count": len(detections),
                    "analyzed_file_count": len(analyses),
                    "baseline_change_count": delta.meaningful_change_count,
                    "escalation": escalation,
                    "baseline_established": baseline_established,
                    "learning_anomaly_score": learned.anomaly_score,
                    "learning_confidence": learned.confidence,
                    "learning_model_version": learned.model_version,
                    "learning_sample_accepted": learning_sample_accepted,
                },
                outcome=(
                    ProcessOutcome.PARTIAL
                    if self._degraded_reasons
                    else ProcessOutcome.SUCCEEDED
                ),
                confidence=coverage.overall,
                promote=(status is AegisCaseStatus.THREAT_CONFIRMED),
            )
            current_model = self.learning.snapshot()
            self.bridge.publish(
                event_type="intelligent_scan_completed",
                status=("degraded" if self._degraded_reasons else "completed"),
                duration_ms=elapsed * 1000,
                metadata={
                    "state": self.state.value,
                    "scan_strategy": strategy.value,
                    "case_status": case.status.value,
                    "provider_detection_count": len(detections),
                    "analyzed_file_count": len(analyses),
                    "baseline_change_count": delta.meaningful_change_count,
                    "risk_band": _band(risk.overall),
                    "coverage_band": _band(coverage.overall),
                    "escalation": escalation,
                    "sensor_error_count": len(self._degraded_reasons),
                    "baseline_available": (
                        baseline is not None or baseline_established
                    ),
                    "learning_anomaly_band": _band(learned.anomaly_score),
                    "learning_confidence_band": _band(learned.confidence),
                    "learning_model_version": current_model.model_version,
                    "learning_sample_count": current_model.sample_count,
                    "learning_ready": current_model.ready,
                    "learning_sample_accepted": learning_sample_accepted,
                },
            )
            return IntelligentScanResult(
                case=case,
                provider_scan_summary=provider_scan_summary,
                baseline_established=baseline_established,
                elapsed_seconds=elapsed,
                learning_sample_accepted=learning_sample_accepted,
            )
        except Exception:
            self._set_state(AegisState.DEGRADED)
            self._degraded_reasons = ("intelligent_scan_failed",)
            self.bridge.publish(
                event_type="intelligent_scan_failed",
                status="failed",
                duration_ms=(time.monotonic() - started) * 1000,
                metadata={
                    "state": self.state.value,
                    "scan_strategy": strategy.value,
                    "sensor_error_count": 1,
                },
            )
            raise

    def _analyze_candidates(
        self,
        candidates: tuple[Path, ...],
        detections: tuple[ProviderDetection, ...],
    ) -> tuple[ThreatAnalysisRecord, ...]:
        output: list[ThreatAnalysisRecord] = []
        for path in candidates:
            detection = _matching_detection(path, detections)
            try:
                output.append(
                    self.threat_analysis.analyze(
                        path,
                        detection=detection,
                        source="aegis_intelligent_scan",
                    )
                )
            except (FileNotFoundError, OSError, RuntimeError, ValueError):
                continue
        return tuple(output)

    def _read_detections(self) -> tuple[ProviderDetection, ...]:
        try:
            return tuple(self.detection_reader() or ())
        except Exception:
            return ()

    @staticmethod
    def _can_establish_initial_baseline(
        *,
        baseline: object | None,
        snapshot: object,
        detections: tuple[ProviderDetection, ...],
        risk_overall: float,
    ) -> bool:
        if baseline is not None or detections or risk_overall >= 0.20:
            return False
        health = getattr(snapshot, "provider_health", ProviderHealth())
        errors = tuple(getattr(snapshot, "sensor_errors", ()))
        return (
            health.available is not False
            and health.active is not False
            and health.healthy is not False
            and not errors
        )

    @staticmethod
    def _training_eligible(
        *,
        baseline_available: bool,
        snapshot: object,
        detections: tuple[ProviderDetection, ...],
        analyses: tuple[ThreatAnalysisRecord, ...],
        risk_overall: float,
        learned_anomaly: float,
        learned_warmup: bool,
    ) -> bool:
        if not baseline_available or detections or risk_overall >= 0.20:
            return False
        if tuple(getattr(snapshot, "sensor_errors", ())):
            return False
        if any(
            analysis.assessment
            in {
                ThreatAssessmentLevel.SUSPICIOUS,
                ThreatAssessmentLevel.LIKELY_MALICIOUS,
                ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS,
            }
            for analysis in analyses
        ):
            return False
        return learned_warmup or learned_anomaly < 0.55

    def _observation_loop(self) -> None:
        if self._stop_event.wait(self.initial_observation_delay_seconds):
            return
        while not self._stop_event.is_set():
            self.observe_once()
            if self._stop_event.wait(self.observation_interval_seconds):
                return

    def _set_state(self, state: AegisState) -> None:
        with self._lock:
            self._state = state


def render_intelligent_scan(result: IntelligentScanResult) -> str:
    case = result.case
    strategy = case.scan_strategy.replace("_", " ").title()
    lines = [
        f"AEGIS {strategy.upper()} SECURITY SCAN",
        "",
        f"Mode: {strategy}",
        f"Case: {case.case_id}",
        f"Assessment: {case.status.value.replace('_', ' ').title()}",
        f"Threat likelihood: {round(case.risk.likelihood * 100)}%",
        f"Potential impact: {round(case.risk.impact * 100)}%",
        f"Current activity: {round(case.risk.activity * 100)}%",
        f"Persistence concern: {round(case.risk.persistence * 100)}%",
        f"Exposure concern: {round(case.risk.exposure * 100)}%",
        f"Urgency: {round(case.risk.urgency * 100)}%",
        f"Overall risk: {round(case.risk.overall * 100)}%",
        f"Evidence coverage: {round(case.coverage.overall * 100)}%",
        "",
        "Adaptive learning:",
        f"- Model version: {case.learning_model_version}",
        f"- Trusted samples before this assessment: {case.learning_sample_count}",
        f"- Learned anomaly: {round(case.learning_anomaly_score * 100)}%",
        f"- Learning confidence: {round(case.learning_confidence * 100)}%",
        f"- Model state: {'WARMING UP' if case.learning_warmup else 'ACTIVE'}",
        f"- Current sample accepted for learning: {'yes' if result.learning_sample_accepted else 'no'}",
        "",
        case.summary,
        "",
        "Security-relevant change review:",
        f"- New process images: {len(case.baseline_delta.new_process_paths)}",
        f"- New persistence entries: {len(case.baseline_delta.new_persistence)}",
        f"- New listening endpoints: {len(case.baseline_delta.new_listeners)}",
        f"- Provider detections correlated: {case.provider_detection_count}",
        f"- Files locally analyzed: {case.analyzed_file_count}",
        f"- Evidence graph: {len(case.evidence_nodes)} node(s), {len(case.evidence_edges)} relationship(s)",
    ]
    if result.baseline_established:
        lines.extend(
            [
                "",
                "Aegis established the first machine security baseline from this low-risk, non-degraded assessment.",
            ]
        )
    if case.hypotheses:
        lines.extend(["", "Competing hypotheses:"])
        for item in case.hypotheses:
            lines.append(
                f"- {item.title}: {round(item.confidence * 100)}% ({item.category})"
            )
            for evidence in item.evidence_for[:3]:
                lines.append(f"  Supports: {evidence}")
            for evidence in item.evidence_against[:2]:
                lines.append(f"  Counters: {evidence}")
    lines.extend(["", "Escalation decision:"])
    if case.escalation == "full_sweep_recommended":
        lines.append(
            "- Full-System Sweep recommended. Aegis did not start it automatically."
        )
    elif case.escalation == "targeted_investigation_recommended":
        lines.append(
            "- Additional targeted investigation recommended before any destructive response."
        )
    elif case.escalation == "additional_evidence_recommended":
        lines.append(
            "- Additional evidence is recommended because observable coverage was incomplete."
        )
    else:
        lines.append(
            "- No further scan escalation is currently justified by the correlated evidence."
        )
    if case.remaining_uncertainty:
        lines.extend(["", "Remaining uncertainty:"])
        lines.extend(f"- {item}" for item in case.remaining_uncertainty[:8])
    lines.extend(
        [
            "",
            "Aegis learned inference is advisory and did not override provider evidence or security policy.",
            "Aegis did not delete, quarantine, restore, exclude, terminate, or weaken any security control.",
            f"Aegis correlation phase elapsed: {result.elapsed_seconds:.2f}s",
        ]
    )
    return "\n".join(lines)


def _matching_detection(
    path: Path,
    detections: tuple[ProviderDetection, ...],
) -> ProviderDetection | None:
    target = _path_key(path)
    matches = [
        item
        for item in detections
        if item.file_path is not None and _path_key(Path(item.file_path)) == target
    ]
    if not matches:
        return None
    active = [item for item in matches if item.metadata.get("is_active") is not False]
    return (active or matches)[0]


def _path_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve()).replace("/", "\\").lower()
    except OSError:
        return str(path.expanduser().absolute()).replace("/", "\\").lower()


def _state_for_case(
    status: AegisCaseStatus,
    degraded_reasons: tuple[str, ...],
) -> AegisState:
    if degraded_reasons:
        return AegisState.DEGRADED
    if status is AegisCaseStatus.THREAT_CONFIRMED:
        return AegisState.THREAT_CONFIRMED
    if status in {AegisCaseStatus.ACTION_PENDING, AegisCaseStatus.MONITORING}:
        return AegisState.ELEVATED
    return AegisState.OBSERVING


def _band(value: float) -> str:
    if value >= 0.80:
        return "high"
    if value >= 0.55:
        return "moderate"
    return "low"
