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
from PyQt6.QtCore import QEvent, QItemSelectionModel, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QIcon, QImage, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QListView,
    QListWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from src.core.project import FrameStatus, Project
from src.core.propagation import LOW_SCORE

# Most important first: a failed or suspicious frame must stand out in a long list.
PRIORITY = (
    (FrameStatus.FAILED, "✕"),
    (FrameStatus.WARNING, "⚠"),
    (FrameStatus.MANUAL, "★"),
    (FrameStatus.PROPAGATED, "✓"),
    (FrameStatus.IMPORTED, "↓"),
)


NO_MASK = "–"  # marks for one Object: it has no mask on this image
PROBLEMS = ("✕", "⚠", NO_MASK)  # what [ / ] jump between
MARK_COLORS = {  # the mark's text color in both views (✓ and ↓ keep the default: gray rows are ⊘ excluded)
    "✕": QColor(215, 40, 40),
    "⚠": QColor(215, 130, 0),
    "★": QColor(40, 110, 220),
    NO_MASK: QColor(150, 150, 150),
}
LEGEND = ("★ edited here · ✓ propagated (here, or by the batch run that made an imported folder) · "
          "↓ imported from a mask folder, unchanged · ⚠ worth a look (area jumped, or the batch report says why: "
          "hover the frame) · ✕ empty after propagation")
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


def frame_note(fs) -> str:
    """Where a frame's mask came from: the batch report's note (p150), else the app run it was propagated in
    (p152); "" for neither."""
    if fs.note:
        return fs.note
    if fs.origin is None:
        return ""
    text = fs.origin.describe()
    score = fs.variants[0].score if fs.variants else None
    if score is not None and score != 1.0:  # SAM2's object score (p153; earlier runs kept none)
        text += f", score {score:.2f}"
    if fs.status == FrameStatus.WARNING:
        low = score is not None and score < LOW_SCORE
        text += " · ⚠ " + ("SAM2 is unsure it is there (low score)" if low else
                           "its area changed a lot from the reference")
    return text


def image_notes(project: Project, only: Optional[int] = None) -> Dict[str, str]:
    """Each image's frame notes (where an imported or propagated mask came from, why it is worth a look; p150,
    p152), one line an Object: ``people_masks: propagated from cam0/00006 forward``. *only*: that Object's alone."""
    notes: Dict[str, List[str]] = {}
    for o in project.objects:
        if only is not None and o.id != only:
            continue
        for k, fs in o.frames.items():
            note = frame_note(fs)
            if note and fs.mask is not None:
                notes.setdefault(k, []).append(f"{o.name}: {note}")
    return {k: "\n".join(v) for k, v in notes.items()}


PIN_COLOR = QColor(255, 225, 140)  # pinned tiles
CURRENT_FILL = QColor(40, 110, 220)  # the open frame: the whole row / tile filled (white text)
PICKED_FILL = QColor(40, 110, 220, 70)  # the other picked frames (Shift / Ctrl-click): a light tint
EXCLUDED_COLOR = QColor(150, 150, 150)  # ⊘ rows: left out of a new dataset
COLUMN_RULE = QColor(128, 128, 128, 70)  # the Frame List's faint lines between ID | marks | name
REFERENCE_OUTLINE = QColor(255, 130, 0)  # the propagation reference ◎: an orange frame (stands out from blue / 📌)


def selection_fill(option, index, reference: Optional[int]) -> tuple:
    """(fill, outlined) for a row / tile: the open frame filled, a picked one tinted,
    the reference ◎ outlined.

    Clears the selected state in *option*, so the style draws neither its
    highlight nor a tinted (selected-mode) icon: the fill alone shows it.
    """
    view = option.widget
    current = view is not None and view.currentIndex() == index
    picked = bool(option.state & QStyle.StateFlag.State_Selected) and not current
    option.state &= ~QStyle.StateFlag.State_Selected
    fill = CURRENT_FILL if current else PICKED_FILL if picked else None
    return fill, index.row() == reference


def draw_outline(painter, rect: QRect) -> None:
    """The reference's frame, inside *rect*."""
    painter.save()
    pen = QPen(REFERENCE_OUTLINE, 3)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(rect.adjusted(1, 1, -2, -2))
    painter.restore()


class TileDelegate(QStyledItemDelegate):
    """The strip's tiles: the open frame's tile filled, picked ones tinted, the reference outlined."""

    reference: Optional[int] = None  # the ◎ row (set by the panel)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        fill, outlined = selection_fill(opt, index, self.reference)
        if fill is not None:
            if opt.backgroundBrush.style() != Qt.BrushStyle.NoBrush:
                painter.fillRect(opt.rect, opt.backgroundBrush)  # 📌 shade under a picked tile's tint
            painter.fillRect(opt.rect, fill)
            opt.backgroundBrush = QBrush()
            if fill is CURRENT_FILL:
                opt.palette.setBrush(QPalette.ColorRole.Text, QBrush(QColor(255, 255, 255)))
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        if outlined:
            draw_outline(painter, opt.rect)


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


def thumb_name(path: Path) -> str:
    """The cache file of *path*: its name, plus its folder when that is not the image folder's own
    (cam0/0001.jpg and cam1/0001.jpg must not share one)."""
    parent = path.parent.name
    return f"{path.name}.jpg" if parent.lower().startswith("images") else f"{parent}__{path.name}.jpg"


def cached_thumbnail(path: Path, cache: Optional[Path]) -> Optional[np.ndarray]:
    """read_thumbnail through a disk cache (``<cache>/<name>.jpg``, rebuilt when the image is newer)."""
    if cache is not None:
        c = cache / thumb_name(path)
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
                buf.tofile(str(cache / thumb_name(path)))
        except OSError:
            pass  # a read-only folder just means no cache
    return img


def camera_heads(keys: Sequence[str]) -> Dict[int, str]:
    """The rows where another folder's images start (a rig's ``cam0/``, ``cam1/``): row -> ``"cam1 · 94"``.
    {} when every image sits in the image folder itself."""
    folders = [k.rpartition("/")[0] for k in keys]
    if not any(folders):
        return {}
    heads, counts = {}, {}
    for f in folders:
        counts[f] = counts.get(f, 0) + 1
    for i, f in enumerate(folders):
        if i == 0 or f != folders[i - 1]:
            heads[i] = f"{f or '(images)'} · {counts[f]}"
    return heads


HEAD_FILL = QColor(128, 128, 128, 45)  # a camera's head line in the Frame List


class OneLineDelegate(QStyledItemDelegate):
    """The vertical frame list: ``12  ★ ◎ 📌  name`` on one line, no thumbnail.

    A rig's images (``cam0/0001.jpg``) show their file name only, under a head line where each camera
    starts (``cam1 · 94``), so the number that tells frames apart is what stays when the name is cut (U6)."""

    names = True  # False: only the ID and the marks (a narrower list)
    reference: Optional[int] = None  # the ◎ row (set by the panel)
    heads: Dict[int, str] = {}  # row -> head line above it (set by the panel)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Qt has already turned the line break into a line separator (U+2028)
        first, _, name = option.text.replace("\n", "\u2028").partition("\u2028")
        option.text = f"{first}   {name}" if self.names else first
        option.icon = QIcon()
        option.features &= ~option.ViewItemFeature.HasDecoration

    def row_height(self, fm) -> int:
        return fm.height() + 6

    def sizeHint(self, option, index):
        h = self.row_height(option.fontMetrics)
        return QSize(option.rect.width(), h * 2 if index.row() in self.heads else h)

    def paint(self, painter, option, index):
        """ID, marks and name in fixed columns, so 9 and 10 line up."""
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        head = self.heads.get(index.row())
        if head is not None:  # the camera's head line, then the row itself below it
            h = self.row_height(opt.fontMetrics)
            band = QRect(opt.rect.left(), opt.rect.top(), opt.rect.width(), opt.rect.height() - h)
            painter.save()
            painter.fillRect(band, HEAD_FILL)
            f = painter.font()
            f.setBold(True)
            painter.setFont(f)
            painter.setPen(opt.palette.color(QPalette.ColorRole.Text))
            painter.drawText(band.adjusted(6, 0, -4, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(head, Qt.TextElideMode.ElideRight, band.width() - 10))
            painter.restore()
            opt.rect = QRect(opt.rect.left(), band.bottom() + 1, opt.rect.width(), h)
        raw = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        first, _, name = raw.replace(" ", "\n").partition("\n")  # "12  ★ ◎" / file name
        opt.text = ""
        fill, outlined = selection_fill(opt, index, self.reference)  # open: filled · picked: tinted · ◎: outlined
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)  # background (📌)
        if fill is not None:
            painter.fillRect(opt.rect, fill)
        num, _, marks = first.partition("  ")
        fm = opt.fontMetrics
        digits = len(str(index.model().rowCount()))
        id_w = fm.horizontalAdvance("0" * max(2, digits))
        marks_w = max(fm.horizontalAdvance("★ ◎"), fm.horizontalAdvance(marks)) + 8  # wider only for 📌 rows
        r = opt.rect.adjusted(2, 0, -2, 0)
        group = (QPalette.ColorGroup.Active if opt.state & QStyle.StateFlag.State_Active
                 else QPalette.ColorGroup.Inactive)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if fill is CURRENT_FILL:
            color = QColor(255, 255, 255)
        elif isinstance(fg, QBrush) and fg.style() != Qt.BrushStyle.NoBrush:
            color = fg.color()
        else:
            color = opt.palette.color(group, QPalette.ColorRole.Text)
        painter.save()
        painter.setPen(color)
        v = Qt.AlignmentFlag.AlignVCenter
        painter.drawText(QRect(r.left(), r.top(), id_w, r.height()), Qt.AlignmentFlag.AlignRight | v, num)
        x = r.left() + id_w + 7
        painter.drawText(QRect(x, r.top(), marks_w, r.height()), Qt.AlignmentFlag.AlignLeft | v, marks)
        # faint column rules (ID | marks | name), so the three read as columns, not as one line of text
        rule = QColor(255, 255, 255, 90) if fill is CURRENT_FILL else QColor(COLUMN_RULE)
        painter.setPen(rule)
        cols = [x - 4] + ([x + marks_w - 4] if self.names and name else [])
        for cx in cols:
            painter.drawLine(cx, r.top() + 3, cx, r.bottom() - 3)
        painter.setPen(color)
        if self.names and name:
            x += marks_w
            if self.heads:
                name = name.rpartition("/")[2]  # the camera is in the head line
            text = fm.elidedText(name, Qt.TextElideMode.ElideLeft, max(0, r.right() - x))  # keep the number
            painter.drawText(QRect(x, r.top(), r.right() - x, r.height()), Qt.AlignmentFlag.AlignLeft | v, text)
        painter.restore()
        if outlined:
            draw_outline(painter, opt.rect)


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
        self._excluded: Set[str] = set()  # ⊘: left out of a new dataset
        self._marks: Dict[str, str] = {}
        self._notes: Dict[str, str] = {}  # image key -> its frame notes (tooltip, p150)
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
        self.list.setTextElideMode(Qt.TextElideMode.ElideLeft)  # cam0/…00083.jpg: the number stays (U6)
        self.list.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Ctrl/Shift-click picks several images; the clicked one becomes current.
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setSelectionRectVisible(False)  # icon mode drew a rubber-band box on a drag (p132)
        self._tiles = TileDelegate(self.list)
        self.list.setItemDelegate(self._tiles)
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemDoubleClicked.connect(lambda it: self.reference_requested.emit(self.list.row(it)))
        self.list.setToolTip(
            "Click: open the image · Shift/Ctrl-click: pick images (batch / propagation Selection)\n"
            "Middle click: open an image, the picks stay · Right click: what to do with the picked images\n"
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
        self.frame_list.setUniformItemSizes(False)  # a camera's first row is taller: its head line (U6)
        self.frame_list.setAlternatingRowColors(True)  # striped rows: easier to follow a row across
        self.frame_list.setTextElideMode(Qt.TextElideMode.ElideLeft)
        self.frame_list.doubleClicked.connect(lambda ix: self.reference_requested.emit(ix.row()))
        self.frame_list.setToolTip(self.list.toolTip())
        self.frame_list.setMinimumWidth(170)  # ID, marks and most of the file name
        # names are elided, never scrolled sideways (no horizontal bar, folded or not)
        self.frame_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # middle click: open that frame, the picked ones stay picked; right click: its menu, picks unchanged
        for view in (self.list, self.frame_list):
            view.viewport().installEventFilter(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.list)
        # the tile (thumbnail + ID / marks line) and the scrollbar always fit
        self.list.setMinimumHeight(THUMB_H + 44 + self.list.horizontalScrollBar().sizeHint().height() + 6)

    # ------------------------------------------------------------------

    def set_images(
        self, keys: Sequence[str], paths: Optional[Sequence[Path]] = None, cache: Optional[Path] = None
    ) -> None:
        self._keys = list(keys)
        self._paths = list(paths) if paths is not None else []
        self._cache = cache
        self._loaded.clear()
        self._pending.clear()
        self._delegate.heads = camera_heads(self._keys)
        self._updating = True
        self.list.clear()
        blank = _blank_icon()
        for i in range(len(self._keys)):
            self.list.addItem(self._text(i))
            it = self.list.item(i)
            it.setIcon(blank)
            it.setToolTip(self._tip(i))
            it.setSizeHint(QSize(TILE_W, THUMB_H + 44))
        self._updating = False
        self._visible_timer.start()

    def _text(self, i: int) -> str:
        """Two lines under the thumbnail: ``"12  ★ ◎ 📌"`` then the file name."""
        k = self._keys[i]
        marks = " ".join(m for m in (self._marks.get(k, ""), "◎" if i == self._reference else "",
                                     "📌" if i in self._pinned else "", "⊘" if k in self._excluded else "") if m)
        return f"{i + 1}  {marks}\n{k}"

    def _tip(self, i: int) -> str:
        k = self._keys[i]
        return f"{k}\n{self._notes[k]}" if k in self._notes else k

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
        notes = image_notes(project, only)
        if notes != self._notes:
            self._notes = notes
            for i in range(min(self.list.count(), len(self._keys))):
                self.list.item(i).setToolTip(self._tip(i))
        self._retext()
        self._summarize()

    def _retext(self) -> None:
        for i in range(min(self.list.count(), len(self._keys))):
            text = self._text(i)
            it = self.list.item(i)
            if it.text() != text:
                it.setText(text)
                color = MARK_COLORS.get(self._marks.get(self._keys[i], ""))
                if self._keys[i] in self._excluded:
                    color = EXCLUDED_COLOR
                it.setForeground(QBrush(color) if color is not None else QBrush())

    def summary_label(self, wrap: bool = False) -> QLabel:
        """A new label with the mark counts (``★3 ✓40 ⚠2 ✕0``), kept up to date.

        *wrap*: break into lines when narrow (the folded Frame List); else one line.
        """
        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setMinimumWidth(10)
        label.setWordWrap(wrap)
        self._summaries.append(label)
        self._summarize()
        return label

    def _summarize(self) -> None:
        counts: Dict[str, int] = {}
        for k in self._keys:
            m = self._marks.get(k)
            if m:
                counts[m] = counts.get(m, 0) + 1
        # ↓ only when there are imported masks: most projects have none
        order = ["★", "✓"] + (["↓"] if counts.get("↓") else []) + ["⚠", "✕"] + ([NO_MASK] if self._only is not None else [])
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

    def set_excluded(self, keys) -> None:
        """⊘ and gray text on the images left out of a new dataset."""
        keys = set(keys)
        if keys != self._excluded:
            self._excluded = keys
            for it in (self.list.item(i) for i in range(self.list.count())):
                it.setText("")  # force _retext to redo every row (text and color)
            self._retext()

    def set_reference(self, index: Optional[int]) -> None:
        """Mark the propagation reference: its row / tile outlined at once, ◎ on the next update_marks."""
        self._reference = index
        if self._tiles.reference != index:
            self._tiles.reference = self._delegate.reference = index
            self.list.viewport().update()
            self.frame_list.viewport().update()

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

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            # a double click arrives as press, release, double-click, release: the middle button's second click
            # opens the frame too, the picks kept (p125)
            view = next((v for v in (self.list, self.frame_list) if obj is v.viewport()), None)
            if view is not None and event.button() == Qt.MouseButton.RightButton:
                return True  # no selection change: the menu (context menu event) works on the picks as they are
            if view is not None and event.button() == Qt.MouseButton.MiddleButton:
                ix = view.indexAt(event.position().toPoint())
                if ix.isValid():
                    view.selectionModel().setCurrentIndex(ix, QItemSelectionModel.SelectionFlag.NoUpdate)
                return True
        return super().eventFilter(obj, event)

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
