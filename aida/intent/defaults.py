from __future__ import annotations

from aida.intent.models import IntentDefinition, IntentRisk
from aida.intent.registry import IntentRegistry


_START = frozenset(
    {"run", "start", "perform", "initiate", "begin", "launch", "execute", "do"}
)
_SCAN_OBJECTS = frozenset(
    {"scan", "security scan", "malware scan", "antivirus scan", "anti virus scan"}
)


def build_default_intent_registry() -> IntentRegistry:
    registry = IntentRegistry()

    definitions = (
        IntentDefinition(
            intent_id="security.status",
            command_type="SECURITY_STATUS",
            actions=frozenset({"check", "show", "read", "report"}),
            objects=frozenset(
                {
                    "antivirus status",
                    "anti virus status",
                    "defender status",
                    "security provider status",
                }
            ),
            aliases=frozenset({"antivirus status", "defender status"}),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="an antivirus status check",
            priority=90,
        ),
        IntentDefinition(
            intent_id="security.scan.full",
            command_type="SECURITY_FULL_SWEEP",
            actions=_START,
            objects=_SCAN_OBJECTS | frozenset({"sweep"}),
            modifiers=frozenset(
                {
                    "full",
                    "full system",
                    "complete",
                    "comprehensive",
                    "entire computer",
                    "whole machine",
                    "all drives",
                }
            ),
            aliases=frozenset(
                {
                    "full system sweep",
                    "full-system sweep",
                    "complete system scan",
                }
            ),
            negative_terms=frozenset({"surface", "low level", "deep", "targeted"}),
            risk=IntentRisk.HIGH_IMPACT,
            local_only=True,
            description="a Full-System Security Sweep",
            priority=100,
        ),
        IntentDefinition(
            intent_id="security.scan.deep",
            command_type="SECURITY_DEEP_SCAN",
            actions=_START,
            objects=_SCAN_OBJECTS | frozenset({"file scan", "folder scan", "path scan"}),
            modifiers=frozenset(
                {
                    "deep",
                    "deeply",
                    "deep level",
                    "targeted",
                    "specific file",
                    "specific folder",
                    "specific path",
                }
            ),
            aliases=frozenset({"deep scan", "targeted security scan"}),
            negative_terms=frozenset({"full system", "surface", "low level"}),
            required_slots=("target_path",),
            risk=IntentRisk.ELEVATED,
            local_only=True,
            description="a targeted Deep Security Scan",
            priority=95,
        ),
        IntentDefinition(
            intent_id="security.scan.surface",
            command_type="SECURITY_SURFACE_SCAN",
            actions=_START,
            objects=_SCAN_OBJECTS,
            modifiers=frozenset(
                {
                    "surface",
                    "surface level",
                    "low level",
                    "light",
                    "basic",
                    "preliminary",
                    "quick malware",
                    "quick security",
                }
            ),
            aliases=frozenset(
                {
                    "surface scan",
                    "surface level scan",
                    "surface-level scan",
                    "low level scan",
                    "light security scan",
                    "basic malware scan",
                    "quick malware scan",
                    "quick security scan",
                }
            ),
            negative_terms=frozenset(
                {"full", "complete system", "deep", "targeted", "folder", "file path"}
            ),
            risk=IntentRisk.LOW_OPERATIONAL,
            local_only=True,
            description="a Surface-Level Security Scan",
            priority=94,
        ),
        IntentDefinition(
            intent_id="security.scan.cancel.confirm",
            command_type="SECURITY_CANCEL_CONFIRM",
            aliases=frozenset({"confirm scan cancellation"}),
            risk=IntentRisk.HIGH_IMPACT,
            local_only=True,
            description="confirmation to cancel the active security scan",
            priority=130,
        ),
        IntentDefinition(
            intent_id="security.scan.cancel",
            command_type="SECURITY_CANCEL_REQUEST",
            actions=frozenset({"cancel", "stop", "terminate"}),
            objects=frozenset(
                {
                    "scan",
                    "security scan",
                    "full sweep",
                    "full system sweep",
                    "surface scan",
                }
            ),
            aliases=frozenset(
                {
                    "cancel the scan",
                    "stop the scan",
                    "stop the full sweep",
                    "cancel full system sweep",
                }
            ),
            risk=IntentRisk.HIGH_IMPACT,
            local_only=True,
            description="a request to cancel the active security scan",
            priority=120,
        ),
        IntentDefinition(
            intent_id="diagnostics.performance",
            command_type="PERFORMANCE_SCAN",
            actions=_START | frozenset({"check", "analyze"}),
            objects=frozenset(
                {"performance scan", "system performance", "performance"}
            ),
            aliases=frozenset({"performance scan", "scan system performance"}),
            risk=IntentRisk.LOW_OPERATIONAL,
            description="a system performance scan",
            priority=80,
        ),
        IntentDefinition(
            intent_id="diagnostics.quickscan",
            command_type="QUICKSCAN",
            actions=_START,
            objects=frozenset(
                {
                    "quickscan",
                    "quick scan",
                    "system health scan",
                    "diagnostic scan",
                }
            ),
            modifiers=frozenset({"system health", "diagnostic", "quick diagnostic"}),
            aliases=frozenset({"quickscan", "quick scan", "quick diagnostic scan"}),
            negative_terms=frozenset(
                {"malware", "antivirus", "security", "defender", "full system"}
            ),
            risk=IntentRisk.LOW_OPERATIONAL,
            description="AIDA's diagnostic Quickscan",
            priority=70,
        ),
        IntentDefinition(
            intent_id="autonomy.enable",
            command_type="AUTONOMY_ENABLE",
            actions=frozenset({"enable", "turn on", "activate"}),
            objects=frozenset({"autonomy", "autonomous mode"}),
            aliases=frozenset({"enable autonomy", "turn on autonomy"}),
            risk=IntentRisk.HIGH_IMPACT,
            local_only=True,
            description="enabling Controlled Autonomy",
            priority=110,
        ),
        IntentDefinition(
            intent_id="autonomy.disable",
            command_type="AUTONOMY_DISABLE",
            actions=frozenset({"disable", "turn off", "deactivate"}),
            objects=frozenset({"autonomy", "autonomous mode"}),
            aliases=frozenset(
                {"disable autonomy", "turn off autonomy", "manual control"}
            ),
            risk=IntentRisk.LOW_OPERATIONAL,
            local_only=True,
            description="disabling autonomy and returning to manual control",
            priority=111,
        ),
        IntentDefinition(
            intent_id="autonomy.status",
            command_type="AUTONOMY_STATUS",
            actions=frozenset({"show", "check", "report"}),
            objects=frozenset({"autonomy status", "autonomous mode status"}),
            aliases=frozenset({"autonomy status"}),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="the current autonomy status",
            priority=90,
        ),
        IntentDefinition(
            intent_id="autonomy.observe.security",
            command_type="AUTONOMY_OBSERVE_SECURITY",
            actions=frozenset({"observe", "inspect", "check", "run", "perform"}),
            objects=frozenset(
                {
                    "security posture",
                    "observation check",
                    "security observation",
                    "autonomy observation",
                }
            ),
            aliases=frozenset(
                {
                    "run observation check",
                    "observe security posture",
                    "run security observation",
                    "autonomy observation",
                    "observation mode check",
                }
            ),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="a read-only Observation-mode security posture check",
            priority=105,
        ),
        IntentDefinition(
            intent_id="memory.show",
            command_type="MEMORY_SHOW",
            actions=frozenset({"show", "open", "list", "display"}),
            objects=frozenset({"memory", "memories", "memory bank"}),
            aliases=frozenset(
                {"show memory bank", "open memory bank", "list memories"}
            ),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="the AIDA Memory Bank",
            priority=90,
        ),
        IntentDefinition(
            intent_id="memory.search",
            command_type="MEMORY_SEARCH",
            actions=frozenset({"search", "find", "look up"}),
            objects=frozenset({"memory", "memories", "memory bank"}),
            aliases=frozenset({"search memory for", "find memories about"}),
            required_slots=("query",),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="a Memory Bank search",
            priority=95,
        ),
        IntentDefinition(
            intent_id="memory.add",
            command_type="MEMORY_ADD",
            actions=frozenset({"remember", "save", "add"}),
            objects=frozenset({"memory", "remember"}),
            aliases=frozenset({"remember that", "add memory", "save memory"}),
            required_slots=("memory_text",),
            risk=IntentRisk.LOW_OPERATIONAL,
            local_only=True,
            description="adding a user memory",
            priority=96,
        ),
        IntentDefinition(
            intent_id="memory.delete",
            command_type="MEMORY_DELETE",
            actions=frozenset({"delete", "forget", "remove"}),
            objects=frozenset({"memory", "memory item"}),
            aliases=frozenset({"delete memory", "forget memory"}),
            required_slots=("memory_id",),
            risk=IntentRisk.HIGH_IMPACT,
            local_only=True,
            description="removing a Memory Bank item",
            priority=98,
        ),
        IntentDefinition(
            intent_id="memory.revise",
            command_type="MEMORY_REVISE",
            actions=frozenset({"revise", "correct", "edit", "update"}),
            objects=frozenset({"memory", "memory item"}),
            aliases=frozenset({"revise memory", "correct memory", "edit memory"}),
            required_slots=("memory_id", "revision_text"),
            risk=IntentRisk.ELEVATED,
            local_only=True,
            description="revising a Memory Bank item",
            priority=98,
        ),
        IntentDefinition(
            intent_id="security.stand_down.revoke.confirm",
            command_type="STAND_DOWN_REVOKE_CONFIRM",
            aliases=frozenset({"confirm stand down revocation"}),
            risk=IntentRisk.HIGH_IMPACT,
            local_only=True,
            description="confirmation to revoke the pending Stand Down exception",
            priority=133,
        ),
        IntentDefinition(
            intent_id="security.stand_down.revoke",
            command_type="STAND_DOWN_REVOKE_REQUEST",
            actions=frozenset({"revoke", "remove", "cancel", "end"}),
            objects=frozenset(
                {"stand down", "trust exception", "trusted item", "user trust"}
            ),
            aliases=frozenset(
                {
                    "revoke stand down",
                    "remove stand down",
                    "revoke trust exception",
                    "end stand down",
                }
            ),
            required_slots=("target_path",),
            risk=IntentRisk.ELEVATED,
            local_only=True,
            description="revoking an AIDA-local Stand Down trust exception",
            priority=117,
        ),
        IntentDefinition(
            intent_id="security.stand_down.confirm",
            command_type="STAND_DOWN_CONFIRM",
            aliases=frozenset({"confirm stand down"}),
            risk=IntentRisk.HIGH_IMPACT,
            local_only=True,
            description="confirmation to create the pending Stand Down exception",
            priority=131,
        ),
        IntentDefinition(
            intent_id="security.stand_down.create",
            command_type="STAND_DOWN_REQUEST",
            actions=frozenset({"stand down", "trust", "retain"}),
            objects=frozenset({"file", "program", "application", "item"}),
            aliases=frozenset({"stand down on", "mark as user trusted"}),
            required_slots=("target_path",),
            risk=IntentRisk.HIGH_IMPACT,
            local_only=True,
            description="creating a user-authorized Stand Down exception",
            priority=115,
        ),
        IntentDefinition(
            intent_id="security.stand_down.list",
            command_type="STAND_DOWN_LIST",
            actions=frozenset({"show", "list", "report"}),
            objects=frozenset({"stand down", "trusted items", "trust exceptions"}),
            aliases=frozenset({"list stand down items", "show trusted items"}),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="the active Stand Down register",
            priority=100,
        ),
        IntentDefinition(
            intent_id="application.repair.plan",
            command_type="APPLICATION_REPAIR_PLAN",
            actions=frozenset({"repair", "fix", "restore"}),
            objects=frozenset(
                {"application", "program", "outlook", "chrome", "edge"}
            ),
            aliases=frozenset(
                {"repair outlook", "repair application", "fix program"}
            ),
            required_slots=("application_name",),
            risk=IntentRisk.ELEVATED,
            local_only=True,
            description="an application repair plan",
            priority=84,
        ),
        IntentDefinition(
            intent_id="application.cache.plan",
            command_type="APPLICATION_CACHE_PLAN",
            actions=frozenset({"clear", "clean", "reset"}),
            objects=frozenset({"cache", "application cache", "browser cache"}),
            aliases=frozenset(
                {"clear outlook cache", "clear chrome cache", "clear edge cache"}
            ),
            required_slots=("application_name",),
            risk=IntentRisk.ELEVATED,
            local_only=True,
            description="an application-specific cache recovery plan",
            priority=86,
        ),
        IntentDefinition(
            intent_id="application.restart.plan",
            command_type="APPLICATION_RESTART_PLAN",
            actions=frozenset({"restart", "close and reopen"}),
            objects=frozenset(
                {"application", "program", "outlook", "chrome", "edge"}
            ),
            aliases=frozenset(
                {"restart outlook", "restart chrome", "restart edge"}
            ),
            required_slots=("application_name",),
            risk=IntentRisk.ELEVATED,
            local_only=True,
            description="a graceful application restart plan",
            priority=85,
        ),
        IntentDefinition(
            intent_id="application.health.inspect",
            command_type="APPLICATION_HEALTH",
            actions=frozenset({"inspect", "check", "diagnose", "analyze"}),
            objects=frozenset(
                {"application", "program", "outlook", "chrome", "edge"}
            ),
            aliases=frozenset(
                {"check application health", "diagnose outlook", "inspect chrome"}
            ),
            required_slots=("application_name",),
            risk=IntentRisk.INFORMATIONAL,
            local_only=True,
            description="an application health inspection",
            priority=75,
        ),
    )

    for definition in definitions:
        registry.register(definition)
    return registry
