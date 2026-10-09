from __future__ import annotations

from dataclasses import dataclass
import math
import secrets
import threading
import time
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

    def __init__(self, policy: ArtificerPolicy, *, approval_authorizer=None) -> None:
        self.policy = policy
        self.approval_authorizer = approval_authorizer
        self._approvals = {}
        self._approval_lock = threading.Lock()

    def issue_approval(self, *, developer_id: str, path: str, rule_id: str,
                       original_sha256: str, proposed_sha256: str, lifetime_seconds: int = 120) -> str:
        if self.approval_authorizer is None or not self.approval_authorizer(developer_id):
            raise PermissionError("A trusted owner confirmation boundary must issue approval")
        token = secrets.token_urlsafe(32)
        with self._approval_lock:
            self._approvals[token] = (self.policy._normalize(path), rule_id, original_sha256,
                                      proposed_sha256, time.monotonic() + min(120, max(1, lifetime_seconds)))
        return token

    def consume_approval(self, token, *, path, rule_id, original_sha256, proposed_sha256) -> bool:
        with self._approval_lock:
            scope = self._approvals.pop(token, None)
        return bool(scope and scope[:4] == (self.policy._normalize(path), rule_id, original_sha256, proposed_sha256)
                    and time.monotonic() <= scope[4])

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
        if (any(not math.isfinite(value) or not 0 <= value <= 1 for value in
                (confidence, evidence_quality, implementation_risk))
                or not isinstance(changed_lines, int) or changed_lines < 0):
            return WardenDecision(False, AuthorityLevel.FORBIDDEN, "Invalid evidence or risk bounds")
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
