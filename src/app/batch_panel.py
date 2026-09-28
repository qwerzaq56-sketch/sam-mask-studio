"""Batch masking: a SAM3 text prompt over many images, one Object per label.

Its own prompt (separate from the current-image Detection tab). Scope: all
images, a Start ~ End range, or the images selected in the Images list. Every
label becomes one Object whose mask on each image is the union of that
label's detections above the score threshold. Processed images are listed
with their counts and can be clicked to jump there.
"""

from __future__ import annotations

from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.app.ui_util import allow_narrow
from src.core.prompts import split_labels

INDEX_ROLE = Qt.ItemDataRole.UserRole

SCOPES = (
    ("all", "All images"),
    ("range", "Range (Start ~ End)"),
    ("selected", "Selected images (Images list, Ctrl/Shift-click)"),
)


class BatchPanel(QWidget):
    batch_requested = pyqtSignal(list, str, int, int, float)  # labels, scope, start, end, threshold
    batch_stop_requested = pyqtSignal()  # stop, keep what is done
    batch_cancel_requested = pyqtSignal()  # stop and discard everything
    navigate_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText("Batch prompt — one Object per label: person, car, tripod")
        self.prompt.returnPressed.connect(self._batch)
        self.scope = QComboBox()
        for value, text in SCOPES:
            self.scope.addItem(text, value)
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.start = QSpinBox()
        self.end = QSpinBox()
        for sb, tip in ((self.start, "Start image (1-based)"), (self.end, "End image (1-based)")):
            sb.setMinimum(1)
            sb.setToolTip(tip)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.05, 1.0)
        self.threshold.setSingleStep(0.05)
        self.threshold.setValue(0.5)
        self.threshold.setToolTip("Detections below this SAM3 score are ignored")
        self.batch_btn = QPushButton("Run on Images")
        self.batch_btn.setToolTip("One Object per label; each image gets the union of that label's detections")
        self.batch_btn.clicked.connect(self._batch)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Stop after the current prompt and keep the images done so far")
        self.stop_btn.clicked.connect(self.batch_stop_requested)
        self.stop_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setToolTip("Stop and discard the whole run (nothing is added)")
        self.cancel_btn.clicked.connect(self.batch_cancel_requested)
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        self.status = QLabel("")
        self.status.setStyleSheet("color: gray;")
        self.results = QListWidget()
        self.results.itemClicked.connect(self._on_result)

        top = QHBoxLayout()
        top.addWidget(self.prompt, 1)
        top.addWidget(self.batch_btn)
        b1 = QHBoxLayout()
        b1.addWidget(QLabel("Images"))
        b1.addWidget(self.scope, 1)
        self.range_row = QWidget()  # shown for the Range scope only
        b2 = QHBoxLayout(self.range_row)
        b2.setContentsMargins(0, 0, 0, 0)
        b2.addWidget(QLabel("Start"))
        b2.addWidget(self.start)
        b2.addWidget(QLabel("End"))
        b2.addWidget(self.end)
        b2.addStretch(1)
        b3 = QHBoxLayout()
        b3.addWidget(QLabel("Min score"))
        b3.addWidget(self.threshold)
        b3.addStretch(1)
        b3.addWidget(self.stop_btn)
        b3.addWidget(self.cancel_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addLayout(b1)
        lay.addWidget(self.range_row)
        lay.addLayout(b3)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addWidget(self.results, 1)
        self._scope_changed()
        allow_narrow(self)  # it shares the left column with the Objects

    def labels(self) -> List[str]:
        return split_labels(self.prompt.text())

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Lock the controls (except Stop / Cancel) while a long job runs."""
        self._busy = busy
        for w in (self.prompt, self.batch_btn, self.scope, self.start, self.end, self.threshold, self.results):
            w.setEnabled(not busy)
        if message:
            self.status.setText(message)

    def set_image_count(self, n: int) -> None:
        for sb in (self.start, self.end):
            sb.setMaximum(max(1, n))
        self.end.setValue(max(1, n))

    def _scope_changed(self, *_):
        self.range_row.setVisible(self.scope.currentData() == "range")

    def _batch(self) -> None:
        labels = self.labels()
        if labels and not self._busy:
            self.batch_requested.emit(
                labels,
                self.scope.currentData(),
                self.start.value() - 1,
                self.end.value() - 1,
                float(self.threshold.value()),
            )

    def batch_begin(self, total: int) -> None:
        self.results.clear()
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self.stop_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)

    def batch_frame(self, index: int, text: str, found: bool) -> None:
        it = QListWidgetItem(f"{'✓' if found else '·'}  {text}")
        it.setData(INDEX_ROLE, index)
        self.results.addItem(it)
        self.progress.setValue(self.results.count())

    def batch_stopping(self) -> None:
        """Stop was pressed: Cancel stays available (it turns the stop into a discard)."""
        self.stop_btn.setEnabled(False)
        self.status.setText("Stopping after the current prompt… (Cancel discards instead)")

    def batch_end(self, message: str) -> None:
        self.stop_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status.setText(message)

    def _on_result(self, item: QListWidgetItem) -> None:
        idx = item.data(INDEX_ROLE)
        if idx is not None:
            self.navigate_requested.emit(int(idx))
