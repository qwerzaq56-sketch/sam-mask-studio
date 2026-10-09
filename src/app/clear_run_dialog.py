"""Clear a Propagation Run (p152): the masks one in-app propagation left on the selected Objects, from its reference
forward / backward / both ways, keeping the first frames out if asked. The Timeline crosses out what goes while
the window is open (the preview); Clear removes it as one undo step. Frames edited since (★) stay.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence

from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                             QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from src.core.propagation import Direction, RunSummary, format_ids


class ClearRunDialog(QDialog):
    def __init__(self, runs: Sequence[RunSummary], frames_of: Callable[[RunSummary, Direction, int], Dict[int, List[str]]],
                 rows_of: Callable[[Dict[int, List[str]]], List[int]], names: str,
                 preview: Callable[[Dict[int, List[str]]], None], run: Optional[int] = None,
                 direction: Direction = Direction.BOTH, keep: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clear a Propagation Run")
        self._runs, self._frames_of, self._rows_of, self._preview = list(runs), frames_of, rows_of, preview
        self.frames: Dict[int, List[str]] = {}

        self.run_box = QComboBox()
        for r in self._runs:
            self.run_box.addItem(r.describe())
        if run is not None:
            self.run_box.setCurrentIndex(next((i for i, r in enumerate(self._runs) if r.run == run), 0))
        self.dir_group = QButtonGroup(self)
        dir_row = QHBoxLayout()
        dir_row.setContentsMargins(0, 0, 0, 0)
        self._dirs = {}
        for d, text in ((Direction.BOTH, "Both ways"), (Direction.BACKWARD, "◀ Backward"),
                        (Direction.FORWARD, "Forward ▶")):
            b = QRadioButton(text)
            self._dirs[d] = b
            self.dir_group.addButton(b)
            dir_row.addWidget(b)
        dir_row.addStretch(1)
        self._dirs[direction].setChecked(True)
        dirs = QWidget()
        dirs.setLayout(dir_row)
        self.keep_box = QSpinBox()
        self.keep_box.setRange(0, 100000)
        self.keep_box.setValue(keep)
        self.keep_box.setSuffix(" frame(s) next to the reference")
        self.keep_box.setToolTip("Keep these first frames out from the reference; clear the run from there on")
        self.summary = QLabel()
        self.summary.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Objects", QLabel(names))
        form.addRow("Run", self.run_box)
        form.addRow("Direction", dirs)
        form.addRow("Keep", self.keep_box)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.summary)
        note = QLabel("Crossed out in the Timeline: what Clear removes (one undo step). "
                      "Frames edited since (★) are kept.")
        note.setWordWrap(True)
        note.setEnabled(False)
        lay.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.clear_btn = self.buttons.addButton("Clear", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self.run_box.currentIndexChanged.connect(self.update_preview)
        self.dir_group.buttonToggled.connect(lambda *_: self.update_preview())
        self.keep_box.valueChanged.connect(self.update_preview)
        self.finished.connect(lambda _r: self._preview({}))
        self.update_preview()

    def run(self) -> Optional[RunSummary]:
        i = self.run_box.currentIndex()
        return self._runs[i] if 0 <= i < len(self._runs) else None

    def direction(self) -> Direction:
        return next(d for d, b in self._dirs.items() if b.isChecked())

    def update_preview(self) -> None:
        r = self.run()
        self.frames = self._frames_of(r, self.direction(), self.keep_box.value()) if r is not None else {}
        n = sum(len(v) for v in self.frames.values())
        rows = self._rows_of(self.frames)
        self.summary.setText(f"Clears {n} mask(s) of {len(self.frames)} Object(s) on frames {format_ids(rows)}"
                             if n else "Nothing to clear with these settings")
        self.clear_btn.setEnabled(bool(n))
        self._preview(self.frames)
