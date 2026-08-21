from __future__ import annotations

import hashlib
import os

from aida.aegis.learning.models import AegisFeatureVector
from aida.aegis.models import BaselineDelta, SecuritySnapshot
from aida.security.models import ProviderDetection
from aida.security.threat_analysis import ThreatAnalysisRecord, ThreatAssessmentLevel


def extract_feature_vector(
    *,
    snapshot: SecuritySnapshot,
    delta: BaselineDelta,
    detections: tuple[ProviderDetection, ...],
    analyses: tuple[ThreatAnalysisRecord, ...],
) -> AegisFeatureVector:
    remote_endpoint_count = sum(
        len(process.remote_endpoints) for process in snapshot.processes
    )
    suspicious_analysis_count = sum(
        1
        for analysis in analyses
        if analysis.assessment
        in {
            ThreatAssessmentLevel.SUSPICIOUS,
            ThreatAssessmentLevel.LIKELY_MALICIOUS,
            ThreatAssessmentLevel.PROVIDER_CONFIRMED_MALICIOUS,
        }
    )
    parent_child_count = sum(
        1 for process in snapshot.processes if process.parent_pid is not None
    )
    numeric = {
        "process_count": float(len(snapshot.processes)),
        "persistence_count": float(len(snapshot.persistence)),
        "listener_count": float(len(snapshot.listeners)),
        "remote_endpoint_count": float(remote_endpoint_count),
        "parent_child_relationship_count": float(parent_child_count),
        "new_process_count": float(len(delta.new_process_paths)),
        "new_persistence_count": float(len(delta.new_persistence)),
        "new_listener_count": float(len(delta.new_listeners)),
        "provider_detection_count": float(len(detections)),
        "analyzed_file_count": float(len(analyses)),
        "suspicious_analysis_count": float(suspicious_analysis_count),
        "sensor_error_count": float(len(snapshot.sensor_errors)),
    }

    identity_tokens: list[str] = []
    process_by_pid = {process.pid: process for process in snapshot.processes}
    for process in snapshot.processes:
        identity = process.executable or process.name
        if not identity:
            continue
        identity_tokens.append(_token("process", identity))
        parent = process_by_pid.get(process.parent_pid or -1)
        if parent is not None:
            parent_identity = parent.executable or parent.name
            if parent_identity:
                identity_tokens.append(
                    _token(
                        "parent_child",
                        f"{parent_identity}|{identity}",
                    )
                )
        if process.remote_endpoints:
            identity_tokens.append(
                _token(
                    "process_remote_activity",
                    f"{identity}|remote_present",
                )
            )
        if process.listening_endpoints:
            identity_tokens.append(
                _token(
                    "process_listener_activity",
                    f"{identity}|listener_present",
                )
            )
    for item in snapshot.persistence:
        identity_tokens.append(
            _token(
                "persistence",
                f"{item.mechanism}|{item.name}|{item.target}",
            )
        )
    for listener in snapshot.listeners:
        identity_tokens.append(_token("listener", listener))

    return AegisFeatureVector(
        numeric=numeric,
        identity_tokens=tuple(sorted(set(identity_tokens))),
    )


def _token(kind: str, value: str) -> str:
    normalized = os.path.normcase(value.strip()).lower()
    digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
    return f"{kind}:{digest}"
