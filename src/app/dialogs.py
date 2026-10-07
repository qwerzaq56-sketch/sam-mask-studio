"""Settings and Export dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QSize, Qt, QTimer
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
    QScrollArea,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.app.settings import Settings
from src.core.colmap_model import dataset_blocker
from src.core.presets import CUSTOM, PRESETS, preset
from src.app.view_preview import ViewPreview
from src.core.colmap import read_cameras_full
from src.core.reproject import CONVERTIBLE, FISHEYES, MIN_VIEW_SHARE, VIEW_LAYOUTS, Erp, Stitch, Views, view_share
from src.core.storage import ExportCheck, ExportOptions, existing_style, mask_files


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


def _section(title: str, layout) -> QGroupBox:
    """One of the Export window's sections (What, Where, Files, Check)."""
    box = QGroupBox(title)
    box.setLayout(layout)
    return box


def _fixed(value: QWidget) -> QWidget:
    """A value a preset fixes: shown as text with a small "preset" tag, not as a grayed-out field (EX-5)."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(value, 1)
    tag = QLabel("preset")
    tag.setStyleSheet("color: palette(mid); border: 1px solid palette(mid); border-radius: 3px; padding: 0 4px;")
    tag.setToolTip("Set by the trainer preset; pick Custom to change it")
    lay.addWidget(tag, 0, Qt.AlignmentFlag.AlignTop)
    return w


class _PathLabel(QLabel):
    """A path that keeps its end (the folder's name) in view: the front is cut, the whole path is the tooltip."""

    def __init__(self):
        super().__init__()
        self._path = ""

    def set_path(self, path: str) -> None:
        self._path = path
        self.setToolTip(path)
        self._fit()
        self.updateGeometry()

    def path(self) -> str:
        return self._path

    def _fit(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._path, Qt.TextElideMode.ElideLeft, max(20, self.width())))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._fit()

    def sizeHint(self) -> QSize:
        return QSize(min(420, self.fontMetrics().horizontalAdvance(self._path) + 4), super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(60, super().minimumSizeHint().height())


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(640)  # room for the checkpoint paths
        self.sam2 = QLineEdit(settings.sam2_checkpoint)
        self.sam3 = QLineEdit(settings.sam3_checkpoint)
        self.sky = QLineEdit(settings.sky_checkpoint)
        self.max_side = QSpinBox()
        self.max_side.setRange(0, 8192)
        self.max_side.setSingleStep(128)
        self.max_side.setSpecialValueText("original size")
        self.max_side.setValue(settings.max_side)
        form = QFormLayout(self)
        form.addRow("SAM2 checkpoint", _path_row(self.sam2, lambda: self._pick(self.sam2)))
        form.addRow("SAM3 checkpoint", _path_row(self.sam3, lambda: self._pick(self.sam3)))
        form.addRow("Sky model (ONNX)", _path_row(self.sky, lambda: self._pick(self.sky)))
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
            self, "Checkpoint", edit.text(), "Checkpoints (*.pt *.pth *.onnx);;All files (*)"
        )
        if path:
            edit.setText(path)

    def apply(self, settings: Settings) -> None:
        settings.sam2_checkpoint = self.sam2.text().strip()
        settings.sam3_checkpoint = self.sam3.text().strip()
        settings.sky_checkpoint = self.sky.text().strip()
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


def _first_sentence(text: str) -> str:
    """Up to the first full stop that ends a sentence (not one inside a name like a.png)."""
    for i, ch in enumerate(text):
        if ch == "." and (i + 1 == len(text) or text[i + 1] == " "):
            return text[:i + 1]
    return text


class ExportDialog(QDialog):
    """Final Mask PNG export options.

    For a COLMAP scene a trainer preset (docs/specs/07-export-presets.md) fixes the
    folder (the scene's masks/), the names and the colors; "Custom" leaves them free.
    Mask: the Final Mask (the checked Objects) goes to the folder, a named mask set
    to ``<folder>_<name>`` (masks_people/); "Every set" writes all of them.
    """

    EVERY = "*"  # the Mask choice that writes the Final Mask and every set
    _open = {"note": False, "views": False}  # More / Edit, kept open for the next window (C-2)

    PATTERNS = (
        ("{stem}.png  (frame_001.png)", "{stem}.png"),
        ("{name}.png  (COLMAP: frame_001.jpg.png)", "{name}.png"),
    )

    def __init__(self, default_dir: Path, parent=None, check: Optional[Callable[..., ExportCheck]] = None,
                 scene=None, target: str = CUSTOM, sets: Optional[dict] = None,
                 save_set: Optional[Callable[[str], bool]] = None, delete_set: Optional[Callable[[str], None]] = None,
                 excluded: int = 0, sky: bool = False, sky_edges: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Export Final Masks")
        self.goto: Optional[str] = None  # an image picked in the check list: leave and open it
        self.setMinimumWidth(540)
        self._check = check
        self._scene = scene
        self._custom_dir = str(default_dir)
        self.target = QComboBox()
        for p in PRESETS if scene is not None else ():
            self.target.addItem(p.label, p.key)
        self.target.addItem("Custom (choose below)", CUSTOM)
        i = self.target.findData(target)
        self.target.setCurrentIndex(i if i >= 0 else 0)
        # the preset's note: its first sentence, the rest (backup, sources) behind More
        self.note_head = QLabel()
        self.note_head.setWordWrap(True)
        self.note = QLabel()  # the whole note
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray;")
        self.note_more = QLabel()
        self.note_more.linkActivated.connect(lambda _l: self._toggle("note"))
        self._note_box = QWidget()
        nb = QVBoxLayout(self._note_box)
        nb.setContentsMargins(0, 0, 0, 0)
        nb.setSpacing(2)
        for w in (self.note_head, self.note, self.note_more):
            nb.addWidget(w)
        self._sets = sets if sets is not None else {}
        self._save_set, self._delete_set = save_set, delete_set
        self.mask = QComboBox()
        self.mask.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.mask.setMinimumContentsLength(24)
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
        self.to_new = QRadioButton("New dataset")
        self.to_scene.setChecked(True)
        self.dataset = QLineEdit(str(scene.root.parent / f"{scene.root.name}_dataset") if scene is not None else "")
        self.dataset.setToolTip("A new folder: images/ (hard links, no extra space on the same drive), "
                                "sparse/0/ without the ⊘ frames, and the masks")
        self._out_row = QWidget()
        orow = QHBoxLayout(self._out_row)
        orow.setContentsMargins(0, 0, 0, 0)
        orow.addWidget(self.to_scene)
        orow.addWidget(self.to_new)
        orow.addStretch(1)
        self._dataset_row = _path_row(self.dataset, self._pick_dataset)
        # the new dataset's cameras: kept, or converted to pinhole views / one 360 image (docs/specs/08)
        models = set(scene.camera_models) if scene is not None else set()
        self._erp = "EQUIRECTANGULAR" in models
        fisheye = bool(models & set(FISHEYES))
        self._convertible = bool(models & set(CONVERTIBLE)) and not models <= {"PINHOLE", "SIMPLE_PINHOLE"}
        self.convert = QComboBox()
        self.convert.addItem("Keep the cameras", None)
        self.convert.addItem("Pinhole views", "pinhole")
        if not self._erp:
            self.convert.addItem("360 (ERP)", "erp")
        self._groups = scene.rig_groups() if scene is not None and not self._erp else []
        if self._groups:
            self._convertible = True
            self.convert.addItem(f"360 from camera pairs ({len(self._groups)} moments)", "stitch")
        self.convert.setToolTip("Pinhole views: every image becomes perspective views (images, masks, model). "
                                "360: one equirectangular image each (a fisheye's unseen part is masked out)")
        self.yaws = QLineEdit("0, 90, 180, 270" if self._erp else "-45, 0, 45" if fisheye else "0")
        self.yaws.setToolTip("Left / right angles in degrees (right is positive), one view each per pitch")
        self.pitches = QLineEdit("-35, 0, 35" if self._erp or fisheye else "0")
        self.pitches.setToolTip("Up / down angles in degrees (up is positive), one row of views each")
        self.view_layout = QComboBox()  # 360 sources: the usual view layouts (docs/specs/08 P4), or the grid below
        for key, lay in VIEW_LAYOUTS.items():
            self.view_layout.addItem(lay.label, key)
            self.view_layout.setItemData(self.view_layout.count() - 1, lay.purpose, Qt.ItemDataRole.ToolTipRole)
        self.view_layout.addItem("Custom", None)
        self.view_layout.setItemData(self.view_layout.count() - 1,
                                     "The yaw × pitch grid typed below: for a special rig or an experiment",
                                     Qt.ItemDataRole.ToolTipRole)
        self.view_layout.setToolTip("Where the pinhole views look (a layout, not a camera model). No layout has been shown "
                                    "to train better; more views = more coverage / overlap and more images")
        # what the layout is for, how many views and how much they overlap, and a map of them
        self.layout_note = QLabel("")
        self.layout_note.setWordWrap(True)
        self.layout_note.setStyleSheet("color: gray;")
        self.view_preview = ViewPreview()
        self._cameras = []
        if scene is not None and not self._erp:  # a fisheye's views are checked against its lens
            try:
                self._cameras = [c for c in read_cameras_full(scene.model_dir).values() if c.model in FISHEYES]
            except (OSError, ValueError):
                self._cameras = []
        if not self._erp:
            self.view_layout.setCurrentIndex(self.view_layout.count() - 1)  # a fisheye looks one way: its own grid
        self.fov = QSpinBox()
        self.fov.setRange(30, 150)
        self.fov.setValue(90)
        self.fov.setSuffix("°")
        self.side = QSpinBox()
        self.side.setRange(0, 16384)
        self.side.setSingleStep(64)
        self.side.setSpecialValueText("auto")
        self.side.setSuffix(" px")
        self.side.setToolTip("Output width; auto = the source's own resolution at that angle")
        for w in (self.yaws, self.pitches):
            w.setMinimumWidth(w.fontMetrics().horizontalAdvance("-135, -90, -45, 0, 45, 90") + 16)
        # the views in one line; Edit opens the fields and the map (C-2)
        self.views_summary = QLabel()
        self.views_summary.setWordWrap(True)
        self.views_summary.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.views_edit = QPushButton()
        self.views_edit.setCheckable(True)
        self.views_edit.setFlat(True)
        self.views_edit.setChecked(self._open["views"])
        self.views_edit.toggled.connect(lambda _on: self._toggle("views"))
        self._cam_row = QWidget()
        crow = QHBoxLayout(self._cam_row)
        crow.setContentsMargins(0, 0, 0, 0)
        crow.addWidget(self.convert)
        crow.addStretch(1)
        self._views_line = QWidget()
        sl = QHBoxLayout(self._views_line)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.views_summary, 1)
        sl.addWidget(self.views_edit, 0, Qt.AlignmentFlag.AlignTop)
        self._views_box = QWidget()
        vb = QVBoxLayout(self._views_box)
        vb.setContentsMargins(0, 0, 0, 0)
        self._views_form = QFormLayout()
        self._views_form.addRow("Layout", self.view_layout)
        self._views_form.addRow("Yaw", self.yaws)
        self._views_form.addRow("Pitch", self.pitches)
        self._views_form.addRow("FOV", self.fov)
        self._views_form.addRow("Size", self.side)
        vb.addLayout(self._views_form)
        vb.addWidget(self.layout_note)
        vb.addWidget(self.view_preview)
        # the files: fields for Custom, the preset's values as text for a preset
        self.out = QLineEdit(str(default_dir))
        self.out_fixed = _PathLabel()
        self.pattern = QComboBox()
        for label, _ in self.PATTERNS:
            self.pattern.addItem(label)
        self.names_fixed = QLabel()
        self.names_fixed.setWordWrap(True)
        self.invert = QCheckBox("Invert (Objects black)")
        self.invert.setToolTip("Objects black, background white")
        self.empty = QCheckBox("Also empty masks")
        self.empty.setToolTip("Also write a mask for the images without Objects (all white: nothing ignored there)")
        self._colours = QWidget()
        cl = QHBoxLayout(self._colours)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.invert)
        cl.addWidget(self.empty)
        cl.addStretch(1)
        self.sky_edges = QCheckBox("Edges at full resolution (slower)")
        self.sky_edges.setToolTip(
            "Sky Objects: the edge is decided again on the full-size image, pixel by pixel, by colour,\n"
            "instead of scaling the working mask up (blocky, over the outer leaves). Also finds the sky\n"
            "between leaves near the edge. Other Objects are scaled up as always. About 1 s per 4K image."
        )
        self.sky_edges.setChecked(sky_edges)
        # the check: what gets written, and the images worth a look before exporting
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setWordWrap(True)
        self.problems = QListWidget()
        self.problems.setMaximumHeight(130)
        self.problems.setToolTip("Double-click: close this and open the image")
        self.problems.itemDoubleClicked.connect(self._open_problem)
        # sections in the order of the questions (EX-1, C-1): What -> Where -> Files, the check last
        self._body = QWidget()
        main = QVBoxLayout(self._body)
        main.setContentsMargins(0, 0, 0, 0)
        number = iter(range(1, 5))
        self._where_form: Optional[QFormLayout] = None
        if save_set is not None:
            what = QFormLayout()
            row = QHBoxLayout()
            row.addWidget(self.mask, 1)
            row.addWidget(self.save_set_btn)
            row.addWidget(self.delete_set_btn)
            what.addRow("Mask", row)
            main.addWidget(_section(f"{next(number)}  What", what))
        if scene is not None:
            self._where_form = QFormLayout()
            self._where_form.addRow("For", self.target)
            self._where_form.addRow(self._note_box)
            self._where_form.addRow("Output", self._out_row)
            self._where_form.addRow("Dataset", self._dataset_row)
            self._where_form.addRow("Cameras", self._cam_row)
            self._where_form.addRow("", self._views_line)
            self._where_form.addRow(self._views_box)
            main.addWidget(_section(f"{next(number)}  Where", self._where_form))
        self._files_form = QFormLayout()
        ff = self._files_form
        self._out_edit = _path_row(self.out, self._pick)
        self._out_preset = _fixed(self.out_fixed)
        self._names_preset = _fixed(self.names_fixed)
        ff.addRow("Folder", self._out_edit)
        ff.addRow("Folder", self._out_preset)
        ff.addRow(self.folders)
        ff.addRow("Names", self.pattern)
        ff.addRow("Names", self._names_preset)
        ff.addRow("", self._colours)
        ff.addRow("Sky", self.sky_edges)
        ff.setRowVisible(self.sky_edges, sky)
        main.addWidget(_section(f"{next(number)}  Files", ff))
        if check is not None:
            box = QVBoxLayout()
            box.addWidget(self.summary)
            box.addWidget(self.problems)
            main.addWidget(_section("✓  Check", box))
        main.addStretch(1)
        # a short screen (1280 x 720): the sections scroll, the buttons stay
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._body)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.export_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.export_btn.setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._buttons = buttons
        outer = QVBoxLayout(self)
        outer.addWidget(self._scroll, 1)
        outer.addWidget(buttons)
        self.pattern.currentIndexChanged.connect(self._run_check)
        self.empty.toggled.connect(self._run_check)
        self.target.currentIndexChanged.connect(self._apply_target)
        self.to_new.toggled.connect(lambda _on: self._apply_target())
        self.convert.currentIndexChanged.connect(lambda _i: self._apply_target())
        self.view_layout.currentIndexChanged.connect(lambda _i: self._apply_target())
        for w in (self.fov, self.side):
            w.valueChanged.connect(lambda _v: self._run_check())
        self.fov.valueChanged.connect(lambda _v: self._apply_target())
        self.side.valueChanged.connect(lambda _v: self._apply_target())
        for w in (self.yaws, self.pitches):
            w.textChanged.connect(lambda _t: self._run_check())
            w.textChanged.connect(lambda _t: self._apply_target())
        self.dataset.textChanged.connect(lambda _t: self._apply_target())
        self.mask.currentIndexChanged.connect(self._run_check)
        self.out.textChanged.connect(lambda _t: self._show_folders())
        self.out.textChanged.connect(self.out_fixed.set_path)
        self.out_fixed.set_path(self.out.text())
        self._apply_target()

    def _toggle(self, part: str) -> None:
        """More / Edit: opened or closed, and kept that way for the next Export window."""
        if part == "note":
            self._open["note"] = not self._open["note"]
        else:
            self._open["views"] = self.views_edit.isChecked()
        self._apply_target()

    # --- mask sets -------------------------------------------------------------------------

    def _fill_sets(self, select: Optional[str] = None) -> None:
        self.mask.blockSignals(True)
        self.mask.clear()
        self.mask.addItem("Final Mask — the checked Objects", None)
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

    def _kept_views(self, v: Views) -> int:
        """The views made per image: all of them, less a fisheye's views its lens cannot fill."""
        if not self._cameras:
            return len(v.pairs())
        return sum(all(view_share(c, y, p, v.fov) >= MIN_VIEW_SHARE for c in self._cameras) for y, p in v.pairs())

    def _show_layout(self, on: bool) -> None:
        """The layout's purpose, its view count and overlap, and the map of the views (docs/specs/08 P4)."""
        self.layout_note.setVisible(on)
        self.view_preview.setVisible(on)
        if not on:
            return
        v = Views(fov=float(self.fov.value()))
        key = self.view_layout.currentData() if self._erp else None
        pairs = VIEW_LAYOUTS[key].pairs() if key is not None else None
        if pairs is None:  # the typed grid
            def angles(field):
                try:
                    return tuple(float(t) for t in field.text().replace(";", ",").split(",") if t.strip())
                except ValueError:
                    return ()
            pairs = Views(yaws=angles(self.yaws) or (0.0,), pitches=angles(self.pitches) or (0.0,)).pairs()
        fov = v.fov
        kept = [all(view_share(c, y, p, fov) >= MIN_VIEW_SHARE for c in self._cameras) if self._cameras else True
                for y, p in pairs]
        self.view_preview.set_views(pairs, fov, kept)
        if key is not None:
            lay = VIEW_LAYOUTS[key]
            side, rings = lay.overlap(fov)
            ov = f"sideways {side:+.0f}°" + (f", between rings {rings:+.0f}°" if rings is not None else "")
            self.layout_note.setText(f"{lay.purpose}<br><b>{lay.count} views</b> per image at {fov:.0f}° · overlap {ov}")
        else:
            dropped = kept.count(False)
            self.layout_note.setText(
                f"<b>{kept.count(True)} views</b> per image at {fov:.0f}°"
                + (f" · {dropped} left out: the fisheye cannot fill them (gray)" if dropped else "")
                + ("" if self._cameras else " · Custom: yaw × pitch as typed"))

    def views(self):
        """What the new dataset's cameras become: ``Views`` (pinhole), ``Erp`` (360) or None (kept)."""
        if not (self._convertible and self.dataset_root() is not None):
            return None
        return self._typed_views()

    def _typed_views(self):
        """What the convert choice and the fields say, whether or not a new dataset is picked."""
        kind = self.convert.currentData()
        if not kind:
            return None
        if kind == "erp":
            return Erp(width=self.side.value())
        if kind == "stitch":
            return Stitch(width=self.side.value())

        def angles(field: QLineEdit):
            try:
                return tuple(float(v) for v in field.text().replace(";", ",").split(",") if v.strip())
            except ValueError:
                return ()

        key = self.view_layout.currentData() if self._erp else None
        if key is not None:
            return Views(fov=float(self.fov.value()), size=self.side.value(), layout=VIEW_LAYOUTS[key])
        return Views(yaws=angles(self.yaws) or (0.0,), pitches=angles(self.pitches) or (0.0,),
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
            self._files_form.setRowVisible(self.folders, False)
        else:
            self._files_form.setRowVisible(self.folders, True)
            text = "Writes: " + " · ".join(f"{n or 'Final'} → {self._folder(n).name}/" for n in chosen)
            p = self.preset()
            if p is not None and any(n is not None for n in chosen):
                text += (f" — {p.label} reads {p.folder}/ only: to train with a set, rename its folder"
                         f" to {p.folder}/ (or pick the set's Objects and export the Final Mask)")
            self.folders.setText(text)

    def preset(self):
        return preset(self.target.currentData())

    def _apply_target(self) -> None:
        """Rows shown / hidden together, then the window sized once: one by one, every step resized the
        window below what Windows allows (word-wrapped text) and Qt warned each time (2026-10-02)."""
        lay = self._body.layout()
        if lay is None:
            self._apply_target_now()
            return
        lay.setEnabled(False)
        try:
            self._apply_target_now()
        finally:
            lay.setEnabled(True)
            lay.invalidate()
            lay.activate()
            self._fit_height(shrink=True)  # grows with an opened part, shrinks back when it closes
            QTimer.singleShot(0, self._fit_height)  # again once the labels' new sizes are known

    def _fit_height(self, shrink: bool = False) -> None:
        """Tall enough for every word-wrapped line at the window's width now (EX-3, EX-4: nothing cut off);
        on a short screen as tall as it can be, the sections scroll."""
        body = self._body.layout()
        outer = self.layout()
        if body is None or outer is None:
            return
        bar = self._scroll.verticalScrollBar().sizeHint().width()
        self._scroll.setMinimumWidth(self._body.minimumSizeHint().width() + bar)  # never cut off sideways
        width = self._scroll.viewport().width()
        need = body.totalHeightForWidth(width) if body.hasHeightForWidth() else body.totalSizeHint().height()
        m = outer.contentsMargins()
        need += self._buttons.sizeHint().height() + outer.spacing() + m.top() + m.bottom()
        screen = self.screen()
        if screen is not None:
            need = min(need, screen.availableGeometry().height() - 60)  # the title bar
        if need > self.height() or (shrink and need < self.height()):
            self.resize(self.width(), need)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._fit_height()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if e.size().width() != e.oldSize().width():
            self._fit_height()  # narrower: more lines

    def _apply_target_now(self) -> None:
        """A preset fixes folder, names and colors (shown as text); Custom gives the fields back."""
        p = self.preset()
        if self.out.isEnabled():
            self._custom_dir = self.out.text()  # keep what was typed for Custom
        for w in (self.out, self.pattern, self.invert, self.empty):
            w.setEnabled(p is None)
        scene = p is not None and self._scene is not None
        new = scene and self.to_new.isChecked()
        kind = self.convert.currentData() if self._convertible and new else None
        wf = self._where_form
        if wf is not None:
            wf.setRowVisible(self._note_box, scene)
            wf.setRowVisible(self._out_row, scene)
            wf.setRowVisible(self._dataset_row, new)
            wf.setRowVisible(self._cam_row, self._convertible and new)
            wf.setRowVisible(self._views_line, kind is not None)
            wf.setRowVisible(self._views_box, kind is not None and self._open["views"])
        self.views_edit.blockSignals(True)
        self.views_edit.setChecked(self._open["views"])
        self.views_edit.blockSignals(False)
        self.views_edit.setText("Hide ▴" if self._open["views"] else "Edit ▸")
        vf = self._views_form
        grid = kind == "pinhole" and (self.view_layout.currentData() is None or not self._erp)
        vf.setRowVisible(self.view_layout, kind == "pinhole" and self._erp)
        vf.setRowVisible(self.yaws, grid)
        vf.setRowVisible(self.pitches, grid)
        vf.setRowVisible(self.fov, kind == "pinhole")
        vf.setRowVisible(self.side, kind is not None)
        self._show_layout(kind == "pinhole")
        self.views_summary.setText(self._views_text(kind))
        ff = self._files_form
        ff.setRowVisible(self._out_edit, p is None)
        ff.setRowVisible(self._out_preset, p is not None)
        ff.setRowVisible(self.pattern, p is None)
        ff.setRowVisible(self._names_preset, p is not None)
        ff.setRowVisible(self._colours, p is None)
        if p is None:
            self.out.setText(self._custom_dir)
            self.note.setText("")
        else:
            if self._scene is not None:
                root = self.dataset_root() or self._scene.root
                self.out.setText(str(root / p.folder))
            pattern, follows = p.pattern, ""
            style = self._scene_style(p)
            if style is not None and style != p.pattern:  # the scene's masks are named the other way: follow them
                pattern, follows = style, f"File names follow the masks already in {p.folder}/ ({style}). "
            self.pattern.setCurrentIndex([v for _, v in self.PATTERNS].index(pattern))
            self.invert.setChecked(p.object_black)
            self.empty.setChecked(p.every_image)
            self.names_fixed.setText(f"{pattern} · Objects {'black' if p.object_black else 'white'}"
                                     + (" · every image" if p.every_image else " · images with a mask")
                                     + (" (as the masks there)" if follows else ""))
            self.note.setText(f"{p.note} {follows}Masks already there for these images (a.png or a.jpg.png) are "
                              f"moved to {p.folder}_backup_<time>/ first. Checked against: {p.verified}.")
            head = _first_sentence(p.note)
            self.note_head.setText(head)
            opened = self._open["note"]
            self.note_head.setVisible(not opened)
            self.note.setVisible(opened)
            self.note_more.setText(f"<a href='more'>{'Less ▴' if opened else 'More ▸'}</a>")
        self._run_check()

    def _views_text(self, kind) -> str:
        """The new dataset's views in one line (the fields are behind Edit)."""
        if kind is None:
            return ""
        side = "auto" if self.side.value() == 0 else f"{self.side.value()} px"
        if kind in ("erp", "stitch"):
            return f"Width {side}"
        v = self._typed_views()
        key = self.view_layout.currentData() if self._erp else None
        where = (VIEW_LAYOUTS[key].label if key is not None
                 else f"Yaw {self.yaws.text().strip()} · Pitch {self.pitches.text().strip()}")
        n = self._kept_views(v)
        return f"{where} · FOV {self.fov.value()}° · Size {side} → <b>{n} view{'s' if n != 1 else ''}</b> per image"

    def _scene_style(self, p) -> Optional[str]:
        """Into the scene, for a trainer that reads either naming: how the masks there are named."""
        if not p.either_name or self._scene is None or self.dataset_root() is not None or self._check is None:
            return None
        return existing_style(self._scene.root / p.folder, self._check(p.pattern).keys)

    def _run_check(self) -> None:
        self._show_folders()
        if self._check is None:
            self._set_button(None)
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
        if isinstance(v, Views):
            written *= self._kept_views(v)  # one mask per view (a fisheye's unfillable views are not made)
        elif isinstance(v, Stitch):
            written = len(self._groups)  # one mask per moment (a moment with a ⊘ image is left out)
        rows = [
            f"<b>{written:,}</b> file(s) will be written for <b>{c.images:,}</b> image(s)",
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
            (set() if self.empty.isChecked() else set(c.without_mask), "no mask → no file"),
            (set(c.empty), "empty mask"),
            (set(c.warning), "suspicious or failed (⚠ ✕)"),
            ({k for ks in c.clashes for k in ks}, "file name clash"),
        )
        index = {k: i for i, k in enumerate(c.keys)}
        for k in c.problems:
            why = ", ".join(r for ks, r in reasons if k in ks)
            if not why:
                continue  # only "no mask", and those are written all white
            self.problems.addItem(f"{index[k] + 1}  {k}  —  {why}")
            self.problems.item(self.problems.count() - 1).setData(Qt.ItemDataRole.UserRole, k)
        self.problems.setVisible(self.problems.count() > 0)
        self._set_button(written)
        if self.layout() is not None:
            QTimer.singleShot(0, self._fit_height)  # the summary may have more lines now

    def _set_button(self, written: Optional[int]) -> None:
        """Export N files → where (EX-12); nothing to write: off."""
        chosen = self._chosen()
        root = self.dataset_root()
        to = (f"{len(chosen)} folders" if len(chosen) > 1
              else "new dataset" if root is not None
              else f"{self._folder(chosen[0]).name}/")
        count = "" if written is None or len(chosen) > 1 else f" {written:,} file{'s' if written != 1 else ''}"
        self.export_btn.setText(f"Export{count} → {to}")
        self.export_btn.setEnabled(written != 0)

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
            what = (f"{len(self._groups)} 360 image(s) stitched from camera pairs" if isinstance(v, Stitch)
                    else "one 360 image each" if isinstance(v, Erp)
                    else f"{self._kept_views(v)} pinhole views per image ({v.fov:.0f}°)" if v is not None
                    else "images/ linked, sparse/0/ filtered")
            rows.append(line(not why, why or f"New dataset: {root.name}/ — {what}"
                                              + (f", {self._excluded} ⊘ frame(s) left out" if self._excluded else "")))
        elif self._excluded:
            rows.append(line(False, f"{self._excluded} frame(s) are ⊘ excluded: that only applies to a New dataset"))
        odd = [m for m in sc.camera_models if m in p.unconfirmed_cameras]
        if self.views() is not None:
            to = "EQUIRECTANGULAR (360)" if isinstance(self.views(), (Erp, Stitch)) else "PINHOLE views"
            rows.append(line(True, f"Cameras: {', '.join(sc.camera_models)} → {to}"))
        elif sc.camera_models:
            rows.append(line(not odd, "Cameras: " + ", ".join(sc.camera_models)
                             + (f" ({', '.join(odd)}: not confirmed for {p.label})" if odd else "")))
        out = Path(self.out.text().strip())
        c = getattr(self, "check_result", None)
        if c is not None and out.is_dir():
            n = len(mask_files(out, c.keys))
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
                sky_edges=not self.sky_edges.isHidden() and self.sky_edges.isChecked(),
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
        ("Ctrl+Shift+E", "Export Current Mask: this image only, Final or one Object, one PNG"),
        ("", "Every command is also in the menu bar (File, Edit, View, Go, Help) with its key"),
    )),
    ("Edit", (
        ("Ctrl+Z", "Undo"),
        ("Ctrl+Y / Ctrl+Shift+Z", "Redo"),
        ("N", "New Object from points"),
        ("E", "Edit with points: start editing the selected Object; from the brush / an auto tool: back to points; "
              "points again: finish editing"),
        ("D", "Edit with the brush: start editing (the selected Object); from points: the brush; "
              "the brush again: finish editing; in an auto tool: Paint mode (in Paint: pick all / none)"),
        ("Delete", "Delete the selected point, else the selected Objects (no question: Ctrl+Z; 🔒 locked ones stay)"),
        ("Esc", "Leave the tool (drops an auto tool's result), then finish editing"),
        ("Ctrl+I", "While editing: invert the mask on this image (inside the region, if any)"),
        ("Ctrl+Backspace", "While editing: clear the mask on this image (inside the region, if any)"),
        ("F / Shift+Enter", "Auto tool: Apply & Close (confirm); F over the frame lists: reference ◎"),
        ("G / Enter", "Auto tool: Apply & Continue (Fill: all, Paint: the picks)"),
        ("A", "Auto tool: leave it, dropping its result (cancel, back to points)"),
        ("S / D", "Auto tool: Fill / Paint mode (the picks are kept in between); D in Paint: pick all / none"),
        ("Shift+A", "Auto tool: Fill -> Paint with everything picked; Paint: pick all / none"),
        ("The active auto tool again", "Leave it, dropping its result (like Esc)"),
        ("Ctrl+D, mouse over Objects", "Duplicate the selected Objects (this image's mask)"),
        ("Ctrl+Shift+D, mouse over Objects", "Duplicate All (every linked mask)"),
        ("Objects buttons / Edit > Objects", "Move A → B: the first selected's mask into the last (Add, this image) · "
                                             "Merge: Add · ⚙ next to them: Copy / Replace / every image, Override · "
                                             "🔒: cannot be deleted"),
    )),
    ("Images", (
        ("Right / PgDown", "Next image (while editing: the same Object there)"),
        ("Left / PgUp", "Previous image (while editing: the same Object there)"),
        ("Up / Down", "Previous / next Object with a mask on this image (Edit follows)"),
        ("W A S D / arrows, mouse over the Frame List or Frames strip",
         "W A ↑ ← previous frame · S D ↓ → next frame"),
        ("Space, mouse over the Frame List or Frames strip", "Same as Enter: the current image is the reference ◎"),
        ("W A S D / arrows, mouse over the Objects list", "Previous / next Object row (Show all rows too; wraps around)"),
        ("W / S, mouse over the image", "Previous / next Object row (the list's order; wraps around)"),
        ("⌖", "Scroll the frame list and strip to the current frame (Go to ID: type + Enter)"),
        ("[ / ]", "Previous / next ⚠ or ✕ image (with the Frame List's 1 on: also – = no mask of the Object)"),
        (", / .", "Nearest earlier / later keyframe ★ (edited there, a propagation source; the 1 on: its Object's only)"),
        ("F", "Go to the propagation reference ◎ (with an auto tool on and the mouse off the frame lists: apply)"),
        ("Middle click an image", "Open it, the picked images stay picked · Right click: what to do with the picks"),
        ("Enter", "Make the current image the propagation reference ◎ (again: back to none); an auto tool's Enter comes first"),
        ("Double-click an image", "Make it the propagation reference (◎); again: back to the current image"),
        ("Shift / Ctrl-click images", "Pick the images for the Selection propagation scope (📌 Pin keeps them)"),
    )),
    ("View", (
        ("Z (hold)", "Mask Preview while held"),
        ("V", "Mask Preview (black and white) on / off"),
        ("X", "Mask Preview in black and white: the Final Mask <-> the selected Object's mask (in a cut-out: back to black and white)"),
        ("C", "Mask Preview cut out: inside the mask <-> outside it (in black and white: to the cut-out)"),
        ("O", "Outline on / off"),
        ("Q / `", "Solo: color only the selected Objects"),
        ("H", "Hide Masks: the plain image"),
        ("T", "Hold while picking colors: Original, the photo alone (no tool preview either), back on release. The Original button toggles it"),
        ("Right-click while picking colors", "A color to leave out (−); Shift: one more, Alt: the 5×5 mean"),
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
        ("Ctrl+click / Ctrl+right-click", "Add / take out the piece SAM2 sees there (the rest of the mask stays)"),
        ("Drag with a brush", "Paint: add · Restore: undo edits · auto tool Paint mode: pick"),
        ("Drag a point / double-click it", "Move the point / delete it"),
        ("Alt+drag", "Paint: subtract · auto tool Paint mode: unpick · Region Box: remove a box"),
        ("Shift+drag", "Paint without turning the brush on"),
        ("Ctrl+left-drag left / right, Ctrl+wheel / Shift+wheel", "Brush size (down to one image pixel; Ctrl+click: a piece of the image; Ctrl+right-click takes one out, even moved a little)"),
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
