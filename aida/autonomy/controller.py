
from __future__ import annotations

from dataclasses import asdict
from typing import Callable
import logging
from functools import wraps
from threading import RLock

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


def _serialized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        notifications = ()
        try:
            with self._settings_lock:
                self._notification_depth += 1
                try:
                    return method(self, *args, **kwargs)
                finally:
                    self._notification_depth -= 1
                    if self._notification_depth == 0:
                        notifications = tuple(self._pending_notifications)
                        self._pending_notifications.clear()
        finally:
            # A lifecycle listener may initialize an Engine. Never keep the
            # settings lock while it runs: another caller must be able to revoke.
            for settings in notifications:
                self._notify(settings)
    return run


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
        self._settings_lock = RLock()
        self._notification_depth = 0
        self._pending_notifications = []
        self._settings = self._load()
        self._committed_settings = self._settings
        self._listeners: list[Callable[[AutonomySettings], None]] = []

    @_serialized
    def subscribe(self, callback: Callable[[AutonomySettings], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    @_serialized
    def unsubscribe(self, callback: Callable[[AutonomySettings], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    @property
    def settings(self) -> AutonomySettings:
        with self._settings_lock:
            return self._settings

    @_serialized
    def set_enabled(self, enabled: bool, *, changed_by: str) -> AutonomySettings:
        if not isinstance(enabled, bool):
            raise ValueError("Autonomy enablement requires a Boolean")
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

        candidate = AutonomySettings(
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
        self._save(candidate)
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

    @_serialized
    def engage_kill_switch(self, *, changed_by: str) -> AutonomySettings:
        previous = self._settings
        candidate = AutonomySettings(
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
        self._save(candidate)
        self.memory.log_event(
            "AUTONOMY_KILL_SWITCH_ENGAGED",
            "autonomy.settings",
            "The autonomy kill switch was engaged. All operational actions require the user.",
            payload={"changed_by": changed_by},
            outcome=ProcessOutcome.SUCCEEDED,
            promote=True,
        )
        return self._settings

    @_serialized
    def release_kill_switch(self, *, changed_by: str) -> AutonomySettings:
        current = self._settings
        candidate = AutonomySettings(
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
        self._save(candidate)
        self.memory.log_event(
            "AUTONOMY_KILL_SWITCH_RELEASED",
            "autonomy.settings",
            "The autonomy kill switch was released. Autonomy remains disabled until separately enabled.",
            payload={"changed_by": changed_by},
            outcome=ProcessOutcome.SUCCEEDED,
            promote=True,
        )
        return self._settings

    @_serialized
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
        if any(key in payload and not isinstance(payload[key], bool) for key in (
            "enabled", "kill_switch_engaged", "allow_autonomous_surface_scan", "allow_autonomous_deep_scan",
        )):
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

    @_serialized
    def _save(self, candidate: AutonomySettings | None = None) -> None:
        candidate = candidate or self._settings
        payload = asdict(candidate)
        payload["level"] = int(candidate.level)
        try:
            self.memory.set_preference(self._PREFERENCE_KEY, payload)
        except Exception:
            # Also protects legacy callers that directly prepared _settings.
            self._settings = self._committed_settings
            raise
        self._settings = candidate
        self._committed_settings = candidate
        self._pending_notifications.append(candidate)

    def _notify(self, settings: AutonomySettings) -> None:
        with self._settings_lock:
            if settings is not self._settings:
                return  # A newer committed setting superseded this notification.
            listeners = tuple(self._listeners)
        for callback in listeners:
            try:
                with self._settings_lock:
                    current = self._settings
                callback(current)
            except Exception:
                logging.getLogger(__name__).warning("An autonomy lifecycle listener failed")
