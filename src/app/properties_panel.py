"""Properties (spec 01 §5, §8, §9): the selected / edited Object, its Variants and Points.

Points are listed as Positive (●) and Negative (×) groups, numbered in the
order they were placed; selecting one highlights it on the canvas and Delete
removes exactly that point.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.app.objects_panel import later
from src.app.ui_util import CollapsibleBox, shrinkable
from src.core.special import LABELS as SPECIAL_LABELS
from src.core.project import FrameState, MaskObject

THUMB = 56
# the selected mode button stands out
MODE_STYLE = (  # the selected mode is shown by color only (no sunken "pressed" look)
    "QPushButton { border: 1px solid #9a9a9a; border-radius: 3px; padding: 3px 8px; background: transparent; }"
    "QPushButton:checked { background: #2f6fd6; color: white; border-color: #2f6fd6; }"
)
# Direct brushes act as you paint; auto tools compute a result that is shown live
# and either filled in at once (Fill mode) or painted in (Brush mode).
DIRECT_TOOLS = ("paint", "restore")
AUTO_TOOLS = ("object_fill", "fill_holes", "remove_specks", "grow", "shrink", "close_gaps", "invert", "by_color")
TOOL_TEXT = {
    "paint": ("Paint", "Drag = add, Alt+drag = subtract (D)"),
    "restore": ("Restore", "Drag to undo the edit layer's changes where you paint (see the box)"),
    "object_fill": ("Object Fill", "Grow the mask to the object's edges in the image"),
    "fill_holes": ("Fill Holes", "Fill holes enclosed by the mask"),
    "remove_specks": ("Remove Specks", "Remove separate small pieces (the main piece stays)"),
    "grow": ("Grow", "Widen the whole mask by the amount"),
    "shrink": ("Shrink", "Narrow the whole mask by the amount"),
    "close_gaps": ("Close Gaps", "Fill narrow gaps between parts of the mask and narrow notches cut into it"),
    "invert": ("Invert", "Flip the mask: the object becomes the background and the background the object"),
    "by_color": ("By Color", "Redraw the mask's edge by brightness or color (skylines, leaves against the sky)"),
}
RESTORE_MODES = (
    ("added", "Add"),  # undo what the edit layer added
    ("removed", "Subtract"),  # undo what it subtracted
    ("both", "Both"),
)
POINT_ROLE = Qt.ItemDataRole.UserRole
LAYER_ROLE = Qt.ItemDataRole.UserRole + 1  # Points tree: the point layer a row belongs to (0 = Original)


def mask_thumbnail(image: Optional[np.ndarray], mask: np.ndarray, color, size: int = THUMB) -> QIcon:
    """Small preview of *mask* tinted over *image*."""
    h, w = mask.shape
    s = size / max(h, w)
    tw, th = max(1, int(w * s)), max(1, int(h * s))
    base = (
        cv2.resize(image, (tw, th), interpolation=cv2.INTER_AREA)
        if image is not None
        else np.zeros((th, tw, 3), np.uint8)
    )
    m = cv2.resize(mask.astype(np.uint8), (tw, th), interpolation=cv2.INTER_NEAREST) > 0
    out = (base.astype(np.float32) * 0.45).astype(np.uint8)
    out[m] = (0.4 * base[m] + 0.6 * np.array(color)).astype(np.uint8)
    out = np.ascontiguousarray(out)
    qi = QImage(out.data, tw, th, 3 * tw, QImage.Format.Format_RGB888).copy()
    return QIcon(QPixmap.fromImage(qi))


def _scrolled(page: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidget(page)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    page.setMinimumHeight(page.sizeHint().height())  # scroll instead of squashing the lists
    return area


class SliderField(QWidget):
    """A slider with a number box beside it (type a value or drag); *log* for wide ranges."""

    valueChanged = pyqtSignal(int)
    STEPS = 1000

    def __init__(self, lo: int, hi: int, value: int, suffix: str = "", log: bool = False, parent=None):
        super().__init__(parent)
        self._lo, self._hi, self._log = lo, hi, log
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.STEPS if log else hi - lo)
        self.spin = QSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setSuffix(suffix)
        self.spin.setMinimumWidth(80)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.spin)
        self.slider.valueChanged.connect(lambda t: self.spin.setValue(self._from_slider(t)))
        self.spin.valueChanged.connect(self._on_spin)
        self.setValue(value)

    def _from_slider(self, t: int) -> int:
        if not self._log:
            return self._lo + t
        lo = max(1, self._lo)
        return int(round(lo * (self._hi / lo) ** (t / self.STEPS)))

    def _to_slider(self, v: int) -> int:
        if not self._log:
            return v - self._lo
        lo = max(1, self._lo)
        return int(round(self.STEPS * np.log(max(v, lo) / lo) / np.log(self._hi / lo)))

    def _on_spin(self, v: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(self._to_slider(v))
        self.slider.blockSignals(False)
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.spin.value()

    def setValue(self, v: int) -> None:
        self.spin.setValue(int(v))
        self._on_spin(self.spin.value())


class PropertiesPanel(QWidget):
    variant_selected = pyqtSignal(int)
    point_selected = pyqtSignal(int)
    delete_point_requested = pyqtSignal()
    layer_selected = pyqtSignal(int)  # Points tree: clicks go to this layer (0 = Original)
    add_layer_requested = pyqtSignal()
    toggle_layer_requested = pyqtSignal()  # the current layer: add <-> subtract
    remove_layer_requested = pyqtSignal()
    delete_prompt_requested = pyqtSignal(int, int)  # × on a row: layer, point index (-1: the box)
    clear_points_requested = pyqtSignal()
    clear_box_requested = pyqtSignal()
    finish_requested = pyqtSignal()
    brush_tool_selected = pyqtSignal(str)  # "" = no tool, else a DIRECT_TOOLS / AUTO_TOOLS name
    auto_mode_changed = pyqtSignal(str)  # "fill" | "paint"
    auto_settings_changed = pyqtSignal()  # an auto tool's parameter moved (settled for a moment)
    color_pick_toggled = pyqtSignal(bool)  # By Color's picker: clicks on the image sample colors
    region_mode_toggled = pyqtSignal(bool)  # a drag on the image sets the tool region
    clear_region_requested = pyqtSignal()
    auto_apply_requested = pyqtSignal()  # write the auto tool's result in and leave the tool
    auto_recompute_requested = pyqtSignal()  # write it in, stay, compute the next one
    auto_apply_all_requested = pyqtSignal()  # Fill mode: the tool on every frame of the Object
    apply_layer_requested = pyqtSignal()
    delete_layer_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self._tool = ""
        self.title = QLabel("No Object selected")
        self.title.setWordWrap(True)
        self.hint = QLabel(
            "Pick an Object's <b>Points</b> (E), or <b>+ New Object from Points</b>.<br>"
            "Left click = positive, right click = negative, drag = box.<br>"
            "Ctrl+click adds the piece under the cursor, Ctrl+right-click takes it out (the rest stays).<br>"
            "Hand edits go to the <b>Edit Layer</b> tab (Paint: D)."
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray;")

        self.variants = QListWidget()
        self.variants.setIconSize(QSize(THUMB, THUMB))
        self.variants.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.variants.currentRowChanged.connect(self._on_variant)
        vbox = QGroupBox("Variants (pick one)")
        QVBoxLayout(vbox).addWidget(self.variants)

        # the Original and its point layers (docs/specs/10), each with its points / box and a × per row
        self.points = QTreeWidget()
        self.points.setColumnCount(2)
        self.points.setHeaderHidden(True)
        self.points.setRootIsDecorated(True)
        self.points.header().setStretchLastSection(False)
        self.points.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.points.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.points.currentItemChanged.connect(self._on_point)
        self.points.itemClicked.connect(self._on_prompt_row)
        self.add_layer_btn = QPushButton("+ Layer")
        self.add_layer_btn.setToolTip("A point layer: its own points make a piece added to the mask "
                                      "(the mask under it is kept)")
        self.add_layer_btn.clicked.connect(self.add_layer_requested)
        self.layer_sign_btn = QPushButton("+ / −")
        self.layer_sign_btn.setToolTip("The current point layer adds its piece <-> takes it out")
        self.layer_sign_btn.clicked.connect(self.toggle_layer_requested)
        self.remove_layer_btn = QPushButton("Remove Layer")
        self.remove_layer_btn.setToolTip("Remove the current point layer (its piece goes with it)")
        self.remove_layer_btn.clicked.connect(self.remove_layer_requested)
        self.box_label = QLabel("Box: —")
        self.box_label.setVisible(False)  # the box is a row in the tree now
        self.del_point_btn = QPushButton("Delete Point")
        self.del_point_btn.setToolTip("Delete the selected point (Delete)")
        self.del_point_btn.clicked.connect(self.delete_point_requested)
        self.clear_btn = QPushButton("Clear Points")
        self.clear_btn.clicked.connect(self.clear_points_requested)
        self.clear_box_btn = QPushButton("Clear Box")
        self.clear_box_btn.clicked.connect(self.clear_box_requested)
        row = QHBoxLayout()
        for b in (self.del_point_btn, self.clear_btn, self.clear_box_btn):
            row.addWidget(b)
        pbox = QGroupBox("Points")
        pl = QVBoxLayout(pbox)
        pl.addWidget(self.points)
        lrow = QHBoxLayout()
        for b in (self.add_layer_btn, self.layer_sign_btn, self.remove_layer_btn):
            lrow.addWidget(b)
        pl.addLayout(lrow)
        pl.addLayout(row)

        # --- edit layer (hand edits on top of the prompt-based mask)
        self.tool_btns = {}

        def tool_button(name: str) -> QPushButton:
            text, tip = TOOL_TEXT[name]
            b = QPushButton(text)
            b.setCheckable(True)
            b.setToolTip(tip + " — Ctrl+wheel = brush size, wheel = zoom")
            # an auto tool's button is never a toggle: clicking it again applies once more
            b.clicked.connect(
                lambda on, t=name: self.brush_tool_selected.emit(t if on or t in AUTO_TOOLS else "")
            )
            self.tool_btns[name] = b
            return b

        def note(text: str) -> QLabel:
            lb = QLabel(text)
            lb.setStyleSheet("color: gray;")
            lb.setWordWrap(True)
            return lb

        # Brush: acts as you paint.
        self.brush_btn = tool_button("paint")
        self.restore_mode = QComboBox()
        for value, text in RESTORE_MODES:
            self.restore_mode.addItem(text, value)
        self.restore_mode.setCurrentIndex(self.restore_mode.findData("both"))
        self.restore_mode.setToolTip(
            "What the Restore brush undoes: Add = what was painted on, Subtract = what was erased, Both"
        )
        self.brush_size = note("")
        tbox = QGroupBox("Brush")
        tg = QGridLayout(tbox)
        tg.addWidget(self.brush_btn, 0, 0, 1, 2)
        tg.addWidget(tool_button("restore"), 1, 0)
        tg.addWidget(self.restore_mode, 1, 1)
        tg.addWidget(self.brush_size, 2, 0, 1, 2)

        # Auto tools: one result; Fill takes all of it, Paint the parts you pick.
        self.mode_fill_btn = QPushButton("Fill")
        self.mode_paint_btn = QPushButton("Paint")
        for b, value, tip in (
            (self.mode_fill_btn, "fill", "Take the whole result (inside the region, if any)"),
            (self.mode_paint_btn, "paint", "Pick parts of the result with the brush; Alt+drag unpicks"),
        ):
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setStyleSheet(MODE_STYLE)
            b.clicked.connect(lambda _on, v=value: self._set_mode(v, emit=True))
        self.mode_hint = note("")
        self.region_btn = QPushButton("Region Box")
        self.region_btn.setCheckable(True)
        self.region_btn.setToolTip(
            "Drag boxes on the image to limit the auto tools to a region (cyan);\n"
            "Alt+drag removes a box. Without a region they act on the whole mask."
        )
        self.region_btn.toggled.connect(self._on_region_mode)
        self.clear_region_btn = QPushButton("Clear")
        self.clear_region_btn.clicked.connect(self.clear_region_requested)
        self.scope_label = note("")
        self.apply_auto_btn = QPushButton("Apply && Close")
        self.apply_auto_btn.setToolTip("Write the auto tool's result in (Fill: all of it, Paint: the picks) and leave it")
        self.apply_auto_btn.clicked.connect(self.auto_apply_requested)
        self.apply_auto_btn.setEnabled(False)
        self.recompute_btn = QPushButton("Apply && Continue")
        self.recompute_btn.setToolTip("Write the result in and compute the next one (Enter)")
        self.recompute_btn.clicked.connect(self.auto_recompute_requested)
        self.recompute_btn.setEnabled(False)
        self.apply_all_btn = QPushButton("Apply to All Frames")
        self.apply_all_btn.setToolTip(
            "Fill mode: this tool with these settings on every frame where the Object has a mask\n"
            "(inside the region, if any). One undo step (Ctrl+Z)"
        )
        self.apply_all_btn.clicked.connect(self.auto_apply_all_requested)
        self.apply_all_btn.setEnabled(False)
        abox = QGroupBox("Auto tools")
        av = QVBoxLayout(abox)
        rows = (
            (None, [tool_button("object_fill"), tool_button("fill_holes"), tool_button("remove_specks")]),
            (None, [tool_button("grow"), tool_button("shrink"), tool_button("close_gaps")]),
            (None, [tool_button("invert"), tool_button("by_color")]),
            ("Mode", [self.mode_fill_btn, self.mode_paint_btn]),
            (" ", [self.recompute_btn, self.apply_auto_btn]),
            (" ", [self.apply_all_btn]),
            (self.mode_hint, None),
            ("Region", [self.region_btn, self.clear_region_btn]),
            (self.scope_label, None),
        )
        for head, buttons in rows:
            if buttons is None:
                av.addWidget(head)
                continue
            row = QHBoxLayout()
            if head:
                label = QLabel(head)
                label.setMinimumWidth(48)
                row.addWidget(label)
            for b in buttons:
                shrinkable(b)  # shrink with the dock
                row.addWidget(b, 1)
            av.addLayout(row)
        self.mode = "fill"
        self._set_mode("fill")

        # Settings of the selected auto tool; any change is reported once it settles.
        self._settings_timer = QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.setInterval(120)
        self._settings_timer.timeout.connect(self.auto_settings_changed)
        self.fill_area = SliderField(1, 100_000, 200, " px", log=True)
        self.speck_area = SliderField(1, 100_000, 200, " px", log=True)
        self.grow = SliderField(1, 200, 20, " px")
        self.sensitivity = SliderField(0, 100, 50)
        self.amount = SliderField(1, 100, 3, " px")
        self.gap = SliderField(1, 200, 10, " px")
        self.color_basis = QComboBox()
        self.color_basis.addItem("Auto: Color", "color")
        self.color_basis.addItem("Auto: Brightness", "brightness")
        self.color_basis.addItem("Range (picked colors / brightness)", "range")
        self.color_basis.setToolTip(
            "Auto: Color: the colors near the edge in groups; a group the mask mostly covers is the mask's.\n"
            "Auto: Brightness: one gray-level threshold between the two sides.\n"
            "Range: the pixels like the colors you pick and / or within a brightness range.")
        self.color_basis.currentIndexChanged.connect(self._on_color_basis)
        self.color_action = QComboBox()
        for value, text in (("both", "Add & Remove"), ("add", "Add only"), ("remove", "Remove only")):
            self.color_action.addItem(text, value)
        self.color_action.setToolTip("Auto: what the result may change: both ways, only add to the mask, or only "
                                     "take out of it.\nRange: A = the pixels the filter catches, B = the rest. "
                                     "Add & Remove: A in, B out. Add only: A in. Remove only: B out")
        self.color_action.currentIndexChanged.connect(lambda _i: self._settings_timer.start())
        self.color_balance = SliderField(0, 100, 50)
        self.color_band = SliderField(0, 300, 30, " px")
        # Range: picked colors (hue and saturation, not brightness) and a brightness range
        self._samples: List[Tuple[int, int, int]] = []
        self.pick_btn = QPushButton("Pick Color")
        self.pick_btn.setCheckable(True)
        self.pick_btn.setStyleSheet("QPushButton:checked { background: #e08a00; color: black; font-weight: bold; }")
        self.pick_btn.setToolTip("On by itself in Range: clicking the image picks a color (no SAM point); Shift+click adds "
                                 "another (sky and cloud). Turn it off to place SAM points")
        self.pick_btn.toggled.connect(self._on_pick_toggled)
        self.clear_colors_btn = QPushButton("Clear")
        self.clear_colors_btn.clicked.connect(lambda: self.set_samples([]))
        self.swatches = QLabel("No color picked")
        self.swatches.setWordWrap(True)
        # each picked color is a link: clicking it removes just that one (ui-issues 22, p90)
        self.swatches.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.swatches.linkActivated.connect(self.remove_sample)
        self.color_use = QCheckBox("Color within")
        self.color_use.setChecked(True)
        self.color_tol = SliderField(1, 100, 30)
        self.color_tol.setToolTip("How far (Lab: lightness, hue and saturation) a pixel's color may be "
                                  "from a picked one")
        self.color_invert = QCheckBox("Invert (swap A and B)")
        self.color_invert.setToolTip("A = what the filter catches (picked colors / brightness range), B = the rest. "
                                     "Invert: the caught pixels are B, the rest A")
        self.color_invert.toggled.connect(lambda _on: self._settings_timer.start())
        self.bright_use = QCheckBox("Brightness from")
        self.bright_lo = SliderField(0, 255, 0)
        self.bright_hi = SliderField(0, 255, 255)
        for c in (self.color_use, self.bright_use):
            c.toggled.connect(lambda _on: self._settings_timer.start())
        for w in (self.fill_area, self.speck_area, self.grow, self.sensitivity, self.amount, self.gap,
                  self.color_balance, self.color_band, self.color_tol, self.bright_lo, self.bright_hi):
            w.valueChanged.connect(lambda _v: self._settings_timer.start())

        def page(rows, text: str) -> QWidget:
            w = QWidget()
            f = QFormLayout(w)
            f.setContentsMargins(0, 0, 0, 0)
            for label, field in rows:
                f.addRow(label, field)
            f.addRow(note(text))
            return w

        self.settings_stack = QStackedWidget()
        self._pages = {
            "object_fill": self.settings_stack.addWidget(page(
                (("Max grow", self.grow), ("Sensitivity", self.sensitivity)),
                "Max grow: how far the mask may spread. Sensitivity: higher spreads further "
                "into colors like the object's, lower stops sooner.",
            )),
            "fill_holes": self.settings_stack.addWidget(page(
                (("Max size", self.fill_area),), "Holes up to this many pixels are filled."
            )),
            "remove_specks": self.settings_stack.addWidget(page(
                (("Max size", self.speck_area),), "Separate pieces up to this many pixels are removed."
            )),
        }
        self._pages["grow"] = self._pages["shrink"] = self.settings_stack.addWidget(page(
            (("Amount", self.amount),), "How many pixels Grow widens / Shrink narrows the mask (shared)."
        ))
        self._pages["invert"] = self.settings_stack.addWidget(page(
            (), "No settings: inside the region (if any) the mask is flipped. Same as Ctrl+I, shown first."
        ))
        self._pages["close_gaps"] = self.settings_stack.addWidget(page(
            (("Max gap", self.gap),), "Gaps and notches up to this wide are filled; the mask never shrinks."
        ))
        by_color = QWidget()
        bf = QFormLayout(by_color)
        bf.setContentsMargins(0, 0, 0, 0)
        bf.addRow("By", self.color_basis)
        bf.addRow("Changes", self.color_action)
        self.color_band_on = QCheckBox("Near edge")
        self.color_band_on.setChecked(True)
        self.color_band_on.setToolTip("On: only pixels this close to the mask's edge may change (a skyline). "
                                      "Off: anywhere (inside the region if any)")
        self.color_band_on.toggled.connect(self._on_band_on)
        bf.addRow(self.color_band_on, self.color_band)
        self.balance_row = QWidget()
        brl = QFormLayout(self.balance_row)
        brl.setContentsMargins(0, 0, 0, 0)
        brl.addRow("Balance", self.color_balance)
        bf.addRow(self.balance_row)
        self.range_box = QWidget()
        rl = QGridLayout(self.range_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.pick_btn, 0, 0)
        rl.addWidget(self.clear_colors_btn, 0, 1)
        rl.addWidget(self.swatches, 1, 0, 1, 2)
        rl.addWidget(self.color_use, 2, 0)
        rl.addWidget(self.color_tol, 2, 1)
        rl.addWidget(self.bright_use, 3, 0)
        rl.addWidget(self.bright_lo, 3, 1)
        rl.addWidget(QLabel("to"), 4, 0, Qt.AlignmentFlag.AlignRight)
        rl.addWidget(self.bright_hi, 4, 1)
        rl.addWidget(self.color_invert, 5, 0, 1, 2)
        bf.addRow(self.range_box)
        bf.addRow(note(
            "Near edge (on): only pixels this close to the mask's edge may change; off: anywhere. Inside the "
            "region if any; Paint mode takes it only where you brush. Auto: like what the mask covers there "
            "or like the outside (the mask only has to be roughly right; Balance 50 = even, higher gives the "
            "mask more). Range: the pixels like the picked colors and / or within the brightness range, added to the "
            "mask, removed from it, or replacing it."))
        self._pages["by_color"] = self.settings_stack.addWidget(by_color)
        self._on_color_basis(emit=False)
        self.preview_label = note("")
        self.settings_box = CollapsibleBox("Settings")  # foldable: its state is kept in the settings
        sl = QVBoxLayout(self.settings_box.body)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.settings_stack)
        sl.addWidget(self.preview_label)
        self.settings_box.setVisible(False)

        self.layer_label = QLabel("Layer: none")
        self.apply_layer_btn = QPushButton("Apply Layer")
        self.apply_layer_btn.setToolTip("Make the edited mask the main mask (points are cleared; new points refine it)")
        self.apply_layer_btn.clicked.connect(self.apply_layer_requested)
        self.delete_layer_btn = QPushButton("Delete Layer")
        self.delete_layer_btn.setToolTip("Discard the hand edits and go back to the point/prompt mask")
        self.delete_layer_btn.clicked.connect(self.delete_layer_requested)
        lbox = self.layer_box = CollapsibleBox("Layer")
        ll = QGridLayout(lbox.body)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.layer_label, 0, 0, 1, 2)
        ll.addWidget(self.apply_layer_btn, 1, 0)
        ll.addWidget(self.delete_layer_btn, 1, 1)

        self.finish_btn = QPushButton("Finish Editing")
        self.finish_btn.setToolTip("Esc")
        self.finish_btn.clicked.connect(self.finish_requested)

        # Two tabs, each scrollable, so the panel fits a short window.
        mask_page = QWidget()
        ml = QVBoxLayout(mask_page)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(vbox, 1)
        ml.addWidget(pbox, 2)  # the point layers need the room more than the Variants
        layer_page = QWidget()
        el = QVBoxLayout(layer_page)
        el.setContentsMargins(0, 0, 0, 0)
        for box in (tbox, abox, self.settings_box, lbox):
            el.addWidget(box)
        el.addStretch(1)
        self.tabs = QTabWidget()
        self.mask_tab = self.tabs.addTab(_scrolled(mask_page), "Mask")
        self.layer_tab = self.tabs.addTab(_scrolled(layer_page), "Edit Layer")
        from src.app.special_panel import SpecialPanel

        self.special = SpecialPanel()  # a special Object's frames and settings (instead of the two above)
        self.special_tab = self.tabs.addTab(_scrolled(self.special), "Special")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.title)
        lay.addWidget(self.hint)
        lay.addWidget(self.tabs, 1)
        self.empty_space = QWidget()  # keeps the title and how-to at the top while the tabs are hidden
        self.empty_space.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        lay.addWidget(self.empty_space, 1)
        lay.addWidget(self.finish_btn)
        self.show_frame(None, None, None, None)

    def selected_point(self) -> Optional[int]:
        it = self.points.currentItem()
        return it.data(0, POINT_ROLE) if it is not None else None

    def _prompt_rows(self, frame: FrameState, layer: int, selected_point: Optional[int], editing: bool) -> None:
        """The Points tree: Original, Layer 1 (+), ... each with its points and box; the current layer bold."""
        sets = [("Original", frame.points, frame.box, None)]
        sets += [(f"Layer {n} ({'−' if ly.subtract else '+'})", ly.points, ly.box, ly)
                 for n, ly in enumerate(frame.layers, 1)]
        if layer > len(frame.layers):  # the next click makes it
            sets.append((f"Layer {layer} (+) · next click", (), None, None))
        for n, (title, pts, box, ly) in enumerate(sets):
            head = QTreeWidgetItem([title])
            head.setData(0, LAYER_ROLE, n)
            if ly is not None and ly.mask is None and ly.has_prompts:
                head.setToolTip(0, "No piece yet")
            f = QFont()
            f.setBold(n == layer and editing)
            head.setFont(0, f)
            self.points.addTopLevelItem(head)
            for i, p in enumerate(pts):
                it = QTreeWidgetItem([f"{'●' if p.positive else '×'} Point {i + 1}   ({p.x:.0f}, {p.y:.0f})"])
                it.setData(0, POINT_ROLE, i)
                it.setData(0, LAYER_ROLE, n)
                head.addChild(it)
                if editing:
                    self.points.setItemWidget(it, 1, self._x_button(n, i))
                if n == layer and i == selected_point:
                    self.points.setCurrentItem(it)
            if box is not None:
                it = QTreeWidgetItem(["▭ Box   " + ", ".join(f"{v:.0f}" for v in box)])
                it.setData(0, LAYER_ROLE, n)
                head.addChild(it)
                if editing:
                    self.points.setItemWidget(it, 1, self._x_button(n, -1))
            head.setExpanded(True)

    def _x_button(self, layer: int, index: int) -> QPushButton:
        b = QPushButton("×")
        b.setFixedWidth(22)
        b.setFlat(True)
        b.setToolTip("Delete this point" if index >= 0 else "Delete the box")
        b.clicked.connect(lambda _=False: self.delete_prompt_requested.emit(layer, index))
        return b

    def _on_prompt_row(self, item, _column: int = 0) -> None:
        if not self._updating and item is not None and item.parent() is None:
            self.layer_selected.emit(item.data(0, LAYER_ROLE))

    def show_frame(
        self,
        obj: Optional[MaskObject],
        frame: Optional[FrameState],
        selected_point: Optional[int],
        image: Optional[np.ndarray],
        new_mode: bool = False,
        editing: bool = False,
        layer: int = 0,
    ) -> None:
        """Show *obj*'s frame on the current image; point/box controls only work while *editing*."""
        self._updating = True
        self.variants.clear()
        self.points.clear()
        self.hint.setVisible(obj is None)  # the how-to only while nothing is shown
        self.tabs.setVisible(obj is not None)  # no empty lists / gray tools with nothing to show
        self.empty_space.setVisible(obj is None)
        if obj is None:
            self.title.setText(
                "<b>New Object</b> — click or drag a box on the image" if new_mode else "No Object selected"
            )
        else:
            state = "Editing" if editing else "Selected"
            what = f"Special: {SPECIAL_LABELS[obj.special.kind]}" if obj.special is not None else obj.source.value
            self.title.setText(f"{state}: <b>{obj.name}</b> · {what}")
        special = obj is not None and obj.special is not None
        for tab, on in ((self.mask_tab, not special), (self.layer_tab, not special), (self.special_tab, special)):
            self.tabs.setTabVisible(tab, on)
        if special:
            self.tabs.setCurrentIndex(self.special_tab)
        elif self.tabs.currentIndex() == self.special_tab:
            self.tabs.setCurrentIndex(self.mask_tab)
        if frame is not None and obj is not None:
            for i, v in enumerate(frame.variants):
                sel = i == min(frame.selected, len(frame.variants) - 1)
                it = QListWidgetItem(
                    mask_thumbnail(image, v.mask, obj.color),
                    f"{'●' if sel else '○'} Variant {i + 1}   {v.score:.3f}\n{v.area:,} px",
                )
                self.variants.addItem(it)
            if frame.variants:
                self.variants.setCurrentRow(min(frame.selected, len(frame.variants) - 1))
            self._prompt_rows(frame, layer, selected_point, editing)
            self.box_label.setText("Box: " + (", ".join(f"{v:.0f}" for v in frame.box) if frame.box else "—"))
        else:
            self.box_label.setText("Box: —")
        editing = editing and obj is not None
        has_points = frame is not None and (frame.has_prompts or bool(frame.layers))
        on_layer = frame is not None and 1 <= layer <= len(frame.layers)
        if frame is None:
            cur_pts, cur_box = (), None
        elif layer == 0:
            cur_pts, cur_box = frame.points, frame.box
        elif on_layer:
            cur_pts, cur_box = frame.layers[layer - 1].points, frame.layers[layer - 1].box
        else:
            cur_pts, cur_box = (), None
        self.del_point_btn.setEnabled(editing and selected_point is not None)
        self.clear_btn.setEnabled(editing and (bool(cur_pts) or cur_box is not None))
        self.clear_box_btn.setEnabled(editing and cur_box is not None)
        self.add_layer_btn.setEnabled(editing and frame is not None)
        self.layer_sign_btn.setEnabled(editing and on_layer)
        self.remove_layer_btn.setEnabled(editing and on_layer)
        self.points.setEnabled(has_points or editing)
        self.variants.setEnabled(obj is not None)
        layer = frame.edit if frame is not None else None
        self.layer_label.setText(
            f"Layer: +{layer.added:,} px / −{layer.removed:,} px" if layer is not None else "Layer: none"
        )
        has_mask = editing and frame is not None and frame.mask is not None
        self.brush_btn.setEnabled(editing)
        for name, b in self.tool_btns.items():
            if name == "restore":
                b.setEnabled(editing and frame is not None and frame.edit is not None or b.isChecked())
            elif name != "paint":
                b.setEnabled(has_mask or b.isChecked())
        if not editing:
            self.set_brush_tool("")  # the window turns the canvas brush off itself
            self.set_region_mode(False)
        for w in (self.mode_fill_btn, self.mode_paint_btn, self.region_btn):
            w.setEnabled(editing)
        self.apply_layer_btn.setEnabled(editing and layer is not None)
        self.delete_layer_btn.setEnabled(editing and layer is not None)
        self.finish_btn.setEnabled(editing or new_mode)
        self.finish_btn.setText("Cancel New Object" if new_mode else "Finish Editing")
        self._updating = False

    def set_brush_tool(self, tool: str) -> None:
        """Reflect the tool ("" = none) without re-emitting; picking one shows this tab."""
        if tool and tool != self._tool:
            self.tabs.setCurrentIndex(self.layer_tab)
        self._tool = tool
        for name, b in self.tool_btns.items():
            b.blockSignals(True)
            b.setChecked(name == tool)
            b.blockSignals(False)
        auto = tool in AUTO_TOOLS
        if tool != "by_color" and self.pick_btn.isChecked():
            self.pick_btn.setChecked(False)  # the picker belongs to By Color
        elif tool == "by_color" and self.color_basis.currentData() == "range":
            self.pick_btn.setChecked(True)  # Range: clicks pick colors, not SAM points (p77)
        self.settings_box.setVisible(auto)
        self.apply_auto_btn.setEnabled(auto)
        self.recompute_btn.setEnabled(auto)
        self._show_apply_all()
        if auto:
            self.settings_stack.setCurrentIndex(self._pages[tool])
            for i in range(self.settings_stack.count()):  # size to the page in use, not the tallest
                page = self.settings_stack.widget(i)
                policy = QSizePolicy.Policy.Preferred if i == self._pages[tool] else QSizePolicy.Policy.Ignored
                page.setSizePolicy(policy, policy)
            self.settings_stack.adjustSize()
            self.settings_box.setTitle(f"{TOOL_TEXT[tool][0]} settings")
        else:
            self.preview_label.setText("")

    def set_brush(self, on: bool) -> None:
        self.set_brush_tool("paint" if on else "")

    def _set_mode(self, mode: str, emit: bool = False) -> None:
        self.mode = mode
        self.mode_fill_btn.setChecked(mode == "fill")
        self.mode_paint_btn.setChecked(mode == "paint")
        if hasattr(self, "apply_all_btn"):
            self._show_apply_all()
        self.mode_hint.setText(
            "Blue = added, orange = removed (Range: blue = A, orange = B, light = stays). Enter applies · A: pick in Paint mode."
            if mode == "fill"
            else "Drag over the gray to pick · Alt+drag unpicks · A: all / none · Enter applies."
        )
        if emit:
            self.auto_mode_changed.emit(mode)

    def _show_apply_all(self) -> None:
        """Apply to All Frames: Fill mode only (Paint's picks belong to one image)."""
        fill = self.mode == "fill"
        self.apply_all_btn.setVisible(fill)
        self.apply_all_btn.setEnabled(fill and self._tool in AUTO_TOOLS)

    def set_region_mode(self, on: bool) -> None:
        """Reflect the region-box mode without re-emitting."""
        self.region_btn.blockSignals(True)
        self.region_btn.setChecked(on)
        self.region_btn.blockSignals(False)

    def tool_settings(self) -> dict:
        return {
            "fill_area": self.fill_area.value(),
            "speck_area": self.speck_area.value(),
            "max_grow": self.grow.value(),
            "sensitivity": self.sensitivity.value(),
            "amount": self.amount.value(),
            "gap": self.gap.value(),
            "color_basis": self.color_basis.currentData(),
            "color_balance": self.color_balance.value(),
            "color_band": self.color_band.value(),
            "color_band_on": self.color_band_on.isChecked(),
            "color_invert": self.color_invert.isChecked(),
            "color_action": self.color_action.currentData(),
            "color_samples": tuple(self._samples),
            "color_tol": self.color_tol.value(),
            "color_use": self.color_use.isChecked(),
            "bright_range": (self.bright_lo.value(), self.bright_hi.value()),
            "bright_use": self.bright_use.isChecked(),
            "restore": self.restore_mode.currentData(),
        }

    def set_preview(self, added: int, removed: int, total_added: int = 0, total_removed: int = 0,
                    busy: bool = False) -> None:
        """What leaving the tool will apply (and, in Paint mode, how much of the result that is)."""
        if busy:
            self.preview_label.setText("Computing…")
            return
        text = f"Will apply: +{added:,} px / −{removed:,} px"
        if self.mode == "paint":
            text += f"  (of +{total_added:,} / −{total_removed:,})"
        self.preview_label.setText(text)

    def set_region(self, region: Optional[np.ndarray]) -> None:
        has = region is not None
        self.clear_region_btn.setEnabled(has)
        self.scope_label.setText(
            f"Auto tools act inside the region ({int(region.sum()):,} px)" if has
            else "Auto tools act on the whole mask"
        )

    def set_brush_size(self, px: int) -> None:
        self.brush_size.setText(f"size {px}px · Ctrl+drag left / right or Ctrl+wheel to change")

    def _on_pick_toggled(self, on: bool) -> None:
        """The button says the state and the way out; the canvas follows."""
        self.pick_btn.setText("Stop Picking (Esc)" if on else "Pick Color")
        self.color_pick_toggled.emit(on)

    def _on_color_basis(self, _i: int = 0, emit: bool = True) -> None:
        """Balance is for the Auto ways, the picker and ranges for Range."""
        rng = self.color_basis.currentData() == "range"
        self.balance_row.setVisible(not rng)
        texts = ({"both": "Add A & Remove B", "add": "Add only (A)", "remove": "Remove only (B)"} if rng
                 else {"both": "Add & Remove", "add": "Add only", "remove": "Remove only"})
        for i in range(self.color_action.count()):
            self.color_action.setItemText(i, texts[self.color_action.itemData(i)])
        self.range_box.setVisible(rng)
        if not rng and self.pick_btn.isChecked():
            self.pick_btn.setChecked(False)
        elif rng and self._tool == "by_color":
            self.pick_btn.setChecked(True)  # Range: clicks pick colors, not SAM points (p77)
        if emit:
            self._settings_timer.start()

    def _on_band_on(self, on: bool) -> None:
        self.color_band.setEnabled(on)
        self._settings_timer.start()

    def add_sample(self, color, add: bool = False) -> None:
        """A color picked on the image: instead of the picked ones, or (*add*, Shift+click) one more."""
        self.set_samples((self._samples if add else []) + [tuple(int(v) for v in color)])

    def set_samples(self, colors) -> None:
        self._samples = [tuple(c) for c in colors][-8:]
        if self._samples:
            boxes = "".join(
                f'<a href="{i}" style="text-decoration: none;"><span style="background-color: rgb{c}; color: rgb{c};">'
                f'&nbsp;&nbsp;&nbsp;&nbsp;</span></a>&nbsp;'
                for i, c in enumerate(self._samples))
            self.swatches.setText(boxes + f" {len(self._samples)} color(s)")
            self.swatches.setToolTip("Click a color to remove just that one (Clear: all)")
        else:
            self.swatches.setText("No color picked")
            self.swatches.setToolTip("")
        self._settings_timer.start()

    def remove_sample(self, index) -> None:
        """Drop one picked color (its swatch was clicked); the rest stay."""
        i = int(index)
        if 0 <= i < len(self._samples):
            self.set_samples(self._samples[:i] + self._samples[i + 1:])

    def _on_region_mode(self, on: bool) -> None:
        if on:
            self.tabs.setCurrentIndex(self.layer_tab)
        self.region_mode_toggled.emit(on)

    def _on_variant(self, row: int) -> None:
        if not self._updating and row >= 0:
            later(self, self.variant_selected, row)

    def _on_point(self, item, _previous=None) -> None:
        if not self._updating and item is not None and item.data(0, POINT_ROLE) is not None:
            later(self, self.layer_selected, item.data(0, LAYER_ROLE))
            later(self, self.point_selected, item.data(0, POINT_ROLE))
