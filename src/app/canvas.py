"""The image canvas: per-Object overlays, prompt points, box drag, brush, zoom/pan.

The canvas only *shows* state and *reports* gestures (in working-resolution
image pixels); it never changes the project itself. What a gesture means
depends on the mode the main window sets:

* IDLE        left click reports ``object_picked`` (select the Object under it)
* NEW_OBJECT  left click / drag report ``clicked`` / ``box_drawn``
* EDIT        left / right click report positive / negative ``clicked``,
              clicking a drawn point reports ``point_picked``, dragging reports
              ``box_drawn``. With the Brush on (``brush_mode``) a drag paints
              and Alt+drag subtracts on the edited Object (``brush_finished``);
              Shift+drag / Alt+Shift+drag do the same without turning it on.
              ``brush_tool`` picks what a stroke does: ``paint`` adds (Alt:
              subtracts) and ``restore`` brings back the prompt mask (from
              ``tool_target_fn``), both live; with an auto tool
              (``fill_holes`` / ``remove_specks`` / ``object_fill``) a stroke
              marks an area (yellow) and releasing reports ``tool_stroke``
              (Alt: unpick).
              With ``region_mode`` on, a drag reports ``region_box`` instead
              (Alt or Ctrl: subtract); the region is shown in cyan.

Middle-drag or Space+drag pans and the wheel zooms at the cursor. Ctrl+drag left / right
(as in Photoshop), Ctrl+wheel or Shift+wheel set the brush size while an Object is in Edit. The Final Mask
preview is a toggle (``set_final_preview``) or held (``set_final_peek``);
editing keeps working in it. ``set_preview_style`` picks how it looks: the mask in black and white, the
image cut out by the mask, or the image outside it; ``set_cutout_fill`` fills the rest with the mask's own
color there (black outside the mask, white inside) or a gray checkerboard (as transparency).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

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
    "region": 70,  # where the edit-layer tools act
    "auto_add": 150,  # an auto tool's result: pixels it adds
    "auto_sub": 130,  # ...and removes
    "auto_a": 60,  # By Color Range: A where nothing changes (light blue; the changes are dense)
    "auto_b": 60,  # ...and B (light orange)
    "area": 45,  # where By Color decides pixels again (Near edge): faint, under the mask colors
    "guide": 210,  # an auto tool's result, not picked yet (Paint mode): dark and dense to stand out
}


@dataclass(frozen=True)
class Overlay:
    """One colored mask layer. ``style``: normal | edit | faint | candidate | candidate_off | layer_*."""

    mask: np.ndarray
    color: Tuple[int, int, int]
    style: str = "normal"


# Overlays are drawn as three cached images, so changing one group (checking a
# candidate, a brush stroke) never re-blends the others.
GROUPS = ("objects", "edit", "region", "candidates")
def checkerboard(h: int, w: int) -> np.ndarray:
    """A gray checkerboard (RGB) the size of the image, squares about 1/64 of its long side (at least 8 px)."""
    cell = max(8, round(max(h, w) / 64))
    yy, xx = np.indices((h, w))
    g = np.where(((yy // cell) + (xx // cell)) % 2 == 0, *CUTOUT_GRAYS).astype(np.uint8)
    return np.repeat(g[..., None], 3, axis=2)


ORIGINAL_BANNER = "ORIGINAL (T)"  # BC-P3: the overlays are hidden, not gone
PICK_BANNER = ("PICK COLOR · click: pick (1 px) · right-click: leave out · Shift: add · Alt: 5×5 mean · "
               "T: original · Esc: stop")
OVERLAP_COLOR = (255, 230, 0)  # By Color: pixels both a picked and a left-out color claim (outlined, BC-P4 b)
STYLE_BANNER = {"mask": "", "cutout": " (CUT OUT)", "outside": " (OUTSIDE)"}
REGION_COLOR = (0, 200, 255)
TOOL_STROKE_COLOR = (255, 210, 0)
UNPICK_STROKE_COLOR = (255, 60, 60)  # Alt: the stroke takes picks back out
PREVIEW_STYLES = ("mask", "cutout", "outside")  # black and white | the image inside the mask | outside it
CUTOUT_FILLS = ("mask", "checker")  # the cut-out previews' rest: the mask's color there | a checkerboard
CUTOUT_GRAYS = (102, 153)  # the cut-out previews' checkerboard: gray, unlike sky, leaves and the tool tints
ALT_COLOR = (255, 70, 70)  # brush circle / region box while Alt (subtract) is held


BLENDED = ("auto_a", "auto_b", "auto_add", "auto_sub")  # blended over the layers below (the mask shows through, p86)


def group_of(style: str) -> str:
    if style in ("edit", "layer_add", "layer_sub", "auto_a", "auto_b", "auto_add", "auto_sub"):
        return "edit"
    if style == "edit_hidden":  # Hide Masks: the Object in Edit is not drawn, but strokes still start from it
        return "hidden"
    if style == "overlap":  # outlined only (``_draw_outlines``), never filled
        return "outline"
    if style.startswith("candidate"):
        return "candidates"
    if style in ("region", "guide"):
        return "region"
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


def compose(overlays: Sequence[Overlay], hw: Tuple[int, int], info: Optional[MaskInfo] = None,
            opacity: float = 1.0) -> np.ndarray:
    """Blend overlay fills into one RGBA image (later layers on top); outlines are drawn separately.
    *opacity* scales every style's alpha (the toolbar's Overlay %)."""
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
        sel = m[y : y + bh, x : x + bw]
        if ov.style in BLENDED:  # over what is there (the mask stays visible under it), not instead of it
            dst = rgba[y : y + bh, x : x + bw][sel].astype(np.float32)
            a_s, a_d = min(255.0, ALPHA[ov.style] * opacity) / 255.0, dst[:, 3:] / 255.0
            a_o = a_s + a_d * (1 - a_s)
            rgb = (np.float32(ov.color) * a_s + dst[:, :3] * a_d * (1 - a_s)) / np.maximum(a_o, 1e-6)
            rgba[y : y + bh, x : x + bw][sel] = np.concatenate([rgb, a_o * 255], 1).round().astype(np.uint8)
        else:
            rgba[y : y + bh, x : x + bw][sel] = (*ov.color, min(255, round(ALPHA.get(ov.style, 105) * opacity)))
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
    segment_clicked = pyqtSignal(float, float, bool)  # Ctrl+click while editing: x, y, add (left) / take out (right)
    box_drawn = pyqtSignal(float, float, float, float)
    point_picked = pyqtSignal(int)
    point_moved = pyqtSignal(int, float, float)  # index, new x, y (dragged)
    point_deleted = pyqtSignal(int)  # double-clicked
    candidates_clicked = pyqtSignal(float, float, str)  # x, y, "add" | "toggle" (Shift) | "remove" (Ctrl)
    candidates_boxed = pyqtSignal(float, float, float, float, str)  # a drag box, same ops
    object_picked = pyqtSignal(float, float)
    brush_finished = pyqtSignal(object)  # bool mask
    region_box = pyqtSignal(float, float, float, float, bool)  # x0, y0, x1, y1, subtract
    tool_stroke = pyqtSignal(str, object, bool)  # tool, area the stroke covered, Alt (unpick)
    zoom_changed = pyqtSignal(float)
    brush_size_changed = pyqtSignal(int)
    color_picked = pyqtSignal(object, bool)  # (r, g, b) under a click while picking colors, Shift (add a color)
    color_picked_out = pyqtSignal(object, bool)  # ...under a right-click: a color to leave out (BC-P4 b)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image: Optional[np.ndarray] = None
        self._image_q: Optional[QImage] = None
        self._overlays: List[Overlay] = []
        self._info = MaskInfo()
        # group -> (signature of its overlays, blended image or None when empty)
        self._layers: Dict[str, Tuple[tuple, Optional[QImage]]] = {}
        self._stroke_mask: Optional[np.ndarray] = None  # the edited mask as the live stroke shows it
        self._tool_area: Optional[np.ndarray] = None  # a live tool stroke's area (shown, not applied)
        self._region: Optional[np.ndarray] = None
        self.brush_tool = "paint"  # paint | fill_holes | remove_specks | object_fill
        self.region_mode = False  # a drag sets the tool region (box) instead of a SAM2 box
        self._tool_stroke = False  # the live stroke marks a tool area rather than painting
        self._tool_erase = False  # ...and unpicks it (Alt)
        self._live_base: Optional[np.ndarray] = None  # restore strokes: the mask before the stroke
        self._live_target: Optional[np.ndarray] = None  # ...and the restored mask
        # tool -> the edited mask with that tool applied everywhere (live strokes: restore)
        self.tool_target_fn: Optional[Callable[[str], Optional[np.ndarray]]] = None
        self._peek = False  # the Final Mask shown while a key is held
        self.original_view = False  # the photo alone while picking colors (BC-P3)
        self.outline_visible = True
        self.overlay_opacity = 1.0  # scales every overlay's alpha (1 = as designed)
        self.outline_width = 1.0  # screen px, independent of zoom
        self._final: Optional[np.ndarray] = None
        self._final_q: Optional[QImage] = None
        self._final_label = "FINAL MASK"
        self.preview_style = "mask"
        self.cutout_fill = "mask"
        self.color_pick_mode = False  # a click samples the image's color (By Color's picker)
        self.final_preview = False
        self.mode = Mode.IDLE
        self.banner = ""
        self.legend: List[Tuple[Tuple[int, int, int], int, str]] = []  # (color, alpha, meaning), bottom left (p91)
        self.points: Tuple[Point, ...] = ()
        self.selected_point: Optional[int] = None
        self.box: Optional[Box] = None

        self.zoom = 1.0
        self._pan = QPointF(0, 0)
        self._pan_from: Optional[Tuple[QPointF, QPointF]] = None
        self._space_held = False
        self._point_drag: Optional[Tuple[int, QPointF, bool]] = None  # index, press pos, moved
        # Select on Image: left clicks / drags pick Detections (and do nothing else)
        self.candidates_pickable = False
        self._cand_pick: Optional[str] = None  # the press picks candidates: add | toggle | remove
        self._press: Optional[Tuple[QPointF, Qt.MouseButton]] = None
        self._drag_to: Optional[QPointF] = None
        self._mouse: Optional[QPointF] = None

        self.brush_size = 30  # screen px diameter
        self._size_drag = None  # Ctrl+drag left / right: (start, size then, where the circle stays)
        self._seg_press = None  # Ctrl+press while editing: (where, button; None = picking colors): click or size drag
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
        self._final_q = None  # a cut-out preview shows this image
        self._layers.clear()
        self._stroke_mask = None
        self._region = None
        if reset_view:
            self.zoom = 1.0
            self._pan = QPointF(0, 0)
            self.zoom_changed.emit(self.zoom)
        self.update()

    def set_overlays(self, overlays: List[Overlay]) -> None:
        self._overlays = list(overlays)
        self._info.keep_only([o.mask for o in self._overlays] + [self._region])
        if not self._brush.is_drawing:
            self._stroke_mask = None
        self._rebuild_overlay()

    def set_region(self, region: Optional[np.ndarray]) -> None:
        """The area the edit-layer tools are limited to (None: none set)."""
        self._region = region
        self._rebuild_overlay(("region",))

    def set_region_mode(self, on: bool) -> None:
        self.region_mode = on
        self._update_cursor()
        self.update()

    def set_brush_tool(self, tool: str) -> None:
        if self._brush.is_drawing:
            self._finish_stroke()
        self.brush_tool = tool
        self.update()

    def _group_layers(self, group: str) -> List[Overlay]:
        if group == "region":
            layers = [o for o in self._overlays if o.style == "guide"]
            if self._region is not None:
                layers.append(Overlay(self._region, REGION_COLOR, "region"))
            if self._tool_area is not None:
                color = UNPICK_STROKE_COLOR if self._tool_erase else TOOL_STROKE_COLOR
                layers.append(Overlay(self._tool_area, color, "region"))
            return layers
        layers = [o for o in self._overlays if group_of(o.style) == group]
        if group == "edit" and self._stroke_mask is not None and self._edit_shown():
            # a live stroke replaces the edit fill; Paint drops the (now stale) tints, but Restore
            # keeps them, trimmed to what is still added / removed, so its effect shows as it paints
            color = next((o.color for o in layers if o.style == "edit"), (255, 255, 255))
            live = self._stroke_mask
            tints = []
            if self._live_target is not None:
                for o in layers:
                    if o.style == "layer_add":
                        tints.append(Overlay(o.mask & live, o.color, o.style))
                    elif o.style == "layer_sub":
                        tints.append(Overlay(o.mask & ~live, o.color, o.style))
            layers = [Overlay(live, color, "edit")] + tints
        return layers

    def _rebuild_overlay(self, groups: Sequence[str] = GROUPS) -> None:
        """Re-blend the overlay groups whose layers changed."""
        if self.image is None:
            self._layers.clear()
        else:
            hw = self.image.shape[:2]
            for g in groups:
                layers = self._group_layers(g)
                sig = (self.overlay_opacity,) + tuple((id(o.mask), o.color, o.style) for o in layers)
                old = self._layers.get(g)
                if old is not None and old[0] == sig:
                    continue
                img = _qimage(compose(layers, hw, self._info, self.overlay_opacity)) if layers else None
                self._layers[g] = (sig, img)
        self.update()

    def set_final(self, mask: Optional[np.ndarray], label: str = "FINAL MASK") -> None:
        """The Mask Preview's mask (*label*: what it is, on the banner)."""
        if mask is self._final and label == self._final_label:
            return  # unchanged (masks are immutable): keep the built image
        self._final = mask
        self._final_label = label
        self._final_q = None  # built lazily when shown
        self.update()

    def set_color_pick(self, on: bool) -> None:
        """While on, a left click reports the image's color there (``color_picked``) and does nothing else."""
        self.color_pick_mode = on
        if not on:
            self.original_view = False  # never left hiding the result once picking is over (BC-P3 d)
        self.update()  # the banner
        self._update_cursor()

    def set_original_view(self, on: bool) -> None:
        """Only the photo: no mask colors, tool preview, points or legend; the banner says so (BC-P3)."""
        self.original_view = on
        self.update()

    def sample_color(self, x: float, y: float, r: int = 0) -> Optional[Tuple[int, int, int]]:
        """The color of image pixel (x, y) (the mean of (2r+1)² pixels around it when *r* > 0). One pixel by
        default (p93): a 5×5 mean picked mixed colors at leaf and cloud edges (BC-14)."""
        if self.image is None:
            return None
        h, w = self.image.shape[:2]
        xi, yi = int(np.clip(x, 0, w - 1)), int(np.clip(y, 0, h - 1))
        patch = self.image[max(0, yi - r): yi + r + 1, max(0, xi - r): xi + r + 1, :3].reshape(-1, 3)
        return tuple(int(round(v)) for v in patch.mean(0))

    def set_preview_style(self, style: str) -> None:
        """How Mask Preview looks: ``mask`` (black and white), ``cutout`` (the image where the mask is, the rest
        filled), ``outside`` (the image where it is not)."""
        if style not in PREVIEW_STYLES:
            raise ValueError(f"Unknown preview style: {style}")
        if style != self.preview_style:
            self.preview_style = style
            self._final_q = None
            self.update()

    def set_cutout_fill(self, fill: str) -> None:
        """What the cut-out previews fill the rest with: ``mask`` (its black / white there) or ``checker``."""
        if fill not in CUTOUT_FILLS:
            raise ValueError(f"Unknown cut-out fill: {fill}")
        if fill != self.cutout_fill:
            self.cutout_fill = fill
            self._final_q = None
            self.update()

    def _preview_image(self, h: int, w: int) -> QImage:
        final = self._final if self._final is not None and self._final.shape == (h, w) else np.zeros((h, w), bool)
        if self.preview_style == "mask":
            return _qimage(final.astype(np.uint8) * 255)
        keep = final if self.preview_style == "cutout" else ~final
        out = self.image[..., :3].copy()
        if self.cutout_fill == "checker":
            out[~keep] = checkerboard(h, w)[~keep]
        else:  # the mask as it is there: black outside it (Cut Out), white inside it (Outside)
            out[~keep] = 255 if self.preview_style == "outside" else 0
        return _qimage(out)

    def set_final_preview(self, on: bool) -> None:
        self.final_preview = on
        self.update()

    @property
    def showing_final(self) -> bool:
        return self.final_preview or self._peek

    def set_final_peek(self, on: bool) -> None:
        """Show the Final Mask while a key is held (the toggle stays as it is)."""
        self._peek = on
        self.update()

    def set_legend(self, items: Sequence[Tuple[Tuple[int, int, int], int, str]]) -> None:
        """What the colors on the image mean right now (an auto tool's preview); empty: none."""
        items = list(items)
        if items != self.legend:
            self.legend = items
            self.update()

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
        self.brush_size = max(1, min(800, int(px)))
        self.brush_size_changed.emit(self.brush_size)
        self.update()

    def _brush_on(self) -> bool:
        """Brush strokes are what a left drag does right now."""
        return self.mode == Mode.EDIT and not self.region_mode and (self.brush_mode or self._shift())

    def _show_stroke(self, m: np.ndarray) -> None:
        if self._tool_stroke:
            self._tool_area = m > 0
            self._rebuild_overlay(("region",))
        else:
            painted = m > 0
            if self._live_target is not None:  # restore: its result where the stroke passed, live
                painted = np.where(painted, self._live_target, self._live_base)
            self._stroke_mask = painted
            self._rebuild_overlay(("edit",))

    def _finish_stroke(self) -> None:
        m = self._brush.finalize_stroke()
        if self._tool_stroke:
            self._tool_stroke = False
            self._tool_area = None
            self._rebuild_overlay(("region",))
            if m is not None:
                self.tool_stroke.emit(self.brush_tool, m > 0, self._tool_erase)
            return
        result = self._stroke_mask
        self._live_base = self._live_target = None
        if m is not None and result is not None:
            self.brush_finished.emit(result)

    def set_prompts(self, points: Sequence[Point], selected: Optional[int], box: Optional[Box]) -> None:
        self.points = tuple(points)
        self.selected_point = selected
        self.box = box
        self.update()

    def set_overlay_opacity(self, factor: float) -> None:
        """Every overlay fill's opacity times *factor* (0.1-2; the Mask Preview is not an overlay)."""
        factor = min(2.0, max(0.1, float(factor)))
        if factor != self.overlay_opacity:
            self.overlay_opacity = factor
            self._rebuild_overlay()

    def set_outline(self, visible: bool, width: float) -> None:
        self.outline_visible = bool(visible)
        self.outline_width = max(0.5, float(width))
        self.update()

    def edit_mask(self) -> Optional[np.ndarray]:
        """The mask of the Object in Edit, drawn or not (Hide Masks): what a brush stroke starts from."""
        for o in self._overlays:
            if o.style in ("edit", "edit_hidden"):
                return o.mask
        return None

    def _edit_shown(self) -> bool:
        return any(o.style == "edit" for o in self._overlays)

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

        if self.original_view:
            painter.drawImage(target, self._image_q)
            groups = ()
        elif self.showing_final:
            # the Final Mask in black and white; editing still works on top of it
            if self._final_q is None:
                self._final_q = self._preview_image(h, w)
            painter.drawImage(target, self._final_q)
            groups = ("edit", "region") if self._stroke_mask is not None else ("region",)
        else:
            painter.drawImage(target, self._image_q)
            groups = GROUPS
        for g in groups:
            img = self._layers.get(g, ((), None))[1]
            if img is not None:
                painter.drawImage(target, img)
        if not self.original_view:
            self._draw_outlines(painter, o, s)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.box is not None and self.mode == Mode.EDIT and not self.original_view:
            self._draw_box(painter, self.box, QColor(255, 220, 0))
        if self._drag_to is not None and self._press is not None and not self._brush.is_drawing:
            x0, y0 = self.to_image(self._press[0])
            x1, y1 = self.to_image(self._drag_to)
            removing = (self.mode == Mode.EDIT and self.region_mode and self._alt()) or self._cand_pick == "remove"
            color = QColor(*ALT_COLOR) if removing else QColor(255, 220, 0) if self._cand_pick == "toggle" else QColor(
                255, 255, 255
            )
            self._draw_box(painter, (x0, y0, x1, y1), color)
        if self.mode == Mode.EDIT and not self.original_view:
            for i, pt in enumerate(self.points):
                q = self.to_widget(pt.x, pt.y)
                if i == self.selected_point:
                    painter.setPen(QPen(QColor(255, 230, 0), 2.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(q, POINT_RADIUS + 4, POINT_RADIUS + 4)
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.setBrush(QColor(40, 200, 60) if pt.positive else QColor(230, 40, 40))
                painter.drawEllipse(q, POINT_RADIUS, POINT_RADIUS)
        if self._mouse is not None and (self._size_drag is not None
                                        or (self._brush_on() and not self.color_pick_mode)):
            # white on the photo; green over the black-and-white Final Mask, where white disappears;
            # red while Alt is held (the stroke subtracts / unpicks)
            if self._alt():
                color = QColor(*ALT_COLOR)
            else:
                color = QColor(60, 230, 90) if self.showing_final else QColor(255, 255, 255)
            painter.setPen(QPen(color, 1.5 if self.showing_final or self._alt() else 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = (2 * self._brush_radius() + 1) * self._scale() / 2  # what a stroke covers, in screen px
            painter.drawEllipse(self._mouse, r, r)
        pick = PICK_BANNER if self.color_pick_mode else ""
        final = f"MASK PREVIEW{STYLE_BANNER[self.preview_style]} · {self._final_label}" if self.showing_final else ""
        if self.original_view:
            final = ORIGINAL_BANNER
        banner = "  ·  ".join(t for t in (final, pick, self.banner) if t)
        if banner:
            self._draw_banner(painter, banner)
        if self.legend and not self.showing_final and not self.original_view:
            self._draw_legend(painter)

    def _draw_outlines(self, painter: QPainter, origin: QPointF, scale: float) -> None:
        """Thin outlines in screen pixels: the edited mask (white) and checked candidates (their color)."""
        lines = []
        for ov in self._overlays:
            if ov.style == "candidate":
                lines.append((self._info.outline(ov.mask), QColor(*ov.color), 1.0))
            elif ov.style == "candidate_off":  # unchecked: faint fill, but the outline still shows where it is
                lines.append((self._info.outline(ov.mask), QColor(*ov.color, 150), 1.0))
        if self._region is not None:
            lines.append((self._info.outline(self._region), QColor(*REGION_COLOR), 1.0))
        for ov in self._overlays:
            if ov.style == "overlap":  # decided by the nearer color: worth a look
                lines.append((self._info.outline(ov.mask), QColor(*ov.color), 1.0, Qt.PenStyle.DotLine))
        if self.outline_visible and self._edit_shown():
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
        for polys, color, width, *dash in lines:
            pen = QPen(color, width, *dash)
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

    def _draw_legend(self, painter: QPainter) -> None:
        """One row per color in use: a swatch (as strong as on the image, over gray) and what it means."""
        fm = painter.fontMetrics()
        row, sw, pad = fm.height() + 4, 14, 8
        w = sw + 8 + max(fm.horizontalAdvance(t) for _c, _a, t in self.legend) + 2 * pad
        h = row * len(self.legend) + 2 * pad - 4
        r = QRectF(8, self.height() - h - 8, w, h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(r, 4, 4)
        for i, (color, alpha, text) in enumerate(self.legend):
            y = r.top() + pad + i * row
            box = QRectF(r.left() + pad, y + (fm.height() - sw) / 2, sw, sw)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(128, 128, 128))
            painter.drawRect(box)
            painter.setBrush(QColor(*color, alpha))
            painter.drawRect(box)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QRectF(box.right() + 8, y, w, fm.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

    # ------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------

    @staticmethod
    def _shift() -> bool:
        return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)

    @staticmethod
    def _ctrl() -> bool:
        return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)

    @staticmethod
    def _alt() -> bool:
        return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier)

    def _update_cursor(self) -> None:
        if self.color_pick_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self.mode == Mode.EDIT and self.brush_mode:
            self.setCursor(Qt.CursorShape.BlankCursor)  # the brush circle is the cursor
        elif self.mode in (Mode.NEW_OBJECT, Mode.EDIT):
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()

    def _brush_radius(self) -> int:
        """Image px around the center: 0 = one pixel (the disc is 2r + 1 wide; the circle drawn is that size)."""
        return max(0, round((self.brush_size / self._scale() - 1) / 2))

    def mousePressEvent(self, event):
        if self.image is None:
            return
        pos, btn = event.position(), event.button()
        if btn == Qt.MouseButton.MiddleButton or (btn == Qt.MouseButton.LeftButton and self._space_held):
            self._pan_from = (pos, QPointF(self._pan))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        mods = event.modifiers()
        ctrl_edit = (self.mode == Mode.EDIT and not self.region_mode and mods & Qt.KeyboardModifier.ControlModifier
                     and btn in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton))
        if ctrl_edit and self.color_pick_mode:
            self._seg_press = (QPointF(pos), None)  # picking colors: a Ctrl+drag only sizes the brush
            return
        if self.color_pick_mode:
            if btn in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                # one pixel; Alt: the 5×5 mean around it (noisy areas, p95); right-click: a color to leave out
                color = self.sample_color(*self.to_image(pos), r=2 if mods & Qt.KeyboardModifier.AltModifier else 0)
                if color is not None:
                    signal = self.color_picked if btn == Qt.MouseButton.LeftButton else self.color_picked_out
                    signal.emit(color, bool(mods & Qt.KeyboardModifier.ShiftModifier))
            return  # while picking colors, clicks do nothing else
        if ctrl_edit:  # a click: a piece of the image added / taken out (brush on or off); a drag: brush size
            self._seg_press = (QPointF(pos), btn)
            return
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if self.mode == Mode.EDIT and self.region_mode:
            if btn == Qt.MouseButton.LeftButton:
                self._press = (pos, btn)  # a drag sets the region; clicks do nothing
                self._drag_to = None
            return
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if self.mode != Mode.EDIT and self.candidates_pickable:
            if btn == Qt.MouseButton.LeftButton:
                self._cand_pick = "remove" if ctrl else "toggle" if shift else "add"
                self._press = (pos, btn)
                self._drag_to = None
            return  # while picking, clicks do nothing else
        if self.mode == Mode.EDIT and (self.brush_mode or shift):
            if btn != Qt.MouseButton.LeftButton:
                return  # with the brush on, clicks never add points
            x, y = self._clamped(pos)
            base = self.edit_mask()
            h, w = self.image.shape[:2]
            alt = bool(mods & Qt.KeyboardModifier.AltModifier)
            self._tool_stroke = self.brush_tool not in ("paint", "restore")
            if self._tool_stroke:
                if base is None:
                    return
                self._tool_erase = alt
                start, value = None, 255  # the stroke only marks an area for the auto tool
            elif self.brush_tool == "restore":
                target = self.tool_target_fn("restore") if self.tool_target_fn else None
                if target is None or base is None:
                    return
                self._live_base, self._live_target = base, target
                start, value = None, 255  # the stroke marks where the restored mask shows
            else:
                erase = bool(mods & Qt.KeyboardModifier.AltModifier)
                start = base.astype(np.uint8) * 255 if base is not None else None
                value = 0 if erase else 255
            m = self._brush.start_stroke(x, y, value, start, (h, w), self._brush_radius())
            self._show_stroke(m)
            return
        if btn == Qt.MouseButton.LeftButton and self.mode == Mode.EDIT:
            hit = self._point_at(pos)
            if hit is not None:
                self.point_picked.emit(hit)
                self._point_drag = (hit, pos, False)  # a drag moves it
                return
        if btn in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._press = (pos, btn)
            self._drag_to = None

    def mouseMoveEvent(self, event):
        pos = event.position()
        self._mouse = pos
        if self._seg_press is not None and self._size_drag is None:
            start = self._seg_press[0]
            d = pos - start
            if (d.x() ** 2 + d.y() ** 2) ** 0.5 > CLICK_SLOP:  # Ctrl+drag, not a click: the brush size
                self._seg_press = None
                self._size_drag = (start, self.brush_size, QPointF(start))
        if self._size_drag is not None:
            p0, size0, anchor = self._size_drag
            self.set_brush_size(size0 + 2 * (pos.x() - p0.x()))  # right: bigger, left: smaller, twice as fast
            self._mouse = anchor  # the circle stays where the drag began
        elif self._pan_from is not None:
            start, pan = self._pan_from
            self._pan = pan + (pos - start)
        elif self._point_drag is not None:
            i, start, moved = self._point_drag
            d = pos - start
            if moved or (d.x() ** 2 + d.y() ** 2) ** 0.5 > CLICK_SLOP:
                self._point_drag = (i, start, True)
                if 0 <= i < len(self.points):  # show it where it will land
                    x, y = self._clamped(pos)
                    pts = list(self.points)
                    pts[i] = Point(float(x), float(y), pts[i].positive)
                    self.points = tuple(pts)
        elif self._brush.is_drawing:
            x, y = self._clamped(pos)
            m = self._brush.continue_stroke(x, y, self._brush_radius())
            if m is not None:
                self._show_stroke(m)
        elif (
            self._press is not None
            and self._press[1] == Qt.MouseButton.LeftButton
            and (self.mode != Mode.IDLE or self._cand_pick is not None)
        ):
            d = pos - self._press[0]
            if self._drag_to is not None or (d.x() ** 2 + d.y() ** 2) ** 0.5 > CLICK_SLOP:
                self._drag_to = pos
        self.update()

    def mouseReleaseEvent(self, event):
        pos = event.position()
        if self._size_drag is not None:
            self._size_drag = None
            self.update()
            return
        if self._seg_press is not None:
            start, btn = self._seg_press
            self._seg_press = None
            d = pos - start
            if (btn is not None and btn == event.button() and (d.x() ** 2 + d.y() ** 2) ** 0.5 <= CLICK_SLOP
                    and self._inside(pos)):
                self.segment_clicked.emit(*self.to_image(pos), btn == Qt.MouseButton.LeftButton)
            return
        if self._pan_from is not None:
            self._pan_from = None
            self._update_cursor()
            return
        if self._brush.is_drawing:
            self._finish_stroke()
            return
        if self._point_drag is not None:
            i, _, moved = self._point_drag
            self._point_drag = None
            if moved:
                x, y = self._clamped(pos)
                self.point_moved.emit(i, float(x), float(y))
            return
        if self._press is None:
            return
        start, btn = self._press
        dragged = self._drag_to is not None
        self._press = self._drag_to = None
        self.update()
        if btn != event.button():
            return
        if self._cand_pick is not None:
            op, self._cand_pick = self._cand_pick, None
            if dragged:
                x0, y0 = self._clamped(start)
                x1, y1 = self._clamped(pos)
                self.candidates_boxed.emit(float(x0), float(y0), float(x1), float(y1), op)
            elif self._inside(pos):
                self.candidates_clicked.emit(*self.to_image(pos), op)
            return
        if dragged and self.mode != Mode.IDLE:
            x0, y0 = self._clamped(start)
            x1, y1 = self._clamped(pos)
            if x0 != x1 and y0 != y1:
                if self.mode == Mode.EDIT and self.region_mode:
                    subtract = bool(
                        event.modifiers() & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier)
                    )
                    self.region_box.emit(float(x0), float(y0), float(x1), float(y1), subtract)
                else:
                    self.box_drawn.emit(float(x0), float(y0), float(x1), float(y1))
            return
        if self.mode == Mode.EDIT and self.region_mode:
            return
        if not self._inside(pos):
            return
        x, y = self.to_image(pos)
        if self.mode == Mode.IDLE:
            if btn == Qt.MouseButton.LeftButton:
                self.object_picked.emit(x, y)
        else:
            self.clicked.emit(x, y, btn == Qt.MouseButton.LeftButton)

    def mouseDoubleClickEvent(self, event):
        """Double-clicking a point deletes it; anywhere else it is a second click."""
        if self.color_pick_mode:
            return  # picking colors: the first click picked; a second one would only start over
        if (
            self.image is not None
            and event.button() == Qt.MouseButton.LeftButton
            and self.mode == Mode.EDIT
            and not self.brush_mode
            and not self.region_mode
        ):
            hit = self._point_at(event.position())
            if hit is not None:
                self._point_drag = None
                self.point_deleted.emit(hit)
                return
        self.mousePressEvent(event)

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
        if k == Qt.Key.Key_Alt:
            self.update()  # the brush circle / region box turns red
        elif k == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif k == Qt.Key.Key_Shift:
            self.update()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        k = event.key()
        if k == Qt.Key.Key_Alt:
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
        self._space_held = False
        if self._brush.is_drawing:
            self._finish_stroke()
        self.update()
        super().focusOutEvent(event)
