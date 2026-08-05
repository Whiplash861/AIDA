from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from aida.artificer.event_bus import EventBus
from aida.artificer.events import make_event
from aida.config import AidaConfig


class TaskSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    finished = Signal(str)


class ManagedTask(QRunnable):
    def __init__(self, name: str, function: Callable[[], Any]) -> None:
        super().__init__()
        self.name = name
        self.function = function
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            self.signals.result.emit(self.function())
        except Exception as exc:
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.signals.finished.emit(self.name)


class TaskManager(QObject):
    task_started = Signal(str)
    task_finished = Signal(str)
    task_failed = Signal(str, str)

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        config: AidaConfig | None = None,
    ) -> None:
        super().__init__()
        self._pool = QThreadPool.globalInstance()
        self._active_tasks: dict[str, ManagedTask] = {}
        self._operation_ids: dict[str, str] = {}
        self._started_at: dict[str, float] = {}
        self._failed: set[str] = set()
        self.event_bus = event_bus
        self.config = config

    @property
    def active_task_names(self) -> tuple[str, ...]:
        return tuple(self._active_tasks.keys())

    def is_running(self, name: str) -> bool:
        return name in self._active_tasks

    def run_task(
        self,
        name: str,
        function: Callable[[], Any],
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ) -> bool:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Task name cannot be empty")
        if self.is_running(clean_name):
            return False
        task = ManagedTask(name=clean_name, function=function)
        operation_id = str(uuid.uuid4())
        self._operation_ids[clean_name] = operation_id
        self._started_at[clean_name] = time.monotonic()
        self._failed.discard(clean_name)
        if on_result is not None:
            task.signals.result.connect(on_result)
        if on_error is not None:
            task.signals.error.connect(on_error)
        if on_finished is not None:
            task.signals.finished.connect(lambda _name: on_finished())
        task.signals.error.connect(
            lambda message: self._handle_error(clean_name, message)
        )
        task.signals.finished.connect(self._handle_finished)
        self._active_tasks[clean_name] = task
        self._publish(
            clean_name,
            "task_started",
            "started",
            operation_id=operation_id,
        )
        self.task_started.emit(clean_name)
        self._pool.start(task)
        return True

    @Slot(str, str)
    def _handle_error(self, task_name: str, message: str) -> None:
        self._failed.add(task_name)
        operation_id = self._operation_ids.get(task_name)
        duration = self._duration_ms(task_name)
        self._publish(
            task_name,
            "task_failed",
            "failed",
            operation_id=operation_id,
            duration_ms=duration,
            error_category=message.split(":", 1)[0],
            metadata={"error": message},
        )
        self.task_failed.emit(task_name, message)

    @Slot(str)
    def _handle_finished(self, task_name: str) -> None:
        operation_id = self._operation_ids.pop(task_name, None)
        duration = self._duration_ms(task_name)
        self._started_at.pop(task_name, None)
        failed = task_name in self._failed
        self._failed.discard(task_name)
        self._active_tasks.pop(task_name, None)
        self._publish(
            task_name,
            "task_finished",
            "failed" if failed else "completed",
            operation_id=operation_id,
            duration_ms=duration,
        )
        self.task_finished.emit(task_name)

    def _duration_ms(self, task_name: str) -> float | None:
        started = self._started_at.get(task_name)
        return None if started is None else (time.monotonic() - started) * 1000.0

    def _publish(
        self,
        task_name: str,
        event_type: str,
        status: str,
        *,
        operation_id: str | None,
        duration_ms: float | None = None,
        error_category: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self.event_bus is None or self.config is None:
            return
        self.event_bus.publish(
            make_event(
                source=f"task.{task_name}",
                event_type=event_type,
                status=status,
                aida_version=self.config.version,
                operation_id=operation_id,
                task_name=task_name,
                duration_ms=duration_ms,
                error_category=error_category,
                metadata=metadata or {},
            )
        )

    def wait_for_done(self, timeout_ms: int = 5000) -> bool:
        return self._pool.waitForDone(timeout_ms)
