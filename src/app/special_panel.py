"""The Special tab of Properties: a special Object's frames and settings (docs/specs/09-special-objects.md).

Settings apply as they move (masks made again on every frame the Object covers); **Make masks**
adds frames; **Apply** turns the Object into an ordinary one.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.project import MaskObject
from src.core.special import LABELS, LENS_EDGE, SKY

SCOPES = (("all", "All frames"), ("range", "Range"), ("selected", "Frames picked in the Frame List"))


class SpecialPanel(QWidget):
    params_changed = pyqtSignal(int, dict)  # Object id, its settings (settled for a moment)
    generate_requested = pyqtSignal(str, int, int)  # scope, start, end (0-based)
    detect_requested = pyqtSignal()
    apply_requested = pyqtSignal()

    def __init__(self, parent=None):
        from src.app.properties_panel import SliderField  # (a sibling module that imports this one)

        super().__init__(parent)
        self._updating = False
        self._kind: Optional[str] = None
        self.obj_id: Optional[int] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._send)

        # --- which frames
        self.scope = QComboBox()
        for key, text in SCOPES:
            self.scope.addItem(text, key)
        self.start = QSpinBox()
        self.end = QSpinBox()
        for sb in (self.start, self.end):
            sb.setMinimum(1)
        self.scope.currentIndexChanged.connect(self._on_scope)
        rng = QHBoxLayout()
        rng.addWidget(self.start)
        rng.addWidget(QLabel("~"))
        rng.addWidget(self.end)
        self.range_row = QWidget()
        self.range_row.setLayout(rng)
        rng.setContentsMargins(0, 0, 0, 0)
        self.generate_btn = QPushButton("Make Masks")
        self.generate_btn.clicked.connect(
            lambda: self.generate_requested.emit(self.scope.currentData(), self.start.value() - 1, self.end.value() - 1))
        self.coverage = QLabel("")
        self.coverage.setWordWrap(True)
        self.coverage.setStyleSheet("color: gray;")
        fbox = QGroupBox("Frames")
        fl = QVBoxLayout(fbox)
        fl.addWidget(self.scope)
        fl.addWidget(self.range_row)
        fl.addWidget(self.generate_btn)
        fl.addWidget(self.coverage)

        # --- settings, per kind
        self.threshold = SliderField(0, 100, 50, " %")
        self.threshold.setToolTip("How sure the model must be that a pixel is sky (higher: less sky)")
        self.refine = QCheckBox("Refine edges")
        self.refine.setToolTip("Snap the sky's edge to the image's colors (the model's own post-processing)")
        self.grow = SliderField(-50, 50, 0, " px")
        self.grow.setToolTip("Widen (+) or narrow (−) the sky")
        self.top_only = QCheckBox("Only sky touching the top edge")
        self.top_only.setToolTip("Drops sky-like pieces below the horizon (windows, water, reflections)")
        sky = QWidget()
        sf = QFormLayout(sky)
        sf.setContentsMargins(0, 0, 0, 0)
        sf.addRow("Threshold", self.threshold)
        sf.addRow("Grow / shrink", self.grow)
        sf.addRow(self.refine)
        sf.addRow(self.top_only)

        self.radius = SliderField(20, 300, 100, " %")
        self.radius.setToolTip("The image circle's radius, in % of half the shorter side")
        self.cx = SliderField(-100, 100, 0, " %")
        self.cy = SliderField(-100, 100, 0, " %")
        self.detect_btn = QPushButton("Detect from Images")
        self.detect_btn.setToolTip("Find the circle where the images are not black")
        self.detect_btn.clicked.connect(self.detect_requested)
        lens = QWidget()
        lf = QFormLayout(lens)
        lf.setContentsMargins(0, 0, 0, 0)
        lf.addRow("Radius", self.radius)
        lf.addRow("Center X", self.cx)
        lf.addRow("Center Y", self.cy)
        lf.addRow(self.detect_btn)

        self.stack = QStackedWidget()
        self._pages = {SKY: self.stack.addWidget(sky), LENS_EDGE: self.stack.addWidget(lens)}
        sbox = QGroupBox("Settings (applied to every covered frame)")
        QVBoxLayout(sbox).addWidget(self.stack)
        for w in (self.threshold, self.grow, self.radius, self.cx, self.cy):
            w.valueChanged.connect(self._changed)
        for c in (self.refine, self.top_only):
            c.toggled.connect(self._changed)

        self.apply_btn = QPushButton("Apply (make it an ordinary Object)")
        self.apply_btn.setToolTip("Keep the masks as they are and edit them by hand from now on; "
                                  "the settings go (Ctrl+Z brings them back)")
        self.apply_btn.clicked.connect(self.apply_requested)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(fbox)
        lay.addWidget(sbox)
        lay.addWidget(self.apply_btn)
        lay.addStretch(1)
        self._on_scope()

    def _on_scope(self) -> None:
        self.range_row.setVisible(self.scope.currentData() == "range")

    def _changed(self, *_a) -> None:
        if not self._updating:
            self._timer.start()

    def values(self) -> dict:
        if self._kind == SKY:
            return {"threshold": self.threshold.value(), "refine": float(self.refine.isChecked()),
                    "grow": self.grow.value(), "top_only": float(self.top_only.isChecked())}
        if self._kind == LENS_EDGE:
            return {"radius": self.radius.value(), "cx": self.cx.value(), "cy": self.cy.value()}
        return {}

    def _send(self) -> None:
        if self.obj_id is not None:
            self.params_changed.emit(self.obj_id, self.values())

    def flush(self) -> None:
        """A pending settings change, sent now (before the shown Object changes)."""
        if self._timer.isActive():
            self._timer.stop()
            self._send()

    def show_object(self, obj: Optional[MaskObject], frames: int, note: str = "") -> None:
        """*obj*'s settings (a special one); *frames*: how many images there are."""
        sp = obj.special if obj is not None else None
        if obj is None or obj.id != self.obj_id:
            self.flush()  # a setting moved just before another Object was shown: it goes to its own Object
        if sp is None:
            self._kind = self.obj_id = None
            return
        if self._timer.isActive():
            return  # still moving: the values on screen are newer than the Object's
        self._updating = True
        self.obj_id = obj.id
        self._kind = sp.kind
        self.stack.setCurrentIndex(self._pages[sp.kind])
        for sb in (self.start, self.end):
            sb.setMaximum(max(1, frames))
        if self.end.value() < 2:
            self.end.setValue(frames)
        if sp.kind == SKY:
            self.threshold.setValue(round(sp.get("threshold")))
            self.grow.setValue(round(sp.get("grow")))
            self.refine.setChecked(bool(sp.get("refine")))
            self.top_only.setChecked(bool(sp.get("top_only")))
        else:
            self.radius.setValue(round(sp.get("radius")))
            self.cx.setValue(round(sp.get("cx")))
            self.cy.setValue(round(sp.get("cy")))
        self.generate_btn.setText(f"Make {LABELS[sp.kind]} Masks")
        self.coverage.setText(f"Covers {len(sp.keys)} of {frames} frame(s); "
                              f"{len(obj.frames)} with a mask." + (f"\n{note}" if note else ""))
        self._updating = False
