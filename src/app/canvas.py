"""The image canvas: per-Object overlays, prompt points, box drag, brush, zoom/pan.

The canvas only *shows* state and *reports* gestures (in working-resolution
image pixels); it never changes the project itself. What a gesture means
depends on the mode the main window sets:

* IDLE        left click reports ``object_picked`` (select the Object under it)
* NEW_OBJECT  left click / drag report ``clicked`` / ``box_drawn``
* EDIT        left / right click report positive / negative ``clicked``,
              clicking a drawn point reports ``point_picked``, dragging reports
              ``box_drawn``, Shift+drag paints and Ctrl+Shift+drag erases the
              edited Object's mask (``brush_finished``)

Middle-drag or Space+drag pans, the wheel zooms at the cursor, Shift+wheel
changes the brush size, and holding Alt shows the Final Mask.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

from src.app.brush import BrushEngine
from src.app.session import Mode
from src.core.project import Box, Point

CLICK_SLOP = 4.0  # screen px a press may move and still count as a click
POINT_RADIUS = 5.0  # screen px
POINT_HIT = 9.0

ALPHA = {"normal": 105, "edit": 140, "faint": 40, "candidate": 120, "candidate_off": 35}


@dataclass(frozen=True)
class Overlay:
    """One colored mask layer. ``style``: normal | edit | faint | candidate | candidate_off."""

    mask: np.ndarray
    color: Tuple[int, int, int]
    style: str = "normal"


def compose(overlays: Sequence[Overlay], hw: Tuple[int, int]) -> np.ndarray:
    """Blend overlay layers into one RGBA image (later layers on top, outlines on edit/candidates)."""
    h, w = hw
    rgba = np.zeros((h, w, 4), np.uint8)
    outlines = []
    for ov in overlays:
        m = ov.mask
        if m is None or m.shape != (h, w):
            continue
        rgba[m] = (*ov.color, ALPHA.get(ov.style, 105))
        if ov.style in ("edit", "candidate"):
            outlines.append(ov)
    for ov in outlines:
        contours, _ = cv2.findContours(ov.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        color = (255, 255, 255, 255) if ov.style == "edit" else (*ov.color, 255)
        cv2.drawContours(rgba, contours, -1, color, 2 if ov.style == "edit" else 1)
    return rgba


def _qimage(arr: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    if arr.ndim == 2:
        fmt, bpl = QImage.Format.Format_Grayscale8, w
    elif arr.shape[2] == 3:
        fmt, bpl = QImage.Format.Format_RGB888, 3 * w
    else:
        fmt, bpl = QImage.Format.Format_RGBA8888, 4 * w
    return QImage(arr.data, w, h, bpl, fmt).copy()  # copy: QImage must not outlive arr's buffer


class Canvas(QWidget):
    clicked = pyqtSignal(float, float, bool)  # x, y, positive
    box_drawn = pyqtSignal(float, float, float, float)
    point_picked = pyqtSignal(int)
    object_picked = pyqtSignal(float, float)
    brush_finished = pyqtSignal(object)  # bool mask
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image: Optional[np.ndarray] = None
        self._image_q: Optional[QImage] = None
        self._overlays: List[Overlay] = []
        self._overlay_q: Optional[QImage] = None
        self._final: Optional[np.ndarray] = None
        self._final_q: Optional[QImage] = None
        self.final_preview = False
        self._alt_held = False
        self.mode = Mode.IDLE
        self.banner = ""
        self.points: Tuple[Point, ...] = ()
        self.selected_point: Optional[int] = None
        self.box: Optional[Box] = None

        self.zoom = 1.0
        self._pan = QPointF(0, 0)
        self._pan_from: Optional[Tuple[QPointF, QPointF]] = None
        self._space_held = False
        self._press: Optional[Tuple[QPointF, Qt.MouseButton]] = None
        self._drag_to: Optional[QPointF] = None
        self._mouse: Optional[QPointF] = None

        self.brush_size = 30  # screen px diameter
        self._brush = BrushEngine()

        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(False)

    # ------------------------------------------------------------------
    # State from the main window
    # ------------------------------------------------------------------

    def set_image(self, image: Optional[np.ndarray], reset_view: bool = True) -> None:
        if self._brush.is_drawing:
            self._brush.cancel()
        self.image = image
        self._image_q = _qimage(image) if image is not None else None
        if reset_view:
            self.zoom = 1.0
            self._pan = QPointF(0, 0)
            self.zoom_changed.emit(self.zoom)
        self.update()

    def set_overlays(self, overlays: List[Overlay]) -> None:
        self._overlays = list(overlays)
        self._rebuild_overlay()

    def _rebuild_overlay(self, replace_edit: Optional[np.ndarray] = None) -> None:
        if self.image is None:
            self._overlay_q = None
        else:
            layers = self._overlays
            if replace_edit is not None:
                layers = [Overlay(replace_edit, o.color, o.style) if o.style == "edit" else o for o in layers]
                if not any(o.style == "edit" for o in layers):
                    layers.append(Overlay(replace_edit, (255, 255, 255), "edit"))
            self._overlay_q = _qimage(compose(layers, self.image.shape[:2]))
        self.update()

    def set_final(self, mask: Optional[np.ndarray]) -> None:
        self._final = mask
        self._final_q = None  # built lazily when shown
        self.update()

    def set_final_preview(self, on: bool) -> None:
        self.final_preview = on
        self.update()

    @property
    def showing_final(self) -> bool:
        return self.final_preview or self._alt_held

    def set_mode(self, mode: Mode, banner: str = "") -> None:
        self.mode = mode
        self.banner = banner
        if mode != Mode.EDIT and self._brush.is_drawing:
            self._brush.cancel()
        self._update_cursor()
        self.update()

    def set_prompts(self, points: Sequence[Point], selected: Optional[int], box: Optional[Box]) -> None:
        self.points = tuple(points)
        self.selected_point = selected
        self.box = box
        self.update()

    def edit_mask(self) -> Optional[np.ndarray]:
        for o in self._overlays:
            if o.style == "edit":
                return o.mask
        return None

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _scale(self) -> float:
        if self.image is None:
            return 1.0
        h, w = self.image.shape[:2]
        return min(self.width() / w, self.height() / h) * self.zoom

    def _origin(self) -> QPointF:
        h, w = self.image.shape[:2]
        s = self._scale()
        return QPointF((self.width() - w * s) / 2 + self._pan.x(), (self.height() - h * s) / 2 + self._pan.y())

    def to_image(self, p: QPointF) -> Tuple[float, float]:
        o, s = self._origin(), self._scale()
        return (p.x() - o.x()) / s, (p.y() - o.y()) / s

    def to_widget(self, x: float, y: float) -> QPointF:
        o, s = self._origin(), self._scale()
        return QPointF(o.x() + x * s, o.y() + y * s)

    def _clamped(self, p: QPointF) -> Tuple[int, int]:
        h, w = self.image.shape[:2]
        x, y = self.to_image(p)
        return max(0, min(w - 1, int(x))), max(0, min(h - 1, int(y)))

    def _inside(self, p: QPointF) -> bool:
        h, w = self.image.shape[:2]
        x, y = self.to_image(p)
        return 0 <= x < w and 0 <= y < h

    def set_zoom(self, zoom: float, anchor: Optional[QPointF] = None) -> None:
        if self.image is None:
            return
        anchor = anchor or QPointF(self.width() / 2, self.height() / 2)
        ix, iy = self.to_image(anchor)
        self.zoom = max(1.0, min(20.0, zoom))
        if self.zoom == 1.0:
            self._pan = QPointF(0, 0)
        else:
            moved = self.to_widget(ix, iy)
            self._pan += anchor - moved
        self.zoom_changed.emit(self.zoom)
        self.update()

    def _point_at(self, p: QPointF) -> Optional[int]:
        best, best_d = None, POINT_HIT
        for i, pt in enumerate(self.points):
            q = self.to_widget(pt.x, pt.y)
            d = ((q.x() - p.x()) ** 2 + (q.y() - p.y()) ** 2) ** 0.5
            if d <= best_d:
                best, best_d = i, d
        return best

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(32, 32, 36))
        if self.image is None:
            painter.setPen(QColor(160, 160, 160))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open an image folder (Ctrl+O)")
            return
        h, w = self.image.shape[:2]
        o, s = self._origin(), self._scale()
        target = QRectF(o.x(), o.y(), w * s, h * s)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, s < 1.0)

        if self.showing_final:
            if self._final_q is None:
                final = self._final if self._final is not None else np.zeros((h, w), bool)
                self._final_q = _qimage(final.astype(np.uint8) * 255)
            painter.drawImage(target, self._final_q)
            self._draw_banner(painter, "FINAL MASK PREVIEW")
            return

        painter.drawImage(target, self._image_q)
        if self._overlay_q is not None:
            painter.drawImage(target, self._overlay_q)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.box is not None and self.mode == Mode.EDIT:
            self._draw_box(painter, self.box, QColor(255, 220, 0))
        if self._drag_to is not None and self._press is not None and not self._brush.is_drawing:
            x0, y0 = self.to_image(self._press[0])
            x1, y1 = self.to_image(self._drag_to)
            self._draw_box(painter, (x0, y0, x1, y1), QColor(255, 255, 255))
        if self.mode == Mode.EDIT:
            for i, pt in enumerate(self.points):
                q = self.to_widget(pt.x, pt.y)
                if i == self.selected_point:
                    painter.setPen(QPen(QColor(255, 230, 0), 2.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(q, POINT_RADIUS + 4, POINT_RADIUS + 4)
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.setBrush(QColor(40, 200, 60) if pt.positive else QColor(230, 40, 40))
                painter.drawEllipse(q, POINT_RADIUS, POINT_RADIUS)
        if self.mode == Mode.EDIT and self._mouse is not None and self._shift():
            painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = self.brush_size / 2
            painter.drawEllipse(self._mouse, r, r)
        if self.banner:
            self._draw_banner(painter, self.banner)

    def _draw_box(self, painter: QPainter, box: Box, color: QColor) -> None:
        a = self.to_widget(min(box[0], box[2]), min(box[1], box[3]))
        b = self.to_widget(max(box[0], box[2]), max(box[1], box[3]))
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(a, b))

    def _draw_banner(self, painter: QPainter, text: str) -> None:
        fm = painter.fontMetrics()
        r = QRectF(8, 8, fm.horizontalAdvance(text) + 16, fm.height() + 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(r, 4, 4)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    @staticmethod
    def _shift() -> bool:
        return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)

    @staticmethod
    def _ctrl() -> bool:
        return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)

    def _update_cursor(self) -> None:
        if self.mode in (Mode.NEW_OBJECT, Mode.EDIT):
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()

    def _brush_radius(self) -> int:
        return max(1, int(self.brush_size / 2 / self._scale()))

    def mousePressEvent(self, event):
        if self.image is None or self.showing_final:
            return
        pos, btn = event.position(), event.button()
        if btn == Qt.MouseButton.MiddleButton or (btn == Qt.MouseButton.LeftButton and self._space_held):
            self._pan_from = (pos, QPointF(self._pan))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if (
            btn == Qt.MouseButton.LeftButton
            and self.mode == Mode.EDIT
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            x, y = self._clamped(pos)
            base = self.edit_mask()
            h, w = self.image.shape[:2]
            erase = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            start = base.astype(np.uint8) * 255 if base is not None else None
            m = self._brush.start_stroke(x, y, 0 if erase else 255, start, (h, w), self._brush_radius())
            self._rebuild_overlay(replace_edit=m > 0)
            return
        if btn == Qt.MouseButton.LeftButton and self.mode == Mode.EDIT:
            hit = self._point_at(pos)
            if hit is not None:
                self.point_picked.emit(hit)
                return
        if btn in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._press = (pos, btn)
            self._drag_to = None

    def mouseMoveEvent(self, event):
        pos = event.position()
        self._mouse = pos
        if self._pan_from is not None:
            start, pan = self._pan_from
            self._pan = pan + (pos - start)
        elif self._brush.is_drawing:
            x, y = self._clamped(pos)
            m = self._brush.continue_stroke(x, y, self._brush_radius())
            if m is not None:
                self._rebuild_overlay(replace_edit=m > 0)
        elif self._press is not None and self._press[1] == Qt.MouseButton.LeftButton and self.mode != Mode.IDLE:
            d = pos - self._press[0]
            if self._drag_to is not None or (d.x() ** 2 + d.y() ** 2) ** 0.5 > CLICK_SLOP:
                self._drag_to = pos
        self.update()

    def mouseReleaseEvent(self, event):
        pos = event.position()
        if self._pan_from is not None:
            self._pan_from = None
            self._update_cursor()
            return
        if self._brush.is_drawing:
            m = self._brush.finalize_stroke()
            if m is not None:
                self.brush_finished.emit(m > 0)
            return
        if self._press is None:
            return
        start, btn = self._press
        dragged = self._drag_to is not None
        self._press = self._drag_to = None
        self.update()
        if btn != event.button():
            return
        if dragged and self.mode != Mode.IDLE:
            x0, y0 = self._clamped(start)
            x1, y1 = self._clamped(pos)
            if x0 != x1 and y0 != y1:
                self.box_drawn.emit(float(x0), float(y0), float(x1), float(y1))
            return
        if not self._inside(pos):
            return
        x, y = self.to_image(pos)
        if self.mode == Mode.IDLE:
            if btn == Qt.MouseButton.LeftButton:
                self.object_picked.emit(x, y)
        else:
            self.clicked.emit(x, y, btn == Qt.MouseButton.LeftButton)

    def wheelEvent(self, event):
        if self.image is None:
            return
        delta = event.angleDelta().y() or event.angleDelta().x()
        if not delta:
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            step = max(2, int(self.brush_size * 0.1))
            self.brush_size = max(2, min(800, self.brush_size + (step if delta > 0 else -step)))
            self.update()
            return
        self.set_zoom(self.zoom * (1.15 if delta > 0 else 1 / 1.15), event.position())

    def leaveEvent(self, event):
        self._mouse = None
        self.update()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update()

    # ------------------------------------------------------------------
    # Keys (held modifiers only; commands are window shortcuts)
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        k = event.key()
        if k == Qt.Key.Key_Alt and not event.isAutoRepeat():
            self._alt_held = True
            self.update()
        elif k == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif k == Qt.Key.Key_Shift:
            self.update()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        k = event.key()
        if k == Qt.Key.Key_Alt and not event.isAutoRepeat():
            self._alt_held = False
            self.update()
        elif k == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self._update_cursor()
        elif k == Qt.Key.Key_Shift:
            if self._brush.is_drawing:
                m = self._brush.finalize_stroke()
                if m is not None:
                    self.brush_finished.emit(m > 0)
            self.update()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self._alt_held = self._space_held = False
        if self._brush.is_drawing:
            m = self._brush.finalize_stroke()
            if m is not None:
                self.brush_finished.emit(m > 0)
        self.update()
        super().focusOutEvent(event)
