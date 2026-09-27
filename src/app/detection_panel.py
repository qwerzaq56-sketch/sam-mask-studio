"""SAM3 text prompt → Detection candidates (checkboxes) → Add Selected as Objects."""

from __future__ import annotations

from typing import List, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.app.objects_panel import color_icon
from src.core.project import Detection

CANDIDATE_COLORS = ((255, 200, 0), (0, 220, 255), (255, 90, 200), (140, 255, 90), (255, 140, 60), (170, 140, 255))


def candidate_color(i: int):
    return CANDIDATE_COLORS[i % len(CANDIDATE_COLORS)]


class DetectionPanel(QWidget):
    detect_requested = pyqtSignal(str)
    checks_changed = pyqtSignal(list)
    add_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText("Text prompt for SAM3, e.g. person, car, tripod")
        self.prompt.returnPressed.connect(self._detect)
        self.detect_btn = QPushButton("Detect")
        self.detect_btn.clicked.connect(self._detect)
        top = QHBoxLayout()
        top.addWidget(self.prompt, 1)
        top.addWidget(self.detect_btn)

        self.list = QListWidget()
        self.list.itemChanged.connect(self._on_changed)
        self.status = QLabel("")
        self.status.setStyleSheet("color: gray;")

        self.all_btn = QPushButton("Select All")
        self.all_btn.clicked.connect(lambda: self._set_all(True))
        self.none_btn = QPushButton("Select None")
        self.none_btn.clicked.connect(lambda: self._set_all(False))
        self.add_btn = QPushButton("Add Selected as Objects")
        self.add_btn.clicked.connect(self.add_requested)
        self.clear_btn = QPushButton("Discard")
        self.clear_btn.clicked.connect(self.clear_requested)
        row = QHBoxLayout()
        for b in (self.all_btn, self.none_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.clear_btn)
        row.addWidget(self.add_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self.set_detections([], [])

    def _detect(self) -> None:
        text = self.prompt.text().strip()
        if text:
            self.detect_requested.emit(text)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.detect_btn.setEnabled(not busy)
        self.prompt.setEnabled(not busy)
        if message:
            self.status.setText(message)

    def set_detections(self, detections: Sequence[Detection], checked: Sequence[bool]) -> None:
        self._updating = True
        self.list.clear()
        for i, (d, c) in enumerate(zip(detections, checked, strict=True)):
            it = QListWidgetItem(color_icon(candidate_color(i)), f"{d.label}  {d.score:.2f}  · {int(d.mask.sum()):,} px")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if c else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        self._updating = False
        has = bool(detections)
        for b in (self.all_btn, self.none_btn, self.clear_btn):
            b.setEnabled(has)
        self.add_btn.setEnabled(any(checked))

    def checked(self) -> List[bool]:
        return [self.list.item(i).checkState() == Qt.CheckState.Checked for i in range(self.list.count())]

    def _set_all(self, on: bool) -> None:
        self._updating = True
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self._updating = False
        self._on_changed()

    def _on_changed(self, *_):
        if self._updating:
            return
        c = self.checked()
        self.add_btn.setEnabled(any(c))
        self.checks_changed.emit(c)
