"""Propagation controls: Start/End bounds, Current reference, direction, progress, per-frame status."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from src.core.project import FrameStatus
from src.core.propagation import Direction

INDEX_ROLE = Qt.ItemDataRole.UserRole
MARK = {
    None: "·",
    "reference": "★",
    FrameStatus.PROPAGATED: "✓",
    FrameStatus.WARNING: "⚠",
    FrameStatus.FAILED: "✕",
}


class PropagationPanel(QWidget):
    propagate_requested = pyqtSignal(int, int, object)  # start, end, Direction
    cancel_requested = pyqtSignal()
    navigate_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: List[str] = []
        self._rows: Dict[int, QListWidgetItem] = {}
        self.start = QComboBox()
        self.end = QComboBox()
        self.current = QLabel("—")
        self.dirs = QButtonGroup(self)
        drow = QHBoxLayout()
        for i, (d, text) in enumerate(((Direction.BOTH, "Both"), (Direction.FORWARD, "Forward →"), (Direction.BACKWARD, "← Backward"))):
            rb = QRadioButton(text)
            rb.setProperty("direction", d.value)
            self.dirs.addButton(rb, i)
            drow.addWidget(rb)
        self.dirs.button(0).setChecked(True)
        form = QFormLayout()
        form.addRow("Start", self.start)
        form.addRow("End", self.end)
        form.addRow("Current (reference)", self.current)
        form.addRow("Direction", drow)

        self.run_btn = QPushButton("Propagate Checked Objects")
        self.run_btn.setToolTip("Each checked Object propagates from its selected Variant on the Current image")
        self.run_btn.clicked.connect(self._run)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        brow = QHBoxLayout()
        brow.addWidget(self.run_btn, 1)
        brow.addWidget(self.cancel_btn)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.phase = QLabel("")
        self.frames = QListWidget()
        self.frames.itemClicked.connect(lambda it: self.navigate_requested.emit(it.data(INDEX_ROLE)))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(form)
        lay.addLayout(brow)
        lay.addWidget(self.progress)
        lay.addWidget(self.phase)
        lay.addWidget(self.frames, 1)

    # ------------------------------------------------------------------

    def set_images(self, keys: Sequence[str]) -> None:
        self._keys = list(keys)
        for combo in (self.start, self.end):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([f"{i + 1}: {k}" for i, k in enumerate(keys)])
            combo.blockSignals(False)
        if keys:
            self.start.setCurrentIndex(0)
            self.end.setCurrentIndex(len(keys) - 1)
        self.frames.clear()
        self._rows.clear()

    def set_current(self, index: int) -> None:
        self.current.setText(f"{index + 1}: {self._keys[index]}" if 0 <= index < len(self._keys) else "—")

    def direction(self) -> Direction:
        return Direction(self.dirs.checkedButton().property("direction"))

    def _run(self) -> None:
        self.propagate_requested.emit(self.start.currentIndex(), self.end.currentIndex(), self.direction())

    def set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        for w in (self.start, self.end, *self.dirs.buttons()):
            w.setEnabled(not running)

    def begin(self, current: int, targets: Sequence[int]) -> None:
        """List the reference and target frames (in sequence order) with pending marks."""
        self.frames.clear()
        self._rows.clear()
        for idx in sorted([current, *targets]):
            it = QListWidgetItem()
            it.setData(INDEX_ROLE, idx)
            self.frames.addItem(it)
            self._rows[idx] = it
            self.mark(idx, "reference" if idx == current else None)
        self.progress.setRange(0, max(1, len(targets)))
        self.progress.setValue(0)
        self.phase.setText("Starting…")

    def mark(self, index: int, status: Optional[object]) -> None:
        it = self._rows.get(index)
        if it is not None:
            it.setText(f"{MARK.get(status, '·')}  {index + 1}: {self._keys[index]}")

    def on_progress(self, phase: str, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.phase.setText(f"{phase}: {done}/{total}")
        else:
            self.progress.setRange(0, 0)  # busy
            self.phase.setText(phase)

    def finish(self, message: str) -> None:
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 1)
        self.phase.setText(message)
        self.set_running(False)
