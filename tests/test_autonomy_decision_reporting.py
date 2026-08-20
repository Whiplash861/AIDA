from aida.autonomy.models import (
    ActionKind,
    ActionProposal,
    ActionRisk,
    PolicyDecision,
    PolicyDisposition,
)
from aida.autonomy.reporting import (
    AutonomousDecisionReport,
    render_decision_report,
)


def test_decision_report_includes_authority_trigger_and_action_boundary():
    proposal = ActionProposal(
        action_kind=ActionKind.SURFACE_SCAN,
        reason="Provider health was degraded.",
        risk=ActionRisk.LOW,
        autonomous=True,
        trigger="Provider health degraded",
    )
    decision = PolicyDecision(
        proposal_id=proposal.proposal_id,
        disposition=PolicyDisposition.REQUIRE_USER,
        reason="Observation mode cannot execute scans.",
        policy_version="test-policy",
        requires_confirmation=True,
    )
    report = AutonomousDecisionReport(
        proposal=proposal,
        decision=decision,
        observed_evidence=("Provider healthy: no",),
        action_taken="No operational action taken. Observation executor only.",
        autonomy_enabled=True,
        autonomy_level="Observe",
        authorization_source=(
            "No operational authorization; direct user confirmation required"
        ),
    )

    rendered = render_decision_report(report)

    assert "Trigger: Provider health degraded" in rendered
    assert "Autonomy state: Enabled" in rendered
    assert "Autonomy level: Observe" in rendered
    assert "Action risk: Low" in rendered
    assert "No operational authorization" in rendered
    assert "No operational action taken" in rendered
