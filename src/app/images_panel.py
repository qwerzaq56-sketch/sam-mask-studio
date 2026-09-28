"""The frames: a thumbnail strip along the bottom, and a one-line-per-image list.

Both views show the same model with one selection model, so the current
image, the picked images, ◎ and 📌 are always the same in both.
The strip:

Each tile shows the image, its 1-based ID, its status mark (spec 02 §13: ✕
failed, ⚠ warning, ★ manual, ✓ propagated; colored, counted in the summary
labels, and for one Object only with – where it has no mask), ◎ for the propagation reference
and 📌 when pinned, and the file name. Click opens an image, Shift/Ctrl-click
picks several (batch masking, the propagation Selection), double-click makes
it the propagation reference. Thumbnails are cached on disk (in the project's
sidecar folder) and read on the UI thread in ~8 ms slices, the tiles in view
first, then the rest of the folder while idle; no threads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

import cv2
import numpy as np
from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QListView,
    QListWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from src.core.project import FrameStatus, Project

# Most important first: a failed or suspicious frame must stand out in a long list.
PRIORITY = (
    (FrameStatus.FAILED, "✕"),
    (FrameStatus.WARNING, "⚠"),
    (FrameStatus.MANUAL, "★"),
    (FrameStatus.PROPAGATED, "✓"),
)


NO_MASK = "–"  # marks for one Object: it has no mask on this image
PROBLEMS = ("✕", "⚠", NO_MASK)  # what [ / ] jump between
MARK_COLORS = {  # the mark's text color in both views (✓ keeps the default)
    "✕": QColor(215, 40, 40),
    "⚠": QColor(215, 130, 0),
    "★": QColor(40, 110, 220),
    NO_MASK: QColor(150, 150, 150),
}
LEGEND = "★ edited here · ✓ propagated · ⚠ suspicious (area jumped) · ✕ empty after propagation"
LEGEND_ONE = LEGEND + " · – the Object has no mask here"


def image_marks(project: Project, only: Optional[int] = None) -> Dict[str, str]:
    """Each image's most important status of the Object masks on it.

    With *only* (an Object id) just that Object counts, and every image
    without its mask is marked ``–``.
    """
    seen: Dict[str, set] = {}
    for o in project.objects:
        if only is not None and o.id != only:
            continue
        for k, fs in o.frames.items():
            if fs.mask is not None:
                seen.setdefault(k, set()).add(fs.status)
    return {k: next(m for st, m in PRIORITY if st in sts) for k, sts in seen.items()}


PIN_COLOR = QColor(255, 225, 140)  # pinned tiles
THUMB_H = 72  # thumbnail height in px
TILE_W = 132  # tile width (the file name is elided to fit)


def read_thumbnail(path: Path, height: int = THUMB_H) -> Optional[np.ndarray]:
    """A small RGB array of *path* (JPEG decoded at reduced size when possible); None if unreadable."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_REDUCED_COLOR_8) if data.size else None
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    tw = max(1, int(w * height / h))
    small = cv2.cvtColor(cv2.resize(img, (tw, height), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(small)


def cached_thumbnail(path: Path, cache: Optional[Path]) -> Optional[np.ndarray]:
    """read_thumbnail through a disk cache (``<cache>/<name>.jpg``, rebuilt when the image is newer)."""
    if cache is not None:
        c = cache / f"{path.name}.jpg"
        try:
            if c.is_file() and c.stat().st_mtime >= path.stat().st_mtime:
                img = cv2.imdecode(np.fromfile(str(c), dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is not None:
                    return np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        except OSError:
            pass
    img = read_thumbnail(path)
    if img is not None and cache is not None:
        try:
            cache.mkdir(parents=True, exist_ok=True)
            ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                buf.tofile(str(cache / f"{path.name}.jpg"))
        except OSError:
            pass  # a read-only folder just means no cache
    return img


class OneLineDelegate(QStyledItemDelegate):
    """The vertical frame list: ``12  ★ ◎ 📌  name`` on one line, no thumbnail."""

    names = True  # False: only the ID and the marks (a narrower list)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Qt has already turned the line break into a line separator (U+2028)
        first, _, name = option.text.replace("\n", "\u2028").partition("\u2028")
        option.text = f"{first}   {name}" if self.names else first
        option.icon = QIcon()
        option.features &= ~option.ViewItemFeature.HasDecoration

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), option.fontMetrics.height() + 6)


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
        self._only: Optional[int] = None  # marks for this Object only (None: every Object)
        self._summaries: List[QLabel] = []
        self._loaded: Set[int] = set()  # rows whose thumbnail is set (or queued)
        self._pending: List[int] = []  # rows to read, nearest first
        self._cache: Optional[Path] = None  # thumbnail cache folder

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
            "Double-click: make it the propagation reference (◎) · shaded tiles are pinned (📌)\n" + LEGEND_ONE
        )
        self.list.horizontalScrollBar().valueChanged.connect(lambda _v: self._visible_timer.start())
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(30)
        self._visible_timer.timeout.connect(self._load_visible)
        # thumbnails in ~8 ms slices, so the window stays responsive while they load
        self._load_timer = QTimer(self)
        self._load_timer.setInterval(1)
        self._load_timer.timeout.connect(self._load_some)

        # The vertical list: the strip's own model and selection, one line per image.
        self.frame_list = QListView()
        self.frame_list.setModel(self.list.model())
        self.frame_list.setSelectionModel(self.list.selectionModel())
        self._delegate = OneLineDelegate(self.frame_list)
        self.frame_list.setItemDelegate(self._delegate)
        self.frame_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.frame_list.setUniformItemSizes(True)
        self.frame_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.frame_list.doubleClicked.connect(lambda ix: self.reference_requested.emit(ix.row()))
        self.frame_list.setToolTip(self.list.toolTip())
        self.frame_list.setMinimumWidth(170)  # ID, marks and most of the file name
        # names are elided, never scrolled sideways (no horizontal bar, folded or not)
        self.frame_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.list)
        self.setMinimumHeight(THUMB_H + 70)

    # ------------------------------------------------------------------

    def set_images(
        self, keys: Sequence[str], paths: Optional[Sequence[Path]] = None, cache: Optional[Path] = None
    ) -> None:
        self._keys = list(keys)
        self._paths = list(paths) if paths is not None else []
        self._cache = cache
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

    def update_marks(self, project: Project, only: Optional[int] = None) -> None:
        """Mark each image with the most important status of the Object masks on it.

        *only*: an Object id — its marks alone, ``–`` where it has no mask.
        """
        marks = image_marks(project, only)
        if only is not None:
            marks = {k: marks.get(k, NO_MASK) for k in self._keys}
        self._marks = marks
        self._only = only
        self._retext()
        self._summarize()

    def _retext(self) -> None:
        for i in range(min(self.list.count(), len(self._keys))):
            text = self._text(i)
            it = self.list.item(i)
            if it.text() != text:
                it.setText(text)
                color = MARK_COLORS.get(self._marks.get(self._keys[i], ""))
                it.setForeground(QBrush(color) if color is not None else QBrush())

    def summary_label(self) -> QLabel:
        """A new label with the mark counts (``★3 ✓40 ⚠2 ✕0``), kept up to date."""
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setMinimumWidth(10)
        self._summaries.append(label)
        self._summarize()
        return label

    def _summarize(self) -> None:
        counts: Dict[str, int] = {}
        for k in self._keys:
            m = self._marks.get(k)
            if m:
                counts[m] = counts.get(m, 0) + 1
        order = ["★", "✓", "⚠", "✕"] + ([NO_MASK] if self._only is not None else [])
        parts = []
        for m in order:
            c = MARK_COLORS.get(m)
            style = f" style='color: {c.name()}'" if c is not None and counts.get(m) else ""
            parts.append(f"<span{style}>{m}{counts.get(m, 0)}</span>")
        text = " ".join(parts)
        problems = "⚠ ✕ –" if self._only is not None else "⚠ ✕"
        tip = f"{LEGEND_ONE if self._only is not None else LEGEND}\n[ / ]: previous / next {problems} image"
        for label in self._summaries:
            label.setText(text)
            label.setToolTip(tip)

    def problem_frame(self, start: int, step: int) -> Optional[int]:
        """The next image (after *start*, going *step* = ±1, wrapping) marked ⚠ / ✕ / –; None if there is none."""
        n = len(self._keys)
        for d in range(1, n + 1):
            i = (start + step * d) % n
            if self._marks.get(self._keys[i]) in PROBLEMS:
                return i
        return None

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

    def set_names_visible(self, on: bool) -> None:
        """Frame List: show the file names, or only the IDs and marks (a narrow column)."""
        self._delegate.names = on
        self.frame_list.setMinimumWidth(170 if on else 60)
        self.frame_list.doItemsLayout()
        self.frame_list.viewport().update()

    @property
    def names_visible(self) -> bool:
        return self._delegate.names

    def set_current(self, index: int) -> None:
        if self.list.currentRow() == index:
            return  # keep a multi-selection intact
        self._updating = True
        self.list.setCurrentRow(index)
        self._updating = False
        it = self.list.item(index)
        if it is not None:
            self.list.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
            self.frame_list.scrollTo(self.list.indexFromItem(it), QAbstractItemView.ScrollHint.EnsureVisible)
        self._visible_timer.start()

    def focus_current(self) -> None:
        """Scroll both views to the current frame (centered in the strip and the list)."""
        it = self.list.item(self.list.currentRow())
        if it is None:
            return
        self.list.scrollToItem(it, QAbstractItemView.ScrollHint.PositionAtCenter)
        self.frame_list.scrollTo(self.list.indexFromItem(it), QAbstractItemView.ScrollHint.PositionAtCenter)
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

    SLICE_S = 0.008  # UI-thread time per timer tick

    def _load_some(self) -> None:
        """Read thumbnails for ~8 ms: the tiles in view first, then the rest (nearest the current first)."""
        import time

        if not self._pending:
            rest = [r for r in range(len(self._paths)) if r not in self._loaded]
            if not rest:
                self._load_timer.stop()
                return
            cur = max(0, self.list.currentRow())
            rest.sort(key=lambda r: abs(r - cur))  # idle: prefetch the whole folder
            self._loaded.update(rest)
            self._pending = rest
        end = time.perf_counter() + self.SLICE_S
        while self._pending and time.perf_counter() < end:
            row = self._pending.pop(0)
            try:
                img = cached_thumbnail(self._paths[row], self._cache)
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
