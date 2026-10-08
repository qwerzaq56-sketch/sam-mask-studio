"""A small map of the pinhole views a conversion makes (docs/specs/08 P4): where each view looks.

The map is the whole sphere laid flat like a 360 image: left / right = yaw -180..180 (0 = the source's
forward, in the middle), up / down = pitch 90..-90. Each view is its outline on the sphere (the square
image's edges, curved as they are on a 360 image) and a dot at its center; overlaps show where outlines
cross. Views a fisheye cannot fill are drawn gray and dashed: the conversion leaves them out.

Beside it, :class:`RigPreview` draws the same views as virtual cameras in 3D (p124): seen from in front of
the source, a little to its left and above, each view a numbered tile on a sphere (its image, shrunk so neighbours stay apart), coloured
by its row (up / level / down) like the map's outlines and numbers; a fisheye's lens edge (a pair's seam) red.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from src.core.reproject import view_rotation

UP, LEVEL, DOWN, OFF = (QColor(225, 130, 20), QColor(40, 110, 220), QColor(30, 150, 80), QColor(140, 140, 140))


def row_color(pitch: float, kept: bool = True) -> QColor:
    """A view's colour by where it looks: up (orange), level (blue), down (green); gray when left out."""
    if not kept:
        return QColor(OFF)
    return QColor(UP if pitch > 10 else DOWN if pitch < -10 else LEVEL)


def view_outline(yaw: float, pitch: float, fov: float, n: int = 24) -> np.ndarray:
    """(yaw, pitch) in degrees along the edge of a square view, source frame (X right, Y down, Z forward)."""
    t = np.tan(np.radians(fov) / 2)
    s = np.linspace(-t, t, n)
    edge = np.concatenate([
        np.stack([s, np.full(n, -t)], 1), np.stack([np.full(n, t), s], 1),
        np.stack([s[::-1], np.full(n, t)], 1), np.stack([np.full(n, -t), s[::-1]], 1),
    ])
    rays = np.column_stack([edge, np.ones(len(edge))]) @ view_rotation(yaw, pitch)  # view -> source (R.T)
    x, y, z = rays[:, 0], rays[:, 1], rays[:, 2]
    return np.column_stack([np.degrees(np.arctan2(x, z)), np.degrees(np.arctan2(-y, np.hypot(x, z)))])


class ViewPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._views: List[Tuple[float, float, bool]] = []  # yaw, pitch, kept
        self._fov = 90.0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(120)
        self.setToolTip("Where each view looks: the whole sphere laid flat (middle = forward, top = up). "
                        "Outlines crossing = overlap. Gray, dashed: a fisheye cannot fill it, so it is left out")

    def sizeHint(self) -> QSize:
        return QSize(320, 170)

    def set_views(self, pairs: Sequence[Tuple[float, float]], fov: float,
                  kept: Optional[Sequence[bool]] = None) -> None:
        kept = list(kept) if kept is not None else [True] * len(pairs)
        self._views = [(float(y), float(p), bool(k)) for (y, p), k in zip(pairs, kept)]
        self._fov = float(fov)
        self.update()

    def _map(self) -> QRectF:
        w, h = self.width() - 8, self.height() - 8
        mw = min(w, 2 * h)  # 2 : 1, like a 360 image
        return QRectF(4 + (w - mw) / 2, 4 + (h - mw / 2) / 2, mw, mw / 2)

    def _pt(self, r: QRectF, yaw: float, pitch: float) -> QPointF:
        return QPointF(r.left() + (yaw + 180) / 360 * r.width(), r.top() + (90 - pitch) / 180 * r.height())

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._map()
        pal = self.palette()
        p.fillRect(r, pal.color(pal.ColorRole.Base))
        grid = QColor(pal.color(pal.ColorRole.Text))
        grid.setAlpha(45)
        p.setPen(QPen(grid, 1))
        for yaw in range(-180, 181, 90):
            p.drawLine(self._pt(r, yaw, 90), self._pt(r, yaw, -90))
        for pitch in (-45, 0, 45):
            p.drawLine(self._pt(r, -180, pitch), self._pt(r, 180, pitch))
        text = QColor(pal.color(pal.ColorRole.Text))
        text.setAlpha(140)
        p.setPen(text)
        f = p.font()
        f.setPointSizeF(max(6.5, f.pointSizeF() - 2))
        p.setFont(f)
        for yaw, label in ((-180, "back"), (-90, "left"), (0, "front"), (90, "right")):
            p.drawText(self._pt(r, yaw, 90) + QPointF(3, 11), label)
        p.drawText(self._pt(r, 180, 0) + QPointF(-22, -3), "0°")
        for n, (yaw, pitch, kept) in enumerate(self._views, 1):
            color = row_color(pitch, kept)
            color.setAlpha(150 if kept else 170)  # light lines: where many cross is where views overlap
            pen = QPen(color, 1.0, Qt.PenStyle.SolidLine if kept else Qt.PenStyle.DashLine)
            p.setPen(pen)
            outline = view_outline(yaw, pitch, self._fov)
            path = QPainterPath()
            prev = None
            for y, pt in outline:
                q = self._pt(r, y, pt)
                if prev is None or abs(y - prev) > 180:  # wrapped around the back: start a new stroke
                    path.moveTo(q)
                else:
                    path.lineTo(q)
                prev = y
            p.drawPath(path)
            p.setBrush(QColor(color.red(), color.green(), color.blue()))
            p.setPen(Qt.PenStyle.NoPen)
            yy = ((yaw + 180) % 360) - 180
            c = self._pt(r, yy, pitch)
            p.drawEllipse(c, 2.6, 2.6)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(color.darker(130))
            p.drawText(c + QPointF(3.5, -2.5), str(n))  # the same number as in the 3D picture
        p.setPen(QPen(grid, 1))
        p.drawRect(r)
        p.end()


# --- the views as virtual cameras in 3D (p124) ---------------------------------------------------------------

SOURCES = ("360", "fisheye", "pairs", "pinhole")


def _basis(azimuth: float = 330.0, elevation: float = 30.0):
    """The drawing's viewer: in front of the source, a little to its left and above, looking back at it (the
    source faces you, so its right is on your left; the labels say which way). Returns (right, up, toward the
    viewer) in the drawing frame (x right, y up, z forward)."""
    a, e = np.radians(azimuth), np.radians(elevation)
    v = np.array([np.sin(a) * np.cos(e), np.sin(e), np.cos(a) * np.cos(e)])
    r = np.cross(v, [0.0, 1.0, 0.0])
    r /= np.linalg.norm(r)
    return r, np.cross(r, v), v


def tile(yaw: float, pitch: float, fov: float, size: float = 0.42) -> np.ndarray:
    """A view as a tile on the sphere: its image's 4 corners, shrunk to *size* of the true field of view so
    neighbours stay apart, on the plane touching the sphere where the view looks (drawing frame, y up)."""
    t = np.tan(np.radians(min(fov, 150.0)) / 2) * size
    corners = np.array([[-t, -t, 1], [t, -t, 1], [t, t, 1], [-t, t, 1]]) @ view_rotation(yaw, pitch)
    return corners * [1, -1, 1]  # source Y down -> drawing y up


def frustum(yaw: float, pitch: float, fov: float, depth: float = 1.0) -> np.ndarray:
    """The 4 far corners of a view's true frustum at *depth* (drawing frame)."""
    return tile(yaw, pitch, fov, 1.0) * depth


def paint_rig(p: QPainter, r: QRectF, views: Sequence[Tuple[float, float, bool]], fov: float, source: str,
              text: QColor, base: QColor) -> None:
    """The views as numbered tiles on a sphere around the source, in *r* (square)."""
    right, up, toward = _basis()
    side = min(r.width(), r.height())
    scale = side * 0.34
    c0 = QPointF(r.center().x(), r.center().y() + side * 0.03)

    def pt(v) -> QPointF:
        return QPointF(c0.x() + float(np.dot(v, right)) * scale, c0.y() - float(np.dot(v, up)) * scale)

    def circle(points, pen_front: QPen, pen_back: QPen, front_only: bool = False):
        for a, b in zip(points[:-1], points[1:]):
            near = np.dot(a + b, toward) > 0
            if front_only and not near:
                continue
            p.setPen(pen_front if near else pen_back)
            p.drawLine(pt(a), pt(b))

    ang = np.linspace(0, 2 * np.pi, 97)
    faint = QColor(text)
    faint.setAlpha(60)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(faint, 1))
    p.drawEllipse(c0, scale, scale)  # the sphere's outline
    horizon = np.column_stack([np.sin(ang), np.zeros_like(ang), np.cos(ang)])
    circle(horizon, QPen(faint, 1), QPen(faint, 1, Qt.PenStyle.DashLine))
    meridian = np.column_stack([np.zeros_like(ang), np.sin(ang), np.cos(ang)])  # front - up - back - down
    circle(meridian, QPen(faint, 1), QPen(faint, 1, Qt.PenStyle.DashLine))
    if source in ("fisheye", "pairs"):  # where one lens ends (a pair: where the two meet)
        seam = np.column_stack([np.sin(ang), np.cos(ang), np.zeros_like(ang)])
        lens = QColor(200, 60, 60, 170)
        circle(seam, QPen(lens, 1.6), QPen(QColor(200, 60, 60, 90), 1.2, Qt.PenStyle.DashLine))
    dark = QColor(text)  # the source in the middle (behind the near tiles)
    dark.setAlpha(200)
    p.setPen(QPen(dark, 1.4))
    p.setBrush(QColor(base))
    p.drawEllipse(pt((0, 0, 0)), 4, 4)
    # views: farthest first, each a tile with its number, a thin line from the center
    items = []
    for n, (yaw, pitch, kept) in enumerate(views, 1):
        f = tile(yaw, pitch, fov)
        items.append((float(np.dot(f.mean(0), toward)), n, f, pitch, kept))
    fm = p.fontMetrics()
    for depth, n, f, pitch, kept in sorted(items, key=lambda it: it[0]):
        color = row_color(pitch, kept)
        near = depth > -0.15
        style = Qt.PenStyle.SolidLine if kept else Qt.PenStyle.DashLine
        ray = QColor(color)
        ray.setAlpha(110 if near else 50)
        p.setPen(QPen(ray, 1, Qt.PenStyle.DotLine))
        p.drawLine(pt((0, 0, 0)), pt(f.mean(0)))
        fill = QColor(color)
        fill.setAlpha(225 if near else 70)
        edge = QColor(color.darker(140))
        edge.setAlpha(255 if near else 90)
        face = QPainterPath(pt(f[0]))
        for corner in f[1:]:
            face.lineTo(pt(corner))
        face.closeSubpath()
        p.setPen(QPen(edge, 1.2, style))
        p.setBrush(fill)
        p.drawPath(face)
        mid = pt(f.mean(0))
        p.setPen(QColor(255, 255, 255) if near else QColor(color.darker(150)))
        w = fm.horizontalAdvance(str(n))
        p.drawText(QPointF(mid.x() - w / 2, mid.y() + fm.ascent() / 2 - 1), str(n))
    p.setBrush(Qt.BrushStyle.NoBrush)
    # which way is front / up / right (on top of everything)
    lab = QColor(text)
    lab.setAlpha(170)
    for vec, name in (((0, 0, 1.32), "front"), ((1.3, 0, 0), "right"), ((0, 1.25, 0), "up")):
        p.setPen(QPen(lab, 1.2))
        tip = pt(vec)
        p.drawLine(pt(np.array(vec) * 0.86), tip)
        p.drawText(tip + QPointF(-fm.horizontalAdvance(name) / 2, -4), name)
    if source in ("fisheye", "pairs"):
        p.setPen(QColor(200, 60, 60))
        note = "lens edge" if source == "fisheye" else "lens seam"
        p.drawText(QPointF(r.left() + 4, r.bottom() - 5), note)


class RigPreview(QWidget):
    """The views as virtual cameras in 3D, numbered like the map beside it (p124)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._views: List[Tuple[float, float, bool]] = []
        self._fov = 90.0
        self._source = "360"
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(190, 190)
        self.setToolTip("The views as cameras around the source, seen from in front (left, above): each tile is one "
                        "image (drawn smaller), numbered like the map. Orange looks up, blue level, green down; "
                        "gray, dashed: left out. Red: where the fisheye lens ends (a pair: where the lenses meet)")

    def set_views(self, pairs: Sequence[Tuple[float, float]], fov: float, kept: Optional[Sequence[bool]] = None,
                  source: str = "360") -> None:
        kept = list(kept) if kept is not None else [True] * len(pairs)
        self._views = [(float(y), float(p), bool(k)) for (y, p), k in zip(pairs, kept)]
        self._fov = float(fov)
        self._source = source if source in SOURCES else "360"
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.fillRect(r, pal.color(pal.ColorRole.Base))
        f = p.font()
        f.setPointSizeF(max(6.5, f.pointSizeF() - 1.5))
        p.setFont(f)
        paint_rig(p, r, self._views, self._fov, self._source, QColor(pal.color(pal.ColorRole.Text)),
                  QColor(pal.color(pal.ColorRole.Base)))
        p.end()
