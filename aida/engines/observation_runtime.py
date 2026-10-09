from __future__ import annotations

import logging
from threading import RLock
from aida.autonomy.models import AutonomyLevel


class ObservationRuntime:
    """Reconcile existing background readers with consent and shutdown.

    Only an explicit apply can construct an engine. Periodic reconciliation
    retries desired starts after an older observer drains, never construction.
    """

    def __init__(self, factory):
        self._factory = factory
        self._engine = None
        self._lock = RLock()
        self._closed = False
        self._desired_enabled = False
        self._initializing = False
        self._initialization_failed = False
        self._stop_pending = set()
        self._stopped = set()
        self._last_error = None

    def apply(self, settings) -> None:
        allowed = (settings.enabled is True and settings.kill_switch_engaged is False
                   and settings.level >= AutonomyLevel.OBSERVE)
        with self._lock:
            if self._closed:
                return
            if not allowed:
                # A subsequent explicit enable may retry a repaired configuration.
                self._initialization_failed = False
            self._desired_enabled = allowed
            initialize = (allowed and self._engine is None and not self._initializing
                          and not self._initialization_failed)
            if initialize:
                self._initializing = True
        if initialize:
            # Construction may read persistent state. Revocation and close must
            # be able to update the desired state while it is in progress.
            try:
                engine = self._factory()
            except Exception:
                with self._lock:
                    self._initializing = False
                    self._initialization_failed = True
                raise
            with self._lock:
                self._engine = engine
                self._initializing = False
        self.reconcile()

    @staticmethod
    def _running(observer) -> bool:
        return bool(getattr(observer, "running", False))

    def _stop(self, observer, *, timeout=0) -> None:
        identity = id(observer)
        running = self._running(observer)
        if identity in self._stopped and not running:
            return
        if identity in self._stop_pending and running and timeout == 0:
            return
        observer.stop(timeout=timeout)
        if self._running(observer):
            self._stop_pending.add(identity)
        else:
            self._stop_pending.discard(identity)
            self._stopped.add(identity)

    def reconcile(self) -> None:
        """Nonblocking lifecycle retry for an already-created engine only."""
        with self._lock:
            if self._engine is None:
                return
            engine = self._engine
            observers = (engine, engine.remote_monitor)
            errors = []
            for observer in observers:
                allowed = (not self._closed and self._desired_enabled
                           and getattr(engine, "enabled", True) is True)
                try:
                    if not allowed or getattr(observer, "enabled", True) is not True:
                        self._stop(observer)
                        continue
                    identity = id(observer)
                    if identity in self._stop_pending:
                        if self._running(observer):
                            continue
                        self._stop(observer)  # Finalize a drained shutdown once.
                    if not self._running(observer):
                        observer.start()
                        self._stopped.discard(identity)
                except Exception as exc:
                    errors.append(type(exc).__name__)
                    # A partially started observer must still receive revocation.
                    try:
                        self._stop(observer)
                    except Exception:
                        pass
            error = tuple(errors) or None
            if error and error != self._last_error:
                logging.getLogger(__name__).warning("Observation lifecycle reconciliation failed: %s", ", ".join(error))
            self._last_error = error

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._desired_enabled = False
            if self._engine is not None:
                for observer in (self._engine, self._engine.remote_monitor):
                    try:
                        self._stop(observer, timeout=2)
                    except Exception as exc:
                        logging.getLogger(__name__).warning("Observation shutdown failed: %s", type(exc).__name__)
