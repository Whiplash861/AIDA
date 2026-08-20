from __future__ import annotations

from datetime import datetime
from typing import Any

from aida.artificer.models import ArtificerFinding, UpgradeProposal


def finding_from_record(record: dict[str, Any]) -> ArtificerFinding:
    return ArtificerFinding(
        finding_id=record["finding_id"],
        category=record["category"],
        title=record["title"],
        severity=record["severity"],
        confidence=float(record["confidence"]),
        evidence_quality=float(record["evidence_quality"]),
        affected_components=tuple(record.get("affected_components", [])),
        first_seen_utc=datetime.fromisoformat(record["first_seen_utc"]),
        last_seen_utc=datetime.fromisoformat(record["last_seen_utc"]),
        observation_count=int(record["observation_count"]),
        finding=record["finding"],
        evidence_summary=record["evidence_summary"],
        reasoning_summary=record["reasoning_summary"],
        recommended_change=record["recommended_change"],
        expected_outcomes=tuple(record.get("expected_outcomes", [])),
        implementation_risk=float(record["implementation_risk"]),
        regression_risk=float(record["regression_risk"]),
        authority_required=record["authority_required"],
        status=record.get("status", "open"),
        fingerprint=record.get("fingerprint", ""),
    )


def proposal_from_record(record: dict[str, Any]) -> UpgradeProposal:
    return UpgradeProposal(
        proposal_id=record["proposal_id"],
        title=record["title"],
        affected_subsystem=record["affected_subsystem"],
        current_version=record["current_version"],
        proposed_version=record["proposed_version"],
        supporting_findings=tuple(record.get("supporting_findings", [])),
        rationale=record["rationale"],
        alternatives_considered=tuple(record.get("alternatives_considered", [])),
        expected_outcomes=tuple(record.get("expected_outcomes", [])),
        success_metrics=tuple(record.get("success_metrics", [])),
        required_tests=tuple(record.get("required_tests", [])),
        compatibility_requirements=tuple(record.get("compatibility_requirements", [])),
        rollback_procedure=record["rollback_procedure"],
        implementation_risk=float(record["implementation_risk"]),
        regression_risk=float(record["regression_risk"]),
        authority_required=record["authority_required"],
        status=record.get("status", "pending"),
        created_at_utc=datetime.fromisoformat(record["created_at_utc"]),
    )
