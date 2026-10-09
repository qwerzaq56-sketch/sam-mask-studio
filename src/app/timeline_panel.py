"""The Timeline: one row per Object, one cell per frame, colored by where the mask came from (p151).

The Frame List shows each frame's most important status over every Object; the Timeline shows them apart,
so a gap, a run of propagated frames or a warning is seen for the Object it belongs to
(tools.html ③, after Sammie-Roto 2). A click on a cell goes to that frame and selects that Object;
hovering a cell says its status and, for an imported batch mask, where it came from (p150's note).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QAbstractScrollArea, QLabel, QToolTip, QVBoxLayout, QWidget

from src.app.images_panel import REFERENCE_OUTLINE, camera_heads, frame_note
from src.core.project import FrameStatus, Project

FILL = {  # the cell colors: the Frame List's mark colors, ✓ and ↓ told apart here
    FrameStatus.MANUAL: QColor(40, 110, 220),
    FrameStatus.PROPAGATED: QColor(70, 165, 95),
    FrameStatus.IMPORTED: QColor(150, 150, 150),
    FrameStatus.WARNING: QColor(230, 140, 0),
    FrameStatus.FAILED: QColor(215, 40, 40),
}
WORDS = {
    FrameStatus.MANUAL: "★ edited here",
    FrameStatus.PROPAGATED: "✓ propagated",
    FrameStatus.IMPORTED: "↓ imported, unchanged",
    FrameStatus.WARNING: "⚠ worth a look",
    FrameStatus.FAILED: "✕ empty after propagation",
}
LEGEND = ("<span style='color:#286edc'>■</span>★ <span style='color:#46a55f'>■</span>✓ "
          "<span style='color:#969696'>■</span>↓ <span style='color:#e68c00'>■</span>⚠ "
          "<span style='color:#d72828'>■</span>✕ · blank: no mask")
LEGEND_TIP = ("★ edited here · ✓ propagated · ↓ imported, unchanged · ⚠ worth a look · ✕ empty after propagation.\n"
              "Click a cell: that frame and Object. Click a name: that Object, on its nearest frame with a mask.\n"
              "Hover a cell: its status and where it came from (a batch report, or the run it was propagated in).\n"
              "Right-click a propagated cell: clear its run from there on (Objects > Clear a Propagation Run…).")

ROW_H = 18
HEAD_H = 14  # the line over the rows: the open frame ▼, the reference ◎, camera names
NAME_W = 130
CELL_MIN, CELL_MAX = 3, 14


def object_rows(project: Project) -> List[Tuple[int, str, Dict[str, FrameStatus]]]:
    """(Object id, name, image key -> status of its mask there) per Object; frames without a mask left out."""
    rows = []
    for o in project.objects:
        rows.append((o.id, o.name, {k: fs.status for k, fs in o.frames.items() if fs.mask is not None}))
    return rows


class TimelineView(QAbstractScrollArea):
    """The grid: names on the left (they stay when the frames scroll sideways), a cell per frame."""

    cell_clicked = pyqtSignal(int, int)  # Object id, frame index (-1: its name)
    cell_menu = pyqtSignal(int, int, QPoint)  # right-click on a cell: Object id, frame index, where (global)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preview: Dict[int, set] = {}  # Object id -> image keys a Clear would remove (p152), crossed out
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.viewport().setMouseTracking(True)
        self._keys: List[str] = []
        self._rows: List[Tuple[int, str, Dict[str, FrameStatus]]] = []
        self._notes: Dict[Tuple[int, str], str] = {}
        self._heads: Dict[int, str] = {}
        self._current: Optional[int] = None
        self._reference: Optional[int] = None
        self._selected: Tuple[int, ...] = ()

    # --- data ------------------------------------------------------------------------------

    def set_data(self, keys: Sequence[str], rows, notes, current, reference, selected) -> None:
        keys = list(keys)
        state = (keys, rows, notes, current, reference, tuple(selected))
        if state == (self._keys, self._rows, self._notes, self._current, self._reference, self._selected):
            return
        if keys != self._keys:
            self._heads = camera_heads(keys)
        self._keys, self._rows, self._notes = keys, rows, notes
        moved = current != self._current
        self._current, self._reference, self._selected = current, reference, tuple(selected)
        self._layout()
        if moved:
            self.show_frame(current)
        self.viewport().update()

    def set_preview(self, frames: Dict[int, Sequence[str]]) -> None:
        """Cross out the cells a Clear would remove ({Object id: image keys}); {} ends the preview."""
        preview = {oid: set(keys) for oid, keys in frames.items() if keys}
        if preview != self._preview:
            self._preview = preview
            self.viewport().update()

    def cell_width(self) -> int:
        n = max(1, len(self._keys))
        room = self.viewport().width() - NAME_W
        return max(CELL_MIN, min(CELL_MAX, room // n)) if room > 0 else CELL_MIN

    def _layout(self) -> None:
        w = self.cell_width()
        hs, vs = self.horizontalScrollBar(), self.verticalScrollBar()
        hs.setRange(0, max(0, len(self._keys) * w - (self.viewport().width() - NAME_W)))
        hs.setPageStep(max(1, self.viewport().width() - NAME_W))
        hs.setSingleStep(w * 5)
        vs.setRange(0, max(0, HEAD_H + len(self._rows) * ROW_H - self.viewport().height()))
        vs.setPageStep(max(1, self.viewport().height()))
        vs.setSingleStep(ROW_H)

    def show_frame(self, index: Optional[int]) -> None:
        """Scroll the open frame into view (sideways)."""
        if index is None:
            return
        w, hs = self.cell_width(), self.horizontalScrollBar()
        room = self.viewport().width() - NAME_W
        x = index * w
        if x < hs.value():
            hs.setValue(x)
        elif x + w > hs.value() + room:
            hs.setValue(x + w - room)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout()

    def sizeHint(self) -> QSize:
        return QSize(600, HEAD_H + ROW_H * max(3, min(8, len(self._rows))) + 6)

    def minimumSizeHint(self) -> QSize:
        return QSize(NAME_W + 60, HEAD_H + ROW_H * 2)

    # --- where things are --------------------------------------------------------------------

    def cell_at(self, pos: QPoint) -> Optional[Tuple[int, int]]:
        """(row, frame index) under *pos* (viewport coordinates); the frame is None over the names."""
        y = pos.y() - HEAD_H + self.verticalScrollBar().value()
        if pos.y() < HEAD_H or y < 0 or y // ROW_H >= len(self._rows):
            return None
        row = y // ROW_H
        if pos.x() < NAME_W:
            return row, None
        i = (pos.x() - NAME_W + self.horizontalScrollBar().value()) // self.cell_width()
        return (row, i) if 0 <= i < len(self._keys) else None

    def mousePressEvent(self, e):
        hit = self.cell_at(e.position().toPoint())
        if hit is not None and hit[1] is not None and e.button() == Qt.MouseButton.RightButton:
            self.cell_menu.emit(self._rows[hit[0]][0], hit[1], e.globalPosition().toPoint())
        if hit is not None and e.button() == Qt.MouseButton.LeftButton:
            row, i = hit
            self.cell_clicked.emit(self._rows[row][0], -1 if i is None else i)  # -1: the name
        super().mousePressEvent(e)

    def viewportEvent(self, e):
        if e.type() == QEvent.Type.ToolTip:
            hit = self.cell_at(e.pos())
            if hit is None or hit[1] is None:
                QToolTip.hideText()
                if hit is not None:
                    QToolTip.showText(e.globalPos(), self._rows[hit[0]][1], self.viewport())
                return True
            QToolTip.showText(e.globalPos(), self.cell_text(*hit), self.viewport())
            return True
        return super().viewportEvent(e)

    def cell_text(self, row: int, i: int) -> str:
        oid, name, frames = self._rows[row]
        key = self._keys[i]
        st = frames.get(key)
        text = f"{i + 1}  {key}\n{name}: {WORDS[st] if st is not None else 'no mask'}"
        note = self._notes.get((oid, key))
        return f"{text}\n{note}" if note else text

    # --- painting ----------------------------------------------------------------------------

    def paintEvent(self, e):
        p = QPainter(self.viewport())
        pal = self.palette()
        vw, vh = self.viewport().width(), self.viewport().height()
        w = self.cell_width()
        hx, vy = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        n = len(self._keys)
        first, last = max(0, hx // w), min(n, (hx + vw - NAME_W) // w + 2)
        line = QColor(pal.text().color())
        line.setAlpha(40)
        mid = QColor(pal.text().color())
        mid.setAlpha(14)
        fm = QFontMetrics(self.font())

        p.save()
        p.setClipRect(QRect(NAME_W, 0, vw - NAME_W, vh))
        # rows: stripes, the selected Objects' rows tinted
        for r, (oid, _name, frames) in enumerate(self._rows):
            y = HEAD_H + r * ROW_H - vy
            if y + ROW_H < HEAD_H or y > vh:
                continue
            if oid in self._selected:
                sel = QColor(pal.highlight().color())
                sel.setAlpha(45)
                p.fillRect(NAME_W, y, vw - NAME_W, ROW_H, sel)
            elif r % 2:
                p.fillRect(NAME_W, y, vw - NAME_W, ROW_H, mid)
            for i in range(first, last):
                st = frames.get(self._keys[i])
                if st is not None:
                    p.fillRect(NAME_W + i * w - hx, y + 2, max(1, w - (1 if w > 4 else 0)), ROW_H - 4, FILL[st])
            gone = self._preview.get(oid)
            if gone:  # what a Clear would remove: dimmed, with a dark line through
                for i in range(first, last):
                    if self._keys[i] in gone:
                        x = NAME_W + i * w - hx
                        p.fillRect(x, y + 2, max(1, w - (1 if w > 4 else 0)), ROW_H - 4, QColor(255, 255, 255, 170))
                        p.fillRect(x, y + ROW_H // 2 - 1, max(1, w), 2, QColor(40, 40, 40))
        # camera folders: a line where the next one starts, its name in the head line
        p.setPen(QPen(line, 1))
        for i, head in self._heads.items():
            x = NAME_W + i * w - hx
            if i and NAME_W <= x <= vw:
                p.drawLine(x, 0, x, vh)
            if NAME_W - 200 <= x <= vw:
                p.drawText(QRect(x + 3, 0, 200, HEAD_H), Qt.AlignmentFlag.AlignVCenter, head.split(" · ")[0])
        # the reference ◎: an orange frame round its column; the open frame: a filled column and ▼
        if self._reference is not None and 0 <= self._reference < n:
            x = NAME_W + self._reference * w - hx
            p.setPen(QPen(REFERENCE_OUTLINE, 2))
            p.drawRect(x, HEAD_H, max(2, w - 1), vh - HEAD_H - 1)
        if self._current is not None and 0 <= self._current < n:
            x = NAME_W + self._current * w - hx
            cur = QColor(pal.highlight().color())
            cur.setAlpha(70)
            p.fillRect(x, HEAD_H, max(2, w), vh - HEAD_H, cur)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(pal.highlight())
            c = x + w // 2
            p.drawPolygon([QPoint(c - 5, 1), QPoint(c + 5, 1), QPoint(c, HEAD_H - 2)])
        p.restore()

        # names: they stay put when the cells scroll sideways
        p.fillRect(0, 0, NAME_W, vh, pal.base())
        p.setPen(pal.text().color())
        for r, (oid, name, frames) in enumerate(self._rows):
            y = HEAD_H + r * ROW_H - vy
            if y + ROW_H < HEAD_H or y > vh:
                continue
            if oid in self._selected:
                sel = QColor(pal.highlight().color())
                sel.setAlpha(45)
                p.fillRect(0, y, NAME_W, ROW_H, sel)
            label = f"{name}  {len(frames)}"
            p.drawText(QRect(4, y, NAME_W - 8, ROW_H), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(label, Qt.TextElideMode.ElideMiddle, NAME_W - 8))
        p.setPen(QPen(line, 1))
        p.drawLine(NAME_W - 1, 0, NAME_W - 1, vh)
        p.drawLine(0, HEAD_H - 1, vw, HEAD_H - 1)
        if not self._rows:
            p.setPen(pal.placeholderText().color())
            p.drawText(QRect(NAME_W + 8, HEAD_H, vw - NAME_W - 8, ROW_H * 2), Qt.AlignmentFlag.AlignVCenter,
                       "No Objects yet")


class TimelinePanel(QWidget):
    """The Timeline dock: the legend over the grid."""

    cell_clicked = pyqtSignal(int, int)  # Object id, frame index (-1: its name)
    cell_menu = pyqtSignal(int, int, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.legend = QLabel(LEGEND)
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setToolTip(LEGEND_TIP)
        self.legend.setMinimumWidth(10)
        self.view = TimelineView()
        self.view.cell_clicked.connect(self.cell_clicked)
        self.view.cell_menu.connect(self.cell_menu)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(2)
        lay.addWidget(self.legend)
        lay.addWidget(self.view, 1)

    def update_from(self, project: Project, keys: Sequence[str], current: Optional[int],
                    reference: Optional[int], selected: Sequence[int]) -> None:
        if not self.isVisible():
            self._stale = (project, keys, current, reference, selected)  # drawn when the tab is shown
            return
        self._stale = None
        notes = {(o.id, k): n for o in project.objects for k, fs in o.frames.items() if (n := frame_note(fs))}
        self.view.set_data(keys, object_rows(project), notes, current, reference, selected)

    def showEvent(self, e):
        super().showEvent(e)
        stale = getattr(self, "_stale", None)
        if stale is not None:
            self.update_from(*stale)
