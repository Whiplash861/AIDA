from __future__ import annotations

from aida.intent.models import IntentDefinition, IntentRisk
from aida.intent.registry import IntentRegistry


def register_technomancer_intents(registry: IntentRegistry) -> IntentRegistry:
    """Register current native Technomancer fast paths with AIDA's intent layer.

    This platform-neutral copy lets standalone runtimes preserve native trigger
    semantics without importing the Windows-oriented Technomancer execution
    package onto a provider gateway. Keep synchronized with
    ``aida/technomancer/intents.py`` until the shared intent definitions are
    physically consolidated during the main branch integration.
    """

    definitions = (
        IntentDefinition(
            intent_id="technomancer.health",
            command_type="TECHNOMANCER_HEALTH",
            actions=frozenset({"check", "show", "assess", "review"}),
            objects=frozenset({"technomancer health", "machine health", "computer health", "system health"}),
            aliases=frozenset({"technomancer health", "check machine health", "how is my computer doing", "review system health"}),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="Technomancer longitudinal machine-health assessment",
            priority=135,
        ),
        IntentDefinition(
            intent_id="technomancer.hardware",
            command_type="TECHNOMANCER_HARDWARE",
            actions=frozenset({"show", "inspect", "identify", "list"}),
            objects=frozenset({"technomancer hardware", "hardware inventory", "machine hardware", "computer hardware"}),
            aliases=frozenset({"technomancer hardware", "show hardware inventory", "identify my hardware", "show my machine hardware"}),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="Technomancer hardware and compatibility inventory",
            priority=134,
        ),
        IntentDefinition(
            intent_id="technomancer.upgrades",
            command_type="TECHNOMANCER_UPGRADES",
            actions=frozenset({"assess", "review", "recommend", "check", "show"}),
            objects=frozenset({"technomancer upgrades", "hardware upgrades", "upgrade recommendations", "machine upgrades"}),
            aliases=frozenset({"technomancer upgrades", "what should i upgrade", "do i need more ram", "review hardware upgrades"}),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="evidence-based Technomancer upgrade-worthiness assessment",
            priority=136,
        ),
        IntentDefinition(
            intent_id="technomancer.advisories",
            command_type="TECHNOMANCER_ADVISORIES",
            actions=frozenset({"show", "review", "list", "check"}),
            objects=frozenset({"technomancer advisories", "machine advisories", "health advisories", "technomancer findings"}),
            aliases=frozenset({"technomancer advisories", "show technomancer findings", "review machine advisories"}),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="active mature Technomancer advisories",
            priority=133,
        ),
        IntentDefinition(
            intent_id="technomancer.background.enable",
            command_type="TECHNOMANCER_BACKGROUND_ENABLE",
            actions=frozenset({"enable", "start", "allow"}),
            objects=frozenset({"technomancer background monitoring", "technomancer monitoring"}),
            aliases=frozenset({"enable technomancer background monitoring", "start technomancer background monitoring", "allow technomancer monitoring"}),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="grant Technomancer background-observation scope",
            priority=142,
        ),
        IntentDefinition(
            intent_id="technomancer.background.disable",
            command_type="TECHNOMANCER_BACKGROUND_DISABLE",
            actions=frozenset({"disable", "stop", "revoke"}),
            objects=frozenset({"technomancer background monitoring", "technomancer monitoring"}),
            aliases=frozenset({"disable technomancer background monitoring", "stop technomancer background monitoring", "revoke technomancer monitoring"}),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="revoke Technomancer background-observation scope",
            priority=143,
        ),
    )
    for definition in definitions:
        registry.register(definition)
    return registry
