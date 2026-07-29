
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from aida.intent.defaults import build_default_intent_registry
from aida.intent.models import IntentContext
from aida.intent.resolver import IntentResolver


class CommandType(Enum):
    QUICKSCAN = auto()
    PERFORMANCE_SCAN = auto()
    SECURITY_STATUS = auto()
    SECURITY_SURFACE_SCAN = auto()
    SECURITY_DEEP_SCAN = auto()
    SECURITY_FULL_SWEEP = auto()
    SECURITY_CANCEL_REQUEST = auto()
    SECURITY_CANCEL_CONFIRM = auto()
    AUTONOMY_ENABLE = auto()
    AUTONOMY_DISABLE = auto()
    AUTONOMY_STATUS = auto()
    MEMORY_SHOW = auto()
    MEMORY_SEARCH = auto()
    MEMORY_ADD = auto()
    MEMORY_DELETE = auto()
    MEMORY_REVISE = auto()
    STAND_DOWN_REQUEST = auto()
    STAND_DOWN_CONFIRM = auto()
    STAND_DOWN_LIST = auto()
    APPLICATION_HEALTH = auto()
    APPLICATION_REPAIR_PLAN = auto()
    APPLICATION_CACHE_PLAN = auto()
    APPLICATION_RESTART_PLAN = auto()
    INTENT_CLARIFICATION = auto()


@dataclass(frozen=True, slots=True)
class RoutedCommand:
    command_type: CommandType
    original_text: str
    target_path: str | None = None
    local_only: bool = False
    intent_id: str | None = None
    confidence: float | None = None
    requires_confirmation: bool = False
    slots: dict[str, Any] = field(default_factory=dict)
    clarification_text: str = ""
    user_initiated: bool = True


class CommandRouter:
    """Routes speech or typed language through AIDA's local intent resolver."""

    _CONTROL_COMMANDS = frozenset(
        {
            CommandType.SECURITY_CANCEL_REQUEST,
            CommandType.SECURITY_CANCEL_CONFIRM,
            CommandType.AUTONOMY_DISABLE,
            CommandType.AUTONOMY_STATUS,
        }
    )

    def __init__(self, resolver: IntentResolver | None = None) -> None:
        self.resolver = resolver or IntentResolver(
            build_default_intent_registry()
        )
        self._context = IntentContext()

    @property
    def context(self) -> IntentContext:
        return self._context

    def set_context(self, context: IntentContext) -> None:
        self._context = context

    def set_active_task(self, task_name: str | None) -> None:
        self._context = IntentContext(
            last_intent_id=self._context.last_intent_id,
            current_domain=self._context.current_domain,
            last_path=self._context.last_path,
            active_task=task_name,
            pending_confirmation_id=self._context.pending_confirmation_id,
            pending_confirmation_action=self._context.pending_confirmation_action,
            extra=self._context.extra,
        )

    def route(self, text: str) -> RoutedCommand | None:
        resolution = self.resolver.resolve(text, self._context)
        if resolution.resolved is None:
            if resolution.clarification:
                return RoutedCommand(
                    command_type=CommandType.INTENT_CLARIFICATION,
                    original_text=text,
                    local_only=any(
                        candidate.definition.local_only
                        for candidate in resolution.candidates
                    ),
                    clarification_text=resolution.clarification,
                )
            return None

        resolved = resolution.resolved
        try:
            command_type = CommandType[resolved.command_type]
        except KeyError:
            return None

        target_path = resolved.slots.get("target_path")
        self._context = IntentContext(
            last_intent_id=resolved.intent_id,
            current_domain=resolved.intent_id.split(".", 1)[0],
            last_path=(
                str(target_path)
                if target_path
                else self._context.last_path
            ),
            active_task=self._context.active_task,
            pending_confirmation_id=self._context.pending_confirmation_id,
            pending_confirmation_action=(
                self._context.pending_confirmation_action
            ),
            extra=self._context.extra,
        )
        return RoutedCommand(
            command_type=command_type,
            original_text=text,
            target_path=str(target_path) if target_path else None,
            local_only=resolved.local_only,
            intent_id=resolved.intent_id,
            confidence=resolved.confidence,
            requires_confirmation=resolved.requires_confirmation,
            slots=resolved.slots,
        )

    def is_control_command(self, command: RoutedCommand) -> bool:
        return command.command_type in self._CONTROL_COMMANDS
