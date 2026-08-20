
from __future__ import annotations

from aida.intent.models import IntentDefinition


class IntentRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, IntentDefinition] = {}

    def register(self, definition: IntentDefinition) -> None:
        if definition.intent_id in self._definitions:
            raise ValueError(f"Intent already registered: {definition.intent_id}")
        self._definitions[definition.intent_id] = definition

    def replace(self, definition: IntentDefinition) -> None:
        self._definitions[definition.intent_id] = definition

    def get(self, intent_id: str) -> IntentDefinition | None:
        return self._definitions.get(intent_id)

    def definitions(self) -> tuple[IntentDefinition, ...]:
        return tuple(
            sorted(
                self._definitions.values(),
                key=lambda item: (-item.priority, item.intent_id),
            )
        )
