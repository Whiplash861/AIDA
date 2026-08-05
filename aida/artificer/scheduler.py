from __future__ import annotations

import threading
from collections.abc import Callable


class ArtificerScheduler:
    def __init__(self, callback: Callable[[], None], interval_seconds: int) -> None:
        self.callback = callback
        self.interval_seconds = max(60, int(interval_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="AIDA-Artificer-Scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.callback()
            except Exception:
                continue
