from __future__ import annotations

import re
import uuid

from aida.artificer.models import ArtificerFinding, UpgradeProposal


class Architect:
    """Converts mature findings into reviewable subsystem upgrade proposals."""

    def propose(self, finding: ArtificerFinding, current_version: str = "1.0.0") -> UpgradeProposal:
        proposed_version = self._next_minor(current_version)
        return UpgradeProposal(
            proposal_id=f"AE-PROP-{uuid.uuid4().hex[:10].upper()}",
            title=f"Improve {finding.title}",
            affected_subsystem=finding.affected_components[0] if finding.affected_components else "AIDA",
            current_version=current_version,
            proposed_version=proposed_version,
            supporting_findings=(finding.finding_id,),
            rationale=finding.reasoning_summary,
            alternatives_considered=("Retain current behavior and continue observation",),
            expected_outcomes=finding.expected_outcomes,
            success_metrics=(
                "Finding does not recur across the next validated observation window",
                "No regression findings are created by the change",
            ),
            required_tests=("Focused unit tests", "Integration regression test", "Rollback verification"),
            compatibility_requirements=("Preserve current public interfaces",),
            rollback_procedure="Restore the pre-change file hashes and restart the affected subsystem.",
            implementation_risk=finding.implementation_risk,
            regression_risk=finding.regression_risk,
            authority_required=finding.authority_required,
        )

    @staticmethod
    def _next_minor(version: str) -> str:
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
        if not match:
            return "1.1.0"
        major, minor, _patch = (int(part) for part in match.groups())
        return f"{major}.{minor + 1}.0"
