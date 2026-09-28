"""SAM3 text prompts: Detections on the current image, and batch masking over many images.

Current image: ``person, car, tripod`` is detected label by label; results are
grouped per label in a collapsible tree (the label row checks/unchecks all its
candidates) → Add Selected as Objects.

Batch (all / range / selected images): every label becomes one Object whose
mask on each image is the union of that label's detections above the score
threshold; frames are listed with their counts and can be clicked to jump.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.app.objects_panel import color_icon, later
from src.core.project import Detection
from src.core.prompts import split_labels

CANDIDATE_COLORS = ((255, 200, 0), (0, 220, 255), (255, 90, 200), (140, 255, 90), (255, 140, 60), (170, 140, 255))
INDEX_ROLE = Qt.ItemDataRole.UserRole

SCOPES = (
    ("all", "All images"),
    ("range", "Range (Start ~ End)"),
    ("selected", "Selected images (Images list, Ctrl/Shift-click)"),
)


def candidate_color(i: int):
    return CANDIDATE_COLORS[i % len(CANDIDATE_COLORS)]


class DetectionPanel(QWidget):
    detect_requested = pyqtSignal(list)  # labels, current image
    checks_changed = pyqtSignal(list)
    add_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    batch_requested = pyqtSignal(list, str, int, int, float)  # labels, scope, start, end, threshold
    batch_cancel_requested = pyqtSignal()
    navigate_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self._busy = False
        self._n = 0
        self._shown: Sequence[Detection] = ()
        # A label row's checkbox changes all its candidates at once (plus the tristate
        # parent for a single one): report that as one change, not one per row.
        self._checks_timer = QTimer(self)
        self._checks_timer.setSingleShot(True)
        self._checks_timer.setInterval(0)
        self._checks_timer.timeout.connect(lambda: self.checks_changed.emit(self.checked()))
        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText("SAM3 text prompt — separate labels with commas: person, car, tripod")
        self.prompt.returnPressed.connect(self._detect)
        self.detect_btn = QPushButton("Detect")
        self.detect_btn.setToolTip("Detect on the current image (each comma-separated label separately)")
        self.detect_btn.clicked.connect(self._detect)
        top = QHBoxLayout()
        top.addWidget(self.prompt, 1)
        top.addWidget(self.detect_btn)

        # --- current image: grouped candidates
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self._on_changed)
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
        cur = QGroupBox("Current image")
        cl = QVBoxLayout(cur)
        cl.addWidget(self.tree, 1)
        cl.addWidget(self.status)
        cl.addLayout(row)

        # --- batch
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
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.batch_cancel_requested)
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        self.progress.setFormat("%v / %m")
        self.results = QListWidget()
        self.results.itemClicked.connect(self._on_result)
        b1 = QHBoxLayout()
        b1.addWidget(QLabel("Images"))
        b1.addWidget(self.scope, 1)
        b1.addWidget(QLabel("Start"))
        b1.addWidget(self.start)
        b1.addWidget(QLabel("End"))
        b1.addWidget(self.end)
        b2 = QHBoxLayout()
        b2.addWidget(QLabel("Min score"))
        b2.addWidget(self.threshold)
        b2.addStretch(1)
        b2.addWidget(self.cancel_btn)
        b2.addWidget(self.batch_btn)
        batch = QGroupBox("Batch masking (prompt → one Object per label)")
        bl = QVBoxLayout(batch)
        bl.addLayout(b1)
        bl.addLayout(b2)
        bl.addWidget(self.progress)
        bl.addWidget(self.results, 1)

        body = QHBoxLayout()
        body.addWidget(cur, 1)
        body.addWidget(batch, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addLayout(body, 1)
        self.set_detections([], [])
        self._scope_changed()

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    def labels(self) -> List[str]:
        return split_labels(self.prompt.text())

    def _detect(self) -> None:
        labels = self.labels()
        if labels:
            self.detect_requested.emit(labels)

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Lock everything except the batch Cancel button while a long job runs."""
        self._busy = busy
        for w in (self.detect_btn, self.prompt, self.batch_btn, self.scope, self.start, self.end, self.threshold,
                  self.tree, self.results):
            w.setEnabled(not busy)
        for b in (self.all_btn, self.none_btn, self.clear_btn, self.add_btn):
            b.setEnabled(not busy and b.property("wanted") is not False)
        if message:
            self.status.setText(message)

    # ------------------------------------------------------------------
    # Current-image candidates
    # ------------------------------------------------------------------

    def set_detections(self, detections: Sequence[Detection], checked: Sequence[bool]) -> None:
        if detections is self._shown and len(detections) == self._n:
            self._sync_checks(checked)  # same results: keep the tree (scroll, collapsed groups)
            return
        self._shown = detections
        self._updating = True
        self.tree.clear()
        groups: Dict[str, QTreeWidgetItem] = {}
        for i, (d, c) in enumerate(zip(detections, checked, strict=True)):
            parent = groups.get(d.label)
            if parent is None:
                parent = QTreeWidgetItem([d.label])
                parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                self.tree.addTopLevelItem(parent)
                parent.setExpanded(True)
                groups[d.label] = parent
            it = QTreeWidgetItem([f"#{parent.childCount() + 1}   {d.score:.2f}  · {int(d.mask.sum()):,} px"])
            it.setIcon(0, color_icon(candidate_color(i)))
            it.setData(0, INDEX_ROLE, i)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked if c else Qt.CheckState.Unchecked)
            parent.addChild(it)
        for label, parent in groups.items():
            parent.setText(0, f"{label}  ({parent.childCount()})")
        self._n = len(detections)
        self._updating = False
        has = bool(detections)
        for b in (self.all_btn, self.none_btn, self.clear_btn):
            self._want(b, has)
        self._want(self.add_btn, any(checked))

    def _sync_checks(self, checked: Sequence[bool]) -> None:
        self._updating = True
        for it in self._leaves():
            state = Qt.CheckState.Checked if checked[it.data(0, INDEX_ROLE)] else Qt.CheckState.Unchecked
            if it.checkState(0) != state:
                it.setCheckState(0, state)
        self._updating = False
        self._want(self.add_btn, any(checked))

    def _want(self, button: QPushButton, on: bool) -> None:
        """Enable *button* when *on*, unless a long job is running (remembered for afterwards)."""
        button.setProperty("wanted", on)
        button.setEnabled(on and not self._busy)

    def _leaves(self) -> List[QTreeWidgetItem]:
        out = []
        for g in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(g)
            out.extend(parent.child(c) for c in range(parent.childCount()))
        return out

    def item(self, index: int) -> QTreeWidgetItem:
        """The tree row of flat detection *index*."""
        for it in self._leaves():
            if it.data(0, INDEX_ROLE) == index:
                return it
        raise IndexError(index)

    def checked(self) -> List[bool]:
        out = [False] * self._n
        for it in self._leaves():
            out[it.data(0, INDEX_ROLE)] = it.checkState(0) == Qt.CheckState.Checked
        return out

    def _set_all(self, on: bool) -> None:
        self._updating = True
        for it in self._leaves():
            it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self._updating = False
        self._on_changed()

    def _on_changed(self, *_):
        if self._updating:
            return
        self._want(self.add_btn, any(self.checked()))
        self._checks_timer.start()

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    def set_image_count(self, n: int) -> None:
        for sb in (self.start, self.end):
            sb.setMaximum(max(1, n))
        self.end.setValue(max(1, n))

    def _scope_changed(self, *_):
        ranged = self.scope.currentData() == "range"
        self.start.setVisible(ranged)
        self.end.setVisible(ranged)

    def _batch(self) -> None:
        labels = self.labels()
        if labels:
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
        self.cancel_btn.setEnabled(True)

    def batch_frame(self, index: int, text: str, found: bool) -> None:
        it = QListWidgetItem(f"{'✓' if found else '·'}  {text}")
        it.setData(INDEX_ROLE, index)
        self.results.addItem(it)
        self.progress.setValue(self.results.count())

    def batch_end(self, message: str) -> None:
        self.cancel_btn.setEnabled(False)
        self.status.setText(message)

    def _on_result(self, item: QListWidgetItem) -> None:
        idx = item.data(INDEX_ROLE)
        if idx is not None:
            self.navigate_requested.emit(int(idx))
