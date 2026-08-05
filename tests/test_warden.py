from __future__ import annotations

from aida.artificer.models import AuthorityLevel
from aida.artificer.policy import ArtificerPolicy
from aida.artificer.warden import Warden


def test_warden_denies_protected_paths(tmp_path) -> None:
    policy = ArtificerPolicy(tmp_path)
    decision = Warden(policy).authorize(
        path="aida/artificer/policy.py",
        rule_id="python.format_only",
        confidence=1.0,
        evidence_quality=1.0,
        implementation_risk=0.0,
        rollback_ready=True,
        changed_lines=1,
    )
    assert decision.allowed is False
    assert decision.authority is AuthorityLevel.FORBIDDEN


def test_warden_allows_proven_formatting_patch(tmp_path) -> None:
    policy = ArtificerPolicy(tmp_path)
    decision = Warden(policy).authorize(
        path="aida/example.py",
        rule_id="python.format_only",
        confidence=0.99,
        evidence_quality=0.99,
        implementation_risk=0.05,
        rollback_ready=True,
        changed_lines=3,
    )
    assert decision.allowed is True
