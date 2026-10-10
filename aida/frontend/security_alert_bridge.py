"""Deliver durable local alerts without querying providers on the Qt thread."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot
from aida.investigations.presentation import load_alert_context, render_alert


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
                        self.alerts_ready.emit([(alert, None if alert.alert_id in self._shown else load_alert_context(service, alert))
                                               for alert in alerts])
            except Exception as exc:
                logging.getLogger(__name__).debug("Alert inbox unavailable: %s", type(exc).__name__)
            self._stop.wait(self.interval)

    @Slot(object)
    def deliver(self, alerts):
        if self._stop.is_set():
            return
        for entry in alerts:
            alert, context = entry if isinstance(entry, tuple) else (entry, None)
            if alert.alert_id in self._shown or alert.acknowledged_at or alert.ended_at:
                continue
            self.history.add_system(
                render_alert(alert, context) + "\n\n"
                f"View case: show investigation {alert.case_id}\n"
                f"Mark as read: acknowledge alert {alert.alert_id}",
                include_in_context=False,
            )
            self._shown.add(alert.alert_id)
        # Bound session deduplication; the durable acknowledgement remains in SQLite.
        if len(self._shown) > 2000:
            self._shown.intersection_update((entry[0] if isinstance(entry, tuple) else entry).alert_id for entry in alerts)

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.1)
