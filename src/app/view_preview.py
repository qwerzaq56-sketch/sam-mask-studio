"""A small map of the pinhole views a conversion makes (docs/specs/08 P4): where each view looks.

The map is the whole sphere laid flat like a 360 image: left / right = yaw -180..180 (0 = the source's
forward, in the middle), up / down = pitch 90..-90. Each view is its outline on the sphere (the square
image's edges, curved as they are on a 360 image) and a dot at its center; overlaps show where outlines
cross. Views a fisheye cannot fill are drawn gray and dashed: the conversion leaves them out.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from src.core.reproject import view_rotation


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
        on = QColor(40, 110, 220, 150)  # light lines: where many cross is where views overlap
        off = QColor(140, 140, 140, 170)
        for yaw, pitch, kept in self._views:
            color = on if kept else off
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
            p.drawEllipse(self._pt(r, yy, pitch), 2.6, 2.6)
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(grid, 1))
        p.drawRect(r)
        p.end()
