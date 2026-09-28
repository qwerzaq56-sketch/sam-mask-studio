"""Properties (spec 01 §5, §8, §9): the selected / edited Object, its Variants and Points.

Points are listed as Positive (●) and Negative (×) groups, numbered in the
order they were placed; selecting one highlights it on the canvas and Delete
removes exactly that point.
"""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QSize, Qt, pyqtSignal
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
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.app.objects_panel import later
from src.core.project import FrameState, MaskObject

THUMB = 56
BRUSH_TOOLS = (
    ("paint", "Paint", "Drag = add, Alt+drag = subtract (B)"),
    ("restore", "Restore", "Drag over an area; on release the edit layer's changes there are undone (see below)"),
    ("fill_holes", "Fill Holes", "Drag over an area; on release its holes are filled (up to the area below)"),
    ("remove_specks", "Remove Specks", "Drag over an area; on release its specks are removed"),
    ("object_fill", "Object Fill", "Drag over an area; on release the mask grows to the object's edges there"),
)
TOOL_CELLS = {  # grid row, column; the Restore options sit beside Restore
    "paint": (0, 0),
    "object_fill": (0, 1),
    "fill_holes": (1, 0),
    "remove_specks": (1, 1),
    "restore": (2, 0),
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
    brush_tool_selected = pyqtSignal(str)  # "" = brush off, else a BRUSH_TOOLS name
    fill_holes_requested = pyqtSignal(int)  # max hole area in working-resolution px
    remove_specks_requested = pyqtSignal(int)  # max speck area
    object_fill_requested = pyqtSignal(int, int)  # max growth in px, sensitivity 0-100
    region_mode_toggled = pyqtSignal(bool)  # a drag on the image sets the tool region
    clear_region_requested = pyqtSignal()
    apply_layer_requested = pyqtSignal()
    delete_layer_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
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
        # Brush tools: Paint edits directly; the others mark an area and run on release.
        self.tool_btns = {}
        tools = QGridLayout()
        for n, (name, text, tip) in enumerate(BRUSH_TOOLS):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setToolTip(tip + " — Ctrl+wheel = size, wheel = zoom")
            b.clicked.connect(lambda on, t=name: self.brush_tool_selected.emit(t if on else ""))
            tools.addWidget(b, *TOOL_CELLS[name])
            self.tool_btns[name] = b
        self.restore_mode = QComboBox()
        for value, text in RESTORE_MODES:
            self.restore_mode.addItem(text, value)
        self.restore_mode.setCurrentIndex(self.restore_mode.findData("both"))
        self.restore_mode.setToolTip(
            "What the Restore brush undoes: Add = what was painted on, Subtract = what was erased, Both"
        )
        tools.addWidget(self.restore_mode, 2, 1)
        self.brush_btn = self.tool_btns["paint"]
        self.brush_size = QLabel("")
        self.brush_size.setStyleSheet("color: gray;")
        tbox = QGroupBox("Brush tools")
        tl = QVBoxLayout(tbox)
        tl.addLayout(tools)
        tl.addWidget(self.brush_size)

        # Settings shared by the brushes and the whole-mask buttons.
        self.refine_area = QSpinBox()
        self.refine_area.setRange(1, 1_000_000)
        self.refine_area.setValue(200)
        self.refine_area.setSuffix(" px")
        self.refine_area.setToolTip("Holes / separate specks up to this area are filled / removed")
        self.grow = QSpinBox()
        self.grow.setRange(1, 500)
        self.grow.setValue(20)
        self.grow.setSuffix(" px")
        self.grow.setToolTip("How far Object Fill may grow the mask")
        self.sensitivity = QSpinBox()
        self.sensitivity.setRange(0, 100)
        self.sensitivity.setValue(50)
        self.sensitivity.setToolTip(
            "Object Fill sensitivity: higher grows further into colors like the object's,\n"
            "lower stops sooner (50 = grow where the color is more object than background)"
        )
        # One settings box per tool, so it is clear which value drives what.
        def note(text: str) -> QLabel:
            lb = QLabel(text)
            lb.setStyleSheet("color: gray;")
            lb.setWordWrap(True)
            return lb

        hbox = QGroupBox("Fill Holes / Remove Specks")
        hf = QFormLayout(hbox)
        hf.addRow("Max size", self.refine_area)
        hf.addRow(note("Only holes / specks up to this many pixels are filled / removed."))
        obox = QGroupBox("Object Fill")
        of = QFormLayout(obox)
        of.addRow("Max grow", self.grow)
        of.addRow("Sensitivity", self.sensitivity)
        of.addRow(note("Max grow: how far the mask may spread. Sensitivity: higher spreads further "
                       "into colors like the object's, lower stops sooner."))

        # The same tools at once on the whole mask, or inside the region.
        self.fill_btn = QPushButton("Fill Holes")
        self.fill_btn.setToolTip("Fill holes enclosed by the mask, up to the hole area")
        self.fill_btn.clicked.connect(lambda: self.fill_holes_requested.emit(int(self.refine_area.value())))
        self.specks_btn = QPushButton("Remove Specks")
        self.specks_btn.setToolTip("Remove separate small pieces, up to the area (the main piece stays)")
        self.specks_btn.clicked.connect(lambda: self.remove_specks_requested.emit(int(self.refine_area.value())))
        self.object_fill_btn = QPushButton("Object Fill")
        self.object_fill_btn.setToolTip("Grow the mask outward to the object's edges in the image (never shrinks it)")
        self.object_fill_btn.clicked.connect(
            lambda: self.object_fill_requested.emit(int(self.grow.value()), int(self.sensitivity.value()))
        )
        self.region_btn = QPushButton("Region Box")
        self.region_btn.setCheckable(True)
        self.region_btn.setToolTip(
            "Drag boxes on the image to set the region (cyan) the buttons above act in;\n"
            "Alt+drag removes a box from it. Without a region they act on the whole mask."
        )
        self.region_btn.toggled.connect(self._on_region_mode)
        self.clear_region_btn = QPushButton("Clear Region")
        self.clear_region_btn.clicked.connect(self.clear_region_requested)
        self.scope_label = QLabel("")
        self.scope_label.setStyleSheet("color: gray;")
        abox = QGroupBox("Apply at once")
        ag = QGridLayout(abox)
        ag.addWidget(self.object_fill_btn, 0, 0, 1, 2)
        ag.addWidget(self.fill_btn, 1, 0)
        ag.addWidget(self.specks_btn, 1, 1)
        ag.addWidget(self.region_btn, 2, 0)
        ag.addWidget(self.clear_region_btn, 2, 1)
        ag.addWidget(self.scope_label, 3, 0, 1, 2)

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
        for box in (tbox, hbox, obox, abox, lbox):
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
                b.setEnabled(editing and frame is not None and frame.edit is not None)
            elif name != "paint":
                b.setEnabled(has_mask)
        if not editing:
            self.set_brush_tool("")  # the window turns the canvas brush off itself
            self.set_region_mode(False)
        for b in (self.fill_btn, self.specks_btn, self.object_fill_btn):
            b.setEnabled(has_mask)
        for w in (self.refine_area, self.grow, self.sensitivity, self.region_btn):
            w.setEnabled(editing)
        self.apply_layer_btn.setEnabled(editing and layer is not None)
        self.delete_layer_btn.setEnabled(editing and layer is not None)
        self.finish_btn.setEnabled(editing or new_mode)
        self.finish_btn.setText("Cancel New Object" if new_mode else "Finish Editing")
        self._updating = False

    def set_brush_tool(self, tool: str) -> None:
        """Reflect the brush tool ("" = off) without re-emitting; a tool turning on shows this tab."""
        if tool and not any(b.isChecked() for b in self.tool_btns.values()):
            self.tabs.setCurrentIndex(self.layer_tab)
        for name, b in self.tool_btns.items():
            b.blockSignals(True)
            b.setChecked(name == tool)
            b.blockSignals(False)

    def set_brush(self, on: bool) -> None:
        self.set_brush_tool("paint" if on else "")

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

    def set_region(self, region: Optional[np.ndarray]) -> None:
        has = region is not None
        self.clear_region_btn.setEnabled(has)
        self.scope_label.setText(
            f"Buttons act inside the region ({int(region.sum()):,} px)" if has else "Buttons act on the whole mask"
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
