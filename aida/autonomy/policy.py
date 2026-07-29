
from __future__ import annotations

from dataclasses import dataclass

from aida.autonomy.models import (
    ActionKind,
    ActionProposal,
    AutonomyLevel,
    AutonomySettings,
    PolicyDecision,
    PolicyDisposition,
)


_READ_ONLY = {
    ActionKind.OBSERVE,
    ActionKind.REPORT,
    ActionKind.ALERT,
    ActionKind.SECURITY_STATUS,
}

_NEVER_AUTONOMOUS = {
    ActionKind.FULL_SWEEP,
    ActionKind.CANCEL_SCAN,
    ActionKind.STAND_DOWN,
    ActionKind.QUARANTINE,
    ActionKind.DELETE,
    ActionKind.RESTORE,
    ActionKind.ALLOW,
    ActionKind.PROCESS_TERMINATE,
    ActionKind.APPLICATION_RESTART,
    ActionKind.CACHE_CLEAR,
    ActionKind.APPLICATION_REPAIR,
    ActionKind.APPLICATION_RESET,
    ActionKind.WINDOWS_REPAIR,
}

_FORBIDDEN = {
    ActionKind.DELETE,
    ActionKind.RESTORE,
    ActionKind.ALLOW,
}


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    version: str = "2026.07-alpha-1"

    def evaluate(
        self,
        proposal: ActionProposal,
        settings: AutonomySettings,
    ) -> PolicyDecision:
        if proposal.action_kind in _FORBIDDEN:
            return self._decision(
                proposal,
                PolicyDisposition.DENY,
                "This action is not authorized in the current prototype.",
                requires_confirmation=False,
            )

        if proposal.action_kind in _READ_ONLY:
            return self._decision(
                proposal,
                PolicyDisposition.ALLOW,
                "Observation, reporting, and alerts do not modify the system.",
                requires_confirmation=False,
            )

        if not proposal.autonomous:
            return self._decision(
                proposal,
                PolicyDisposition.REQUIRE_USER,
                "The requested operational action requires direct user authorization.",
                requires_confirmation=True,
            )

        if settings.kill_switch_engaged:
            return self._decision(
                proposal,
                PolicyDisposition.REQUIRE_USER,
                "The autonomy kill switch is engaged. All operational decisions route to the user.",
                requires_confirmation=True,
            )

        if not settings.enabled:
            return self._decision(
                proposal,
                PolicyDisposition.REQUIRE_USER,
                "Autonomy is disabled. All operational decisions route to the user.",
                requires_confirmation=True,
            )

        if proposal.action_kind in _NEVER_AUTONOMOUS:
            return self._decision(
                proposal,
                PolicyDisposition.REQUIRE_USER,
                "This action remains manual even while Controlled Autonomy is enabled.",
                requires_confirmation=True,
            )

        if proposal.action_kind is ActionKind.SURFACE_SCAN:
            if (
                settings.level >= AutonomyLevel.TRIAGE
                and settings.allow_autonomous_surface_scan
            ):
                return self._decision(
                    proposal,
                    PolicyDisposition.ALLOW,
                    "Limited Triage policy permits this Surface Security Scan.",
                    requires_confirmation=False,
                )
            return self._decision(
                proposal,
                PolicyDisposition.REQUIRE_USER,
                "Surface Scan autonomy is not enabled at the current policy level.",
                requires_confirmation=True,
            )

        if proposal.action_kind is ActionKind.DEEP_SCAN:
            if (
                settings.level >= AutonomyLevel.INVESTIGATE
                and settings.allow_autonomous_deep_scan
                and bool(proposal.scope.get("target_path"))
            ):
                return self._decision(
                    proposal,
                    PolicyDisposition.ALLOW,
                    "Controlled Investigation permits a targeted scan of the recorded path.",
                    requires_confirmation=False,
                )
            return self._decision(
                proposal,
                PolicyDisposition.REQUIRE_USER,
                "Targeted Deep Scans require explicit scope and higher authority.",
                requires_confirmation=True,
            )

        return self._decision(
            proposal,
            PolicyDisposition.REQUIRE_USER,
            "No autonomous policy rule permits this action.",
            requires_confirmation=True,
        )

    def _decision(
        self,
        proposal: ActionProposal,
        disposition: PolicyDisposition,
        reason: str,
        *,
        requires_confirmation: bool,
    ) -> PolicyDecision:
        return PolicyDecision(
            proposal_id=proposal.proposal_id,
            disposition=disposition,
            reason=reason,
            policy_version=self.version,
            requires_confirmation=requires_confirmation,
        )
