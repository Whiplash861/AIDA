from __future__ import annotations

from PySide6.QtCore import Qt

from aida.frontend.internal_orb import OrbTroubleCode, OrbVisualState
from aida.frontend.overlay import AIDAOverlay
from aida.frontend.status import AIDAStatus
from aida.frontend.status_orb import AIDAStatusOrb


class AIDALiveOverlay(AIDAStatusOrb):
    """Detached live-state proxy for AIDA while the main frontend is minimized.

    The detached orb deliberately reuses ``AIDAStatusOrb`` so its palette,
    transition pulse, RED ring scheduler, RED core profiles, and Artificer state
    remain identical to the embedded header orb. This subclass restores the
    original overlay's top-level window, click/drag, reveal, and visibility
    behavior around that shared visual-state engine.
    """

    def __init__(self, diameter: int = 120) -> None:
        super().__init__(parent=None)

        safe_diameter = max(80, int(diameter))
        self._orb_diameter = safe_diameter
        self._internal_scale = safe_diameter / 120.0
        self._canvas_margin = max(28, int(round(safe_diameter * 0.233)))
        canvas = safe_diameter + self._canvas_margin * 2
        self.setFixedSize(canvas, canvas)

        self.setParent(None)
        self.setWindowTitle("AIDA Status")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_external_tooltip()

    def _sync_visibility(self) -> None:
        """Restore the detached overlay's minimize/restore visibility contract."""
        AIDAOverlay._sync_visibility(self)

    def _refresh_external_tooltip(self) -> None:
        self.setToolTip(
            f"AIDA: {self.current_live_status_text()} • "
            "Click to open AIDA • Right-drag to move"
        )

    def set_status(self, status: AIDAStatus) -> None:
        super().set_status(status)
        self._refresh_external_tooltip()

    def set_active_task_count(self, count: int) -> None:
        super().set_active_task_count(count)
        self._refresh_external_tooltip()

    def set_artificer_status(self, text: str) -> None:
        super().set_artificer_status(text)
        self._refresh_external_tooltip()

    def report_task_started(self, task_name: str) -> None:
        super().report_task_started(task_name)
        self._refresh_external_tooltip()

    def report_task_finished(self, task_name: str) -> None:
        super().report_task_finished(task_name)
        self._refresh_external_tooltip()

    def report_task_failed(self, task_name: str) -> None:
        super().report_task_failed(task_name)
        self._refresh_external_tooltip()

    def set_backend_connected(self, connected: bool) -> None:
        super().set_backend_connected(connected)
        self._refresh_external_tooltip()

    def set_trouble_code(
        self,
        code: str | OrbTroubleCode,
        *,
        active: bool = True,
        state: OrbVisualState | None = None,
    ) -> None:
        super().set_trouble_code(code, active=active, state=state)
        self._refresh_external_tooltip()

    def clear_trouble_code(self, code: str | OrbTroubleCode) -> None:
        super().clear_trouble_code(code)
        self._refresh_external_tooltip()
