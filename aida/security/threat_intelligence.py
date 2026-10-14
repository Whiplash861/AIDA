from __future__ import annotations

from aida.reporting import render_report

import re

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from aida.security.models import ProviderDetection, SecuritySeverity
from aida.security.threat_analysis import (
    LocalThreatAnalyzer,
    ThreatAnalysisRecord,
)


class AttributionConfidence(StrEnum):
    UNKNOWN = "unknown"
    WEAK_ASSOCIATION = "weak_association"
    POSSIBLE_ASSOCIATION = "possible_association"
    PROBABLE_ASSOCIATION = "probable_association"
    PROVIDER_ATTRIBUTED = "provider_attributed"
    CONFIRMED_LOCAL_EVIDENCE = "confirmed_local_evidence"


@dataclass(frozen=True, slots=True)
class NetworkEndpoint:
    address: str
    port: int | None = None
    registration_region: str | None = None
    autonomous_system: str | None = None
    observed_by: str = "local observation"


@dataclass(frozen=True, slots=True)
class ThreatIntelligenceReport:
    threat_name: str
    severity: SecuritySeverity
    current_state: str
    observed_resource: Path | None
    likely_purpose: str
    classification_confidence: float
    threat_actor: str
    actor_confidence: AttributionConfidence
    actor_location: str
    actor_evidence: tuple[str, ...]
    observed_endpoints: tuple[NetworkEndpoint, ...]
    possible_impacts: tuple[str, ...]
    recommended_response: str
    observed_facts: tuple[str, ...] = ()
    inference_notes: tuple[str, ...] = ()
    provider_classification: str = ""
    aida_assessment: str = "Unknown"
    analysis_confidence: float | None = None
    file_identity: tuple[str, ...] = ()
    current_activity: str = "Unknown"
    remaining_uncertainty: tuple[str, ...] = ()
    analysis_id: str | None = None


class ThreatIntelligenceBuilder:
    """Offline-safe, evidence-limited threat classification and attribution."""

    def __init__(self, analyzer: LocalThreatAnalyzer | None = None) -> None:
        self.analyzer = analyzer or LocalThreatAnalyzer()

    def build(
        self,
        detection: ProviderDetection,
        *,
        endpoints: tuple[NetworkEndpoint, ...] = (),
        analysis: ThreatAnalysisRecord | None = None,
    ) -> ThreatIntelligenceReport:
        metadata = detection.metadata
        name = detection.name.strip() or "Unknown threat"
        if analysis is None and detection.file_path is not None:
            try:
                if detection.file_path.is_file():
                    analysis = self.analyzer.analyze(
                        detection.file_path,
                        detection=detection,
                    )
            except (OSError, RuntimeError, ValueError):
                analysis = None
        purpose, impacts, confidence = _classify(name, metadata)
        actor, actor_confidence, actor_evidence = _actor(metadata)
        resolved_endpoints = endpoints or _endpoints_from_metadata(metadata)
        if analysis is not None:
            process_endpoints = tuple(
                NetworkEndpoint(address=address, observed_by="local process snapshot")
                for process in analysis.process_observations
                for address in process.network_endpoints
            )
            resolved_endpoints = tuple(
                dict.fromkeys(resolved_endpoints + process_endpoints)
            )
            impacts = tuple(
                dict.fromkeys(impacts + analysis.possible_impacts)
            )
            confidence = max(confidence, analysis.confidence)
        active = metadata.get("is_active")
        current_state = (
            "Active — no neutralization confirmed"
            if active is True
            else "Provider reports the item is not currently active"
            if active is False
            else "Current activity state is unknown"
        )
        facts = [
            f"Provider: {detection.source}",
            f"Detection ID: {detection.detection_id}",
        ]
        if detection.file_path is not None:
            facts.append(f"Observed resource: {detection.file_path}")
        if metadata.get("action_success") is not None:
            facts.append(
                "Provider action succeeded"
                if metadata.get("action_success")
                else "Provider action success was not confirmed"
            )
        if analysis is not None:
            facts.extend(analysis.observed_facts)
        inference_notes = [
            "Malware purpose and impacts are predictions based on provider classification and available local evidence.",
            "An observed IP address, ASN, certificate organization, or registered region is not proof of the actor's physical location.",
        ]
        if analysis is not None:
            inference_notes.extend(analysis.inference_notes)
        return ThreatIntelligenceReport(
            threat_name=name,
            severity=detection.severity,
            current_state=current_state,
            observed_resource=detection.file_path,
            likely_purpose=purpose,
            classification_confidence=confidence,
            threat_actor=actor,
            actor_confidence=actor_confidence,
            actor_location="Unknown",
            actor_evidence=actor_evidence,
            observed_endpoints=resolved_endpoints,
            possible_impacts=impacts,
            recommended_response=(
                analysis.recommended_next_step
                if analysis is not None
                else _recommended_response(detection.severity, active)
            ),
            observed_facts=tuple(dict.fromkeys(facts)),
            inference_notes=tuple(dict.fromkeys(inference_notes)),
            provider_classification=name,
            aida_assessment=(
                analysis.assessment.value.replace("_", " ").title()
                if analysis is not None
                else "Unknown — local file analysis unavailable"
            ),
            analysis_confidence=(analysis.confidence if analysis else None),
            file_identity=(
                _identity_lines(analysis) if analysis is not None else ()
            ),
            current_activity=(
                analysis.current_activity if analysis is not None else "Unknown"
            ),
            remaining_uncertainty=(
                analysis.remaining_uncertainty
                if analysis is not None
                else (
                    "The local file identity and runtime context were not available for this report.",
                )
            ),
            analysis_id=(analysis.analysis_id if analysis else None),
        )


def render_threat_report(report: ThreatIntelligenceReport) -> str:
    from aida.aegis.explanations import explain_sensor_limitations

    found = [
        f"Antivirus finding: {report.threat_name}",
        f"Priority reported by the antivirus: {report.severity.name.replace('_', ' ').lower()}.",
        f"Antivirus-reported state: {report.current_state}",
        f"Local activity recorded at this check: {report.current_activity}",
        *report.observed_facts,
    ]
    if report.observed_resource:
        found.append(f"Affected file or resource: {report.observed_resource}")
    for endpoint in report.observed_endpoints:
        address = endpoint.address + (f":{endpoint.port}" if endpoint.port is not None else "")
        found.append(f"Recorded network address: {address} (reported by {endpoint.observed_by}).")
    unknown = [
        *explain_sensor_limitations(report.remaining_uncertainty),
        *report.inference_notes,
        "The detection name and network addresses alone do not identify the person responsible or their physical location.",
    ]
    if not report.observed_resource:
        unknown.append("The affected file or resource was not supplied with this finding.")
    details = [
        f"Provider classification: {report.provider_classification or report.threat_name}",
        f"AIDA assessment: {report.aida_assessment}",
        f"Classification confidence: {round(report.classification_confidence * 100)} percent",
        *report.file_identity,
        f"Threat actor assessment: {report.threat_actor}; attribution confidence: {report.actor_confidence.value}",
        f"Physical actor location assessment: {report.actor_location}",
        *report.actor_evidence,
    ]
    if report.analysis_id:
        details.append(f"Analysis ID: {report.analysis_id}")
    if report.analysis_confidence is not None:
        details.append(f"Local analysis confidence: {round(report.analysis_confidence * 100)} percent (assessment score, not proof)")
    for endpoint in report.observed_endpoints:
        if endpoint.registration_region or endpoint.autonomous_system:
            details.append(f"Address registration for {endpoint.address}: region {endpoint.registration_region or 'unknown'}; network {endpoint.autonomous_system or 'unknown'}. Registration does not establish the operator's location.")
    interpretation = f"Possible purpose suggested by this finding: {report.likely_purpose}"
    if report.possible_impacts:
        interpretation += "\nPossible effects if the suspected threat is present: " + "; ".join(report.possible_impacts)
    priority = report.severity.name.lower() in {"high", "critical", "severe"}
    return render_report("Priority antivirus finding" if priority else "Antivirus finding review",
                         found=found, unknown=unknown,
                         next_steps=(report.recommended_response or "Review the finding in Windows Security before choosing a response.",),
                         interpretation=interpretation, details=details)


def _identity_lines(analysis: ThreatAnalysisRecord) -> tuple[str, ...]:
    identity = analysis.identity
    output = [
        f"Path: {identity.path}",
        f"SHA-256: {identity.sha256 or 'not calculated'}",
        f"Size: {identity.file_size} bytes",
        f"Detected type: {identity.detected_type}",
        f"Signature: {identity.signature_state.value.replace('_', ' ')}",
    ]
    if identity.signer_subject:
        output.append(f"Signer: {identity.signer_subject}")
    if identity.signer_thumbprint:
        output.append(f"Signer thumbprint: {identity.signer_thumbprint}")
    if identity.publisher:
        output.append(f"Publisher: {identity.publisher}")
    if identity.file_version:
        output.append(f"File version: {identity.file_version}")
    return tuple(output)


def _endpoints_from_metadata(
    metadata: dict[str, Any],
) -> tuple[NetworkEndpoint, ...]:
    raw_endpoints = metadata.get("network_endpoints")
    if not isinstance(raw_endpoints, (list, tuple)):
        return ()
    regions = metadata.get("endpoint_regions")
    region_map = regions if isinstance(regions, dict) else {}
    systems = metadata.get("endpoint_autonomous_systems")
    system_map = systems if isinstance(systems, dict) else {}
    output: list[NetworkEndpoint] = []
    for raw in raw_endpoints:
        text = str(raw).strip()
        if not text:
            continue
        address = text
        port: int | None = None
        if text.startswith("[") and "]:" in text:
            host, raw_port = text.rsplit(":", 1)
            address = host[1:-1]
            try:
                port = int(raw_port)
            except ValueError:
                address = text
        elif text.count(":") == 1:
            host, raw_port = text.rsplit(":", 1)
            try:
                port = int(raw_port)
                address = host
            except ValueError:
                pass
        output.append(
            NetworkEndpoint(
                address=address,
                port=port,
                registration_region=(
                    str(region_map.get(text)).strip()
                    if region_map.get(text)
                    else None
                ),
                autonomous_system=(
                    str(system_map.get(text)).strip()
                    if system_map.get(text)
                    else None
                ),
            )
        )
    return tuple(output)


def _classify(
    name: str,
    metadata: dict[str, Any],
) -> tuple[str, tuple[str, ...], float]:
    lowered = name.lower()
    patterns = (
        (("ransom", "crypt"), "File encryption or destructive extortion", ("Files may be encrypted or made unavailable", "Business operations may be disrupted", "Backups and shared locations may be targeted"), 0.88),
        (("credential", "stealer", "password"), "Credential theft and unauthorized account access", ("Browser or application credentials may be stolen", "Accounts may be accessed without authorization", "Sensitive information may be transmitted externally"), 0.84),
        (("trojan", "loader", "dropper"), "Secondary payload delivery or remote control", ("Additional software may be installed", "Persistent unauthorized access may be established", "System stability and privacy may be affected"), 0.78),
        (("backdoor", "rat", "remoteaccess"), "Remote control and persistence", ("The device may be controlled remotely", "Files and credentials may be accessed", "The program may survive restarts"), 0.86),
        (("miner", "coinminer"), "Unauthorized resource consumption", ("CPU or GPU resources may be consumed", "System responsiveness may degrade", "Power use and thermal load may increase"), 0.82),
        (("adware", "pua", "potentially unwanted"), "Unwanted software or browser manipulation", ("Advertisements or redirects may appear", "Browser settings may change", "System performance or privacy may be reduced"), 0.74),
    )
    for keywords, purpose, impacts, confidence in patterns:
        if any((re.search(r"\brat\b", lowered) is not None) if keyword == "rat" else keyword in lowered for keyword in keywords):
            return purpose, impacts, confidence
    family = metadata.get("malware_family")
    if family:
        return (
            f"Behavior associated with the reported {family} family",
            ("Unauthorized system changes may occur", "Data confidentiality or availability may be affected"),
            0.70,
        )
    return (
        "Unknown; insufficient evidence for a reliable behavioral category",
        ("Potential impact is unknown", "Further provider validation is recommended"),
        0.35,
    )


def _actor(
    metadata: dict[str, Any],
) -> tuple[str, AttributionConfidence, tuple[str, ...]]:
    provider_actor = str(metadata.get("provider_attributed_actor") or "").strip()
    if provider_actor:
        evidence = tuple(
            str(item)
            for item in metadata.get("actor_evidence", [])
            if str(item).strip()
        )
        return (
            provider_actor,
            AttributionConfidence.PROVIDER_ATTRIBUTED,
            evidence or ("The antivirus provider supplied this attribution.",),
        )
    return (
        "Unknown — no reliable attribution evidence",
        AttributionConfidence.UNKNOWN,
        (),
    )


def _recommended_response(
    severity: SecuritySeverity,
    active: object,
) -> str:
    if active is True and severity in {
        SecuritySeverity.HIGH,
        SecuritySeverity.CRITICAL,
    }:
        return (
            "Review the exact file in AIDA's Threat Center and prepare guarded Defender remediation. Fresh user authorization is required."
        )
    return (
        "Review the item in AIDA's Threat Center and Microsoft Defender Protection History. AIDA has not taken remediation action."
    )
