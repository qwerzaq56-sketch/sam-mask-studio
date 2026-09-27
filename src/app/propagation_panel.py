"""Propagation panel (spec 02).

Start / End only bound the range; the Current image is the reference and is
never re-processed. Shows one progress bar per direction with its frame chain,
a per-Object status, and a per-frame result list (✓ / ⚠ / ✕ / ★) whose rows
navigate to that image when clicked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.core.project import FrameStatus
from src.core.propagation import Direction, PropagationPlan

INDEX_ROLE = Qt.ItemDataRole.UserRole
REFERENCE = "reference"
MARK = {
    None: "·",
    REFERENCE: "★",
    FrameStatus.MANUAL: "★",
    FrameStatus.PROPAGATED: "✓",
    FrameStatus.WARNING: "⚠",
    FrameStatus.FAILED: "✕",
}


def chain(keys: Sequence[str], indices: Sequence[int], current: int, limit: int = 6) -> str:
    """``005 → 004 → 003 → 002`` (shortened with … for long ranges)."""
    names = [Path(keys[current]).stem] + [Path(keys[i]).stem for i in indices]
    if len(names) > limit:
        names = names[: limit - 2] + ["…", names[-1]]
    return " → ".join(names)


class PropagationPanel(QWidget):
    propagate_requested = pyqtSignal(int, int, object)  # start, end, Direction
    cancel_requested = pyqtSignal()
    navigate_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: List[str] = []
        self._rows: Dict[int, QListWidgetItem] = {}
        self._plan: Optional[PropagationPlan] = None
        self._objects: List[Tuple[int, str]] = []
        self._obj_rows: Dict[int, QListWidgetItem] = {}
        self._obj_done: Dict[int, int] = {}
        self._dir_done = {"Backward": 0, "Forward": 0}

        self.start = QComboBox()
        self.end = QComboBox()
        self.current = QLabel("—")
        self.dirs = QButtonGroup(self)
        drow = QHBoxLayout()
        for i, (d, text) in enumerate(
            ((Direction.BOTH, "Both"), (Direction.FORWARD, "Forward"), (Direction.BACKWARD, "Backward"))
        ):
            rb = QRadioButton(text)
            rb.setProperty("direction", d.value)
            self.dirs.addButton(rb, i)
            drow.addWidget(rb)
        self.dirs.button(0).setChecked(True)
        form = QFormLayout()
        form.addRow("Start Image", self.start)
        form.addRow("End Image", self.end)
        form.addRow("Current Image", self.current)
        form.addRow("Direction", drow)

        self.run_btn = QPushButton("Propagate Selected Objects")
        self.run_btn.setToolTip("Every checked Object propagates from its selected Variant on the Current image")
        self.run_btn.clicked.connect(self._run)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        brow = QHBoxLayout()
        brow.addWidget(self.run_btn, 1)
        brow.addWidget(self.cancel_btn)

        self.phase = QLabel("")
        self.bars: Dict[str, Tuple[QLabel, QProgressBar]] = {}
        prog = QVBoxLayout()
        prog.addWidget(self.phase)
        for name in ("Backward", "Forward"):
            label, bar = QLabel(name), QProgressBar()
            bar.setFormat("%v / %m")
            prog.addWidget(label)
            prog.addWidget(bar)
            self.bars[name] = (label, bar)

        self.objects = QListWidget()
        self.frames = QListWidget()
        self.frames.itemClicked.connect(lambda it: self.navigate_requested.emit(it.data(INDEX_ROLE)))
        obox, fbox = QGroupBox("Objects"), QGroupBox("Frames (click to open)")
        QVBoxLayout(obox).addWidget(self.objects)
        QVBoxLayout(fbox).addWidget(self.frames)
        lists = QSplitter(Qt.Orientation.Horizontal)
        lists.addWidget(obox)
        lists.addWidget(fbox)

        left = QVBoxLayout()
        left.addLayout(form)
        left.addLayout(brow)
        left.addLayout(prog)
        left.addStretch(1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(left, 1)
        lay.addWidget(lists, 2)
        self._reset_bars()

    # ------------------------------------------------------------------

    def set_images(self, keys: Sequence[str]) -> None:
        self._keys = list(keys)
        for combo in (self.start, self.end):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(list(keys))
            combo.blockSignals(False)
        if keys:
            self.start.setCurrentIndex(0)
            self.end.setCurrentIndex(len(keys) - 1)
        self.frames.clear()
        self.objects.clear()
        self._rows.clear()
        self._obj_rows.clear()

    def set_current(self, index: int) -> None:
        self.current.setText(self._keys[index] if 0 <= index < len(self._keys) else "—")

    def direction(self) -> Direction:
        return Direction(self.dirs.checkedButton().property("direction"))

    def _run(self) -> None:
        self.propagate_requested.emit(self.start.currentIndex(), self.end.currentIndex(), self.direction())

    def set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        for w in (self.start, self.end, *self.dirs.buttons()):
            w.setEnabled(not running)

    def _reset_bars(self) -> None:
        for name, (label, bar) in self.bars.items():
            label.setText(name)
            bar.setRange(0, 1)
            bar.setValue(0)
        self._dir_done = {"Backward": 0, "Forward": 0}

    # ------------------------------------------------------------------
    # A run
    # ------------------------------------------------------------------

    def begin(self, plan: PropagationPlan, objects: Sequence[Tuple[int, str]]) -> None:
        """Lay out the run: direction chains, Objects waiting, frames pending (reference ★)."""
        self._plan = plan
        self._reset_bars()
        for name, targets in (("Backward", plan.backward), ("Forward", plan.forward)):
            label, bar = self.bars[name]
            label.setText(f"{name}   {chain(self._keys, targets, plan.current)}" if targets else f"{name}   —")
            bar.setRange(0, max(1, len(targets)))
            bar.setValue(0)
            bar.setEnabled(bool(targets))
        self._objects = list(objects)
        self._obj_done = {oid: 0 for oid, _ in objects}
        self.objects.clear()
        self._obj_rows.clear()
        for oid, name in objects:
            it = QListWidgetItem()
            self.objects.addItem(it)
            self._obj_rows[oid] = it
            self._set_obj(oid, "Waiting")
        self.frames.clear()
        self._rows.clear()
        for idx in sorted([plan.current, *plan.targets]):
            it = QListWidgetItem()
            it.setData(INDEX_ROLE, idx)
            self.frames.addItem(it)
            self._rows[idx] = it
            self.mark(idx, REFERENCE if idx == plan.current else None)
        self.phase.setText(f"Current: {self._keys[plan.current]}")
        self.set_running(True)

    def _set_obj(self, oid: int, text: str) -> None:
        name = dict(self._objects).get(oid, str(oid))
        it = self._obj_rows.get(oid)
        if it is not None:
            it.setText(f"{name}    {text}")

    def mark(self, index: int, status: Optional[object]) -> None:
        it = self._rows.get(index)
        if it is not None:
            it.setText(f"{self._keys[index]}  {MARK.get(status, '·')}")

    def on_progress(self, phase: str, done: int, total: int) -> None:
        """Model-side phases (preparing frames, loading the video model, …)."""
        if phase in self.bars:
            return  # direction progress is counted per finished frame
        self.phase.setText(f"{phase} {done}/{total}" if total else f"{phase}…")

    def on_frame(self, index: int, obj_ids: Sequence[int]) -> None:
        plan = self._plan
        if plan is None:
            return
        name = "Backward" if index < plan.current else "Forward"
        self._dir_done[name] += 1
        self.bars[name][1].setValue(self._dir_done[name])
        total = len(plan.targets)
        for oid in obj_ids:
            if oid in self._obj_done:
                self._obj_done[oid] += 1
                self._set_obj(oid, f"{round(100 * self._obj_done[oid] / max(1, total))}%")
        self.phase.setText(f"{name}: {self._keys[index]}   (Current: {self._keys[plan.current]})")

    def finish(self, statuses: Dict[int, FrameStatus], message: str) -> None:
        for idx, st in statuses.items():
            self.mark(idx, st)
        total = len(self._plan.targets) if self._plan else 0
        for oid, n in self._obj_done.items():
            self._set_obj(oid, "✓ Complete" if n >= total else f"Stopped at {n}/{total}")
        self.phase.setText(message)
        self.set_running(False)
