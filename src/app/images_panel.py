"""Image list with a marker for images that have masks (and for suspicious propagated ones)."""

from __future__ import annotations

from typing import Sequence

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QListWidget, QVBoxLayout, QWidget

from src.core.project import FrameStatus, Project


class ImagesPanel(QWidget):
    navigate_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: list = []
        self._updating = False
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_row)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.list)

    def set_images(self, keys: Sequence[str]) -> None:
        self._keys = list(keys)
        self._updating = True
        self.list.clear()
        self.list.addItems(["   " + k for k in keys])
        self._updating = False

    def update_marks(self, project: Project) -> None:
        """● = some Object has a mask here, ⚠ = a propagated mask there looks wrong or failed."""
        has, bad = set(), set()
        for o in project.objects:
            for k, fs in o.frames.items():
                if fs.mask is not None:
                    has.add(k)
                if fs.status in (FrameStatus.WARNING, FrameStatus.FAILED):
                    bad.add(k)
        for i, k in enumerate(self._keys):
            mark = "⚠" if k in bad else ("●" if k in has else " ")
            text = f"{mark}  {k}"
            it = self.list.item(i)
            if it is not None and it.text() != text:
                it.setText(text)

    def set_current(self, index: int) -> None:
        self._updating = True
        self.list.setCurrentRow(index)
        self._updating = False

    def _on_row(self, row: int) -> None:
        if not self._updating and row >= 0:
            self.navigate_requested.emit(row)
