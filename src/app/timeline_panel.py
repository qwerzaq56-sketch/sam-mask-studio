"""The Timeline: one row per Object, one cell per frame, colored by where the mask came from (p151).

The Frame List shows each frame's most important status over every Object; the Timeline shows them apart,
so a gap, a run of propagated frames or a warning is seen for the Object it belongs to
(tools.html ③, after Sammie-Roto 2). A click on a cell goes to that frame and selects that Object;
hovering a cell says its status and, for an imported batch mask, where it came from (p150's note).

p154: *By camera* splits each Object's row per camera folder of a rig (a batch run propagates within a folder
only), its cells then the frames' places in that folder; a batch run's detections (SAM3 / keyframe) and the
frames its report says nothing about get their own colors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QAbstractScrollArea, QHBoxLayout, QLabel, QToolButton, QToolTip, QVBoxLayout, QWidget

from src.app.images_panel import REFERENCE_OUTLINE, camera_heads, frame_note
from src.core.project import FrameStatus, Project

# what a cell shows: (fill, words for its tooltip)
KINDS = {
    "manual": (QColor(40, 110, 220), "★ edited here"),
    "propagated": (QColor(70, 165, 95), "✓ propagated"),
    "detected": (QColor(130, 95, 205), "↓ detected in the batch run (SAM3 / keyframe)"),
    "imported": (QColor(150, 150, 150), "↓ imported, unchanged"),
    "unknown": (QColor(205, 205, 205), "↓ imported, not in the batch report (no information)"),
    "warning": (QColor(230, 140, 0), "⚠ worth a look"),
    "failed": (QColor(215, 40, 40), "✕ empty after propagation"),
}
FILL = {k: c for k, (c, _w) in KINDS.items()}
WORDS = {k: w for k, (_c, w) in KINDS.items()}
STATUS_KIND = {
    FrameStatus.MANUAL: "manual",
    FrameStatus.PROPAGATED: "propagated",
    FrameStatus.IMPORTED: "imported",
    FrameStatus.WARNING: "warning",
    FrameStatus.FAILED: "failed",
}
LEGEND = ("<span style='color:#286edc'>■</span>★ <span style='color:#46a55f'>■</span>✓ "
          "<span style='color:#825fcd'>■</span>↓ found <span style='color:#969696'>■</span>↓ "
          "<span style='color:#cdcdcd'>■</span>↓ ? <span style='color:#e68c00'>■</span>⚠ "
          "<span style='color:#d72828'>■</span>✕ · blank: no mask")
LEGEND_TIP = ("★ edited here · ✓ propagated · ↓ found = detected in a batch run (SAM3 / keyframe) · ↓ imported · "
              "↓ ? = imported, the batch report says nothing about it · ⚠ worth a look · ✕ empty after propagation.\n"
              "Click a cell: that frame and Object. Click a name: that Object, on its nearest frame with a mask.\n"
              "Hover a cell: its status and where it came from (a batch report, or the run it was propagated in).\n"
              "Right-click a propagated cell: clear its run from there on (Objects > Clear a Propagation Run…).\n"
              "By camera (a rig): a row per Object and camera folder, a cell per frame's place in that folder.")

ROW_H = 18
HEAD_H = 14  # the line over the rows: the open frame ▼, the reference ◎, camera names
NAME_W = 130
CELL_MIN, CELL_MAX = 3, 14


def cell_kind(fs, reported: bool) -> str:
    """What a mask's cell shows. *reported*: its Object came with a batch report (some frame has its note)."""
    kind = STATUS_KIND.get(fs.status, "imported")
    if kind == "imported" and reported:
        return "detected" if fs.note else "unknown"
    return kind


def object_kinds(project: Project) -> List[Tuple[int, str, Dict[str, str]]]:
    """(Object id, name, image key -> its cell kind) per Object; frames without a mask left out."""
    rows = []
    for o in project.objects:
        reported = any(fs.note for fs in o.frames.values())
        rows.append((o.id, o.name, {k: cell_kind(fs, reported) for k, fs in o.frames.items()
                                    if fs.mask is not None}))
    return rows


def camera_of(key: str) -> str:
    return key.rpartition("/")[0]


@dataclass(frozen=True)
class Row:
    """One line: an Object (in one camera folder when split), its cells' image keys left to right."""

    oid: int
    label: str
    cols: Tuple[Optional[str], ...]
    kinds: Dict[str, str]

    @property
    def count(self) -> int:
        return sum(1 for k in self.cols if k is not None and k in self.kinds)


def build_rows(keys: Sequence[str], objects, split: bool) -> List[Row]:
    """The Timeline's lines: an Object each, or (*split*, with camera folders) an Object and camera each."""
    keys = tuple(keys)
    cams: Dict[str, List[str]] = {}
    for k in keys:
        cams.setdefault(camera_of(k), []).append(k)
    if not split or len(cams) < 2:
        return [Row(oid, name, keys, kinds) for oid, name, kinds in objects]
    width = max(len(v) for v in cams.values())
    rows = []
    for oid, name, kinds in objects:
        for cam, ks in cams.items():
            rows.append(Row(oid, f"{name} · {cam or '(images)'}", tuple(ks) + (None,) * (width - len(ks)), kinds))
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
        self._index: Dict[str, int] = {}
        self._objects: list = []
        self._rows: List[Row] = []
        self._split = False
        self._cols = 0
        self._pos: Dict[str, int] = {}  # image key -> its column
        self._notes: Dict[Tuple[int, str], str] = {}
        self._heads: Dict[int, str] = {}
        self._current: Optional[int] = None
        self._reference: Optional[int] = None
        self._selected: Tuple[int, ...] = ()

    # --- data ------------------------------------------------------------------------------

    def set_data(self, keys: Sequence[str], objects, notes, current, reference, selected,
                 split: bool = False) -> None:
        """*objects*: (Object id, name, image key -> cell kind) each, as :func:`object_kinds` makes them."""
        keys = list(keys)
        state = (keys, objects, notes, current, reference, tuple(selected), split)
        if state == (self._keys, self._objects, self._notes, self._current, self._reference, self._selected,
                     self._split):
            return
        relaid = keys != self._keys or split != self._split or len(objects) != len(self._objects)
        if keys != self._keys:
            self._heads = camera_heads(keys)
            self._index = {k: i for i, k in enumerate(keys)}
        self._keys, self._objects, self._notes, self._split = keys, objects, notes, split
        self._rows = build_rows(keys, objects, split)
        self._pos = {}
        for r in self._rows[:max(1, len(self._rows) // max(1, len(objects)))]:  # one Object's rows lay it out
            for c, k in enumerate(r.cols):
                if k is not None:
                    self._pos.setdefault(k, c)
        if not self._rows:
            self._pos = {k: i for i, k in enumerate(keys)}
        self._cols = len(self._rows[0].cols) if self._rows else len(keys)
        moved = current != self._current or relaid
        self._current, self._reference, self._selected = current, reference, tuple(selected)
        self._layout()
        if moved:
            self.show_frame(current)
        self.viewport().update()

    @property
    def split(self) -> bool:
        """Rows per camera folder (the rig had more than one)."""
        return len(self._rows) != len(self._objects)

    def set_preview(self, frames: Dict[int, Sequence[str]]) -> None:
        """Cross out the cells a Clear would remove ({Object id: image keys}); {} ends the preview."""
        preview = {oid: set(keys) for oid, keys in frames.items() if keys}
        if preview != self._preview:
            self._preview = preview
            self.viewport().update()

    def cell_width(self) -> int:
        n = max(1, self._cols)
        room = self.viewport().width() - NAME_W
        return max(CELL_MIN, min(CELL_MAX, room // n)) if room > 0 else CELL_MIN

    def _layout(self) -> None:
        w = self.cell_width()
        hs, vs = self.horizontalScrollBar(), self.verticalScrollBar()
        hs.setRange(0, max(0, self._cols * w - (self.viewport().width() - NAME_W)))
        hs.setPageStep(max(1, self.viewport().width() - NAME_W))
        hs.setSingleStep(w * 5)
        vs.setRange(0, max(0, HEAD_H + len(self._rows) * ROW_H - self.viewport().height()))
        vs.setPageStep(max(1, self.viewport().height()))
        vs.setSingleStep(ROW_H)

    def _col(self, index: Optional[int]) -> Optional[int]:
        """The column frame *index* is in."""
        if index is None or not (0 <= index < len(self._keys)):
            return None
        return self._pos.get(self._keys[index])

    def show_frame(self, index: Optional[int]) -> None:
        """Scroll the open frame into view (sideways)."""
        col = self._col(index)
        if col is None:
            return
        w, hs = self.cell_width(), self.horizontalScrollBar()
        room = self.viewport().width() - NAME_W
        x = col * w
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

    def cell_at(self, pos: QPoint) -> Optional[Tuple[int, Optional[int]]]:
        """(row, frame index) under *pos* (viewport coordinates); the frame is None over the names.
        None off the rows and on a split row's empty end (that camera has fewer frames)."""
        y = pos.y() - HEAD_H + self.verticalScrollBar().value()
        if pos.y() < HEAD_H or y < 0 or y // ROW_H >= len(self._rows):
            return None
        row = y // ROW_H
        if pos.x() < NAME_W:
            return row, None
        c = (pos.x() - NAME_W + self.horizontalScrollBar().value()) // self.cell_width()
        cols = self._rows[row].cols
        key = cols[c] if 0 <= c < len(cols) else None
        return (row, self._index[key]) if key is not None else None

    def mousePressEvent(self, e):
        hit = self.cell_at(e.position().toPoint())
        if hit is not None and hit[1] is not None and e.button() == Qt.MouseButton.RightButton:
            self.cell_menu.emit(self._rows[hit[0]].oid, hit[1], e.globalPosition().toPoint())
        if hit is not None and e.button() == Qt.MouseButton.LeftButton:
            row, i = hit
            self.cell_clicked.emit(self._rows[row].oid, -1 if i is None else i)  # -1: the name
        super().mousePressEvent(e)

    def viewportEvent(self, e):
        if e.type() == QEvent.Type.ToolTip:
            hit = self.cell_at(e.pos())
            if hit is None or hit[1] is None:
                QToolTip.hideText()
                if hit is not None:
                    QToolTip.showText(e.globalPos(), self._rows[hit[0]].label, self.viewport())
                return True
            QToolTip.showText(e.globalPos(), self.cell_text(*hit), self.viewport())
            return True
        return super().viewportEvent(e)

    def cell_text(self, row: int, i: int) -> str:
        """The tooltip of row *row*'s cell for frame *i*."""
        r = self._rows[row]
        key = self._keys[i]
        kind = r.kinds.get(key)
        text = f"{i + 1}  {key}\n{r.label}: {WORDS[kind] if kind is not None else 'no mask'}"
        note = self._notes.get((r.oid, key))
        return f"{text}\n{note}" if note else text

    # --- painting ----------------------------------------------------------------------------

    def paintEvent(self, e):
        p = QPainter(self.viewport())
        pal = self.palette()
        vw, vh = self.viewport().width(), self.viewport().height()
        w = self.cell_width()
        cw = max(1, w - (1 if w > 4 else 0))
        hx, vy = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        first, last = max(0, hx // w), min(self._cols, (hx + vw - NAME_W) // w + 2)
        line = QColor(pal.text().color())
        line.setAlpha(40)
        mid = QColor(pal.text().color())
        mid.setAlpha(14)
        sel = QColor(pal.highlight().color())
        sel.setAlpha(45)
        cur = QColor(pal.highlight().color())
        cur.setAlpha(70)
        fm = QFontMetrics(self.font())
        n = len(self._keys)
        cur_key = self._keys[self._current] if self._current is not None and 0 <= self._current < n else None
        ref_key = self._keys[self._reference] if self._reference is not None and 0 <= self._reference < n else None
        cur_col, ref_col = self._pos.get(cur_key), self._pos.get(ref_key)
        whole = not self.split  # every row has every frame: the open / reference frame is a whole column

        p.save()
        p.setClipRect(QRect(NAME_W, 0, vw - NAME_W, vh))
        prev_oid = None
        for r, row in enumerate(self._rows):
            y = HEAD_H + r * ROW_H - vy
            new_object = row.oid != prev_oid
            prev_oid = row.oid
            if y + ROW_H < HEAD_H or y > vh:
                continue
            if row.oid in self._selected:
                p.fillRect(NAME_W, y, vw - NAME_W, ROW_H, sel)
            elif r % 2:
                p.fillRect(NAME_W, y, vw - NAME_W, ROW_H, mid)
            gone = self._preview.get(row.oid, ())
            for c in range(first, min(last, len(row.cols))):
                k = row.cols[c]
                if k is None:
                    continue
                x = NAME_W + c * w - hx
                kind = row.kinds.get(k)
                if kind is not None:
                    p.fillRect(x, y + 2, cw, ROW_H - 4, FILL[kind])
                if k in gone:  # what a Clear would remove: dimmed, with a dark line through
                    p.fillRect(x, y + 2, cw, ROW_H - 4, QColor(255, 255, 255, 170))
                    p.fillRect(x, y + ROW_H // 2 - 1, max(1, w), 2, QColor(40, 40, 40))
                if not whole and k == cur_key:
                    p.fillRect(x, y, max(2, w), ROW_H, cur)
                if not whole and k == ref_key:
                    p.setPen(QPen(REFERENCE_OUTLINE, 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(x, y + 1, max(2, w - 1), ROW_H - 2)
            if not whole and new_object and r:  # a line between Objects
                p.fillRect(NAME_W, y, vw - NAME_W, 1, line)
        if whole:
            # camera folders: a line where the next one starts, its name in the head line
            p.setPen(QPen(line, 1))
            for i, head in self._heads.items():
                x = NAME_W + i * w - hx
                if i and NAME_W <= x <= vw:
                    p.drawLine(x, 0, x, vh)
                if NAME_W - 200 <= x <= vw:
                    p.drawText(QRect(x + 3, 0, 200, HEAD_H), Qt.AlignmentFlag.AlignVCenter, head.split(" · ")[0])
            # the reference ◎: an orange frame round its column; the open frame: a filled column
            if ref_col is not None:
                x = NAME_W + ref_col * w - hx
                p.setPen(QPen(REFERENCE_OUTLINE, 2))
                p.drawRect(x, HEAD_H, max(2, w - 1), vh - HEAD_H - 1)
            if cur_col is not None:
                p.fillRect(NAME_W + cur_col * w - hx, HEAD_H, max(2, w), vh - HEAD_H, cur)
        elif w * 10 >= 24:  # split: places in the folder, every tenth
            p.setPen(QPen(line, 1))
            for c in range(9, self._cols, 10):
                x = NAME_W + c * w - hx
                if NAME_W - 30 <= x <= vw:
                    p.drawText(QRect(x - 15, 0, 30 + w, HEAD_H), Qt.AlignmentFlag.AlignCenter, str(c + 1))
        if cur_col is not None:  # ▼ over the open frame's column
            x = NAME_W + cur_col * w - hx
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(pal.highlight())
            c = x + w // 2
            p.drawPolygon([QPoint(c - 5, 1), QPoint(c + 5, 1), QPoint(c, HEAD_H - 2)])
        p.restore()

        # names: they stay put when the cells scroll sideways
        p.fillRect(0, 0, NAME_W, vh, pal.base())
        p.setPen(pal.text().color())
        prev_oid = None
        for r, row in enumerate(self._rows):
            y = HEAD_H + r * ROW_H - vy
            new_object = row.oid != prev_oid
            prev_oid = row.oid
            if y + ROW_H < HEAD_H or y > vh:
                continue
            if row.oid in self._selected:
                p.fillRect(0, y, NAME_W, ROW_H, sel)
            if not whole and new_object and r:
                p.fillRect(0, y, NAME_W, 1, line)
            p.setPen(pal.text().color())
            label = f"{row.label}  {row.count}"
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
    """The Timeline dock: the legend and the By camera switch over the grid."""

    cell_clicked = pyqtSignal(int, int)  # Object id, frame index (-1: its name)
    cell_menu = pyqtSignal(int, int, QPoint)
    split_toggled = pyqtSignal(bool)  # By camera switched (remembered in Settings)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.legend = QLabel(LEGEND)
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setToolTip(LEGEND_TIP)
        self.legend.setMinimumWidth(10)
        self.split_btn = QToolButton()
        self.split_btn.setText("By camera")
        self.split_btn.setCheckable(True)
        self.split_btn.setAutoRaise(True)
        self.split_btn.setToolTip("A row per Object and camera folder (a rig): the folders one under another, "
                                  "a cell per frame's place in its folder")
        self.split_btn.setVisible(False)  # shown when the images sit in camera folders
        self.split_btn.toggled.connect(self._split_toggled)
        self.view = TimelineView()
        self.view.cell_clicked.connect(self.cell_clicked)
        self.view.cell_menu.connect(self.cell_menu)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.legend, 1)
        top.addWidget(self.split_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 4)
        lay.setSpacing(2)
        lay.addLayout(top)
        lay.addWidget(self.view, 1)
        self._stale = None
        self._last = None

    def _split_toggled(self, on: bool) -> None:
        if self._last is not None:
            self.update_from(*self._last)
        self.split_toggled.emit(on)

    def set_split(self, on: bool) -> None:
        """By camera on / off without telling (from Settings)."""
        self.split_btn.blockSignals(True)
        self.split_btn.setChecked(bool(on))
        self.split_btn.blockSignals(False)
        if self._last is not None:
            self.update_from(*self._last)

    def update_from(self, project: Project, keys: Sequence[str], current: Optional[int],
                    reference: Optional[int], selected: Sequence[int]) -> None:
        self._last = (project, keys, current, reference, selected)
        self.split_btn.setVisible(len({camera_of(k) for k in keys}) > 1)
        if not self.isVisible():
            self._stale = self._last  # drawn when the tab is shown
            return
        self._stale = None
        notes = {(o.id, k): n for o in project.objects for k, fs in o.frames.items() if (n := frame_note(fs))}
        self.view.set_data(keys, object_kinds(project), notes, current, reference, selected,
                           split=self.split_btn.isChecked())

    def showEvent(self, e):
        super().showEvent(e)
        if self._stale is not None:
            self.update_from(*self._stale)
