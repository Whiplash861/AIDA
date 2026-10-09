from __future__ import annotations

from aida.engines.base import AIDAEngine, EngineRequest, EngineResponse
from aida.engines.bus import EngineBus, EngineEvent
from threading import RLock


class EngineCoordinator:
    """Routes work between AIDA Engines while preserving conversational ownership by AIDA."""

    def __init__(self, bus: EngineBus | None = None) -> None:
        self.bus = bus or EngineBus()
        self._engines: dict[str, AIDAEngine] = {}
        self._foreground: str | None = None
        self._return_stack: list[str] = []
        self._execution_lock = RLock()

    @property
    def foreground_engine(self) -> str | None:
        with self._execution_lock:
            return self._foreground

    def register(self, engine: AIDAEngine) -> None:
        with self._execution_lock:
            self._engines[engine.descriptor.key] = engine

    def activate(self, engine_key: str) -> None:
        with self._execution_lock:
            if engine_key not in self._engines:
                raise KeyError(f"Unknown engine: {engine_key}")
            self._foreground = engine_key
            self.bus.publish(EngineEvent("engine.foreground", "coordinator", {"engine": engine_key}))

    def execute(self, engine_key: str, request: EngineRequest, temporary: bool = False) -> EngineResponse:
        with self._execution_lock:
            return self._execute(engine_key, request, temporary)

    def _execute(self, engine_key: str, request: EngineRequest, temporary: bool) -> EngineResponse:
        engine = self._engines.get(engine_key)
        if engine is None:
            raise KeyError(f"Unknown engine: {engine_key}")

        previous = self._foreground
        if temporary and previous and previous != engine_key:
            self._return_stack.append(previous)

        self.activate(engine_key)
        restore = temporary
        try:
            response = engine.handle(request)
            restore = temporary and response.return_to_previous
            return response
        finally:
            if temporary and previous and previous != engine_key:
                self._return_stack.pop()
                if restore:
                    self.activate(previous)

    def handoff(self, engine_key: str, request: EngineRequest) -> EngineResponse:
        """Temporary cross-Engine excursion; the previous Engine resumes afterwards."""
        return self.execute(engine_key, request, temporary=True)
