
from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from aida.autonomy.models import (
    ActionProposal,
    AutonomyLevel,
    AutonomySettings,
    PolicyDecision,
)
from aida.autonomy.policy import AutonomyPolicy
from aida.memory.models import ProcessOutcome
from aida.memory.service import MemoryService


PreferenceGetter = Callable[[str, object], object]
PreferenceSetter = Callable[[str, object], None]


class AutonomyController:
    """Single policy-enforced source of truth for the frontend autonomy switch."""

    _PREFERENCE_KEY = "autonomy.settings"

    def __init__(
        self,
        memory: MemoryService,
        policy: AutonomyPolicy | None = None,
    ) -> None:
        self.memory = memory
        self.policy = policy or AutonomyPolicy()
        self._settings = self._load()

    @property
    def settings(self) -> AutonomySettings:
        return self._settings

    def set_enabled(self, enabled: bool, *, changed_by: str) -> AutonomySettings:
        previous = self._settings
        if enabled and previous.kill_switch_engaged:
            self.memory.log_event(
                "AUTONOMY_ENABLE_BLOCKED",
                "autonomy.settings",
                (
                    "Controlled Autonomy was not enabled because the "
                    "autonomy kill switch is engaged."
                ),
                payload={"changed_by": changed_by},
                outcome=ProcessOutcome.FAILED,
                confidence=1.0,
                promote=True,
            )
            return previous

        level = previous.level
        if not enabled:
            level = AutonomyLevel.MANUAL
        elif level is AutonomyLevel.MANUAL:
            level = AutonomyLevel.OBSERVE

        self._settings = AutonomySettings(
            enabled=enabled,
            level=level,
            kill_switch_engaged=previous.kill_switch_engaged,
            allow_autonomous_surface_scan=previous.allow_autonomous_surface_scan,
            allow_autonomous_deep_scan=previous.allow_autonomous_deep_scan,
            quiet_hours_start=previous.quiet_hours_start,
            quiet_hours_end=previous.quiet_hours_end,
            daily_surface_scan_budget=previous.daily_surface_scan_budget,
            surface_scan_cooldown_minutes=previous.surface_scan_cooldown_minutes,
        )
        self._save()
        self.memory.log_event(
            "AUTONOMY_ENABLED" if enabled else "AUTONOMY_DISABLED",
            "autonomy.settings",
            (
                "Controlled Autonomy was enabled."
                if enabled
                else "Controlled Autonomy was disabled. Operational decisions now route to the user."
            ),
            payload={
                "changed_by": changed_by,
                "previous_enabled": previous.enabled,
                "new_enabled": enabled,
                "level": self._settings.level.name,
            },
            outcome=ProcessOutcome.SUCCEEDED,
            confidence=1.0,
            promote=True,
        )
        return self._settings

    def engage_kill_switch(self, *, changed_by: str) -> AutonomySettings:
        previous = self._settings
        self._settings = AutonomySettings(
            enabled=False,
            level=AutonomyLevel.MANUAL,
            kill_switch_engaged=True,
            allow_autonomous_surface_scan=previous.allow_autonomous_surface_scan,
            allow_autonomous_deep_scan=False,
            quiet_hours_start=previous.quiet_hours_start,
            quiet_hours_end=previous.quiet_hours_end,
            daily_surface_scan_budget=previous.daily_surface_scan_budget,
            surface_scan_cooldown_minutes=previous.surface_scan_cooldown_minutes,
        )
        self._save()
        self.memory.log_event(
            "AUTONOMY_KILL_SWITCH_ENGAGED",
            "autonomy.settings",
            "The autonomy kill switch was engaged. All operational actions require the user.",
            payload={"changed_by": changed_by},
            outcome=ProcessOutcome.SUCCEEDED,
            promote=True,
        )
        return self._settings

    def release_kill_switch(self, *, changed_by: str) -> AutonomySettings:
        current = self._settings
        self._settings = AutonomySettings(
            enabled=False,
            level=AutonomyLevel.MANUAL,
            kill_switch_engaged=False,
            allow_autonomous_surface_scan=current.allow_autonomous_surface_scan,
            allow_autonomous_deep_scan=False,
            quiet_hours_start=current.quiet_hours_start,
            quiet_hours_end=current.quiet_hours_end,
            daily_surface_scan_budget=current.daily_surface_scan_budget,
            surface_scan_cooldown_minutes=current.surface_scan_cooldown_minutes,
        )
        self._save()
        self.memory.log_event(
            "AUTONOMY_KILL_SWITCH_RELEASED",
            "autonomy.settings",
            "The autonomy kill switch was released. Autonomy remains disabled until separately enabled.",
            payload={"changed_by": changed_by},
            outcome=ProcessOutcome.SUCCEEDED,
            promote=True,
        )
        return self._settings

    def evaluate(self, proposal: ActionProposal) -> PolicyDecision:
        decision = self.policy.evaluate(proposal, self._settings)
        self.memory.log_event(
            "AUTONOMY_DECISION",
            "autonomy.decision",
            decision.reason,
            payload={
                "proposal": {
                    "proposal_id": proposal.proposal_id,
                    "action_kind": proposal.action_kind.value,
                    "risk": proposal.risk.name,
                    "autonomous": proposal.autonomous,
                    "trigger": proposal.trigger,
                    "scope": proposal.scope,
                    "threat_severity": proposal.threat_severity,
                    "predicted_threat": proposal.predicted_threat,
                    "prediction_confidence": proposal.prediction_confidence,
                    "potential_impacts": list(proposal.potential_impacts),
                },
                "decision": {
                    "decision_id": decision.decision_id,
                    "disposition": decision.disposition.value,
                    "policy_version": decision.policy_version,
                    "requires_confirmation": decision.requires_confirmation,
                },
            },
            confidence=proposal.prediction_confidence,
            promote=True,
        )
        return decision

    def _load(self) -> AutonomySettings:
        payload = self.memory.get_preference(self._PREFERENCE_KEY, {})
        if not isinstance(payload, dict):
            return AutonomySettings()
        try:
            return AutonomySettings(
                enabled=bool(payload.get("enabled", False)),
                level=AutonomyLevel(int(payload.get("level", 0))),
                kill_switch_engaged=bool(
                    payload.get("kill_switch_engaged", False)
                ),
                allow_autonomous_surface_scan=bool(
                    payload.get("allow_autonomous_surface_scan", False)
                ),
                allow_autonomous_deep_scan=bool(
                    payload.get("allow_autonomous_deep_scan", False)
                ),
                quiet_hours_start=payload.get("quiet_hours_start"),
                quiet_hours_end=payload.get("quiet_hours_end"),
                daily_surface_scan_budget=int(
                    payload.get("daily_surface_scan_budget", 1)
                ),
                surface_scan_cooldown_minutes=int(
                    payload.get("surface_scan_cooldown_minutes", 360)
                ),
            )
        except (TypeError, ValueError):
            return AutonomySettings()

    def _save(self) -> None:
        payload = asdict(self._settings)
        payload["level"] = int(self._settings.level)
        self.memory.set_preference(self._PREFERENCE_KEY, payload)
