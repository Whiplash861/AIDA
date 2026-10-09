from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from aida.aegis.models import (
    BaselineDelta,
    EvidenceEdge,
    EvidenceNode,
    SecuritySnapshot,
)
from aida.security.models import ProviderDetection
from aida.security.threat_analysis import ThreatAnalysisRecord


class EvidenceGraphBuilder:
    """Correlates provider, file, process, persistence, and network evidence."""

    def build(
        self,
        *,
        snapshot: SecuritySnapshot,
        delta: BaselineDelta,
        detections: Iterable[ProviderDetection],
        analyses: Iterable[ThreatAnalysisRecord],
    ) -> tuple[tuple[EvidenceNode, ...], tuple[EvidenceEdge, ...]]:
        nodes: dict[str, EvidenceNode] = {}
        edges: list[EvidenceEdge] = []

        file_nodes: dict[str, str] = {}
        for analysis in analyses:
            file_id = _node_id("file", str(analysis.path))
            file_nodes[_path_key(str(analysis.path))] = file_id
            nodes[file_id] = EvidenceNode(
                node_id=file_id,
                kind="file",
                label=analysis.path.name,
                attributes={
                    "assessment": analysis.assessment.value,
                    "confidence": round(analysis.confidence, 4),
                    "signature": analysis.identity.signature_state.value,
                    "running_processes": len(analysis.process_observations),
                    "persistence_references": len(
                        analysis.persistence_observations
                    ),
                },
            )

        for detection in detections:
            detection_id = _node_id("provider_detection", detection.detection_id)
            nodes[detection_id] = EvidenceNode(
                node_id=detection_id,
                kind="provider_detection",
                label=detection.name,
                attributes={
                    "source": detection.source,
                    "severity": detection.severity.name,
                    "active": detection.metadata.get("is_active"),
                },
            )
            if detection.file_path is not None:
                path_key = _path_key(str(detection.file_path))
                file_id = file_nodes.get(path_key)
                if file_id is None:
                    file_id = _node_id("file", str(detection.file_path))
                    file_nodes[path_key] = file_id
                    nodes[file_id] = EvidenceNode(
                        node_id=file_id,
                        kind="file",
                        label=Path(detection.file_path).name,
                        attributes={"provider_only": True},
                    )
                edges.append(
                    EvidenceEdge(
                        source_id=detection_id,
                        relationship="DETECTED_AS",
                        target_id=file_id,
                        confidence=1.0,
                    )
                )

        for process in snapshot.processes:
            if not process.executable:
                continue
            process_id = _node_id("process", f"{process.pid}:{process.executable}")
            file_id = file_nodes.get(_path_key(process.executable))
            interesting = (
                file_id is not None
                or process.executable in delta.new_process_paths
                or bool(process.listening_endpoints)
            )
            if not interesting:
                continue
            nodes[process_id] = EvidenceNode(
                node_id=process_id,
                kind="process",
                label=f"{process.name} ({process.pid})",
                attributes={
                    "pid": process.pid,
                    "parent_pid": process.parent_pid,
                    "remote_endpoint_count": len(process.remote_endpoints),
                    "listener_count": len(process.listening_endpoints),
                },
            )
            if file_id is None:
                file_id = _node_id("file", process.executable)
                file_nodes[_path_key(process.executable)] = file_id
                nodes[file_id] = EvidenceNode(
                    node_id=file_id,
                    kind="file",
                    label=Path(process.executable).name,
                    attributes={"new_process_image": True},
                )
            edges.append(
                EvidenceEdge(
                    source_id=process_id,
                    relationship="EXECUTES",
                    target_id=file_id,
                    confidence=1.0,
                )
            )
            for endpoint in process.remote_endpoints:
                endpoint_id = _node_id("network_endpoint", endpoint)
                nodes.setdefault(
                    endpoint_id,
                    EvidenceNode(
                        node_id=endpoint_id,
                        kind="network_endpoint",
                        label=endpoint,
                        attributes={"direction": "remote"},
                    ),
                )
                edges.append(
                    EvidenceEdge(
                        source_id=process_id,
                        relationship="CONNECTED_TO",
                        target_id=endpoint_id,
                        confidence=1.0,
                    )
                )

        for persistence in delta.new_persistence:
            persistence_id = _node_id(
                "persistence",
                f"{persistence.mechanism}:{persistence.name}:{persistence.target}",
            )
            nodes[persistence_id] = EvidenceNode(
                node_id=persistence_id,
                kind="persistence",
                label=f"{persistence.mechanism}: {persistence.name}",
                attributes={"new_since_baseline": True},
            )
            target_file = _matching_file_node(file_nodes, persistence.target)
            if target_file is not None:
                edges.append(
                    EvidenceEdge(
                        source_id=persistence_id,
                        relationship="PERSISTS_AS",
                        target_id=target_file,
                        confidence=0.9,
                    )
                )

        return tuple(nodes.values()), tuple(edges)


def _matching_file_node(file_nodes: dict[str, str], target: str) -> str | None:
    lowered = target.lower()
    matches = [
        node_id
        for path_key, node_id in file_nodes.items()
        if path_key and path_key in lowered
    ]
    return matches[0] if len(matches) == 1 else None


def _node_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}|{value}".encode("utf-8")).hexdigest()[:20]
    return f"{kind}:{digest}"


def _path_key(value: str) -> str:
    return str(value).strip().replace("/", "\\").lower()
