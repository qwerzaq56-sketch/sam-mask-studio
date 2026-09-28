"""The frames: a horizontal strip of thumbnails along the bottom of the window.

Each tile shows the image, its 1-based ID, its status mark (spec 02 §13: ✕
failed, ⚠ warning, ★ manual, ✓ propagated), ◎ for the propagation reference
and 📌 when pinned, and the file name. Click opens an image, Shift/Ctrl-click
picks several (batch masking, the propagation Selection), double-click makes
it the propagation reference. Thumbnails are read a few at a time on the UI
thread (JPEGs decoded at 1/8 size), only for the tiles in view; no threads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

import cv2
import numpy as np
from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import QAbstractItemView, QListView, QListWidget, QVBoxLayout, QWidget

from src.core.project import FrameStatus, Project

# Most important first: a failed or suspicious frame must stand out in a long list.
PRIORITY = (
    (FrameStatus.FAILED, "✕"),
    (FrameStatus.WARNING, "⚠"),
    (FrameStatus.MANUAL, "★"),
    (FrameStatus.PROPAGATED, "✓"),
)


def image_marks(project: Project) -> Dict[str, str]:
    seen: Dict[str, set] = {}
    for o in project.objects:
        for k, fs in o.frames.items():
            if fs.mask is not None:
                seen.setdefault(k, set()).add(fs.status)
    return {k: next(m for st, m in PRIORITY if st in sts) for k, sts in seen.items()}


PIN_COLOR = QColor(255, 225, 140)  # pinned tiles
THUMB_H = 72  # thumbnail height in px
TILE_W = 132  # tile width (the file name is elided to fit)


def read_thumbnail(path: Path, height: int = THUMB_H) -> Optional[np.ndarray]:
    """A small RGB array of *path* (JPEG decoded at reduced size when possible); None if unreadable.

    """
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_REDUCED_COLOR_8) if data.size else None
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    tw = max(1, int(w * height / h))
    small = cv2.cvtColor(cv2.resize(img, (tw, height), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(small)


class ImagesPanel(QWidget):
    navigate_requested = pyqtSignal(int)
    reference_requested = pyqtSignal(int)  # double-click: the propagation reference

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: List[str] = []
        self._paths: List[Path] = []
        self._updating = False
        self._reference: Optional[int] = None
        self._pinned: Set[int] = set()
        self._marks: Dict[str, str] = {}
        self._loaded: Set[int] = set()  # rows whose thumbnail is set (or queued)
        self._pending: List[int] = []  # rows to read, nearest first

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setFlow(QListView.Flow.LeftToRight)
        self.list.setWrapping(False)  # one row, scrolled sideways
        self.list.setMovement(QListView.Movement.Static)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setUniformItemSizes(True)
        self.list.setIconSize(QSize(TILE_W - 12, THUMB_H))
        self.list.setGridSize(QSize(TILE_W, THUMB_H + 44))
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Ctrl/Shift-click picks several images; the clicked one becomes current.
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemDoubleClicked.connect(lambda it: self.reference_requested.emit(self.list.row(it)))
        self.list.setToolTip(
            "Click: open the image · Shift/Ctrl-click: pick images (batch / propagation Selection)\n"
            "Double-click: make it the propagation reference (◎) · shaded tiles are pinned (📌)"
        )
        self.list.horizontalScrollBar().valueChanged.connect(lambda _v: self._visible_timer.start())
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(30)
        self._visible_timer.timeout.connect(self._load_visible)
        # one thumbnail per tick, so the window stays responsive while they load
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(1)
        self._load_timer.timeout.connect(self._load_one)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.list)
        self.setMinimumHeight(THUMB_H + 70)

    # ------------------------------------------------------------------

    def set_images(self, keys: Sequence[str], paths: Optional[Sequence[Path]] = None) -> None:
        self._keys = list(keys)
        self._paths = list(paths) if paths is not None else []
        self._loaded.clear()
        self._pending.clear()
        self._updating = True
        self.list.clear()
        blank = _blank_icon()
        for i in range(len(self._keys)):
            self.list.addItem(self._text(i))
            it = self.list.item(i)
            it.setIcon(blank)
            it.setToolTip(self._keys[i])
            it.setSizeHint(QSize(TILE_W, THUMB_H + 44))
        self._updating = False
        self._visible_timer.start()

    def _text(self, i: int) -> str:
        """Two lines under the thumbnail: ``"12  ★ ◎ 📌"`` then the file name."""
        k = self._keys[i]
        marks = " ".join(m for m in (self._marks.get(k, ""), "◎" if i == self._reference else "",
                                     "📌" if i in self._pinned else "") if m)
        return f"{i + 1}  {marks}\n{k}"

    def status_mark(self, i: int) -> str:
        return self._marks.get(self._keys[i], " ")

    def update_marks(self, project: Project) -> None:
        """Mark each image with the most important status of the Object masks on it."""
        self._marks = image_marks(project)
        self._retext()

    def _retext(self) -> None:
        for i in range(min(self.list.count(), len(self._keys))):
            text = self._text(i)
            it = self.list.item(i)
            if it.text() != text:
                it.setText(text)

    def set_reference(self, index: Optional[int]) -> None:
        """Mark the propagation reference with ◎ (shown on the next update_marks)."""
        self._reference = index

    def set_pinned(self, indices) -> None:
        """Shade the pinned images (the propagation Selection that stays fixed)."""
        pinned = set(indices or ())
        if pinned == self._pinned:
            return
        self._pinned = pinned
        for i in range(self.list.count()):
            self.list.item(i).setBackground(QBrush(PIN_COLOR) if i in pinned else QBrush())
        self._retext()

    def set_current(self, index: int) -> None:
        if self.list.currentRow() == index:
            return  # keep a multi-selection intact
        self._updating = True
        self.list.setCurrentRow(index)
        self._updating = False
        it = self.list.item(index)
        if it is not None:
            self.list.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
        self._visible_timer.start()

    def selected_rows(self) -> list:
        return sorted(self.list.row(it) for it in self.list.selectedItems())

    def _on_row(self, row: int) -> None:
        if not self._updating and row >= 0:
            self.navigate_requested.emit(row)

    # ------------------------------------------------------------------
    # Thumbnails (read off the UI thread, only for the tiles in view)
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._visible_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self._visible_timer.start()

    def _visible_rows(self) -> range:
        n = self.list.count()
        if n == 0:
            return range(0)
        vp = self.list.viewport().rect()
        y = vp.center().y()
        first = self.list.indexAt(QPoint(vp.left() + 2, y)).row()
        last = self.list.indexAt(QPoint(vp.right() - 2, y)).row()
        first = 0 if first < 0 else first
        last = n - 1 if last < 0 else last
        return range(max(0, first - 4), min(n, last + 5))  # a few beyond each edge

    def _load_visible(self) -> None:
        if not self._paths:
            return
        rows = [r for r in self._visible_rows() if r not in self._loaded and r < len(self._paths)]
        self._loaded.update(rows)
        self._pending = rows + [r for r in self._pending if r not in rows]  # in view first
        if self._pending and not self._load_timer.isActive():
            self._load_timer.start()

    def _load_one(self) -> None:
        if not self._pending:
            self._load_timer.stop()
            return
        row = self._pending.pop(0)
        try:
            img = read_thumbnail(self._paths[row])
        except Exception:  # a broken file only loses its thumbnail
            img = None
        it = self.list.item(row)
        if img is not None and it is not None:
            h, w = img.shape[:2]
            qi = QImage(img.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            it.setIcon(QIcon(QPixmap.fromImage(qi)))

    def shutdown(self) -> None:
        self._load_timer.stop()
        self._pending.clear()


def _blank_icon() -> QIcon:
    pm = QPixmap(TILE_W - 12, THUMB_H)
    pm.fill(QColor(70, 70, 76))
    return QIcon(pm)
