from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from aida.frontend.status import AIDAStatus


class AIDAOverlay(QWidget):
    """Floating always-on-top AIDA status orb."""

    clicked = Signal()

    _RING_SPIKE = 0
    _RING_WAVE = 1
    _RING_SPUTTER = 2
    _CORE_SPIKE = 3
    _CORE_WAVE = 4
    _FULL_ICON_INTERFERENCE = 5

    def __init__(self, diameter: int = 120) -> None:
        super().__init__()
        self._orb_diameter = diameter
        self._canvas_margin = 28
        self.setFixedSize(diameter + 56, diameter + 56)

        self._status = AIDAStatus.STARTUP
        self._breath_phase = 0.0
        self._ring_hot_rotation = 38.0
        self._ring_cool_rotation = 218.0
        self._data_rotations = [146.0, 238.0, 30.0, 292.0]
        self._data_tick_rotation = 0.0
        self._notification_progress = 0.0
        self._pulse_progress = 0.0

        self._rng = random.Random()
        self._glitch_style = self._RING_SPIKE
        self._glitch_seed = 0
        self._glitch_center_angle = 0.0
        self._glitch_elapsed = 0.0
        self._glitch_duration = 0.0
        self._next_glitch_due = time.perf_counter() + self._rng.uniform(5.0, 10.0)

        self._activation_elapsed: float | None = None
        self._activation_signal_sent = False
        self._reveal_elapsed: float | None = None
        self._drag_press_global: QPoint | None = None
        self._drag_window_origin: QPoint | None = None
        self._dragging = False
        self._last_tick = time.perf_counter()

        self.setWindowTitle("AIDA Status")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setToolTip("Click to open AIDA • Right-drag to move")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._animation_timer = QTimer(self)
        self._animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._animation_timer.setInterval(16)
        self._animation_timer.timeout.connect(self._advance_animation)
        self._animation_timer.start()

    @staticmethod
    def _pen(color: QColor, width: float, cap: Qt.PenCapStyle | None = None) -> QPen:
        pen = QPen(color)
        pen.setWidthF(width)
        if cap is not None:
            pen.setCapStyle(cap)
        return pen

    @staticmethod
    def _wrapped(angle: float) -> float:
        return angle % 360.0

    @staticmethod
    def _angular_delta(angle: float, center: float) -> float:
        return (angle - center + 180.0) % 360.0 - 180.0

    @staticmethod
    def _angle_in_arc(angle: float, start: float, span: float) -> bool:
        return (angle - start) % 360.0 <= span

    @staticmethod
    def _radial(angle: float) -> QPointF:
        r = math.radians(angle)
        return QPointF(math.cos(r), -math.sin(r))

    @staticmethod
    def _tangent(angle: float) -> QPointF:
        r = math.radians(angle)
        return QPointF(-math.sin(r), -math.cos(r))

    @property
    def activation_in_progress(self) -> bool:
        return self._activation_elapsed is not None

    @property
    def reveal_in_progress(self) -> bool:
        return self._reveal_elapsed is not None

    @property
    def glitch_active(self) -> bool:
        return 0.0 < self._glitch_duration and self._glitch_elapsed < self._glitch_duration

    def set_status(self, status: AIDAStatus) -> None:
        if not isinstance(status, AIDAStatus):
            raise TypeError("status must be an AIDAStatus value")
        self._status = status
        self.setToolTip(f"AIDA status: {status.name}")
        self.update()

    def notify_message(self) -> None:
        self._notification_progress = 1.0
        self.update()

    def move_to_default_position(self, margin: int = 18) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - margin + 1, area.bottom() - self.height() - margin + 1)

    def _main_window(self) -> QMainWindow | None:
        for widget in QApplication.topLevelWidgets():
            if widget is not self and isinstance(widget, QMainWindow) and widget.windowTitle() == "AIDA":
                return widget
        return None

    def _sync_visibility(self) -> None:
        window = self._main_window()
        if window is None:
            return
        minimized = bool(window.windowState() & Qt.WindowState.WindowMinimized)
        if window.isVisible() and not minimized:
            if not self.activation_in_progress and not self.reveal_in_progress and self.isVisible():
                self.hide()
        elif minimized and not self.isVisible() and not self.activation_in_progress:
            self._start_reveal()

    def _schedule_next_glitch(self) -> None:
        self._next_glitch_due = time.perf_counter() + self._rng.uniform(5.0, 10.0)

    def _start_glitch(self, style: int | None = None, duration: float | None = None) -> None:
        if self.glitch_active:
            return
        self._glitch_style = self._rng.randrange(6) if style is None else style
        self._glitch_seed = self._rng.randint(0, 1_000_000)
        self._glitch_center_angle = self._rng.uniform(0.0, 360.0)
        self._glitch_elapsed = 0.0
        self._glitch_duration = duration or (
            self._rng.uniform(0.22, 0.30)
            if self._glitch_style == self._FULL_ICON_INTERFERENCE
            else self._rng.uniform(0.16, 0.24)
        )
        self._schedule_next_glitch()

    def _start_reveal(self) -> None:
        self._reveal_elapsed = 0.0
        self._pulse_progress = 0.001
        self._glitch_duration = 0.0
        self._start_glitch(self._FULL_ICON_INTERFERENCE, 0.30)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

    def _start_activation(self) -> None:
        if self.activation_in_progress:
            return
        self._activation_elapsed = 0.0
        self._activation_signal_sent = False
        self._pulse_progress = 0.001
        self._glitch_duration = 0.0
        self._start_glitch(self._FULL_ICON_INTERFERENCE, 0.32)
        self.setWindowOpacity(1.0)

    def _motion_scale(self) -> float:
        return {
            AIDAStatus.STARTUP: 1.25,
            AIDAStatus.STANDBY: 0.72,
            AIDAStatus.LISTENING: 1.45,
            AIDAStatus.ANALYZING: 2.15,
            AIDAStatus.SPEAKING: 1.80,
            AIDAStatus.WARNING: 1.30,
            AIDAStatus.ERROR: 1.20,
            AIDAStatus.SHUTDOWN: 0.30,
        }[self._status]

    def _advance_animation(self) -> None:
        now = time.perf_counter()
        dt = min(0.050, max(0.001, now - self._last_tick))
        self._last_tick = now
        self._sync_visibility()

        scale = self._motion_scale()
        self._breath_phase = self._wrapped(self._breath_phase + 25.0 * scale * dt)
        self._ring_hot_rotation = self._wrapped(self._ring_hot_rotation + 22.0 * scale * dt)
        self._ring_cool_rotation = self._wrapped(self._ring_cool_rotation - 15.5 * scale * dt)
        for i, velocity in enumerate((-26.0, 19.0, -14.0, 11.5)):
            self._data_rotations[i] = self._wrapped(self._data_rotations[i] + velocity * scale * dt)
        self._data_tick_rotation = self._wrapped(self._data_tick_rotation - 10.5 * scale * dt)

        if self._notification_progress > 0.0:
            self._notification_progress = max(0.0, self._notification_progress - 1.55 * dt)
        if self._pulse_progress > 0.0:
            self._pulse_progress += dt / 0.56
            if self._pulse_progress >= 1.0:
                self._pulse_progress = 0.0

        if self.glitch_active:
            self._glitch_elapsed = min(self._glitch_duration, self._glitch_elapsed + dt)
        elif self.isVisible() and not self.activation_in_progress and not self.reveal_in_progress and now >= self._next_glitch_due:
            self._start_glitch()

        if self._reveal_elapsed is not None:
            self._reveal_elapsed += dt
            p = min(1.0, self._reveal_elapsed / 0.44)
            self.setWindowOpacity(1.0 - (1.0 - p) ** 2)
            if p >= 1.0:
                self._reveal_elapsed = None
                self.setWindowOpacity(1.0)
                self._schedule_next_glitch()

        if self._activation_elapsed is not None:
            self._activation_elapsed += dt
            if self._activation_elapsed >= 0.17 and not self._activation_signal_sent:
                self._activation_signal_sent = True
                self.clicked.emit()
            if self._activation_elapsed >= 0.17:
                p = min(1.0, (self._activation_elapsed - 0.17) / 0.36)
                self.setWindowOpacity(max(0.0, 1.0 - p))
            if self._activation_elapsed >= 0.53:
                self._activation_elapsed = None
                self.setWindowOpacity(1.0)
                self.hide()
                self._schedule_next_glitch()
        self.update()

    @staticmethod
    def _palette() -> tuple[QColor, QColor, QColor, QColor, QColor]:
        return QColor("#278DFF"), QColor("#6EDBFF"), QColor("#F2FDFF"), QColor("#071A31"), QColor("#020711")

    def _orb_rect(self) -> QRectF:
        m = float(self._canvas_margin)
        return QRectF(m, m, float(self._orb_diameter), float(self._orb_diameter))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        full_rect = self._orb_rect().adjusted(2.0, 2.0, -2.0, -2.0)
        center = full_rect.center()
        base, bright, hot, deep, edge = self._palette()
        idle = 0.5 + 0.5 * math.sin(math.radians(self._breath_phase * 1.55))
        notify = math.sin((1.0 - self._notification_progress) * math.pi) if self._notification_progress > 0.0 else 0.0
        boost = 1.38 if self.activation_in_progress or self.reveal_in_progress else 1.0
        glow = 0.30 + idle * 0.14 + notify * 0.50

        self._paint_pulse(painter, center)
        self._paint_ambient_glow(painter, full_rect, center, base, glow)
        ring_radius = full_rect.width() * 0.465
        data_radius = full_rect.width() * 0.302
        core_radius = full_rect.width() * 0.205
        self._paint_main_ring(painter, center, ring_radius, base, bright, hot, boost)
        self._paint_data_rings(painter, center, data_radius, base, bright, hot)
        self._paint_energy_core(painter, center, core_radius, base, bright, hot, deep, edge, glow, boost)
        painter.end()

    def _paint_ambient_glow(self, painter: QPainter, rect: QRectF, center: QPointF, base: QColor, boost: float) -> None:
        glow_rect = rect.adjusted(-8.0, -8.0, 8.0, 8.0)
        gradient = QRadialGradient(center, glow_rect.width() / 2.0)
        c0, c1, c2 = QColor(base), QColor(base), QColor(base)
        c0.setAlpha(int(42 + boost * 145))
        c1.setAlpha(int(18 + boost * 78))
        c2.setAlpha(0)
        gradient.setColorAt(0.0, c0)
        gradient.setColorAt(0.58, c1)
        gradient.setColorAt(1.0, c2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(glow_rect)

    def _life(self) -> float:
        if not self.glitch_active:
            return 0.0
        return math.sin(min(1.0, self._glitch_elapsed / self._glitch_duration) * math.pi)

    def _targets(self, target: str) -> bool:
        if target == "ring":
            return self._glitch_style in (self._RING_SPIKE, self._RING_WAVE, self._RING_SPUTTER, self._FULL_ICON_INTERFERENCE)
        return self._glitch_style in (self._CORE_SPIKE, self._CORE_WAVE, self._FULL_ICON_INTERFERENCE)

    def _centers(self, target: str) -> tuple[float, ...]:
        if self._glitch_style != self._FULL_ICON_INTERFERENCE:
            return (self._glitch_center_angle,)
        offsets = (0.0, 86.0, 176.0, 268.0) if target == "ring" else (24.0, 154.0, 282.0)
        return tuple(self._wrapped(self._glitch_center_angle + offset) for offset in offsets)

    def _profile(self, target: str) -> tuple[float, float, float]:
        profiles = {
            self._RING_SPIKE: (30.0, 7.4, 1.5),
            self._RING_WAVE: (58.0, 5.2, 5.0),
            self._RING_SPUTTER: (72.0, 5.0, 4.5),
            self._CORE_SPIKE: (38.0, 4.0, 1.5),
            self._CORE_WAVE: (62.0, 3.2, 3.5),
        }
        if self._glitch_style == self._FULL_ICON_INTERFERENCE:
            return (34.0, 4.3, 3.8) if target == "ring" else (42.0, 3.0, 2.8)
        return profiles.get(self._glitch_style, (0.0, 0.0, 0.0))

    def _displacement(self, angle: float, index: int, boost: float, target: str) -> tuple[bool, float, float, float]:
        if not self.glitch_active or not self._targets(target):
            return False, 0.0, 0.0, 0.0
        life = self._life()
        span, radial_amp, tangent_amp = self._profile(target)
        delta: float | None = None
        best = 999.0
        for center in self._centers(target):
            candidate = self._angular_delta(angle, center)
            if abs(candidate) <= span / 2.0 and abs(candidate) < best:
                delta, best = candidate, abs(candidate)
        if delta is None:
            return False, 0.0, 0.0, 0.0
        local = delta / (span / 2.0)
        window = max(0.0, 1.0 - abs(local)) ** 2
        strength = boost * life
        bucket = int(self._glitch_elapsed * 120.0)
        rng = random.Random(self._glitch_seed + index * 97 + bucket * 271 + (0 if target == "ring" else 100_003))

        if self._glitch_style in (self._RING_SPIKE, self._CORE_SPIKE):
            radial = radial_amp * window**2.65 * strength
            tangent = rng.uniform(-0.42, 0.42) * tangent_amp * strength
        elif self._glitch_style in (self._RING_WAVE, self._CORE_WAVE):
            radial = radial_amp * math.sin(local * math.pi * 3.0) * window * strength
            tangent = tangent_amp * math.cos(local * math.pi * 2.25) * window * strength
        elif self._glitch_style == self._RING_SPUTTER:
            if rng.random() < 0.28:
                return False, 0.0, 0.0, 0.0
            radial = rng.uniform(-radial_amp * 0.30, radial_amp) * window * strength
            tangent = rng.uniform(-tangent_amp, tangent_amp) * window * strength
        else:
            radial = rng.uniform(-radial_amp * 0.40, radial_amp) * window * strength
            tangent = rng.uniform(-tangent_amp, tangent_amp) * window * strength
        return True, radial, tangent, min(1.0, window * life * boost)

    def _ring_color(self, angle: float, base: QColor, bright: QColor, hot: QColor) -> QColor:
        color = QColor(hot if self._angle_in_arc(angle, self._ring_hot_rotation, 68.0) else base if self._angle_in_arc(angle, self._ring_cool_rotation, 50.0) else bright)
        color.setAlpha(248)
        return color

    def _paint_main_ring(self, painter: QPainter, center: QPointF, radius: float, base: QColor, bright: QColor, hot: QColor, boost: float) -> None:
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        bloom = QColor(base)
        bloom.setAlpha(92)
        painter.setPen(self._pen(bloom, 14.5))
        painter.drawEllipse(rect)

        if not (self.glitch_active and self._targets("ring")):
            ring = QColor(bright)
            ring.setAlpha(248)
            painter.setPen(self._pen(ring, 7.4))
            painter.drawEllipse(rect)
            edge = QColor("#1D86DC")
            edge.setAlpha(215)
            painter.setPen(self._pen(edge, 2.0))
            painter.drawEllipse(rect.adjusted(3.0, 3.0, -3.0, -3.0))
            hi = QColor(hot)
            hi.setAlpha(250)
            painter.setPen(self._pen(hi, 3.4, Qt.PenCapStyle.RoundCap))
            painter.drawArc(rect, int(self._ring_hot_rotation * 16), int(68.0 * 16))
            cool = QColor(base)
            cool.setAlpha(225)
            painter.setPen(self._pen(cool, 2.6, Qt.PenCapStyle.RoundCap))
            painter.drawArc(rect.adjusted(1.8, 1.8, -1.8, -1.8), int(self._ring_cool_rotation * 16), int(50.0 * 16))
            return

        layer = QPixmap(self.size())
        layer.fill(Qt.GlobalColor.transparent)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        lp.setBrush(Qt.BrushStyle.NoBrush)
        ring = QColor(bright)
        ring.setAlpha(248)
        lp.setPen(self._pen(ring, 7.4))
        lp.drawEllipse(rect)
        edge = QColor("#1D86DC")
        edge.setAlpha(215)
        lp.setPen(self._pen(edge, 2.0))
        lp.drawEllipse(rect.adjusted(3.0, 3.0, -3.0, -3.0))
        hi = QColor(hot)
        hi.setAlpha(250)
        lp.setPen(self._pen(hi, 3.4, Qt.PenCapStyle.RoundCap))
        lp.drawArc(rect, int(self._ring_hot_rotation * 16), int(68.0 * 16))
        cool = QColor(base)
        cool.setAlpha(225)
        lp.setPen(self._pen(cool, 2.6, Qt.PenCapStyle.RoundCap))
        lp.drawArc(rect.adjusted(1.8, 1.8, -1.8, -1.8), int(self._ring_cool_rotation * 16), int(50.0 * 16))

        step, span = 2.0, 2.10
        clear_pen = self._pen(QColor(0, 0, 0, 0), 7.6, Qt.PenCapStyle.FlatCap)
        for index in range(int(360.0 / step)):
            angle = index * step
            affected, dr, dt, energy = self._displacement(angle, index, boost, "ring")
            if not affected:
                continue
            start = angle - span / 2.0
            lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            lp.setPen(clear_pen)
            lp.drawArc(rect, int(start * 16), max(1, int(span * 16)))
            rv, tv = self._radial(angle), self._tangent(angle)
            dx, dy = rv.x() * dr + tv.x() * dt, rv.y() * dr + tv.y() * dt
            color = QColor(hot) if energy > 0.80 and index % 7 == 0 else self._ring_color(angle, base, bright, hot)
            color.setAlpha(250 if energy > 0.80 and index % 7 == 0 else 248)
            lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            lp.setPen(self._pen(color, 7.4, Qt.PenCapStyle.FlatCap))
            lp.drawArc(rect.translated(dx, dy), int(start * 16), max(1, int(span * 16)))
        lp.end()
        painter.drawPixmap(0, 0, layer)

    def _full_offset(self, layer: int) -> QPointF:
        if not self.glitch_active or self._glitch_style != self._FULL_ICON_INTERFERENCE:
            return QPointF(0.0, 0.0)
        rng = random.Random(self._glitch_seed + layer * 811 + int(self._glitch_elapsed * 120.0) * 313)
        amp = 1.8 * self._life()
        return QPointF(rng.uniform(-amp, amp), rng.uniform(-amp, amp))

    def _paint_data_rings(self, painter: QPainter, center: QPointF, radius: float, base: QColor, bright: QColor, hot: QColor) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for layer, (scale, alpha) in enumerate(((1.00, 58), (0.76, 46), (0.52, 34))):
            r, offset = radius * scale, self._full_offset(layer)
            c = QPointF(center.x() + offset.x(), center.y() + offset.y())
            color = QColor(base)
            color.setAlpha(alpha)
            painter.setPen(self._pen(color, 0.95))
            painter.drawEllipse(QRectF(c.x() - r, c.y() - r, r * 2.0, r * 2.0))

        specs = ((0.98, 54.0, bright, 178, 1.35), (0.82, 38.0, base, 154, 1.12), (0.67, 28.0, hot, 145, 1.00), (0.57, 24.0, bright, 120, 0.90))
        for i, (scale, span, source, alpha, width) in enumerate(specs):
            r, offset = radius * scale, self._full_offset(10 + i)
            c = QPointF(center.x() + offset.x(), center.y() + offset.y())
            color = QColor(source)
            color.setAlpha(alpha)
            painter.setPen(self._pen(color, width, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(c.x() - r, c.y() - r, r * 2.0, r * 2.0), int(self._data_rotations[i] * 16), int(span * 16))

        r, offset = radius * 0.87, self._full_offset(20)
        c = QPointF(center.x() + offset.x(), center.y() + offset.y())
        for i in range(28):
            angle = i * (360.0 / 28.0) + self._data_tick_rotation
            rv, tv = self._radial(angle), self._tangent(angle)
            anchor = QPointF(c.x() + rv.x() * r, c.y() + rv.y() * r)
            length = 3.0 if i % 4 == 0 else 1.8
            color = QColor(bright)
            color.setAlpha(132 if i % 4 == 0 else 64)
            painter.setPen(self._pen(color, 0.80))
            painter.drawLine(QPointF(anchor.x() - tv.x() * length / 2.0, anchor.y() - tv.y() * length / 2.0), QPointF(anchor.x() + tv.x() * length / 2.0, anchor.y() + tv.y() * length / 2.0))

    @staticmethod
    def _sector(center: QPointF, inner: float, outer: float, start: float, span: float) -> QPainterPath:
        outer_rect = QRectF(center.x() - outer, center.y() - outer, outer * 2.0, outer * 2.0)
        inner_rect = QRectF(center.x() - inner, center.y() - inner, inner * 2.0, inner * 2.0)
        sr, er = math.radians(start), math.radians(start + span)
        path = QPainterPath()
        path.moveTo(QPointF(center.x() + math.cos(sr) * outer, center.y() - math.sin(sr) * outer))
        path.arcTo(outer_rect, start, span)
        path.lineTo(QPointF(center.x() + math.cos(er) * inner, center.y() - math.sin(er) * inner))
        path.arcTo(inner_rect, start + span, -span)
        path.closeSubpath()
        return path

    def _render_core(self, center: QPointF, radius: float, base: QColor, bright: QColor, hot: QColor, deep: QColor, edge: QColor, glow: float) -> QPixmap:
        layer = QPixmap(self.size())
        layer.fill(Qt.GlobalColor.transparent)
        p = QPainter(layer)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        halo_r = radius * 1.72
        halo = QRadialGradient(center, halo_r)
        c0, c1, c2 = QColor(bright), QColor(base), QColor(base)
        c0.setAlpha(int(82 + glow * 88))
        c1.setAlpha(int(38 + glow * 48))
        c2.setAlpha(0)
        halo.setColorAt(0.0, c0)
        halo.setColorAt(0.48, c1)
        halo.setColorAt(1.0, c2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QRectF(center.x() - halo_r, center.y() - halo_r, halo_r * 2.0, halo_r * 2.0))

        body = QRadialGradient(center, radius)
        colors = [QColor(hot), QColor(bright), QColor(base), QColor(deep), QColor(edge)]
        for color, alpha in zip(colors, (255, 248, 215, 248, 252), strict=True):
            color.setAlpha(alpha)
        for pos, color in zip((0.0, 0.12, 0.30, 0.68, 1.0), colors, strict=True):
            body.setColorAt(pos, color)
        p.setBrush(body)
        p.drawEllipse(QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0))

        glass = QColor(bright)
        glass.setAlpha(188)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(self._pen(glass, 1.25))
        gr = radius * 0.92
        p.drawEllipse(QRectF(center.x() - gr, center.y() - gr, gr * 2.0, gr * 2.0))

        flare = QColor(hot)
        flare.setAlpha(220)
        p.setPen(self._pen(flare, 1.25))
        p.drawLine(QPointF(center.x() - radius * 1.36, center.y()), QPointF(center.x() + radius * 1.36, center.y()))
        vertical = QColor(hot)
        vertical.setAlpha(120)
        p.setPen(self._pen(vertical, 0.80))
        p.drawLine(QPointF(center.x(), center.y() - radius * 0.38), QPointF(center.x(), center.y() + radius * 0.38))

        fr = radius * 0.44
        fg = QRadialGradient(center, fr)
        white, mid, fade = QColor("#FFFFFF"), QColor("#BDF1FF"), QColor("#6EDBFF")
        white.setAlpha(255)
        mid.setAlpha(178)
        fade.setAlpha(0)
        fg.setColorAt(0.0, white)
        fg.setColorAt(0.52, mid)
        fg.setColorAt(1.0, fade)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fg)
        p.drawEllipse(QRectF(center.x() - fr, center.y() - fr, fr * 2.0, fr * 2.0))
        p.end()
        return layer

    def _paint_energy_core(self, painter: QPainter, center: QPointF, radius: float, base: QColor, bright: QColor, hot: QColor, deep: QColor, edge: QColor, glow: float, boost: float) -> None:
        source = self._render_core(center, radius, base, bright, hot, deep, edge, glow)
        if not (self.glitch_active and self._targets("core")):
            painter.drawPixmap(0, 0, source)
            return

        result = QPixmap(source)
        rp = QPainter(result)
        rp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        step, span = 4.0, 4.05
        for i in range(int(360.0 / step)):
            angle = i * step
            affected, dr, dt, _ = self._displacement(angle, i, boost, "core")
            if not affected:
                continue
            source_path = self._sector(center, radius * 0.12, radius * 1.02, angle - span / 2.0, span)
            rv, tv = self._radial(angle), self._tangent(angle)
            dx, dy = rv.x() * dr + tv.x() * dt, rv.y() * dr + tv.y() * dt
            dest_path = QPainterPath(source_path)
            dest_path.translate(dx, dy)
            rp.save()
            rp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            rp.setClipPath(source_path)
            rp.fillRect(self.rect(), QColor(0, 0, 0, 0))
            rp.restore()
            rp.save()
            rp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            rp.setClipPath(dest_path)
            rp.drawPixmap(int(round(dx)), int(round(dy)), source)
            rp.restore()
        rp.end()
        painter.drawPixmap(0, 0, result)

    def _paint_pulse(self, painter: QPainter, center: QPointF) -> None:
        if self._pulse_progress <= 0.0:
            return
        p = self._pulse_progress
        radius = 11.0 + (1.0 - (1.0 - p) ** 2) * (self._orb_diameter * 0.66)
        alpha = int(135 * (1.0 - p) ** 1.45)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for offset, width, scale in ((0.0, 2.3, 1.0), (4.0, 1.55, 0.55), (8.5, 1.0, 0.28)):
            color = QColor("#6EDBFF")
            color.setAlpha(int(alpha * scale))
            painter.setPen(self._pen(color, width))
            r = radius + offset
            painter.drawEllipse(QRectF(center.x() - r, center.y() - r, r * 2.0, r * 2.0))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_activation()
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._drag_press_global = event.globalPosition().toPoint()
            self._drag_window_origin = self.frameGeometry().topLeft()
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._drag_press_global is not None and self._drag_window_origin is not None and event.buttons() & Qt.MouseButton.RightButton:
            self.move(self._drag_window_origin + event.globalPosition().toPoint() - self._drag_press_global)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._drag_press_global = None
            self._drag_window_origin = None
            self._dragging = False
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
