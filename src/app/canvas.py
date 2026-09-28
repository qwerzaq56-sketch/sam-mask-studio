"""The image canvas: per-Object overlays, prompt points, box drag, brush, zoom/pan.

The canvas only *shows* state and *reports* gestures (in working-resolution
image pixels); it never changes the project itself. What a gesture means
depends on the mode the main window sets:

* IDLE        left click reports ``object_picked`` (select the Object under it)
* NEW_OBJECT  left click / drag report ``clicked`` / ``box_drawn``
* EDIT        left / right click report positive / negative ``clicked``,
              clicking a drawn point reports ``point_picked``, dragging reports
              ``box_drawn``. With the Brush on (``brush_mode``) a drag paints
              and Ctrl+drag subtracts on the edited Object (``brush_finished``);
              Shift+drag / Ctrl+Shift+drag do the same without turning it on.

Middle-drag or Space+drag pans, the wheel zooms at the cursor, and holding Alt
shows the Final Mask. Ctrl+wheel (or Shift+wheel) sets the brush size while
an Object is in Edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QApplication, QWidget

from src.app.brush import BrushEngine
from src.app.session import Mode
from src.core.project import Box, Point

CLICK_SLOP = 4.0  # screen px a press may move and still count as a click
POINT_RADIUS = 5.0  # screen px
POINT_HIT = 9.0

ALPHA = {
    "normal": 105,
    "edit": 140,
    "faint": 40,
    "candidate": 120,
    "candidate_off": 35,
    "layer_add": 150,  # pixels the edit layer forces on
    "layer_sub": 110,  # pixels the edit layer forces off
}


@dataclass(frozen=True)
class Overlay:
    """One colored mask layer. ``style``: normal | edit | faint | candidate | candidate_off | layer_*."""

    mask: np.ndarray
    color: Tuple[int, int, int]
    style: str = "normal"


# Overlays are drawn as three cached images, so changing one group (checking a
# candidate, a brush stroke) never re-blends the others.
GROUPS = ("objects", "edit", "candidates")


def group_of(style: str) -> str:
    if style in ("edit", "layer_add", "layer_sub"):
        return "edit"
    if style.startswith("candidate"):
        return "candidates"
    return "objects"


def outline_polygons(mask: np.ndarray) -> List[QPolygonF]:
    """Mask boundaries (outer edges and holes) as polygons through the edge pixels' centres."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    polys = []
    for c in contours:
        pts = c.reshape(-1, 2) + 0.5
        polys.append(QPolygonF([QPointF(float(x), float(y)) for x, y in pts]))
    return polys


class MaskInfo:
    """Bounding box and outline of immutable mask arrays, cached by identity."""

    def __init__(self):
        self._rects: Dict[int, Tuple[np.ndarray, Tuple[int, int, int, int]]] = {}
        self._outlines: Dict[int, Tuple[np.ndarray, List[QPolygonF]]] = {}

    def rect(self, m: np.ndarray) -> Tuple[int, int, int, int]:
        e = self._rects.get(id(m))
        if e is None or e[0] is not m:  # hold the array: a freed one's id can be reused
            e = (m, cv2.boundingRect(m.view(np.uint8) if m.dtype == np.bool_ else m.astype(np.uint8)))
            self._rects[id(m)] = e
        return e[1]

    def outline(self, m: np.ndarray) -> List[QPolygonF]:
        e = self._outlines.get(id(m))
        if e is None or e[0] is not m:
            e = (m, outline_polygons(m))
            self._outlines[id(m)] = e
        return e[1]

    def keep_only(self, masks: Iterable[np.ndarray]) -> None:
        live = {id(m) for m in masks}
        for d in (self._rects, self._outlines):
            for k in [k for k in d if k not in live]:
                del d[k]


def compose(overlays: Sequence[Overlay], hw: Tuple[int, int], info: Optional[MaskInfo] = None) -> np.ndarray:
    """Blend overlay fills into one RGBA image (later layers on top); outlines are drawn separately."""
    info = info or MaskInfo()
    h, w = hw
    rgba = np.zeros((h, w, 4), np.uint8)
    for ov in overlays:
        m = ov.mask
        if m is None or m.shape != (h, w):
            continue
        x, y, bw, bh = info.rect(m)
        if bw == 0 or bh == 0:
            continue
        rgba[y : y + bh, x : x + bw][m[y : y + bh, x : x + bw]] = (*ov.color, ALPHA.get(ov.style, 105))
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
    brush_size_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image: Optional[np.ndarray] = None
        self._image_q: Optional[QImage] = None
        self._overlays: List[Overlay] = []
        self._info = MaskInfo()
        # group -> (signature of its overlays, blended image or None when empty)
        self._layers: Dict[str, Tuple[tuple, Optional[QImage]]] = {}
        self._stroke_mask: Optional[np.ndarray] = None  # the edit mask while a brush stroke is live
        self.outline_visible = True
        self.outline_width = 1.0  # screen px, independent of zoom
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
        self.brush_mode = False  # Brush editing turned on (only acts in EDIT)
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
        self._layers.clear()
        self._stroke_mask = None
        if reset_view:
            self.zoom = 1.0
            self._pan = QPointF(0, 0)
            self.zoom_changed.emit(self.zoom)
        self.update()

    def set_overlays(self, overlays: List[Overlay]) -> None:
        self._overlays = list(overlays)
        self._info.keep_only(o.mask for o in self._overlays)
        self._stroke_mask = None
        self._rebuild_overlay()

    def _group_layers(self, group: str) -> List[Overlay]:
        layers = [o for o in self._overlays if group_of(o.style) == group]
        if group == "edit" and self._stroke_mask is not None:
            # a live stroke replaces the edit fill; the layer tints would be stale
            color = next((o.color for o in layers if o.style == "edit"), (255, 255, 255))
            layers = [Overlay(self._stroke_mask, color, "edit")]
        return layers

    def _rebuild_overlay(self, groups: Sequence[str] = GROUPS) -> None:
        """Re-blend the overlay groups whose layers changed."""
        if self.image is None:
            self._layers.clear()
        else:
            hw = self.image.shape[:2]
            for g in groups:
                layers = self._group_layers(g)
                sig = tuple((id(o.mask), o.color, o.style) for o in layers)
                old = self._layers.get(g)
                if old is not None and old[0] == sig:
                    continue
                img = _qimage(compose(layers, hw, self._info)) if layers else None
                self._layers[g] = (sig, img)
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

    def set_brush_mode(self, on: bool) -> None:
        self.brush_mode = on
        if not on and self._brush.is_drawing:
            self._finish_stroke()
        self._update_cursor()
        self.update()

    def set_brush_size(self, px: int) -> None:
        self.brush_size = max(2, min(800, int(px)))
        self.brush_size_changed.emit(self.brush_size)
        self.update()

    def _brush_on(self) -> bool:
        """Brush strokes are what a left drag does right now."""
        return self.mode == Mode.EDIT and (self.brush_mode or self._shift())

    def _show_stroke(self, m: np.ndarray) -> None:
        self._stroke_mask = m > 0
        self._rebuild_overlay(("edit",))

    def _finish_stroke(self) -> None:
        m = self._brush.finalize_stroke()
        if m is not None:
            self.brush_finished.emit(m > 0)

    def set_prompts(self, points: Sequence[Point], selected: Optional[int], box: Optional[Box]) -> None:
        self.points = tuple(points)
        self.selected_point = selected
        self.box = box
        self.update()

    def set_outline(self, visible: bool, width: float) -> None:
        self.outline_visible = bool(visible)
        self.outline_width = max(0.5, float(width))
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
        for g in GROUPS:
            img = self._layers.get(g, ((), None))[1]
            if img is not None:
                painter.drawImage(target, img)
        self._draw_outlines(painter, o, s)

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
        if self._mouse is not None and self._brush_on():
            painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = self.brush_size / 2
            painter.drawEllipse(self._mouse, r, r)
        if self.banner:
            self._draw_banner(painter, self.banner)

    def _draw_outlines(self, painter: QPainter, origin: QPointF, scale: float) -> None:
        """Thin outlines in screen pixels: the edited mask (white) and checked candidates (their color)."""
        lines = []
        for ov in self._overlays:
            if ov.style == "candidate":
                lines.append((self._info.outline(ov.mask), QColor(*ov.color), 1.0))
        if self.outline_visible:
            if self._stroke_mask is not None:
                lines.append((outline_polygons(self._stroke_mask), QColor(255, 255, 255), self.outline_width))
            elif self.edit_mask() is not None:
                lines.append((self._info.outline(self.edit_mask()), QColor(255, 255, 255), self.outline_width))
        if not lines:
            return
        painter.save()
        painter.translate(origin)
        painter.scale(scale, scale)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, scale > 1.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for polys, color, width in lines:
            pen = QPen(color, width)
            pen.setCosmetic(True)  # width in screen pixels at any zoom
            painter.setPen(pen)
            for poly in polys:
                painter.drawPolygon(poly)
        painter.restore()

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
        if self.mode == Mode.EDIT and self.brush_mode:
            self.setCursor(Qt.CursorShape.BlankCursor)  # the brush circle is the cursor
        elif self.mode in (Mode.NEW_OBJECT, Mode.EDIT):
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
        mods = event.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if self.mode == Mode.EDIT and (self.brush_mode or shift):
            if btn != Qt.MouseButton.LeftButton:
                return  # with the brush on, clicks never add points
            x, y = self._clamped(pos)
            base = self.edit_mask()
            h, w = self.image.shape[:2]
            erase = bool(mods & Qt.KeyboardModifier.ControlModifier)
            start = base.astype(np.uint8) * 255 if base is not None else None
            m = self._brush.start_stroke(x, y, 0 if erase else 255, start, (h, w), self._brush_radius())
            self._show_stroke(m)
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
                self._show_stroke(m)
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
            self._finish_stroke()
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
        mods = event.modifiers()
        sized = mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        if self.mode == Mode.EDIT and sized:  # wheel = zoom, Ctrl+wheel = brush size
            step = max(2, int(self.brush_size * 0.1))
            self.set_brush_size(self.brush_size + (step if delta > 0 else -step))
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
            if self._brush.is_drawing and not self.brush_mode:
                self._finish_stroke()  # a Shift stroke ends when Shift is let go
            self.update()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self._alt_held = self._space_held = False
        if self._brush.is_drawing:
            self._finish_stroke()
        self.update()
        super().focusOutEvent(event)
