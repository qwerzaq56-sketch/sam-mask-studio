"""Image list with a per-image status mark (spec 02 §13): ✕ failed, ⚠ warning, ★ manual, ✓ propagated."""

from __future__ import annotations

from typing import Dict, Optional, Sequence

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QAbstractItemView, QListWidget, QVBoxLayout, QWidget

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


PIN_COLOR = QColor(255, 225, 140)  # pinned rows


class ImagesPanel(QWidget):
    navigate_requested = pyqtSignal(int)
    reference_requested = pyqtSignal(int)  # double-click: the propagation reference

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: list = []
        self._updating = False
        self.list = QListWidget()
        # Ctrl/Shift-click selects several images for batch masking; the clicked one becomes current.
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemDoubleClicked.connect(lambda it: self.reference_requested.emit(self.list.row(it)))
        self._reference: Optional[int] = None
        self._pinned: set = set()
        self._marks: Dict[str, str] = {}
        self.list.setToolTip(
            "Click: open the image · Shift/Ctrl-click: pick images (batch / propagation Selection)\n"
            "Double-click: make it the propagation reference (◎) · shaded rows are pinned (📌)"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.list)

    def set_images(self, keys: Sequence[str]) -> None:
        self._keys = list(keys)
        self._updating = True
        self.list.clear()
        self.list.addItems([self._text(i) for i in range(len(keys))])
        self._updating = False

    def _text(self, i: int) -> str:
        """``" 12  ★ ◎ frame_011.jpg 📌"``: image ID (1-based), status, reference, name, pinned."""
        width = len(str(len(self._keys)))
        k = self._keys[i]
        pin = "  📌" if i in self._pinned else ""
        return f"{i + 1:>{width}}  {self._marks.get(k, ' ')} {'◎' if i == self._reference else ' '} {k}{pin}"

    def status_mark(self, i: int) -> str:
        return self._marks.get(self._keys[i], " ")

    def update_marks(self, project: Project) -> None:
        """Mark each image with the most important status of the Object masks on it."""
        self._marks = image_marks(project)
        for i in range(len(self._keys)):
            text = self._text(i)
            it = self.list.item(i)
            if it is not None and it.text() != text:
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
            it = self.list.item(i)
            it.setBackground(QBrush(PIN_COLOR) if i in pinned else QBrush())
            it.setText(self._text(i))

    def set_current(self, index: int) -> None:
        if self.list.currentRow() == index:
            return  # keep a multi-selection intact
        self._updating = True
        self.list.setCurrentRow(index)
        self._updating = False

    def selected_rows(self) -> list:
        return sorted(self.list.row(it) for it in self.list.selectedItems())

    def _on_row(self, row: int) -> None:
        if not self._updating and row >= 0:
            self.navigate_requested.emit(row)
