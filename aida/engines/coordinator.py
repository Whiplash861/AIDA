from __future__ import annotations

from aida.engines.base import AIDAEngine, EngineRequest, EngineResponse
from aida.engines.bus import EngineBus, EngineEvent


class EngineCoordinator:
    """Routes work between AIDA Engines while preserving conversational ownership by AIDA."""

    def __init__(self, bus: EngineBus | None = None) -> None:
        self.bus = bus or EngineBus()
        self._engines: dict[str, AIDAEngine] = {}
        self._foreground: str | None = None
        self._return_stack: list[str] = []

    @property
    def foreground_engine(self) -> str | None:
        return self._foreground

    def register(self, engine: AIDAEngine) -> None:
        self._engines[engine.descriptor.key] = engine

    def activate(self, engine_key: str) -> None:
        if engine_key not in self._engines:
            raise KeyError(f"Unknown engine: {engine_key}")
        self._foreground = engine_key
        self.bus.publish(EngineEvent("engine.foreground", "coordinator", {"engine": engine_key}))

    def execute(self, engine_key: str, request: EngineRequest, temporary: bool = False) -> EngineResponse:
        engine = self._engines.get(engine_key)
        if engine is None:
            raise KeyError(f"Unknown engine: {engine_key}")

        previous = self._foreground
        if temporary and previous and previous != engine_key:
            self._return_stack.append(previous)

        self.activate(engine_key)
        response = engine.handle(request)

        if temporary and response.return_to_previous and self._return_stack:
            self.activate(self._return_stack.pop())

        return response

    def handoff(self, engine_key: str, request: EngineRequest) -> EngineResponse:
        """Temporary cross-Engine excursion; the previous Engine resumes afterwards."""
        return self.execute(engine_key, request, temporary=True)
