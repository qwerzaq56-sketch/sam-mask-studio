"""Settings and Export dialogs."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.app.settings import Settings
from src.core.storage import ExportOptions


def _path_row(edit: QLineEdit, pick) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit, 1)
    b = QPushButton("…")
    b.setFixedWidth(30)
    b.clicked.connect(pick)
    lay.addWidget(b)
    return w


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.sam2 = QLineEdit(settings.sam2_checkpoint)
        self.sam3 = QLineEdit(settings.sam3_checkpoint)
        self.max_side = QSpinBox()
        self.max_side.setRange(0, 8192)
        self.max_side.setSingleStep(128)
        self.max_side.setSpecialValueText("original size")
        self.max_side.setValue(settings.max_side)
        form = QFormLayout(self)
        form.addRow("SAM2 checkpoint", _path_row(self.sam2, lambda: self._pick(self.sam2)))
        form.addRow("SAM3 checkpoint", _path_row(self.sam3, lambda: self._pick(self.sam3)))
        form.addRow("Working max side (px)", self.max_side)
        note = QLabel(
            "Masks are edited at the working resolution and upsampled on export.\nApplies to folders without a saved project."
        )
        note.setStyleSheet("color: gray;")
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _pick(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Checkpoint", edit.text(), "Checkpoints (*.pt *.pth);;All files (*)"
        )
        if path:
            edit.setText(path)

    def apply(self, settings: Settings) -> None:
        settings.sam2_checkpoint = self.sam2.text().strip()
        settings.sam3_checkpoint = self.sam3.text().strip()
        settings.max_side = self.max_side.value()


class ExportDialog(QDialog):
    """Final Mask PNG export options."""

    PATTERNS = (
        ("{stem}.png  (frame_001.png)", "{stem}.png"),
        ("{name}.png  (COLMAP: frame_001.jpg.png)", "{name}.png"),
    )

    def __init__(self, default_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Final Masks")
        self.out = QLineEdit(str(default_dir))
        self.pattern = QComboBox()
        for label, _ in self.PATTERNS:
            self.pattern.addItem(label)
        self.invert = QCheckBox("Invert (object black, background white)")
        self.empty = QCheckBox("Also write empty masks for images without Objects")
        form = QFormLayout(self)
        form.addRow("Folder", _path_row(self.out, self._pick))
        form.addRow("File names", self.pattern)
        form.addRow(self.invert)
        form.addRow(self.empty)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Export folder", self.out.text())
        if d:
            self.out.setText(d)

    def options(self) -> ExportOptions:
        return ExportOptions(
            out_dir=Path(self.out.text().strip()),
            name_pattern=self.PATTERNS[self.pattern.currentIndex()][1],
            invert=self.invert.isChecked(),
            include_empty=self.empty.isChecked(),
        )


# Every keyboard / mouse shortcut, by area (kept here so the Help window and the code agree).
SHORTCUTS = (
    ("File", (
        ("Ctrl+O", "Open an image folder"),
        ("Ctrl+S", "Save (also autosaved)"),
        ("Ctrl+E", "Export Final Masks"),
    )),
    ("Edit", (
        ("Ctrl+Z", "Undo"),
        ("Ctrl+Y / Ctrl+Shift+Z", "Redo"),
        ("N", "New Object from points"),
        ("E", "Edit the selected Object / finish editing"),
        ("Delete", "Delete the selected point, else the selected Objects"),
        ("Esc", "Leave the tool (drops an auto tool's result), then finish editing"),
        ("Enter", "Auto tool: Apply & Recompute (Fill: all, Paint: the picks)"),
        ("The active auto tool again", "Leave it, dropping its result (like Esc)"),
    )),
    ("Images", (
        ("Right / PgDown", "Next image (not while editing)"),
        ("Left / PgUp", "Previous image (not while editing)"),
        ("Up / Down", "Previous / next Object with a mask on this image (Edit follows)"),
        ("Double-click an image", "Make it the propagation reference (◎); again: back to the current image"),
        ("Shift / Ctrl-click images", "Pick the images for the Selection propagation scope (📌 Pin keeps them)"),
    )),
    ("View", (
        ("Z (hold)", "Show the Final Mask while held"),
        ("X", "Final Mask preview on / off"),
        ("O", "Outline on / off"),
        ("Wheel", "Zoom at the cursor"),
        ("Middle-drag / Space+drag", "Pan"),
        ("F1", "This list"),
    )),
    ("Detections: Select on Image on", (
        ("Click / drag", "Add the candidate under the cursor / every one the box touches"),
        ("Shift+click / Shift+drag", "Toggle them"),
        ("Ctrl+click / Ctrl+drag", "Remove them"),
    )),
    ("On the image (Edit)", (
        ("Left click / Right click", "Positive / negative point"),
        ("Drag", "Box prompt (Region Box on: add a box to the region)"),
        ("D", "Paint brush on / off"),
        ("Drag with a brush", "Paint: add · Restore: undo edits · auto tool Paint mode: pick"),
        ("A", "Auto tool: Fill mode -> Paint mode with everything picked; Paint mode: pick all / none"),
        ("Drag a point / double-click it", "Move the point / delete it"),
        ("Alt+drag", "Paint: subtract · auto tool Paint mode: unpick · Region Box: remove a box"),
        ("Shift+drag", "Paint without turning the brush on"),
        ("Ctrl+wheel / Shift+wheel", "Brush size"),
    )),
)


class ShortcutsDialog(QDialog):
    """Help > Keyboard Shortcuts (F1)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.resize(560, 620)
        rows = []
        for group, items in SHORTCUTS:
            rows.append(f"<tr><td colspan=2><h3 style='margin-top:10px'>{group}</h3></td></tr>")
            rows += [f"<tr><td style='padding-right:16px'><b>{k}</b></td><td>{v}</td></tr>" for k, v in items]
        view = QTextBrowser()
        view.setHtml("<table cellspacing=3>" + "".join(rows) + "</table>")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(view)
        lay.addWidget(buttons)
