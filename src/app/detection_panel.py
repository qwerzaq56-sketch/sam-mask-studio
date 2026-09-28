"""SAM3 text prompt on the current image: Detections to check, preview and add.

``person, car, tripod`` is detected label by label; results are grouped per
label in a collapsible tree (the label row checks/unchecks all its
candidates). Checked candidates can be added as one Object each, merged into
one Object, or as one Object per prompt. The canvas can show or hide the
candidates (Preview) and pick them with Shift/Ctrl click or drag. Batch
masking over many images lives in its own tab (``batch_panel``).
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.app.objects_panel import color_icon
from src.core.project import Detection
from src.core.prompts import split_labels

CANDIDATE_COLORS = ((255, 200, 0), (0, 220, 255), (255, 90, 200), (140, 255, 90), (255, 140, 60), (170, 140, 255))
INDEX_ROLE = Qt.ItemDataRole.UserRole


def candidate_color(i: int):
    return CANDIDATE_COLORS[i % len(CANDIDATE_COLORS)]


class DetectionPanel(QWidget):
    detect_requested = pyqtSignal(list)  # labels, current image
    checks_changed = pyqtSignal(list)
    add_requested = pyqtSignal(str)  # "each" | "merged" | "per_label"
    clear_requested = pyqtSignal()
    preview_toggled = pyqtSignal(bool)
    select_toggled = pyqtSignal(bool)  # Select on Image

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
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setChecked(True)
        self.preview_btn.setToolTip("Show the candidates on the image")
        self.preview_btn.toggled.connect(self.preview_toggled)
        self.select_btn = QPushButton("Select on Image")
        self.select_btn.setCheckable(True)
        self.select_btn.setToolTip(
            "Pick candidates on the image: click / drag = add, Shift = toggle, Ctrl = remove.\n"
            "Turns on after a detection; Edit is blocked while it is on."
        )
        self.select_btn.toggled.connect(self.select_toggled)
        self.add_btn = QPushButton("Add Each")
        self.add_btn.setToolTip("One Object per checked candidate")
        self.add_btn.clicked.connect(lambda: self.add_requested.emit("each"))
        self.merge_btn = QPushButton("Add as One")
        self.merge_btn.setToolTip("Merge the checked candidates into one Object")
        self.merge_btn.clicked.connect(lambda: self.add_requested.emit("merged"))
        self.per_label_btn = QPushButton("Add per Prompt")
        self.per_label_btn.setToolTip("One Object per prompt: each label's checked candidates merged")
        self.per_label_btn.clicked.connect(lambda: self.add_requested.emit("per_label"))
        self.clear_btn = QPushButton("Discard")
        self.clear_btn.clicked.connect(self.clear_requested)
        row = QHBoxLayout()  # one row, so the buttons stay visible in a short dock
        for b in (self.all_btn, self.none_btn, self.preview_btn, self.select_btn):
            row.addWidget(b)
        row.addStretch(1)
        for b in (self.clear_btn, self.add_btn, self.merge_btn, self.per_label_btn):
            row.addWidget(b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self.set_detections([], [])

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
        """Lock the controls while a long job runs."""
        self._busy = busy
        for w in (self.detect_btn, self.prompt, self.tree):
            w.setEnabled(not busy)
        for b in (self.all_btn, self.none_btn, self.clear_btn, *self._add_buttons()):
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
        self._want_add(any(checked))

    def _sync_checks(self, checked: Sequence[bool]) -> None:
        self._updating = True
        for it in self._leaves():
            state = Qt.CheckState.Checked if checked[it.data(0, INDEX_ROLE)] else Qt.CheckState.Unchecked
            if it.checkState(0) != state:
                it.setCheckState(0, state)
        self._updating = False
        self._want_add(any(checked))

    def _add_buttons(self):
        return (self.add_btn, self.merge_btn, self.per_label_btn)

    def _want_add(self, on: bool) -> None:
        for b in self._add_buttons():
            self._want(b, on)

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
        self._want_add(any(self.checked()))
        self._checks_timer.start()
