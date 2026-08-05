from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aida.artificer.models import AuthorityLevel
from aida.artificer.policy import ArtificerPolicy


@dataclass(frozen=True, slots=True)
class WardenDecision:
    allowed: bool
    authority: AuthorityLevel
    reason: str


class Warden:
    """Independent authorization gate for every Artificer modification."""

    def __init__(self, policy: ArtificerPolicy) -> None:
        self.policy = policy

    def authorize(
        self,
        *,
        path: str | Path,
        rule_id: str,
        confidence: float,
        evidence_quality: float,
        implementation_risk: float,
        rollback_ready: bool,
        changed_lines: int,
        owner_approved: bool = False,
    ) -> WardenDecision:
        rule = self.policy.get_rule(rule_id)
        if rule is None:
            return WardenDecision(False, AuthorityLevel.FORBIDDEN, "Unknown maintenance rule")
        if self.policy.is_protected(path):
            return WardenDecision(False, AuthorityLevel.FORBIDDEN, "Protected Artificer or security path")
        if not self.policy.is_path_allowed(path, rule):
            return WardenDecision(False, AuthorityLevel.FORBIDDEN, "Path is outside rule scope")
        if changed_lines > rule.maximum_changed_lines:
            return WardenDecision(False, rule.authority, "Patch exceeds rule size limit")
        if not rollback_ready:
            return WardenDecision(False, rule.authority, "Rollback asset is not ready")
        if rule.requires_owner_approval and not owner_approved:
            return WardenDecision(False, AuthorityLevel.OWNER_APPROVAL, "Owner approval required")
        if confidence < 0.95:
            return WardenDecision(False, rule.authority, "Confidence below autonomous threshold")
        if evidence_quality < 0.90:
            return WardenDecision(False, rule.authority, "Evidence quality below autonomous threshold")
        if implementation_risk > 0.20 and not owner_approved:
            return WardenDecision(False, AuthorityLevel.OWNER_APPROVAL, "Implementation risk requires approval")
        return WardenDecision(True, rule.authority, "Policy requirements satisfied")
