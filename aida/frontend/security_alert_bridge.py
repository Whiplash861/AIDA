"""Deliver durable local alerts without querying providers on the Qt thread."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot


class SecurityAlertBridge(QObject):
    alerts_ready = Signal(object)

    def __init__(self, service_reader, history, *, parent=None, interval=3.0):
        super().__init__(parent)
        self.service_reader, self.history = service_reader, history
        self.interval = max(1.0, interval)
        self._stop = threading.Event()
        self._shown: set[str] = set()
        self._thread = None
        self.alerts_ready.connect(self.deliver)

    def start(self):
        if self._thread is not None or self._stop.is_set():
            return
        self._thread = threading.Thread(target=self._run, name="AIDA-Alert-Delivery", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                service = self.service_reader()
                if service is not None:
                    alerts = service.list_alerts(limit=100)
                    if not self._stop.is_set():
                        self.alerts_ready.emit(alerts)
            except Exception as exc:
                logging.getLogger(__name__).debug("Alert inbox unavailable: %s", type(exc).__name__)
            self._stop.wait(self.interval)

    @Slot(object)
    def deliver(self, alerts):
        if self._stop.is_set():
            return
        for alert in alerts:
            if alert.alert_id in self._shown or alert.acknowledged_at or alert.ended_at:
                continue
            self.history.add_system(
                f"SECURITY ALERT | {alert.severity.upper()}\n{alert.message}\n"
                f"Observed: {alert.created_at}\nReview: show investigation {alert.case_id}\n"
                f"Acknowledge: acknowledge alert {alert.alert_id}\n"
                "Review the case's evidence freshness and visibility limitations before choosing a response.",
                include_in_context=False,
            )
            self._shown.add(alert.alert_id)
        # Bound session deduplication; the durable acknowledgement remains in SQLite.
        if len(self._shown) > 2000:
            self._shown.intersection_update(a.alert_id for a in alerts)

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.1)
