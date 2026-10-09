from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional
from uuid import uuid4
import logging

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QThreadPool,
    Signal,
    Slot,
)


class TaskSignals(QObject):
    """
    Signals emitted by a task running in the thread pool.
    """

    result = Signal(object)
    error = Signal(str)
    finished = Signal(str)


class ManagedTask(QRunnable):
    """
    Executes one callable outside the main UI thread.
    """

    def __init__(
        self,
        name: str,
        function: Callable[[], Any],
    ) -> None:
        super().__init__()

        self.name = name
        self.function = function
        self.signals = TaskSignals()

        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.function()
            self.signals.result.emit(result)

        except Exception as exc:
            incident = uuid4().hex[:12]
            logging.getLogger(__name__).warning("Task failed [%s], category=%s", incident, type(exc).__name__)
            error_message = f"{type(exc).__name__}: operation unavailable (reference {incident})."
            self.signals.error.emit(error_message)

        finally:
            self.signals.finished.emit(self.name)

class TaskManager(QObject):
    """
    Central execution manager for AIDA's background operations.

    Tasks run through Qt's shared thread pool so the controller
    does not need to create or destroy QThread objects manually.
    """

    task_started = Signal(str)
    task_finished = Signal(str)
    task_failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()

        self._pool = QThreadPool.globalInstance()
        self._active_tasks: dict[str, ManagedTask] = {}
        self._failed_tasks: set[str] = set()
        self._closing = False

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
        """
        Starts a named background task.

        Returns False when another task with the same name
        is already running.
        """

        clean_name = name.strip()
        if self._closing:
            return False

        if not clean_name:
            raise ValueError("Task name cannot be empty")

        if self.is_running(clean_name):
            return False

        task = ManagedTask(
            name=clean_name,
            function=function,
        )

        def deliver_result(result: Any) -> None:
            if self._closing:
                return
            # Completion of a worker is not proof that its operation succeeded.
            if getattr(result, "successful", True) is False:
                self._handle_error(clean_name, "Operation ended without a verified successful result.")
            if on_result is not None:
                on_result(result)

        task.signals.result.connect(deliver_result)

        if on_error is not None:
            task.signals.error.connect(lambda message: on_error(message) if not self._closing else None)

        if on_finished is not None:
            task.signals.finished.connect(
                lambda _name: on_finished() if not self._closing else None
            )

        task.signals.error.connect(
            lambda message: self._handle_error(
                clean_name,
                message,
            )
        )

        task.signals.finished.connect(
            self._handle_finished
        )

        self._active_tasks[clean_name] = task
        self._failed_tasks.discard(clean_name)

        self.task_started.emit(clean_name)
        self._pool.start(task)

        return True

    @Slot(str, str)
    def _handle_error(
        self,
        task_name: str,
        message: str,
    ) -> None:
        if self._closing:
            return
        self._failed_tasks.add(task_name)
        self.task_failed.emit(
            task_name,
            message,
        )

    @Slot(str)
    def _handle_finished(self, task_name: str) -> None:
        self._active_tasks.pop(
            task_name,
            None,
        )

        if not self._closing:
            self.task_finished.emit(task_name)

    def failed(self, task_name: str) -> bool:
        return task_name in self._failed_tasks

    def close(self, timeout_ms: int = 5000) -> bool:
        self._closing = True
        for task in tuple(self._active_tasks.values()):
            # Detach UI callbacks even when a bounded external call is still
            # completing. The worker retains its own signals until it returns.
            task.signals.result.disconnect()
            task.signals.error.disconnect()
            task.signals.finished.disconnect()
        completed = self.wait_for_done(timeout_ms)
        self._active_tasks.clear()
        return completed

    def wait_for_done(
        self,
        timeout_ms: int = 5000,
    ) -> bool:
        """
        Waits briefly for active tasks during application shutdown.
        """

        return self._pool.waitForDone(timeout_ms)
