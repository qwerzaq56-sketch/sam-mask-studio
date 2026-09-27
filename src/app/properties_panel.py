"""Properties of the Object in Edit: Variants, prompt points, box, and the edit buttons."""

from __future__ import annotations

from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.project import FrameState, MaskObject

THUMB = 56


def mask_thumbnail(image: Optional[np.ndarray], mask: np.ndarray, color, size: int = THUMB) -> QIcon:
    """Small preview of *mask* tinted over *image*."""
    h, w = mask.shape
    s = size / max(h, w)
    tw, th = max(1, int(w * s)), max(1, int(h * s))
    base = cv2.resize(image, (tw, th), interpolation=cv2.INTER_AREA) if image is not None else np.zeros((th, tw, 3), np.uint8)
    m = cv2.resize(mask.astype(np.uint8), (tw, th), interpolation=cv2.INTER_NEAREST) > 0
    out = (base.astype(np.float32) * 0.45).astype(np.uint8)
    out[m] = (0.4 * base[m] + 0.6 * np.array(color)).astype(np.uint8)
    out = np.ascontiguousarray(out)
    qi = QImage(out.data, tw, th, 3 * tw, QImage.Format.Format_RGB888).copy()
    return QIcon(QPixmap.fromImage(qi))


class PropertiesPanel(QWidget):
    variant_selected = pyqtSignal(int)
    point_selected = pyqtSignal(int)
    delete_point_requested = pyqtSignal()
    clear_points_requested = pyqtSignal()
    clear_box_requested = pyqtSignal()
    finish_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._updating = False
        self.title = QLabel("No Object in Edit")
        self.title.setWordWrap(True)
        self.hint = QLabel(
            "Pick an Object's <b>Edit</b>, or <b>+ New Object from Points</b>.<br>"
            "Left click = positive, right click = negative, drag = box,<br>"
            "Shift+drag = brush, Ctrl+Shift+drag = erase."
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
        self.points.currentRowChanged.connect(self._on_point)
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

        self.finish_btn = QPushButton("Finish Editing")
        self.finish_btn.setToolTip("Esc")
        self.finish_btn.clicked.connect(self.finish_requested)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.title)
        lay.addWidget(self.hint)
        lay.addWidget(vbox, 2)
        lay.addWidget(pbox, 2)
        lay.addWidget(self.finish_btn)
        self.show_frame(None, None, None, None)

    def show_frame(
        self,
        obj: Optional[MaskObject],
        frame: Optional[FrameState],
        selected_point: Optional[int],
        image: Optional[np.ndarray],
        new_mode: bool = False,
    ) -> None:
        self._updating = True
        self.variants.clear()
        self.points.clear()
        if obj is None:
            self.title.setText("<b>New Object</b> — click or drag a box on the image" if new_mode else "No Object in Edit")
        else:
            self.title.setText(f"<b>{obj.name}</b> · {obj.source.value}")
        if frame is not None and obj is not None:
            for i, v in enumerate(frame.variants):
                it = QListWidgetItem(mask_thumbnail(image, v.mask, obj.color), f"#{i + 1}  score {v.score:.2f}  · {v.area:,} px")
                self.variants.addItem(it)
            if frame.variants:
                self.variants.setCurrentRow(min(frame.selected, len(frame.variants) - 1))
            for p in frame.points:
                self.points.addItem(f"{'+' if p.positive else '−'}  ({p.x:.0f}, {p.y:.0f})")
            if selected_point is not None and selected_point < self.points.count():
                self.points.setCurrentRow(selected_point)
            self.box_label.setText("Box: " + (", ".join(f"{v:.0f}" for v in frame.box) if frame.box else "—"))
        else:
            self.box_label.setText("Box: —")
        editing = obj is not None
        has_points = frame is not None and bool(frame.points)
        self.del_point_btn.setEnabled(editing and selected_point is not None)
        self.clear_btn.setEnabled(editing and frame is not None and frame.has_prompts)
        self.clear_box_btn.setEnabled(editing and frame is not None and frame.box is not None)
        self.points.setEnabled(has_points)
        self.finish_btn.setEnabled(editing or new_mode)
        self.finish_btn.setText("Cancel New Object" if new_mode else "Finish Editing")
        self._updating = False

    def _on_variant(self, row: int) -> None:
        if not self._updating and row >= 0:
            self.variant_selected.emit(row)

    def _on_point(self, row: int) -> None:
        if not self._updating and row >= 0:
            self.point_selected.emit(row)

