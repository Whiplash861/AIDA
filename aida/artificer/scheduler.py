from __future__ import annotations

import threading
import logging
from collections.abc import Callable


class ArtificerScheduler:
    def __init__(self, callback: Callable[[], None], interval_seconds: int) -> None:
        self.callback = callback
        self.interval_seconds = max(60, int(interval_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lifecycle_lock:
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
        with self._lifecycle_lock:
            self._stop_event.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        with self._lifecycle_lock:
            if self._thread is thread and thread is not None and not thread.is_alive():
                self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.callback()
            except Exception:
                logging.getLogger(__name__).exception("Artificer scheduled review failed")
