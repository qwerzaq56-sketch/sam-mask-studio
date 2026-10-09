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
    QInputDialog,
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

from src.app.objects_panel import SOURCE_SHORT, later
from src.app.ui_util import CollapsibleBox, ColumnScroll, allow_narrow, shrinkable
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
NAME_ROLE = Qt.ItemDataRole.UserRole + 2  # Points tree: a made layer's own name ('' = none yet)


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
    area = ColumnScroll(page)
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
    layer_renamed = pyqtSignal(int, str)  # double-click a layer's row: its index (1..), the new name (p165)
    delete_prompt_requested = pyqtSignal(int, int)  # × on a row: layer, point index (-1: the box)
    clear_points_requested = pyqtSignal()
    clear_box_requested = pyqtSignal()
    finish_requested = pyqtSignal()
    edit_requested = pyqtSignal(int)  # the Edit Layer tab's Edit button: the Object shown (in Edit: finish), p94
    brush_tool_selected = pyqtSignal(str)  # "" = no tool, else a DIRECT_TOOLS / AUTO_TOOLS name
    auto_mode_changed = pyqtSignal(str)  # "fill" | "paint"
    auto_settings_changed = pyqtSignal()  # an auto tool's parameter moved (settled for a moment)
    color_samples_edited = pyqtSignal(object)  # picked / left-out colors changed by hand ((in, out)): an undo step
    color_presets_changed = pyqtSignal(object)  # By Color presets saved / deleted: {name: settings} to keep (p105)
    color_pick_toggled = pyqtSignal(bool)  # By Color's picker: clicks on the image sample colors
    original_view_toggled = pyqtSignal(bool)  # while picking: the photo alone, no overlays (BC-P3)
    region_mode_toggled = pyqtSignal(bool)  # a drag on the image sets the tool region
    clear_region_requested = pyqtSignal()
    auto_apply_requested = pyqtSignal()  # write the auto tool's result in and leave the tool
    auto_recompute_requested = pyqtSignal()  # write it in, stay, compute the next one
    auto_apply_all_requested = pyqtSignal()  # Fill mode: the tool on the Object's frames (all / picked)
    apply_layer_requested = pyqtSignal()
    delete_layer_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self._tool = ""
        self.title = QLabel("No Object selected")
        self.title.setWordWrap(True)
        self.hint = QLabel(
            "Pick an Object's <b>Points</b> (E), or <b>+ New Object</b>.<br>"
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
        self.points.itemDoubleClicked.connect(self._rename_layer_row)
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
        self.apply_all_btn = QPushButton("Apply to Frames…")
        self.apply_all_btn.setToolTip(
            "Fill mode: this tool with these settings on every frame where the Object has a mask, or only on\n"
            "the frames picked in the Frame List (Shift-click a range, Ctrl-click more); inside the region,\n"
            "if any. One undo step (Ctrl+Z)"
        )
        self.apply_all_btn.clicked.connect(self.auto_apply_all_requested)
        self.apply_all_btn.setEnabled(False)
        abox = QGroupBox("Auto tools")
        av = QVBoxLayout(abox)
        rows = (
            # two a row (U3, p133): three cut "Remove Specks" / "Close Gaps" off in a 1280 px window
            (None, [tool_button("object_fill"), tool_button("fill_holes")]),
            (None, [tool_button("remove_specks"), tool_button("close_gaps")]),
            (None, [tool_button("grow"), tool_button("shrink")]),
            (None, [tool_button("invert"), tool_button("by_color")]),
            ("Mode", [self.mode_fill_btn, self.mode_paint_btn]),
            (None, [self.recompute_btn, self.apply_auto_btn]),
            (None, [self.apply_all_btn]),
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
        # By Color = Range only: the Auto ways (Color / Brightness) went in p97 (BC-P5)
        self.color_action = QComboBox()
        for value, text in (("both", "Add A & Remove B"), ("add", "Add only (A)"), ("remove", "Remove only (B)")):
            self.color_action.addItem(text, value)
        self.color_action.setToolTip("A = the pixels the filter catches, B = the rest. "
                                     "Add & Remove: A in, B out. Add only: A in. Remove only: B out")
        self.color_action.currentIndexChanged.connect(lambda _i: self._settings_timer.start())
        self.color_band = SliderField(0, 300, 30, " px")
        # Range: picked colors (hue and saturation, not brightness) and a brightness range
        self._samples: List[Tuple[int, int, int]] = []
        self._samples_out: List[Tuple[int, int, int]] = []  # left-out colors: right-click while picking (BC-P4 b)
        self.pick_btn = QPushButton("Pick Color")
        self.pick_btn.setCheckable(True)
        self.pick_btn.setStyleSheet("QPushButton:checked { background: #e08a00; color: black; font-weight: bold; }")
        self.pick_btn.setToolTip("Clicking the image picks that pixel's color (no SAM point), instead of the picked ones; "
                                 "Shift+click adds another (sky and cloud); with Alt: the 5×5 mean around it. "
                                 "Right-click: a color to leave out (−), the same way. On by itself while no color "
                                 "is picked. Ctrl+Z undoes a change to the colors")
        self.pick_btn.toggled.connect(self._on_pick_toggled)
        self.original_btn = QPushButton("Original (hold T)")
        self.original_btn.setCheckable(True)
        self.original_btn.setEnabled(False)  # only while picking; picking stops -> off (BC-P3)
        self.original_btn.setStyleSheet("QPushButton:checked { background: #e08a00; color: black; font-weight: bold; }")
        self.original_btn.setToolTip("While picking colors: the photo alone, without mask colors, the tool's preview "
                                     "or the legend, to judge the colors you pick. Click: on / off; hold T: turned around "
                                     "just while held. Goes off with the picker")
        self.original_btn.toggled.connect(self.original_view_toggled)
        self.clear_colors_btn = QPushButton("Clear")
        self.clear_colors_btn.clicked.connect(lambda: self.set_samples([], out=[]))
        self.swatches = QLabel("No color picked")
        self.swatches.setWordWrap(True)
        # each picked color is a link: clicking it removes just that one (ui-issues 22, p90)
        self.swatches.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.swatches.linkActivated.connect(self.remove_sample)
        self.color_use = QCheckBox("Color within")
        self.color_use.setChecked(True)
        self.color_tol = SliderField(1, 100, 30)
        self.color_tol.setToolTip("How far a pixel's color may be from a picked one. "
                                  "Lab distance (lightness, hue, saturation): about 10 = almost the same color, 30 = alike (sky blue vs a lighter sky), 60+ = most of the image. 100 takes everything")
        self.color_tol_out = SliderField(1, 100, 30)
        self.color_tol_out.setToolTip("How far a pixel's color may be from a left-out color (−) to be left out. "
                                      "Near both a picked and a left-out color: the nearer one wins. "
                                      "Lab distance (lightness, hue, saturation): about 10 = almost the same color, 30 = alike (sky blue vs a lighter sky), 60+ = most of the image. 100 takes everything")
        self.color_invert = QCheckBox("Swap A / B")
        self.color_invert.setToolTip("A = what the filter catches (picked colors / brightness range), B = the rest. "
                                     "Swap: the caught pixels are B, the rest A. To turn just one condition "
                                     "around, use its Not")
        self.color_invert.toggled.connect(lambda _on: self._settings_timer.start())
        self.bright_use = QCheckBox("Brightness from")
        self.bright_lo = SliderField(0, 255, 0)
        self.bright_hi = SliderField(0, 255, 255)
        # each condition turned around on its own (BC-P4 a): "brightness, but not the sky's colors"
        self.color_not = QCheckBox("Not")
        self.color_not.setToolTip("Not: the pixels far from every picked color (e.g. bright leaves = Brightness "
                                  "from 140 and Not the sky's colors). Picked colors only: left-out colors (−) "
                                  "leave out either way, so with none picked there is nothing to turn around")
        self.color_not.setEnabled(False)  # until a color is picked (p99)
        # what the color condition alone takes where By Color decides: near 0 or 100 % it decides nothing (p99)
        self.color_cover = QLabel("")
        self.color_cover.setWordWrap(True)
        self.color_cover.setVisible(False)
        self.bright_not = QCheckBox("Not")
        self.bright_not.setToolTip("Not: the pixels outside the brightness range")
        # how the color and brightness conditions join (p101): two ways of catching the same thing add up
        self.range_join = QComboBox()
        self.range_join.addItem("Or: either one catches (add up)", "or")
        self.range_join.addItem("And: both must catch", "and")
        self.range_join.setToolTip("Or: A = what the colors catch + what the brightness range catches (e.g. the "
                                   "blue sky by its color and the clouds by their brightness). And: only what "
                                   "both catch (e.g. bright, and Not the sky's colors). Left-out colors (−) are "
                                   "taken out of A either way")
        self.range_join.currentIndexChanged.connect(lambda _i: self._settings_timer.start())
        for c in (self.color_use, self.bright_use, self.color_not, self.bright_not):
            c.toggled.connect(lambda _on: self._settings_timer.start())
        for w in (self.fill_area, self.speck_area, self.grow, self.sensitivity, self.amount, self.gap,
                  self.color_band, self.color_tol, self.color_tol_out, self.bright_lo, self.bright_hi):
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
        # only the shown tool's page sets the width: By Color's must not widen Grow's (U3, p133)
        self.settings_stack.currentChanged.connect(self._fit_stack)
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
        bf.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)  # a narrow dock: the field under its label
        # presets (p105): every By Color setting, the picked and left-out colors too, under a name
        self._color_presets: dict = {}
        self.color_preset = QComboBox()
        self.color_preset.setToolTip("Pick a saved preset to use it: colors, tolerances, brightness, Join, Not, "
                                     "Swap, Changes and Near edge (Ctrl+Z undoes its colors)")
        self.color_preset.activated.connect(self._on_preset_picked)
        self.save_preset_btn = QPushButton("Save…")
        self.save_preset_btn.setToolTip("Save these By Color settings (with the picked colors) as a preset")
        self.save_preset_btn.clicked.connect(self.save_color_preset)
        self.delete_preset_btn = QPushButton("Delete")
        self.delete_preset_btn.setToolTip("Delete the preset shown")
        self.delete_preset_btn.clicked.connect(self.delete_color_preset)
        prow = QWidget()
        pl = QHBoxLayout(prow)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.color_preset, 1)
        pl.addWidget(self.save_preset_btn)
        pl.addWidget(self.delete_preset_btn)
        bf.addRow("Preset", prow)
        self._fill_presets()
        bf.addRow("Changes", self.color_action)
        self.color_band_on = QCheckBox("Near edge")
        self.color_band_on.setChecked(True)
        self.color_band_on.setToolTip("On: only pixels this close to the mask's edge may change (a skyline). "
                                      "Off: anywhere (inside the region if any)")
        self.color_band_on.toggled.connect(self._on_band_on)
        bf.addRow(self.color_band_on, self.color_band)
        self.range_box = QWidget()
        rl = QGridLayout(self.range_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.pick_btn, 0, 0)
        rl.addWidget(self.original_btn, 0, 1, 1, 2)
        rl.addWidget(self.swatches, 1, 0)
        rl.addWidget(self.clear_colors_btn, 1, 1, 1, 2, Qt.AlignmentFlag.AlignTop)
        rl.addWidget(self.color_use, 2, 0)
        rl.addWidget(self.color_tol, 2, 1)
        rl.addWidget(self.color_not, 2, 2)
        self.tol_out_label = QLabel("− except within")
        self.tol_out_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        rl.addWidget(self.tol_out_label, 3, 0)
        rl.addWidget(self.color_tol_out, 3, 1)
        for w in (self.tol_out_label, self.color_tol_out):
            w.setEnabled(False)  # until a color is left out
        rl.addWidget(self.color_cover, 4, 0, 1, 3)
        self.join_label = QLabel("Join")
        self.join_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        rl.addWidget(self.join_label, 5, 0)
        rl.addWidget(self.range_join, 5, 1, 1, 2)
        rl.addWidget(self.bright_use, 6, 0)
        rl.addWidget(self.bright_lo, 6, 1)
        rl.addWidget(self.bright_not, 6, 2)
        rl.addWidget(QLabel("to"), 7, 0, Qt.AlignmentFlag.AlignRight)
        rl.addWidget(self.bright_hi, 7, 1)
        rl.addWidget(self.color_invert, 8, 0, 1, 3)
        bf.addRow(self.range_box)
        bf.addRow(note(
            "Near edge (on): only pixels this close to the mask's edge may change; off: anywhere. Inside the "
            "region if any; Paint mode takes it only where you brush. A = the pixels like the picked colors and / or "
            "within the brightness range (Join: Or = either one, And = both; Not turns one around), less the "
            "left-out colors; B = the rest. Right-click while picking: a color to leave out (−); near a picked and "
            "a left-out color, the nearer one wins."))
        self._pages["by_color"] = self.settings_stack.addWidget(by_color)
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

        # the Object list's Points / Editing button, here too (p94): on while this Object is in Edit
        self._shown_id: Optional[int] = None
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setCheckable(True)
        self.edit_btn.setObjectName("layer_edit_btn")
        self.edit_btn.clicked.connect(self._on_edit_btn)
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
        el.addWidget(self.edit_btn)
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
        allow_narrow(self, min_chars=6)  # combo boxes and buttons shrink with the dock instead of being cut off (U3)
        for b in layer_page.findChildren(QPushButton):
            if b is not self.edit_btn:  # it carries the Object's name
                b.setMinimumWidth(0)  # the tool buttons keep their whole label: the dock widens instead
        self._fit_stack(self.settings_stack.currentIndex())
        self.show_frame(None, None, None, None)

    def _fit_stack(self, index: int) -> None:
        for i in range(self.settings_stack.count()):
            policy = QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored
            self.settings_stack.widget(i).setSizePolicy(policy, policy)

    def selected_point(self) -> Optional[int]:
        it = self.points.currentItem()
        return it.data(0, POINT_ROLE) if it is not None else None

    def _prompt_rows(self, frame: FrameState, layer: int, selected_point: Optional[int], editing: bool) -> None:
        """The Points tree: Original, Layer 1 (+), ... each with its points and box; the current layer bold."""
        sets = [("Original", frame.points, frame.box, None)]
        sets += [(f"{ly.name or f'Layer {n}'} ({'−' if ly.subtract else '+'})", ly.points, ly.box, ly)
                 for n, ly in enumerate(frame.layers, 1)]
        if layer > len(frame.layers):  # the next click makes it
            sets.append((f"Layer {layer} (+) · next click", (), None, None))
        for n, (title, pts, box, ly) in enumerate(sets):
            head = QTreeWidgetItem([title])
            head.setData(0, LAYER_ROLE, n)
            if ly is not None:
                head.setData(0, NAME_ROLE, ly.name)
                head.setToolTip(0, ("No piece yet. " if ly.mask is None and ly.has_prompts else "")
                                + "Double-click to rename")
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

    def _rename_layer_row(self, item, _column: int = 0) -> None:
        n = item.data(0, LAYER_ROLE) if item is not None and item.parent() is None else None
        if not n or item.data(0, NAME_ROLE) is None:  # the Original, or a layer not made yet
            return
        name, ok = QInputDialog.getText(self, "Rename Layer", f"Name of Layer {n} (empty: Layer {n}):",
                                        text=item.data(0, NAME_ROLE))
        if ok:
            self.layer_renamed.emit(n, name)

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
            what = f"Special: {SPECIAL_LABELS[obj.special.kind]}" if obj.special is not None else f"from {SOURCE_SHORT.get(obj.source, obj.source.value)}"  # U8: not SAM3_DETECTION
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
        self._shown_id = obj.id if obj is not None else None
        self.edit_btn.setChecked(editing)
        self.edit_btn.setText(f"Editing: {obj.name}  (Esc: finish)" if editing and obj is not None
                              else f"Edit {obj.name}  (E)" if obj is not None else "Edit")
        self.edit_btn.setToolTip("Finish Editing (Esc); same as the Object list's Editing button" if editing else
                                 "Edit this Object: brush, auto tools and points (E); same as the Object list's "
                                 "Points button")
        self.edit_btn.setEnabled(obj is not None)
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
        elif tool == "by_color" and not self._samples and not self._samples_out:
            # Range with nothing picked yet: clicks pick colors, not SAM points (p77). With colors already
            # picked it stays off, so an unnoticed click does not replace them (p92)
            self.pick_btn.setChecked(True)
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
        """Apply to Frames: Fill mode only (Paint's picks belong to one image)."""
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
            "color_band": self.color_band.value(),
            "color_band_on": self.color_band_on.isChecked(),
            "color_invert": self.color_invert.isChecked(),
            "color_action": self.color_action.currentData(),
            "color_samples": tuple(self._samples),
            "color_samples_out": tuple(self._samples_out),
            "color_tol_out": self.color_tol_out.value(),
            "color_tol": self.color_tol.value(),
            "color_use": self.color_use.isChecked(),
            "color_not": self.color_not.isChecked(),
            "bright_range": (self.bright_lo.value(), self.bright_hi.value()),
            "bright_use": self.bright_use.isChecked(),
            "bright_not": self.bright_not.isChecked(),
            "range_join": self.range_join.currentData(),
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
        if not on:
            self.original_btn.setChecked(False)
        self.original_btn.setEnabled(on)
        self.color_pick_toggled.emit(on)

    def _on_band_on(self, on: bool) -> None:
        self.color_band.setEnabled(on)
        self._settings_timer.start()

    def _on_edit_btn(self) -> None:
        """Start / finish editing the Object shown; the window redraws both buttons (the click's own check
        state is not trusted: it follows the session)."""
        if self._shown_id is not None:
            later(self, self.edit_requested, self._shown_id)

    def add_sample(self, color, add: bool = False) -> None:
        """A color picked on the image: instead of the picked ones, or (*add*, Shift+click) one more."""
        self.set_samples((self._samples if add else []) + [tuple(int(v) for v in color)])

    def add_sample_out(self, color, add: bool = False) -> None:
        """A color to leave out (right-click while picking, BC-P4 b): instead of the left-out ones, or one more."""
        self.set_samples(self._samples, out=(self._samples_out if add else []) + [tuple(int(v) for v in color)])

    def set_samples(self, colors, edited: bool = True, out=None) -> None:
        """*out*: the left-out colors (None: as they are). *edited*: changed by hand (an undo step); False when
        undo / redo puts them back."""
        before = (tuple(self._samples), tuple(self._samples_out))
        self._samples = [tuple(c) for c in colors][-8:]
        if out is not None:
            self._samples_out = [tuple(c) for c in out][-8:]
        now = (tuple(self._samples), tuple(self._samples_out))
        if edited and now != before:
            self.color_samples_edited.emit(now)

        def boxes(cs, prefix: str) -> str:
            return "".join(
                f'<a href="{prefix}{i}" style="text-decoration: none;"><span style="background-color: rgb{c}; '
                f'color: rgb{c};">&nbsp;&nbsp;&nbsp;&nbsp;</span></a>&nbsp;'
                for i, c in enumerate(cs))
        parts = []
        if self._samples:
            parts.append(boxes(self._samples, "") + f" {len(self._samples)} color(s)")
        if self._samples_out:
            parts.append("<b>−</b>&nbsp;" + boxes(self._samples_out, "o") + f" {len(self._samples_out)} left out")
        if parts:
            self.swatches.setText("<br>".join(parts))
            self.swatches.setToolTip("Click a color to remove just that one (Clear: all). −: left out "
                                     "(right-click while picking)")
        else:
            self.swatches.setText("No color picked")
            self.swatches.setToolTip("")
        has_out = bool(self._samples_out)
        self.tol_out_label.setEnabled(has_out)
        self.color_tol_out.setEnabled(has_out)
        self.color_not.setEnabled(bool(self._samples))  # Not turns the picked colors around only (p99)
        self._settings_timer.start()

    # --- By Color presets (p105) -------------------------------------------------------------------------

    PRESET_KEYS = ("color_action", "color_band", "color_band_on", "color_samples", "color_samples_out", "color_tol",
                   "color_tol_out", "color_use", "color_not", "bright_range", "bright_use", "bright_not",
                   "range_join", "color_invert")

    def load_color_presets(self, presets: dict, current: Optional[str] = None) -> None:
        """The saved presets (from the settings file); *current* stays shown."""
        self._color_presets = {str(k): dict(v) for k, v in (presets or {}).items() if isinstance(v, dict)}
        self._fill_presets(current)

    def _fill_presets(self, current: Optional[str] = None) -> None:
        c = self.color_preset
        c.blockSignals(True)
        c.clear()
        if not self._color_presets:
            c.addItem("(no presets: Save… keeps these settings)", None)
        for name in sorted(self._color_presets, key=str.lower):
            c.addItem(name, name)
        if current is not None and c.findData(current) >= 0:
            c.setCurrentIndex(c.findData(current))
        c.blockSignals(False)
        self.delete_preset_btn.setEnabled(bool(self._color_presets))

    def color_preset_values(self) -> dict:
        """These By Color settings as a preset (JSON-friendly)."""
        t = self.tool_settings()
        out = {k: t[k] for k in self.PRESET_KEYS}
        for k in ("color_samples", "color_samples_out", "bright_range"):
            out[k] = [list(c) for c in out[k]] if k != "bright_range" else list(out[k])
        return out

    def apply_color_preset(self, values: dict, edited: bool = True) -> None:
        """Put a preset's settings in (missing keys keep their value); the colors change as one undo step
        (*edited* False: no undo step, e.g. the last settings put back at start)."""
        v = values
        if "color_action" in v and self.color_action.findData(v["color_action"]) >= 0:
            self.color_action.setCurrentIndex(self.color_action.findData(v["color_action"]))
        if "range_join" in v and self.range_join.findData(v["range_join"]) >= 0:
            self.range_join.setCurrentIndex(self.range_join.findData(v["range_join"]))
        for k, w in (("color_band_on", self.color_band_on), ("color_use", self.color_use),
                     ("bright_use", self.bright_use), ("bright_not", self.bright_not),
                     ("color_invert", self.color_invert)):
            if k in v:
                w.setChecked(bool(v[k]))
        for k, w in (("color_band", self.color_band), ("color_tol", self.color_tol),
                     ("color_tol_out", self.color_tol_out)):
            if k in v:
                w.setValue(int(v[k]))
        if "bright_range" in v and len(v["bright_range"]) == 2:
            self.bright_lo.setValue(int(v["bright_range"][0]))
            self.bright_hi.setValue(int(v["bright_range"][1]))
        if "color_samples" in v or "color_samples_out" in v:
            cin = [tuple(int(x) for x in c) for c in v.get("color_samples", self._samples)]
            cout = [tuple(int(x) for x in c) for c in v.get("color_samples_out", self._samples_out)]
            self.set_samples(cin, edited=edited, out=cout)  # edited: emits color_samples_edited, one undo step
        if "color_not" in v:  # after the colors: Not waits for a picked color
            self.color_not.setChecked(bool(v["color_not"]) and self.color_not.isEnabled())
        self._settings_timer.start()

    def _on_preset_picked(self, index: int) -> None:
        name = self.color_preset.itemData(index)
        if name in self._color_presets:
            self.apply_color_preset(self._color_presets[name])

    def ask_preset_name(self, default: str) -> Optional[str]:
        """The name to save under; tests replace this."""
        name, ok = QInputDialog.getText(self, "Save By Color Preset", "Preset name (the same name replaces it):",
                                        text=default)
        return name.strip() if ok and name.strip() else None

    def save_color_preset(self) -> None:
        current = self.color_preset.currentData()
        name = self.ask_preset_name(current or "")
        if name is None:
            return
        self._color_presets[name] = self.color_preset_values()
        self._fill_presets(name)
        self.color_presets_changed.emit(dict(self._color_presets))

    def delete_color_preset(self) -> None:
        name = self.color_preset.currentData()
        if name not in self._color_presets:
            return
        del self._color_presets[name]
        self._fill_presets()
        self.color_presets_changed.emit(dict(self._color_presets))

    def set_color_cover(self, share: Optional[float]) -> None:
        """How much of the area By Color decides the color condition alone takes (None: not in use); a warning
        near 0 or 100 %, where the colors decide nothing (p99: tolerance 100 took everything)."""
        if share is None:
            self.color_cover.setVisible(False)
            return
        pct = share * 100
        warn = pct >= 95 or pct <= 1
        text = f"Color takes {pct:.0f} % of the area"
        if warn:
            text += " — it tells nothing apart: check the tolerances (a wide − takes everything out)"
        self.color_cover.setText(text)
        self.color_cover.setStyleSheet("color: #e08a00; font-weight: bold;" if warn else "color: gray;")
        self.color_cover.setVisible(True)

    def remove_sample(self, index) -> None:
        """Drop one picked (``"2"``) or left-out (``"o2"``) color (its swatch was clicked); the rest stay."""
        index = str(index)
        if index.startswith("o"):
            i = int(index[1:])
            if 0 <= i < len(self._samples_out):
                self.set_samples(self._samples, out=self._samples_out[:i] + self._samples_out[i + 1:])
            return
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
