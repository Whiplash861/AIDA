
from __future__ import annotations

from aida.autonomy.budgets import AutonomyBudgetGuard
from aida.autonomy.controller import AutonomyController
from aida.autonomy.models import (
    ActionKind,
    ActionProposal,
    PolicyDecision,
    PolicyDisposition,
)


class ControlledAutonomyEngine:
    """Evaluates autonomous proposals; it does not execute them."""

    def __init__(
        self,
        controller: AutonomyController,
        budget_guard: AutonomyBudgetGuard,
    ) -> None:
        self.controller = controller
        self.budget_guard = budget_guard

    def evaluate(self, proposal: ActionProposal) -> PolicyDecision:
        decision = self.controller.evaluate(proposal)
        if (
            decision.disposition is not PolicyDisposition.ALLOW
            or not proposal.autonomous
            or proposal.action_kind is not ActionKind.SURFACE_SCAN
        ):
            return decision

        budget = self.budget_guard.evaluate_surface_scan(
            self.controller.settings
        )
        if budget.allowed:
            return decision
        return PolicyDecision(
            proposal_id=proposal.proposal_id,
            disposition=PolicyDisposition.DENY,
            reason=budget.reason,
            policy_version=decision.policy_version,
            requires_confirmation=False,
        )

    def record_started(self, proposal: ActionProposal) -> None:
        if (
            proposal.autonomous
            and proposal.action_kind is ActionKind.SURFACE_SCAN
        ):
            self.budget_guard.record_surface_scan_start(
                trigger=proposal.trigger or "Unspecified deterministic trigger",
                policy_version=self.controller.policy.version,
            )
