
from pathlib import Path
from aida.autonomy.controller import AutonomyController
from aida.autonomy.models import ActionKind, ActionProposal, ActionRisk, AutonomyLevel, PolicyDisposition
from aida.memory.database import MemoryDatabase
from aida.memory.service import MemoryService

def controller(tmp_path):
    memory=MemoryService(MemoryDatabase(tmp_path/"m.db"), user_id="Austin",device_id="PC")
    return AutonomyController(memory), memory

def proposal(kind, autonomous=True):
    return ActionProposal(action_kind=kind, reason="test", risk=ActionRisk.LOW, autonomous=autonomous)

def test_disabled_routes_operations_to_user(tmp_path):
    c,_=controller(tmp_path)
    d=c.evaluate(proposal(ActionKind.SURFACE_SCAN))
    assert d.disposition is PolicyDisposition.REQUIRE_USER

def test_observations_are_allowed_even_when_disabled(tmp_path):
    c,_=controller(tmp_path)
    assert c.evaluate(proposal(ActionKind.ALERT)).disposition is PolicyDisposition.ALLOW

def test_enabling_defaults_to_observe_not_action_authority(tmp_path):
    c,_=controller(tmp_path)
    s=c.set_enabled(True,changed_by="Austin")
    assert s.level is AutonomyLevel.OBSERVE
    assert c.evaluate(proposal(ActionKind.SURFACE_SCAN)).disposition is PolicyDisposition.REQUIRE_USER

def test_destructive_actions_denied(tmp_path):
    c,_=controller(tmp_path)
    assert c.evaluate(proposal(ActionKind.DELETE)).disposition is PolicyDisposition.DENY


from datetime import datetime, timezone, timedelta
from dataclasses import replace
from aida.autonomy.budgets import AutonomyBudgetGuard

def test_autonomous_budget_and_cooldown(tmp_path):
    c,memory=controller(tmp_path)
    c.set_enabled(True,changed_by="Austin")
    c._settings = replace(
        c.settings,
        level=AutonomyLevel.TRIAGE,
        allow_autonomous_surface_scan=True,
        daily_surface_scan_budget=1,
        surface_scan_cooldown_minutes=360,
    )
    c._save()
    guard=AutonomyBudgetGuard(memory)
    now=datetime.now(timezone.utc)
    assert guard.evaluate_surface_scan(c.settings,now=now).allowed is True
    guard.record_surface_scan_start(trigger="scheduled idle check",policy_version=c.policy.version)
    decision=guard.evaluate_surface_scan(c.settings,now=now+timedelta(minutes=1))
    assert decision.allowed is False

def test_kill_switch_blocks_reenabling(tmp_path):
    c, memory = controller(tmp_path)
    c.engage_kill_switch(changed_by="Austin")

    settings = c.set_enabled(True, changed_by="Austin")

    assert settings.enabled is False
    assert settings.kill_switch_engaged is True
    assert any(
        event.event_type == "AUTONOMY_ENABLE_BLOCKED"
        for event in memory.list_events()
    )
