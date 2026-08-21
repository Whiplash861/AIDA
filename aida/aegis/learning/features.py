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
    numeric = {
        "process_count": float(len(snapshot.processes)),
        "persistence_count": float(len(snapshot.persistence)),
        "listener_count": float(len(snapshot.listeners)),
        "remote_endpoint_count": float(remote_endpoint_count),
        "new_process_count": float(len(delta.new_process_paths)),
        "new_persistence_count": float(len(delta.new_persistence)),
        "new_listener_count": float(len(delta.new_listeners)),
        "provider_detection_count": float(len(detections)),
        "analyzed_file_count": float(len(analyses)),
        "suspicious_analysis_count": float(suspicious_analysis_count),
        "sensor_error_count": float(len(snapshot.sensor_errors)),
    }

    identity_tokens: list[str] = []
    for process in snapshot.processes:
        identity = process.executable or process.name
        if identity:
            identity_tokens.append(_token("process", identity))
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
