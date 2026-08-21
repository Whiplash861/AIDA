from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    key: str
    name: str
    color: str
    domain: str


@dataclass(slots=True)
class EngineRequest:
    intent: str
    user_text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    source_engine: str | None = None


@dataclass(slots=True)
class EngineResponse:
    engine_key: str
    text: str
    evidence: list[str] = field(default_factory=list)
    return_to_previous: bool = True


class AIDAEngine(Protocol):
    descriptor: EngineDescriptor

    def handle(self, request: EngineRequest) -> EngineResponse:
        ...
