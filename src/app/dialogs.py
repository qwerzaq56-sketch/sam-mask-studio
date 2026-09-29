"""Settings and Export dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QRadioButton,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.app.settings import Settings
from src.core.storage import ExportCheck, ExportOptions


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
        self.setMinimumWidth(640)  # room for the checkpoint paths
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


class OptionsDialog(QDialog):
    """A question with one or more groups of radio choices (Merge, Copy into).

    *groups*: ``(label, choices, default index)``; ``choice()`` is the picked
    index of each group.
    """

    def __init__(self, title: str, text: str, groups: Sequence[Tuple[str, Sequence[str], int]],
                 ok: str = "OK", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        intro = QLabel(text)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self._groups: List[QButtonGroup] = []
        for label, choices, default in groups:
            box = QGroupBox(label)
            bl = QVBoxLayout(box)
            group = QButtonGroup(box)
            for i, choice in enumerate(choices):
                rb = QRadioButton(choice)
                rb.setChecked(i == default)
                group.addButton(rb, i)
                bl.addWidget(rb)
            self._groups.append(group)
            lay.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def choice(self) -> List[int]:
        return [g.checkedId() for g in self._groups]


class ExportDialog(QDialog):
    """Final Mask PNG export options."""

    PATTERNS = (
        ("{stem}.png  (frame_001.png)", "{stem}.png"),
        ("{name}.png  (COLMAP: frame_001.jpg.png)", "{name}.png"),
    )

    def __init__(self, default_dir: Path, parent=None, check: Optional[Callable[[str], ExportCheck]] = None):
        super().__init__(parent)
        self.setWindowTitle("Export Final Masks")
        self.goto: Optional[str] = None  # an image picked in the check list: leave and open it
        self.setMinimumWidth(480)
        self._check = check
        self.out = QLineEdit(str(default_dir))
        self.pattern = QComboBox()
        for label, _ in self.PATTERNS:
            self.pattern.addItem(label)
        self.invert = QCheckBox("Invert (object black, background white)")
        self.empty = QCheckBox("Also write empty masks for images without Objects")
        form = QFormLayout(self)
        # the check: what gets written, and the images worth a look before exporting
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setWordWrap(True)
        self.problems = QListWidget()
        self.problems.setMaximumHeight(130)
        self.problems.setToolTip("Double-click: close this and open the image")
        self.problems.itemDoubleClicked.connect(self._open_problem)
        if check is not None:
            form.addRow(self.summary)
            form.addRow(self.problems)
        form.addRow("Folder", _path_row(self.out, self._pick))
        form.addRow("File names", self.pattern)
        form.addRow(self.invert)
        form.addRow(self.empty)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.pattern.currentIndexChanged.connect(self._run_check)
        self.empty.toggled.connect(self._run_check)
        self._run_check()

    def _run_check(self) -> None:
        if self._check is None:
            return
        c = self._check(self.PATTERNS[self.pattern.currentIndex()][1])
        self.check_result = c

        def line(ok: bool, text: str) -> str:
            color = "#2a8a2a" if ok else "#d78200"
            return f"<span style='color: {color}'>{'✓' if ok else '⚠'}</span> {text}"

        missing = len(c.without_mask)
        written = len(c.with_mask) + len(c.empty) + (missing if self.empty.isChecked() else 0)
        rows = [
            f"<b>{written}</b> file(s) will be written for <b>{c.images}</b> image(s)",
            line(missing == 0, f"Images without a mask: {missing}"
                 + ("" if missing == 0 or self.empty.isChecked() else " (no file — see “Also write empty masks”)")),
            line(not c.empty, f"Empty masks: {len(c.empty)}"),
            line(not c.warning, f"Suspicious / failed frames (⚠ ✕): {len(c.warning)}"),
            line(not c.clashes, "File names: " + ("OK" if not c.clashes else f"{len(c.clashes)} clash(es)")),
        ]
        self.summary.setText("<br>".join(rows))
        self.problems.clear()
        reasons = (
            (set(c.without_mask), "no mask"),
            (set(c.empty), "empty"),
            (set(c.warning), "⚠ / ✕"),
            ({k for ks in c.clashes for k in ks}, "name clash"),
        )
        index = {k: i for i, k in enumerate(c.keys)}
        for k in c.problems:
            why = ", ".join(r for ks, r in reasons if k in ks)
            self.problems.addItem(f"{index[k] + 1}  {k}  —  {why}")
            self.problems.item(self.problems.count() - 1).setData(Qt.ItemDataRole.UserRole, k)
        self.problems.setVisible(self.problems.count() > 0)

    def _open_problem(self, item) -> None:
        self.goto = item.data(Qt.ItemDataRole.UserRole)
        self.reject()

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
        ("", "Every command is also in the menu bar (File, Edit, View, Go, Help) with its key"),
    )),
    ("Edit", (
        ("Ctrl+Z", "Undo"),
        ("Ctrl+Y / Ctrl+Shift+Z", "Redo"),
        ("N", "New Object from points"),
        ("E", "Points: edit the selected Object with SAM2 points / finish editing"),
        ("Delete", "Delete the selected point, else the selected Objects"),
        ("Esc", "Leave the tool (drops an auto tool's result), then finish editing"),
        ("Enter", "Auto tool: Apply & Continue (Fill: all, Paint: the picks)"),
        ("The active auto tool again", "Leave it, dropping its result (like Esc)"),
        ("Objects buttons / Edit > Objects", "Duplicate: this image's mask · Duplicate All: every linked mask · "
                                             "Copy A → B: Replace / Add · Merge: Add / Override with A / B"),
    )),
    ("Images", (
        ("Right / PgDown", "Next image (not while editing)"),
        ("Left / PgUp", "Previous image (not while editing)"),
        ("Up / Down", "Previous / next Object with a mask on this image (Edit follows)"),
        ("W A S D / arrows, mouse over the Frame List or Frames strip",
         "W A ↑ ← previous frame · S D ↓ → next frame (S here is not Scroll)"),
        ("W A S D / arrows, mouse over the Objects list", "Previous / next Object row (Show all rows too)"),
        ("S", "Scroll the frame list and strip to the current frame (also ⌖; Go to ID: type + Enter)"),
        ("[ / ]", "Previous / next ⚠ or ✕ image (with the Frame List's 1 on: also – = no mask of the Object)"),
        (", / .", "Nearest earlier / later keyframe ★ (edited there, a propagation source; the 1 on: its Object's only)"),
        ("F", "Go to the propagation reference ◎ (the double-clicked image)"),
        ("Enter", "Make the current image the propagation reference ◎ (again: back to none); an auto tool's Enter comes first"),
        ("Double-click an image", "Make it the propagation reference (◎); again: back to the current image"),
        ("Shift / Ctrl-click images", "Pick the images for the Selection propagation scope (📌 Pin keeps them)"),
    )),
    ("View", (
        ("Z (hold)", "Mask Preview while held"),
        ("X", "Mask Preview (black and white) on / off"),
        ("V", "Mask Preview shows: the Final Mask <-> the selected Object's mask"),
        ("O", "Outline on / off"),
        ("R", "Show Changes (the edit layer's green / red tints) on / off"),
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
