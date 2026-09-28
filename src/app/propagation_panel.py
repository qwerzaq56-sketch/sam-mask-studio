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
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.app.ui_util import allow_narrow
from src.core.project import FrameStatus
from src.core.propagation import Direction, PropagationPlan, format_ids, parse_id, parse_id_list

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


SCOPES = (
    ("selection", "Selection (Images list)"),
    ("range", "Range (Start ~ End)"),
    ("custom", "Custom (IDs: 1-4, 35, 23)"),
    ("all", "All images"),
)


class PropagationPanel(QWidget):
    propagate_requested = pyqtSignal(int, int, object, str)  # start, end, Direction, scope
    pin_toggled = pyqtSignal(bool)  # fix the Images-list selection as the Selection scope
    resume_requested = pyqtSignal()  # continue a stopped propagation
    stop_requested = pyqtSignal()  # stop, keep the frames done
    cancel_requested = pyqtSignal()  # stop and discard the run
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

        self.reference = QLabel("—")
        self.reference.setToolTip("Double-click an image in the Images list to make it the reference (◎)")
        self.scope = QComboBox()
        for value, text in SCOPES:
            self.scope.addItem(text, value)
        self.scope.setToolTip(
            "Selection: the images picked in the Images list (Shift/Ctrl-click), or the pinned ones\n"
            "Range: Start ~ End · Custom: IDs and ID ranges, e.g. 1-4, 35, 23 · All images: the whole folder"
        )
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.pin_btn = QPushButton("📌 Pin")
        self.pin_btn.setCheckable(True)
        self.pin_btn.setToolTip("Fix the current Images-list selection, so moving between images keeps it")
        self.pin_btn.toggled.connect(self.pin_toggled)
        self.pin_label = QLabel("")
        self.pin_label.setStyleSheet("color: gray;")
        pin_row = QHBoxLayout()
        pin_row.addWidget(self.pin_btn)
        pin_row.addWidget(self.pin_label, 1)
        self.start_edit = QLineEdit()
        self.end_edit = QLineEdit()
        for e, tip in ((self.start_edit, "First image ID"), (self.end_edit, "Last image ID")):
            e.setToolTip(tip + " (the numbers in the frame list)")
            e.setMaximumWidth(80)
        self.range_row = QWidget()  # Start [ ]  End [ ]
        rr = QHBoxLayout(self.range_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.addWidget(QLabel("Start"))
        rr.addWidget(self.start_edit)
        rr.addWidget(QLabel("End"))
        rr.addWidget(self.end_edit)
        rr.addStretch(1)
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("e.g. 1-4, 35, 23")
        self.custom_edit.setToolTip("Image IDs and ID ranges, in any order")
        self.custom_ids: List[int] = []  # the last Custom scope parsed (0-based)
        self.ref_hint = QLabel("Double-click an image in the Images list to use it as the reference")
        self.ref_hint.setStyleSheet("color: gray;")
        self.ref_hint.setWordWrap(True)
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
        form.addRow("Reference", self.reference)
        form.addRow("", self.ref_hint)
        form.addRow("Scope", self.scope)
        form.addRow("", pin_row)
        form.addRow("Range (IDs)", self.range_row)
        form.addRow("IDs", self.custom_edit)
        form.addRow("Direction", drow)
        self._form = form

        self.run_btn = QPushButton("Propagate Selected Objects")
        self.run_btn.setToolTip("Every checked Object propagates from its mask on the reference image")
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Stop and keep the frames propagated so far")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Stop and discard the whole propagation (nothing changes)")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        brow = QHBoxLayout()
        brow.addWidget(self.run_btn, 1)
        brow.addWidget(self.stop_btn)
        brow.addWidget(self.cancel_btn)
        self.resume_btn = QPushButton("Resume")
        self.resume_btn.setToolTip("Continue a stopped propagation from the last frame it reached")
        self.resume_btn.setEnabled(False)
        self.resume_btn.clicked.connect(self.resume_requested)
        brow.addWidget(self.resume_btn)

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
        lists = QSplitter(Qt.Orientation.Vertical)  # stacked: the panel is a narrow column
        lists.addWidget(obox)
        lists.addWidget(fbox)

        # one column: settings, buttons, progress, then the Object / frame lists
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(form)
        lay.addLayout(brow)
        lay.addLayout(prog)
        lay.addWidget(lists, 1)
        self._reset_bars()
        self._scope_changed()
        allow_narrow(self)  # it shares the left column with the Objects

    # ------------------------------------------------------------------

    def set_images(self, keys: Sequence[str]) -> None:
        self._keys = list(keys)
        self.start_edit.setText("1" if keys else "")
        self.end_edit.setText(str(len(keys)) if keys else "")
        self.frames.clear()
        self.objects.clear()
        self._rows.clear()
        self._obj_rows.clear()

    def set_reference(self, index: int, chosen: bool) -> None:
        """The image propagation starts from; *chosen*: picked by double-click (else the current one)."""
        name = self._keys[index] if 0 <= index < len(self._keys) else "—"
        self.reference.setText(f"◎ {name}" if chosen else f"{name}  (current image)")

    def set_pinned(self, indices: Optional[Sequence[int]]) -> None:
        """Show the pinned images by ID (None: the live Images-list selection is used)."""
        self.pin_btn.blockSignals(True)
        self.pin_btn.setChecked(indices is not None)
        self.pin_btn.blockSignals(False)
        self.pin_label.setText(
            f"Pinned: {format_ids(indices)} ({len(indices)} image(s))" if indices is not None
            else "uses the Images-list selection"
        )

    def scope_value(self) -> str:
        return self.scope.currentData()

    def _scope_changed(self, *_):
        scope = self.scope_value()
        self._form.setRowVisible(self.range_row, scope == "range")
        self._form.setRowVisible(self.custom_edit, scope == "custom")
        self.pin_btn.setVisible(scope == "selection")
        self.pin_label.setVisible(scope == "selection")

    def direction(self) -> Direction:
        return Direction(self.dirs.checkedButton().property("direction"))

    def _run(self) -> None:
        start, end = 0, max(0, len(self._keys) - 1)
        n = len(self._keys)
        try:
            if self.scope_value() == "range":
                start, end = sorted((parse_id(self.start_edit.text(), n), parse_id(self.end_edit.text(), n)))
            elif self.scope_value() == "custom":
                self.custom_ids = parse_id_list(self.custom_edit.text(), n)
        except ValueError as e:
            self.phase.setText(str(e))
            return
        self.propagate_requested.emit(start, end, self.direction(), self.scope_value())

    def set_resumable(self, on: bool) -> None:
        self.resume_btn.setEnabled(on)

    def set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.cancel_btn.setEnabled(running)
        for w in (self.start_edit, self.end_edit, self.custom_edit, self.scope, self.pin_btn, *self.dirs.buttons()):
            w.setEnabled(not running)
        if running:
            self.resume_btn.setEnabled(False)

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
        for oid, _name in objects:
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

    def stopping(self) -> None:
        """Stop was pressed: Cancel stays available (it turns the stop into a discard)."""
        self.stop_btn.setEnabled(False)
        self.phase.setText("Stopping after the current frame… (Cancel discards instead)")

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
