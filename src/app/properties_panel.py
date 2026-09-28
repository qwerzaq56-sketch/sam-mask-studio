"""Properties (spec 01 §5, §8, §9): the selected / edited Object, its Variants and Points.

Points are listed as Positive (●) and Negative (×) groups, numbered in the
order they were placed; selecting one highlights it on the canvas and Delete
removes exactly that point.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.app.objects_panel import later
from src.core.project import FrameState, MaskObject

THUMB = 56
# Direct brushes act as you paint; auto tools compute a result that is shown live
# and either filled in at once (Fill mode) or painted in (Brush mode).
DIRECT_TOOLS = ("paint", "restore")
AUTO_TOOLS = ("object_fill", "fill_holes", "remove_specks")
TOOL_TEXT = {
    "paint": ("Add / Subtract", "Drag = add, Alt+drag = subtract (B)"),
    "restore": ("Restore", "Drag over an area; on release the edit layer's changes there are undone"),
    "object_fill": ("Object Fill", "Grow the mask to the object's edges in the image"),
    "fill_holes": ("Fill Holes", "Fill holes enclosed by the mask"),
    "remove_specks": ("Remove Specks", "Remove separate small pieces (the main piece stays)"),
}
RESTORE_MODES = (
    ("added", "Add"),  # undo what the edit layer added
    ("removed", "Subtract"),  # undo what it subtracted
    ("both", "Both"),
)
POINT_ROLE = Qt.ItemDataRole.UserRole


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


class PropertiesPanel(QWidget):
    variant_selected = pyqtSignal(int)
    point_selected = pyqtSignal(int)
    delete_point_requested = pyqtSignal()
    clear_points_requested = pyqtSignal()
    clear_box_requested = pyqtSignal()
    finish_requested = pyqtSignal()
    brush_tool_selected = pyqtSignal(str)  # "" = no tool, else a DIRECT_TOOLS / AUTO_TOOLS name
    auto_mode_changed = pyqtSignal(str)  # "brush" | "fill"
    auto_settings_changed = pyqtSignal()  # an auto tool's parameter moved (settled for a moment)
    region_mode_toggled = pyqtSignal(bool)  # a drag on the image sets the tool region
    clear_region_requested = pyqtSignal()
    apply_layer_requested = pyqtSignal()
    delete_layer_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self._tool = ""
        self.title = QLabel("No Object selected")
        self.title.setWordWrap(True)
        self.hint = QLabel(
            "Pick an Object's <b>Edit</b>, or <b>+ New Object from Points</b>.<br>"
            "Left click = positive, right click = negative, drag = box.<br>"
            "Hand edits go to the <b>Edit layer</b> below (Brush: B)."
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray;")

        self.variants = QListWidget()
        self.variants.setIconSize(QSize(THUMB, THUMB))
        self.variants.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.variants.currentRowChanged.connect(self._on_variant)
        vbox = QGroupBox("Variants (pick one)")
        QVBoxLayout(vbox).addWidget(self.variants)

        self.points = QListWidget()
        self.points.currentItemChanged.connect(self._on_point)
        self.box_label = QLabel("Box: —")
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
        pl.addWidget(self.box_label)
        pl.addLayout(row)

        # --- edit layer (hand edits on top of the prompt-based mask)
        self.tool_btns = {}

        def tool_button(name: str) -> QPushButton:
            text, tip = TOOL_TEXT[name]
            b = QPushButton(text)
            b.setCheckable(True)
            b.setToolTip(tip + " — Ctrl+wheel = brush size, wheel = zoom")
            b.clicked.connect(lambda on, t=name: self.brush_tool_selected.emit(t if on else ""))
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

        # Auto tools: a live result, filled in at once or painted in.
        self.mode_brush_btn = QPushButton("Brush")
        self.mode_fill_btn = QPushButton("Fill")
        for b, value, tip in (
            (self.mode_brush_btn, "brush", "The result is shown in gray; paint where you want it"),
            (self.mode_fill_btn, "fill", "The result is previewed in green/red (inside the region, if any)\n"
                                         "and written in when you leave the tool; Esc drops it"),
        ):
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _on, v=value: self._set_mode(v, emit=True))
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
        abox = QGroupBox("Auto tools")
        ag = QGridLayout(abox)
        ag.addWidget(tool_button("object_fill"), 0, 0, 1, 3)
        ag.addWidget(tool_button("fill_holes"), 1, 0, 1, 2)
        ag.addWidget(tool_button("remove_specks"), 1, 2)
        ag.addWidget(QLabel("Mode"), 2, 0)
        ag.addWidget(self.mode_brush_btn, 2, 1)
        ag.addWidget(self.mode_fill_btn, 2, 2)
        ag.addWidget(QLabel("Region"), 3, 0)
        ag.addWidget(self.region_btn, 3, 1)
        ag.addWidget(self.clear_region_btn, 3, 2)
        ag.addWidget(self.scope_label, 4, 0, 1, 3)
        self.mode = "brush"
        self._set_mode("brush")

        # Settings of the selected auto tool; any change is reported once it settles.
        self._settings_timer = QTimer(self)
        self._settings_timer.setSingleShot(True)
        self._settings_timer.setInterval(120)
        self._settings_timer.timeout.connect(self.auto_settings_changed)
        self.refine_area = QSpinBox()
        self.refine_area.setRange(1, 1_000_000)
        self.refine_area.setValue(200)
        self.refine_area.setSuffix(" px")
        self.grow = QSpinBox()
        self.grow.setRange(1, 500)
        self.grow.setValue(20)
        self.grow.setSuffix(" px")
        self.sensitivity = QSlider(Qt.Orientation.Horizontal)
        self.sensitivity.setRange(0, 100)
        self.sensitivity.setValue(50)
        self.sensitivity_value = QLabel("50")
        self.sensitivity.valueChanged.connect(lambda v: self.sensitivity_value.setText(str(v)))
        for w in (self.refine_area, self.grow, self.sensitivity):
            w.valueChanged.connect(lambda _v: self._settings_timer.start())
        size_page = QWidget()
        sf = QFormLayout(size_page)
        sf.setContentsMargins(0, 0, 0, 0)
        sf.addRow("Max size", self.refine_area)
        sf.addRow(note("Only holes / specks up to this many pixels."))
        fill_page = QWidget()
        ff = QFormLayout(fill_page)
        ff.setContentsMargins(0, 0, 0, 0)
        ff.addRow("Max grow", self.grow)
        sens = QHBoxLayout()
        sens.addWidget(self.sensitivity, 1)
        sens.addWidget(self.sensitivity_value)
        ff.addRow("Sensitivity", sens)
        ff.addRow(note("Max grow: how far the mask may spread. Sensitivity: higher spreads further "
                       "into colors like the object's, lower stops sooner."))
        self.settings_stack = QStackedWidget()
        self._pages = {"object_fill": self.settings_stack.addWidget(fill_page)}
        size_index = self.settings_stack.addWidget(size_page)
        self._pages.update(fill_holes=size_index, remove_specks=size_index)
        self.preview_label = note("")
        self.settings_box = QGroupBox("Settings")
        sl = QVBoxLayout(self.settings_box)
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
        lbox = QGroupBox("Layer")
        ll = QGridLayout(lbox)
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
        ml.addWidget(pbox, 1)
        layer_page = QWidget()
        el = QVBoxLayout(layer_page)
        el.setContentsMargins(0, 0, 0, 0)
        for box in (tbox, abox, self.settings_box, lbox):
            el.addWidget(box)
        el.addStretch(1)
        self.tabs = QTabWidget()
        self.mask_tab = self.tabs.addTab(_scrolled(mask_page), "Mask")
        self.layer_tab = self.tabs.addTab(_scrolled(layer_page), "Edit Layer")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.title)
        lay.addWidget(self.hint)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.finish_btn)
        self.show_frame(None, None, None, None)

    def selected_point(self) -> Optional[int]:
        it = self.points.currentItem()
        return it.data(POINT_ROLE) if it is not None else None

    def show_frame(
        self,
        obj: Optional[MaskObject],
        frame: Optional[FrameState],
        selected_point: Optional[int],
        image: Optional[np.ndarray],
        new_mode: bool = False,
        editing: bool = False,
    ) -> None:
        """Show *obj*'s frame on the current image; point/box controls only work while *editing*."""
        self._updating = True
        self.variants.clear()
        self.points.clear()
        self.hint.setVisible(obj is None)  # the how-to only while nothing is shown
        if obj is None:
            self.title.setText(
                "<b>New Object</b> — click or drag a box on the image" if new_mode else "No Object selected"
            )
        else:
            state = "Editing" if editing else "Selected"
            self.title.setText(f"{state}: <b>{obj.name}</b> · {obj.source.value}")
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
            for positive, header in ((True, "Positive Points"), (False, "Negative Points")):
                group = [(i, p) for i, p in enumerate(frame.points) if p.positive == positive]
                if not group:
                    continue
                h = QListWidgetItem(header)
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                self.points.addItem(h)
                for i, p in group:
                    it = QListWidgetItem(f"  {'●' if positive else '×'} Point {i + 1}   ({p.x:.0f}, {p.y:.0f})")
                    it.setData(POINT_ROLE, i)
                    if not editing:
                        it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    self.points.addItem(it)
                    if i == selected_point:
                        self.points.setCurrentItem(it)
            self.box_label.setText("Box: " + (", ".join(f"{v:.0f}" for v in frame.box) if frame.box else "—"))
        else:
            self.box_label.setText("Box: —")
        editing = editing and obj is not None
        has_points = frame is not None and bool(frame.points)
        self.del_point_btn.setEnabled(editing and selected_point is not None)
        self.clear_btn.setEnabled(editing and frame is not None and frame.has_prompts)
        self.clear_box_btn.setEnabled(editing and frame is not None and frame.box is not None)
        self.points.setEnabled(has_points)
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
        for w in (self.mode_brush_btn, self.mode_fill_btn, self.region_btn):
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
        self.settings_box.setVisible(auto)
        if auto:
            self.settings_stack.setCurrentIndex(self._pages[tool])
            self.settings_box.setTitle(f"{TOOL_TEXT[tool][0]} settings")
        else:
            self.preview_label.setText("")

    def set_brush(self, on: bool) -> None:
        self.set_brush_tool("paint" if on else "")

    def _set_mode(self, mode: str, emit: bool = False) -> None:
        self.mode = mode
        self.mode_brush_btn.setChecked(mode == "brush")
        self.mode_fill_btn.setChecked(mode == "fill")
        if emit:
            self.auto_mode_changed.emit(mode)

    def set_region_mode(self, on: bool) -> None:
        """Reflect the region-box mode without re-emitting."""
        self.region_btn.blockSignals(True)
        self.region_btn.setChecked(on)
        self.region_btn.blockSignals(False)

    def tool_settings(self) -> dict:
        return {
            "max_area": int(self.refine_area.value()),
            "max_grow": int(self.grow.value()),
            "sensitivity": int(self.sensitivity.value()),
            "restore": self.restore_mode.currentData(),
        }

    def set_preview(self, added: int, removed: int, busy: bool = False) -> None:
        """What the auto tool changes (Fill) or would change where painted (Brush)."""
        if busy:
            self.preview_label.setText("Computing…")
            return
        verb = "Will apply" if self.mode == "fill" else "Available"
        self.preview_label.setText(f"{verb}: +{added:,} px / −{removed:,} px")

    def set_region(self, region: Optional[np.ndarray]) -> None:
        has = region is not None
        self.clear_region_btn.setEnabled(has)
        self.scope_label.setText(
            f"Auto tools act inside the region ({int(region.sum()):,} px)" if has
            else "Auto tools act on the whole mask"
        )

    def set_brush_size(self, px: int) -> None:
        self.brush_size.setText(f"size {px}px · Ctrl+wheel to change")

    def _on_region_mode(self, on: bool) -> None:
        if on:
            self.tabs.setCurrentIndex(self.layer_tab)
        self.region_mode_toggled.emit(on)

    def _on_variant(self, row: int) -> None:
        if not self._updating and row >= 0:
            later(self.variant_selected, row)

    def _on_point(self, item, _previous=None) -> None:
        if not self._updating and item is not None and item.data(POINT_ROLE) is not None:
            later(self.point_selected, item.data(POINT_ROLE))
