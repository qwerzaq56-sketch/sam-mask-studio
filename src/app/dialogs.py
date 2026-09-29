"""Settings and Export dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QInputDialog,
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
from src.core.colmap_model import dataset_blocker
from src.core.presets import CUSTOM, PRESETS, preset
from src.core.reproject import Views
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
    """Final Mask PNG export options.

    For a COLMAP scene a trainer preset (docs/specs/07-export-presets.md) fixes the
    folder (the scene's masks/), the names and the colors; "Custom" leaves them free.
    Mask: the Final Mask (the checked Objects) goes to the folder, a named mask set
    to ``<folder>_<name>`` (masks_people/); "Every set" writes all of them.
    """

    EVERY = "*"  # the Mask choice that writes the Final Mask and every set

    PATTERNS = (
        ("{stem}.png  (frame_001.png)", "{stem}.png"),
        ("{name}.png  (COLMAP: frame_001.jpg.png)", "{name}.png"),
    )

    def __init__(self, default_dir: Path, parent=None, check: Optional[Callable[..., ExportCheck]] = None,
                 scene=None, target: str = CUSTOM, sets: Optional[dict] = None,
                 save_set: Optional[Callable[[str], bool]] = None, delete_set: Optional[Callable[[str], None]] = None,
                 excluded: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Export Final Masks")
        self.goto: Optional[str] = None  # an image picked in the check list: leave and open it
        self.setMinimumWidth(480)
        self._check = check
        self._scene = scene
        self._custom_dir = str(default_dir)
        self.target = QComboBox()
        for p in PRESETS if scene is not None else ():
            self.target.addItem(p.label, p.key)
        self.target.addItem("Custom (choose below)", CUSTOM)
        i = self.target.findData(target)
        self.target.setCurrentIndex(i if i >= 0 else 0)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray;")
        self._sets = sets if sets is not None else {}
        self._save_set, self._delete_set = save_set, delete_set
        self.mask = QComboBox()
        self.save_set_btn = QPushButton("Save Checked as Set…")
        self.save_set_btn.setToolTip("The Objects checked now, under a name: exported to <folder>_<name>")
        self.save_set_btn.clicked.connect(self._new_set)
        self.delete_set_btn = QPushButton("Delete Set")
        self.delete_set_btn.clicked.connect(self._remove_set)
        self.folders = QLabel()
        self.folders.setWordWrap(True)
        self.folders.setStyleSheet("color: gray;")
        self._fill_sets()
        # where a preset writes: into the scene, or a new dataset (images linked, model filtered)
        self._excluded = excluded
        self.to_scene = QRadioButton("Into the scene")
        self.to_new = QRadioButton("New dataset:")
        self.to_scene.setChecked(True)
        self.dataset = QLineEdit(str(scene.root.parent / f"{scene.root.name}_dataset") if scene is not None else "")
        self.dataset.setToolTip("A new folder: images/ (hard links, no extra space on the same drive), "
                                "sparse/0/ without the ⊘ frames, and the masks")
        self._out_row = QWidget()
        orow = QHBoxLayout(self._out_row)
        orow.setContentsMargins(0, 0, 0, 0)
        orow.addWidget(self.to_scene)
        orow.addWidget(self.to_new)
        orow.addWidget(_path_row(self.dataset, self._pick_dataset), 1)
        # a 360 (EQUIRECTANGULAR) scene: the new dataset may be pinhole views instead (docs/specs/08)
        self._erp = scene is not None and "EQUIRECTANGULAR" in scene.camera_models
        self.pinhole = QCheckBox("Convert to pinhole views:")
        self.pinhole.setToolTip("Each 360 image becomes perspective views (images, masks and the model); "
                                "unchecked, the dataset stays 360 (EQUIRECTANGULAR)")
        self.yaws = QSpinBox()
        self.yaws.setRange(1, 24)
        self.yaws.setValue(4)
        self.yaws.setSuffix(" around")
        self.pitches = QLineEdit("-35, 0, 35")
        self.pitches.setToolTip("Up / down angles in degrees (up is positive), one row of views each")
        self.fov = QSpinBox()
        self.fov.setRange(30, 150)
        self.fov.setValue(90)
        self.fov.setSuffix("° FOV")
        self.side = QSpinBox()
        self.side.setRange(0, 8192)
        self.side.setSingleStep(64)
        self.side.setSpecialValueText("auto px")
        self.side.setSuffix(" px")
        self.side.setToolTip("Square view size; auto = the 360 width / 4")
        self._pin_row = QWidget()
        prow = QHBoxLayout(self._pin_row)
        prow.setContentsMargins(0, 0, 0, 0)
        for w in (self.pinhole, self.yaws, QLabel("× pitch"), self.pitches, self.fov, self.side):
            prow.addWidget(w)
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
        if scene is not None:
            form.addRow("For", self.target)
            form.addRow(self.note)
            form.addRow("Output", self._out_row)
            form.addRow("", self._pin_row)
        if check is not None:
            form.addRow(self.summary)
            form.addRow(self.problems)
        if save_set is not None:
            row = QHBoxLayout()
            row.addWidget(self.mask, 1)
            row.addWidget(self.save_set_btn)
            row.addWidget(self.delete_set_btn)
            form.addRow("Mask", row)
        form.addRow("Folder", _path_row(self.out, self._pick))
        form.addRow(self.folders)
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
        self.target.currentIndexChanged.connect(self._apply_target)
        self.to_new.toggled.connect(lambda _on: self._apply_target())
        for w in (self.pinhole,):
            w.toggled.connect(lambda _on: self._apply_target())
        for w in (self.yaws, self.fov, self.side):
            w.valueChanged.connect(lambda _v: self._run_check())
        self.pitches.textChanged.connect(lambda _t: self._run_check())
        self.dataset.textChanged.connect(lambda _t: self._apply_target())
        self.mask.currentIndexChanged.connect(self._run_check)
        self.out.textChanged.connect(lambda _t: self._show_folders())
        self._apply_target()

    # --- mask sets -------------------------------------------------------------------------

    def _fill_sets(self, select: Optional[str] = None) -> None:
        self.mask.blockSignals(True)
        self.mask.clear()
        self.mask.addItem("Final Mask (the checked Objects)", None)
        for name, ids in sorted(self._sets.items()):
            self.mask.addItem(f"{name} ({len(ids)} Object{'s' if len(ids) != 1 else ''})", name)
        if self._sets:
            self.mask.addItem("Every set, one folder each (and the Final Mask)", self.EVERY)
        i = self.mask.findData(select) if select is not None else 0
        self.mask.setCurrentIndex(max(0, i))
        self.mask.blockSignals(False)

    def _new_set(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Mask Set", "Name (the folder becomes <folder>_<name>):")
        name = name.strip()
        if ok and name and name != self.EVERY and self._save_set is not None and self._save_set(name):
            self._fill_sets(select=name)
            self._run_check()

    def _remove_set(self) -> None:
        name = self.mask.currentData()
        if name not in (None, self.EVERY) and self._delete_set is not None:
            self._delete_set(name)
            self._fill_sets()
            self._run_check()

    def _chosen(self) -> List[Optional[str]]:
        """The masks to write: None = the Final Mask, else set names."""
        v = self.mask.currentData()
        return [None] + sorted(self._sets) if v == self.EVERY else [v]

    def dataset_root(self) -> Optional[Path]:
        """The new dataset's folder, or None when writing into the scene (or not a preset)."""
        if self.preset() is None or self._scene is None or not self.to_new.isChecked():
            return None
        text = self.dataset.text().strip()
        return Path(text) if text else None

    def views(self):
        """The pinhole views to make (New dataset of a 360 scene with the box checked), else None."""
        if not (self._erp and self.dataset_root() is not None and self.pinhole.isChecked()):
            return None
        try:
            pitches = tuple(float(v) for v in self.pitches.text().replace(";", ",").split(",") if v.strip())
        except ValueError:
            pitches = ()
        n = self.yaws.value()
        return Views(yaws=tuple(360.0 * i / n for i in range(n)), pitches=pitches or (0.0,),
                     fov=float(self.fov.value()), size=self.side.value())

    def _pick_dataset(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "New dataset folder (an empty one)", self.dataset.text())
        if d:
            self.dataset.setText(d)

    def _folder(self, name: Optional[str]) -> Path:
        base = Path(self.out.text().strip())
        return base if name is None else base.parent / f"{base.name}_{name}"

    def _show_folders(self) -> None:
        chosen = self._chosen()
        self.delete_set_btn.setEnabled(self.mask.currentData() not in (None, self.EVERY))
        if chosen == [None]:
            self.folders.setText("")
        else:
            text = "Writes: " + " · ".join(f"{n or 'Final'} → {self._folder(n).name}/" for n in chosen)
            p = self.preset()
            if p is not None and any(n is not None for n in chosen):
                text += (f" — {p.label} reads {p.folder}/ only: to train with a set, rename its folder"
                         f" to {p.folder}/ (or pick the set's Objects and export the Final Mask)")
            self.folders.setText(text)

    def preset(self):
        return preset(self.target.currentData())

    def _apply_target(self) -> None:
        """A preset fixes folder, names and colors (shown, grayed); Custom frees them again."""
        p = self.preset()
        if self.out.isEnabled():
            self._custom_dir = self.out.text()  # keep what was typed for Custom
        for w in (self.out, self.pattern, self.invert, self.empty):
            w.setEnabled(p is None)
        self._out_row.setVisible(p is not None and self._scene is not None)
        self.dataset.setEnabled(self.to_new.isChecked())
        self._pin_row.setVisible(self._erp and p is not None and self.to_new.isChecked())
        for w in (self.yaws, self.pitches, self.fov, self.side):
            w.setEnabled(self.pinhole.isChecked())
        if p is None:
            self.out.setText(self._custom_dir)
            self.note.setText("")
        else:
            if self._scene is not None:
                root = self.dataset_root() or self._scene.root
                self.out.setText(str(root / p.folder))
            self.pattern.setCurrentIndex([v for _, v in self.PATTERNS].index(p.pattern))
            self.invert.setChecked(p.object_black)
            self.empty.setChecked(p.every_image)
            self.note.setText(f"{p.note} Files already there are moved to {p.folder}_backup_<time>/ first. "
                              f"Checked against: {p.verified}.")
        self._run_check()

    def _run_check(self) -> None:
        self._show_folders()
        if self._check is None:
            return
        name = self._chosen()[0] if len(self._chosen()) == 1 else None  # Every set: the Final Mask's check
        pattern = self.PATTERNS[self.pattern.currentIndex()][1]
        c = self._check(pattern) if name is None else self._check(pattern, list(self._sets[name]))
        self.check_result = c

        def line(ok: bool, text: str) -> str:
            color = "#2a8a2a" if ok else "#d78200"
            return f"<span style='color: {color}'>{'✓' if ok else '⚠'}</span> {text}"

        missing = len(c.without_mask)
        written = len(c.with_mask) + len(c.empty) + (missing if self.empty.isChecked() else 0)
        if self.dataset_root() is not None and self.empty.isChecked():
            written = c.images - self._excluded  # a new dataset holds the kept frames only
        v = self.views()
        if v is not None:
            written *= len(v.pairs())  # one mask per view
        rows = [
            f"<b>{written}</b> file(s) will be written for <b>{c.images}</b> image(s)",
            line(missing == 0 or self.empty.isChecked(), f"Images without a mask: {missing}"
                 + ("" if missing == 0 else " (written all white: nothing ignored there)" if self.empty.isChecked()
                    else " (no file — see “Also write empty masks”)")),
            line(not c.empty, f"Empty masks: {len(c.empty)}"),
            line(not c.warning, f"Suspicious / failed frames (⚠ ✕): {len(c.warning)}"),
            line(not c.clashes, "File names: " + ("OK" if not c.clashes else f"{len(c.clashes)} clash(es)")),
        ]
        rows += self._scene_rows(line)
        self.summary.setText("<br>".join(rows))
        self.problems.clear()
        reasons = (
            (set() if self.empty.isChecked() else set(c.without_mask), "no mask"),
            (set(c.empty), "empty"),
            (set(c.warning), "⚠ / ✕"),
            ({k for ks in c.clashes for k in ks}, "name clash"),
        )
        index = {k: i for i, k in enumerate(c.keys)}
        for k in c.problems:
            why = ", ".join(r for ks, r in reasons if k in ks)
            if not why:
                continue  # only "no mask", and those are written all white
            self.problems.addItem(f"{index[k] + 1}  {k}  —  {why}")
            self.problems.item(self.problems.count() - 1).setData(Qt.ItemDataRole.UserRole, k)
        self.problems.setVisible(self.problems.count() > 0)

    def _scene_rows(self, line) -> List[str]:
        """The scene's side of the check: cameras the trainer may not read, files to be backed up."""
        p, sc = self.preset(), self._scene
        if p is None or sc is None:
            return []
        rows = []
        root = self.dataset_root()
        if root is not None:
            why = dataset_blocker(root)
            v = self.views()
            what = (f"{len(v.pairs())} pinhole views per 360 image ({v.fov:.0f}°)" if v is not None
                    else "images/ linked, sparse/0/ filtered")
            rows.append(line(not why, why or f"New dataset: {root.name}/ — {what}"
                                              + (f", {self._excluded} ⊘ frame(s) left out" if self._excluded else "")))
        elif self._excluded:
            rows.append(line(False, f"{self._excluded} frame(s) are ⊘ excluded: that only applies to a New dataset"))
        odd = [m for m in sc.camera_models if m in p.unconfirmed_cameras]
        if self.views() is not None:
            rows.append(line(True, f"Cameras: {', '.join(sc.camera_models)} → PINHOLE views"))
        elif sc.camera_models:
            rows.append(line(not odd, "Cameras: " + ", ".join(sc.camera_models)
                             + (f" ({', '.join(odd)}: not confirmed for {p.label})" if odd else "")))
        out = Path(self.out.text().strip())
        c = getattr(self, "check_result", None)
        if c is not None and out.is_dir():
            names = [p.pattern.format(stem=Path(k).stem, name=k) for k in c.keys]
            n = sum(1 for nm in names if (out / nm).is_file())
            if n:
                rows.append(line(False, f"{n} file(s) in {out.name}/ will be moved to {out.name}_backup_…/ first"))
        return rows

    def _open_problem(self, item) -> None:
        self.goto = item.data(Qt.ItemDataRole.UserRole)
        self.reject()

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Export folder", self.out.text())
        if d:
            self.out.setText(d)

    def jobs(self) -> List[ExportOptions]:
        """One export per chosen mask (the Final Mask and / or mask sets), each in its own folder."""
        return [
            ExportOptions(
                out_dir=self._folder(name),
                name_pattern=self.PATTERNS[self.pattern.currentIndex()][1],
                invert=self.invert.isChecked(),
                include_empty=self.empty.isChecked(),
                backup=self.preset() is not None,
                object_ids=None if name is None else list(self._sets[name]),
            )
            for name in self._chosen()
        ]

    def options(self) -> ExportOptions:
        return self.jobs()[0]


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
        ("Delete", "Delete the selected point, else the selected Objects (no question: Ctrl+Z; 🔒 locked ones stay)"),
        ("Esc", "Leave the tool (drops an auto tool's result), then finish editing"),
        ("Ctrl+I", "While editing: invert the mask on this image (inside the region, if any)"),
        ("Ctrl+Backspace", "While editing: clear the mask on this image (inside the region, if any)"),
        ("Enter", "Auto tool: Apply & Continue (Fill: all, Paint: the picks)"),
        ("The active auto tool again", "Leave it, dropping its result (like Esc)"),
        ("Ctrl+D, mouse over Objects", "Duplicate the selected Objects (this image's mask)"),
        ("Ctrl+Shift+D, mouse over Objects", "Duplicate All (every linked mask)"),
        ("Objects buttons / Edit > Objects", "Move A → B: the first selected's mask into the last (Add, this image) · "
                                             "Merge: Add · ⚙ next to them: Copy / Replace / every image, Override · "
                                             "🔒: cannot be deleted"),
    )),
    ("Images", (
        ("Right / PgDown", "Next image (not while editing)"),
        ("Left / PgUp", "Previous image (not while editing)"),
        ("Up / Down", "Previous / next Object with a mask on this image (Edit follows)"),
        ("W A S D / arrows, mouse over the Frame List or Frames strip",
         "W A ↑ ← previous frame · S D ↓ → next frame"),
        ("Space, mouse over the Frame List or Frames strip", "Same as Enter: the current image is the reference ◎"),
        ("W A S D / arrows, mouse over the Objects list", "Previous / next Object row (Show all rows too; wraps around)"),
        ("W / S, mouse over the image", "Previous / next Object row (the list's order; wraps around)"),
        ("⌖", "Scroll the frame list and strip to the current frame (Go to ID: type + Enter)"),
        ("[ / ]", "Previous / next ⚠ or ✕ image (with the Frame List's 1 on: also – = no mask of the Object)"),
        (", / .", "Nearest earlier / later keyframe ★ (edited there, a propagation source; the 1 on: its Object's only)"),
        ("F", "Go to the propagation reference ◎ (the double-clicked image)"),
        ("Enter", "Make the current image the propagation reference ◎ (again: back to none); an auto tool's Enter comes first"),
        ("Double-click an image", "Make it the propagation reference (◎); again: back to the current image"),
        ("Shift / Ctrl-click images", "Pick the images for the Selection propagation scope (📌 Pin keeps them)"),
    )),
    ("View", (
        ("Z (hold)", "Mask Preview while held"),
        ("V", "Mask Preview (black and white) on / off"),
        ("X", "Mask Preview shows: the Final Mask <-> the selected Object's mask"),
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
