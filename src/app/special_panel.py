"""The Special tab of Properties: a special Object's frames and settings (docs/specs/09-special-objects.md).

Settings apply as they move (masks made again on every frame the Object covers); **Make masks**
adds frames; **Apply** turns the Object into an ordinary one. Sky's **Finish** (By Color + tree tips + SAM2 at
full resolution, as ``cli sky --color-preset``) is slow: it runs on Make masks only, and frames not finished
for the settings shown keep the model's mask.
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
from src.core.sky_sam2 import tips_apply
from src.core.special import LABELS, LENS_EDGE, LENS_MARGINS, LENS_SFM, LENS_TRAIN, SKY

SCOPES = (("all", "All frames"), ("range", "Range"), ("selected", "Frames picked in the Frame List"))
OWN = "\0own"  # the finish item for values kept in the Object (no By Color preset has them now)


class SpecialPanel(QWidget):
    params_changed = pyqtSignal(int, dict)  # Object id, its settings (settled for a moment)
    generate_requested = pyqtSignal(str, int, int)  # scope, start, end (0-based)
    detect_requested = pyqtSignal()
    apply_requested = pyqtSignal()
    stop_requested = pyqtSignal()  # stop finishing the sky (frames done stay)

    def __init__(self, parent=None):
        from src.app.properties_panel import SliderField  # (a sibling module that imports this one)

        super().__init__(parent)
        self._updating = False
        self._use = LENS_TRAIN  # the Lens edge use shown, to move the circle from on a change
        self._kind: Optional[str] = None
        self._presets: dict = {}  # By Color presets: name -> values
        self._finish: Optional[dict] = None  # the shown Object's finish
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
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setToolTip("Stop after this frame: the frames finished so far stay; Make Masks goes on")
        self.stop_btn.clicked.connect(self.stop_requested)
        self.stop_btn.hide()
        self.coverage = QLabel("")
        self.coverage.setWordWrap(True)
        self.coverage.setStyleSheet("color: gray;")
        fbox = QGroupBox("Frames")
        fl = QVBoxLayout(fbox)
        fl.addWidget(self.scope)
        fl.addWidget(self.range_row)
        fl.addWidget(self.generate_btn)
        fl.addWidget(self.stop_btn)
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
        self.finish = QComboBox()
        self.finish.setToolTip("After the model: this By Color preset at full resolution, the tree tips beyond its "
                               "band taken out, then SAM2 brings back the sky pieces it left out (as "
                               "cli sky --color-preset). Runs on Make Sky Masks; the preset's values are kept "
                               "in the Object")
        self.finish.addItem("Off", None)
        self.tips = QCheckBox("Take out tree tips")  # short: a check box never wraps (U3, p133)
        self.tips.setToolTip("Rough, not-sky-colored pixels up to 120 px from the tree, beyond By Color's "
                             "Near edge band (needs the preset's band on)")
        self.tips.setChecked(True)
        self.finish_note = QLabel("")
        self.finish_note.setWordWrap(True)
        self.finish_note.setStyleSheet("color: gray;")
        head = QLabel("Finish (By Color + SAM2, full resolution)")
        head.setStyleSheet("font-weight: 600; margin-top: 6px;")
        head.setWordWrap(True)
        sf.addRow(head)
        sf.addRow("By Color", self.finish)
        sf.addRow(self.tips)
        sf.addRow(self.finish_note)

        self.radius = SliderField(20, 300, 100, " %")
        self.radius.setToolTip("The image circle's radius, in % of half the shorter side")
        self.cx = SliderField(-100, 100, 0, " %")
        self.cy = SliderField(-100, 100, 0, " %")
        self.detect_btn = QPushButton("Detect from Images")
        self.detect_btn.setToolTip("Find the circle where the images are not black")
        self.detect_btn.clicked.connect(self.detect_requested)
        # p130: what the circle is for; the two differ in how much of the lenses' overlap they keep
        self.use = QComboBox()
        self.use.addItem("Training / stitching (wide)", LENS_TRAIN)
        self.use.addItem("SfM / alignment (tight)", LENS_SFM)
        self.use.setToolTip("Detect pulls the found circle in by this use's margin; changing it moves the "
                            "circle between the two")
        self.use.activated.connect(self._use_changed)
        self.use_note = QLabel("")
        self.use_note.setWordWrap(True)
        self.use_note.setStyleSheet("color: gray;")
        lens = QWidget()
        lf = QFormLayout(lens)
        lf.setContentsMargins(0, 0, 0, 0)
        lf.addRow("Use", self.use)
        lf.addRow(self.use_note)
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
        for c in (self.refine, self.top_only, self.tips):
            c.toggled.connect(self._changed)
        self.finish.currentIndexChanged.connect(self._tips_enabled)
        self.finish.activated.connect(self._changed)

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

    def _use_note(self) -> None:
        use = self.use.currentData()
        m = LENS_MARGINS[use]
        self.use_note.setText(
            f"{m:g} % in from the image circle, as Spirula's own mask (OSMO 360: about 98 %, SfM 186/188). "
            "Keeps most of the lens rim, where a dual fisheye's two lenses overlap: 0022 about 194° a lens, "
            "overlap about 14°, to stitch and train on. The rim is the most distorted part, so SfM may split "
            "on it: align with an SfM circle."
            if use == LENS_TRAIN else
            f"{m:g} % in from the image circle (OSMO 360: about 95 %, SplatBatch's rim95). Leaves out the "
            "distorted rim: 0022 SfM registered 188/188 (106-184 with the rim in). But about 185° a lens, "
            "overlap only about 5°: too little to stitch or train on. Use these masks for SfM only; train "
            "with the wide circle.")

    def _use_changed(self, *_a) -> None:
        """The circle moved from one use's margin to the other's (as if Detect had pulled it in by it)."""
        old = LENS_MARGINS[self._use]
        self._use = self.use.currentData()
        new = LENS_MARGINS[self._use]
        self._use_note()
        self._updating = True
        self.radius.setValue(round(self.radius.value() * (1 - new / 100.0) / (1 - old / 100.0)))
        self._updating = False
        self._changed()

    def _changed(self, *_a) -> None:
        if not self._updating:
            self._timer.start()

    def _finish_values(self) -> Optional[dict]:
        name = self.finish.currentData()
        if name is None:
            return None
        if name == OWN:
            return dict(self._finish or {}, tree_tips=self.tips.isChecked())
        return {"name": name, "color": self._presets[name], "tree_tips": self.tips.isChecked()}

    def _tips_enabled(self, *_a) -> None:
        name = self.finish.currentData()
        color = (self._finish or {}).get("color") if name == OWN else self._presets.get(name)
        self.tips.setEnabled(tips_apply(color))

    def set_color_presets(self, presets: dict) -> None:
        """The By Color presets the finish can use (the app's, as saved)."""
        self._presets = {str(k): dict(v) for k, v in (presets or {}).items() if isinstance(v, dict)}
        self._fill_finish()

    def _fill_finish(self) -> None:
        """The finish list with the shown Object's finish picked: its preset's name while that preset still has
        the same values, else the values kept in the Object."""
        fin = self._finish
        c = self.finish
        c.blockSignals(True)
        c.clear()
        c.addItem("Off", None)
        for name in sorted(self._presets, key=str.lower):
            c.addItem(name, name)
        if fin:
            name = fin.get("name")
            if name in self._presets and self._presets[name] == fin.get("color"):
                c.setCurrentIndex(c.findData(name))
            else:
                c.addItem(f"{name or 'By Color'} (kept in this Object)", OWN)
                c.setCurrentIndex(c.count() - 1)
        c.blockSignals(False)
        self._tips_enabled()

    def set_running(self, running: bool) -> None:
        """Finishing the sky: Stop instead of Make Masks."""
        self.stop_btn.setVisible(running)
        self.stop_btn.setEnabled(True)
        self.generate_btn.setVisible(not running)

    def values(self) -> dict:
        if self._kind == SKY:
            return {"threshold": self.threshold.value(), "refine": float(self.refine.isChecked()),
                    "grow": self.grow.value(), "top_only": float(self.top_only.isChecked()),
                    "finish": self._finish_values()}
        if self._kind == LENS_EDGE:
            return {"radius": self.radius.value(), "cx": self.cx.value(), "cy": self.cy.value(),
                    "use": float(self.use.currentData())}
        return {}

    def _send(self) -> None:
        if self.obj_id is not None:
            self.params_changed.emit(self.obj_id, self.values())

    def flush(self) -> None:
        """A pending settings change, sent now (before the shown Object changes)."""
        if self._timer.isActive():
            self._timer.stop()
            self._send()

    def show_object(self, obj: Optional[MaskObject], frames: int, note: str = "",
                    finished: Optional[int] = None) -> None:
        """*obj*'s settings (a special one); *frames*: how many images there are; *finished*: how many of
        the frames it covers have the sky finish (None: it has none)."""
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
            self._finish = sp.finish_values
            self.tips.setChecked(bool((self._finish or {}).get("tree_tips", True)))
            self._fill_finish()
            self.finish_note.setText(
                "Off: the model's mask (its edges decided at full resolution on Export)" if finished is None else
                f"Finished on {finished} of {len(sp.keys)} covered frame(s); the others show the model's mask. "
                "Make Sky Masks finishes the frames chosen above: SAM2 on the GPU (1 GB free), about 8 s a frame")
        else:
            self.radius.setValue(round(sp.get("radius")))
            self.cx.setValue(round(sp.get("cx")))
            self.cy.setValue(round(sp.get("cy")))
            self._use = LENS_SFM if sp.get("use") == LENS_SFM else LENS_TRAIN
            self.use.setCurrentIndex(self.use.findData(self._use))
            self._use_note()
        self.generate_btn.setText(f"Make {LABELS[sp.kind]} Masks")
        self.coverage.setText(f"Covers {len(sp.keys)} of {frames} frame(s); "
                              f"{len(obj.frames)} with a mask." + (f"\n{note}" if note else ""))
        self._updating = False
