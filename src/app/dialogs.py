"""Settings and Export dialogs."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QInputDialog,
    QButtonGroup,
    QGridLayout,
    QMenu,
    QToolButton,
    QWidgetAction,
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
    QSizePolicy,
    QSpinBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.app.settings import Settings
from src.core.colmap_model import dataset_blocker
from src.core.presets import CUSTOM, PRESETS, RIG, preset
from src.app.view_preview import RigPreview, ViewPreview
from src.core.colmap import read_cameras_full
from src.core.reproject import (ALL_LAYOUTS, CONVERTIBLE, FISHEYE_LAYOUTS, FISHEYES, MIN_VIEW_SHARE, VIEW_LAYOUTS, Erp,
                                Stitch, Views, view_share)
from src.core.project import MaskBar
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
        self.cpu = QCheckBox("Run SAM on the CPU")
        self.cpu.setChecked(settings.use_cpu)
        self.cpu.setToolTip("SAM2 (clicks, propagation, the sky finish) and SAM3 (Detect) run on the CPU: the GPU "
                            "is left to a training. Much slower (SAM2 about 10x, SAM3 more); brushes are the same. "
                            "For one time only: start the app with --cpu (SAM Mask Studio (CPU).bat)")
        form.addRow("", self.cpu)
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
        settings.use_cpu = self.cpu.isChecked()


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


BAD_NAME = '\\/:*?"<>|'  # not in a folder name


class _ObjectsPicker(QWidget):
    """A bar's Objects: the checked ones (as in the Objects panel) or a pick; ⇆ takes one the other way round."""

    changed = pyqtSignal()

    def __init__(self, objects: Sequence[Tuple[int, str, bool]], bar: MaskBar):
        super().__init__()
        lay = QGridLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        self.follow = QCheckBox("Checked Objects (as in the Objects panel)")
        self.follow.setChecked(bar.ids is None)
        lay.addWidget(self.follow, 0, 0, 1, 2)
        self._included = {oid: inc for oid, _n, inc in objects}
        self._names = {oid: name for oid, name, _i in objects}
        self.pick, self.flip = {}, {}
        for r, (oid, name, inc) in enumerate(objects, 1):
            c = QCheckBox(name)
            c.setChecked(inc if bar.ids is None else oid in bar.ids)
            f = QCheckBox("⇆ Invert")
            f.setToolTip("This Object the other way round: what is outside it goes into the mask\n"
                         "(an image where it has no mask: all of the image). Its own mask is not changed.")
            f.setChecked(oid in bar.flipped)
            lay.addWidget(c, r, 0)
            lay.addWidget(f, r, 1)
            self.pick[oid], self.flip[oid] = c, f
            c.toggled.connect(lambda _on: self._changed())
            f.toggled.connect(lambda _on: self._changed())
        self.follow.toggled.connect(lambda _on: self._changed())
        self._sync()

    def _sync(self) -> None:
        follow = self.follow.isChecked()
        for oid, c in self.pick.items():
            c.setEnabled(not follow)
            if follow:
                c.blockSignals(True)
                c.setChecked(self._included[oid])
                c.blockSignals(False)
            self.flip[oid].setEnabled(c.isChecked())  # only an Object in the mask can be inverted

    def _changed(self) -> None:
        self._sync()
        self.changed.emit()

    def ids(self) -> Optional[Tuple[int, ...]]:
        if self.follow.isChecked():
            return None
        return tuple(oid for oid, c in self.pick.items() if c.isChecked())

    def members(self) -> List[int]:
        return [oid for oid, c in self.pick.items() if c.isChecked()]

    def flipped(self) -> Tuple[int, ...]:
        return tuple(oid for oid in self.members() if self.flip[oid].isChecked())

    def text(self) -> str:
        """For the bar's button: "Checked Objects (3) · ⇆lens" or "person 1, ⇆lens"."""
        flip = set(self.flipped())
        if self.follow.isChecked():
            n = len(self.members())
            return f"Checked Objects ({n})" + "".join(f" · ⇆{self._names[o]}" for o in self.flipped())
        names = [("⇆" if oid in flip else "") + self._names[oid] for oid in self.members()]
        return ", ".join(names) if names else "No Objects"


class _BarRow(QWidget):
    """One mask the Export writes, one folder (plan Export 9): on, name, Objects, Invert."""

    changed = pyqtSignal()
    removed = pyqtSignal(object)
    duplicated = pyqtSignal(object)

    def __init__(self, bar: MaskBar, objects: Sequence[Tuple[int, str, bool]]):
        super().__init__()
        self.on = QCheckBox()
        self.on.setChecked(bar.on)
        self.on.setToolTip("Write this mask with the next Export")
        self.name = QLineEdit(bar.name)
        self.name.setPlaceholderText("name")
        self.name.setFixedWidth(110)
        self.name.setToolTip("Its folder becomes <folder>_<name>; left empty: <folder> itself")
        self.picker = _ObjectsPicker(objects, bar)
        self.objects_btn = QPushButton()
        self.objects_btn.setStyleSheet("text-align: left; padding: 3px 8px;")
        self.objects_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.objects_btn.setToolTip("Which Objects go into this mask, and which of them inverted (⇆)")
        menu = QMenu(self.objects_btn)
        act = QWidgetAction(menu)
        act.setDefaultWidget(self.picker)
        menu.addAction(act)
        self.objects_btn.setMenu(menu)
        self.invert = QCheckBox("Invert")
        self.invert.setToolTip("Objects black, the rest white (off: Objects white). Until you change it,\n"
                               "it follows the trainer preset")
        self._invert_set = bar.invert is not None
        self.invert.setChecked(bool(bar.invert))
        self.remove = QToolButton()
        self.remove.setText("✕")
        self.remove.setAutoRaise(True)
        self.remove.setToolTip("Delete this mask (right-click: Duplicate)")
        self.folder = QLabel()
        self.folder.setStyleSheet("color: gray;")
        self.thumb = QLabel()  # this mask on one frame, as written (p123)
        self.thumb.setFixedSize(THUMB + 2, THUMB // 2 + 2)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setVisible(False)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.on)
        top.addWidget(self.name)
        top.addWidget(self.objects_btn, 1)
        top.addWidget(self.invert)
        top.addWidget(self.remove)
        lay = QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.folder)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 2)
        outer.addLayout(lay, 1)
        outer.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignTop)
        self.folder.setContentsMargins(self.on.sizeHint().width() + 6, 0, 0, 0)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.on.toggled.connect(lambda _on: self.changed.emit())
        self.name.textChanged.connect(lambda _t: self.changed.emit())
        self.picker.changed.connect(self._objects_changed)
        self.invert.toggled.connect(self._invert_changed)
        self.remove.clicked.connect(lambda: self.removed.emit(self))
        self._objects_changed(emit=False)

    def _menu(self, pos) -> None:
        m = QMenu(self)
        m.addAction("Duplicate", lambda: self.duplicated.emit(self))
        d = m.addAction("Delete", lambda: self.removed.emit(self))
        d.setEnabled(self.remove.isEnabled())
        m.exec(self.mapToGlobal(pos))

    def _objects_changed(self, emit: bool = True) -> None:
        self.objects_btn.setText(self.picker.text())
        if emit:
            self.changed.emit()

    def _invert_changed(self, _on: bool) -> None:
        self._invert_set = True
        self.changed.emit()

    def set_default_invert(self, black: bool) -> None:
        """The trainer preset's colours, until the user changes this bar's Invert (C-6)."""
        if not self._invert_set and self.invert.isChecked() != black:
            self.invert.blockSignals(True)
            self.invert.setChecked(black)
            self.invert.blockSignals(False)

    def set_thumb(self, mask: Optional[np.ndarray], frame: str) -> None:
        """*mask* (uint8, 0 / 255) as this bar writes it on *frame*; None: no preview."""
        self.thumb.setVisible(mask is not None)
        if mask is None:
            return
        h, w = mask.shape
        img = QImage(np.ascontiguousarray(mask).data, w, h, w, QImage.Format.Format_Grayscale8).copy()
        self.thumb.setPixmap(QPixmap.fromImage(img))
        self.thumb.setStyleSheet("border: 1px solid #888;")
        self.thumb.setToolTip(f"This mask on {frame}, as written (Objects, ⇆ and Invert applied)")

    def bar(self) -> MaskBar:
        return MaskBar(self.name.text().strip(), self.picker.ids(),
                       self.invert.isChecked() if self._invert_set else None, self.picker.flipped(),
                       self.on.isChecked())


def _first_sentence(text: str) -> str:
    """Up to the first full stop that ends a sentence (not one inside a name like a.png)."""
    for i, ch in enumerate(text):
        if ch == "." and (i + 1 == len(text) or text[i + 1] == " "):
            return text[:i + 1]
    return text


THUMB = 96  # the bars' mask previews: this wide at most (a 2:1 frame: 96 x 48)

# what a bar's Objects cover on the preview frame: (ids or None, flipped) -> bool mask, None = nothing there
BarPreview = Callable[[Optional[Tuple[int, ...]], Tuple[int, ...]], Optional[np.ndarray]]


class ExportDialog(QDialog):
    """Final Mask PNG export options.

    For a COLMAP scene a trainer preset (docs/specs/07-export-presets.md) fixes the
    folder (the scene's masks/), the names and the colors; "Custom" leaves them free.
    What: masks as bars (plan Export 9), one folder each: one bar writes the folder, more bars write
    ``<folder>_<name>`` (an empty name: the folder itself); each bar has its Objects (⇆: one inverted) and Invert.
    """

    _open = {"note": False, "views": False}  # More / Edit, kept open for the next window (C-2)

    PATTERNS = (
        ("{stem}.png  (frame_001.png)", "{stem}.png"),
        ("{name}.png  (COLMAP: frame_001.jpg.png)", "{name}.png"),
    )

    def __init__(self, default_dir: Path, parent=None, check: Optional[Callable[..., ExportCheck]] = None,
                 scene=None, target: str = CUSTOM, bars: Optional[Sequence[MaskBar]] = None,
                 objects: Optional[Sequence[Tuple[int, str, bool]]] = None,
                 excluded: int = 0, sky: bool = False, sky_edges: bool = True,
                 preview: Optional[BarPreview] = None, preview_frame: str = "",
                 preview_size: Tuple[int, int] = (THUMB // 2, THUMB)):
        super().__init__(parent)
        self.setWindowTitle("Export Final Masks")
        self._preview = preview  # p123: each bar's mask on one frame, as it would be written
        self._preview_frame = preview_frame
        self._preview_size = preview_size  # (h, w)
        self._preview_cache: dict = {}
        self.goto: Optional[str] = None  # an image picked in the check list: leave and open it
        self.setMinimumWidth(540)
        self._check = check
        self._scene = scene
        self._custom_dir = str(default_dir)
        self.target = QComboBox()
        modelled = scene is not None and scene.model_dir is not None  # a rig without a model: no trainer presets
        for p in PRESETS if modelled else (RIG,) if scene is not None else ():
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
        # the masks to write, as bars (plan Export 9)
        self._objects = list(objects or ())
        self._bar_rows: List[_BarRow] = []
        self._bars_lay = QVBoxLayout()
        self._bars_lay.setSpacing(2)
        self.add_bar_btn = QPushButton("+ Add mask")
        self.add_bar_btn.setFlat(True)
        self.add_bar_btn.setToolTip("Another mask, in its own folder <folder>_<name>: the Objects checked now")
        self.add_bar_btn.clicked.connect(self._new_bar)
        self.name_problem = ""
        for b in (tuple(bars) if bars else (MaskBar(),)):
            self._add_row(b)
        self.folders = QLabel()
        self.folders.setWordWrap(True)
        self.folders.setStyleSheet("color: gray;")
        # where a preset writes: into the scene, or a new dataset (images linked, model filtered)
        self._excluded = excluded
        self.to_scene = QRadioButton("Into the scene" if modelled else "Into the dataset")
        self.to_new = QRadioButton("New dataset")
        self.to_scene.setChecked(True)
        self.dataset = QLineEdit(str(scene.root.parent / f"{scene.root.name}_dataset") if scene is not None else "")
        self.dataset.setToolTip("A new folder: images/ (hard links, no extra space on the same drive), "
                                + ("sparse/0/ without the ⊘ frames, and the masks" if modelled
                                   else "and the masks, without the ⊘ frames (no model to carry over)"))
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
            self.convert.addItem(f"Pinhole views from camera pairs ({len(self._groups)} moments)", "pairs")
            self.convert.setItemData(self.convert.count() - 1,
                                     "Each moment (both lenses) as one sphere, laid out like a 360 image; every view "
                                     "taken straight from the lenses (one resampling), joined where it spans both",
                                     Qt.ItemDataRole.ToolTipRole)
        self.convert.setToolTip("Pinhole views: every image becomes perspective views (images, masks, model). "
                                "360: one equirectangular image each (a fisheye's unseen part is masked out)")
        self.yaws = QLineEdit("0, 90, 180, 270" if self._erp else "-45, 0, 45" if fisheye else "0")
        self.yaws.setToolTip("Left / right angles in degrees (right is positive), one view each per pitch")
        self.pitches = QLineEdit("-35, 0, 35" if self._erp or fisheye else "0")
        self.pitches.setToolTip("Up / down angles in degrees (up is positive), one row of views each")
        # the usual view layouts (docs/specs/08 P4) for a whole sphere (360), a fisheye lens's own (export plan 10,
        # C-9), or the grid below (Custom); none for a plain pinhole source (undistorted: its grid)
        self._fisheye = fisheye
        self._layout_kind: Optional[str] = None
        self._layout_pick: dict = {}  # the layout last picked for each list
        self.view_layout = QComboBox()
        self.view_layout.setToolTip("Where the pinhole views look (a layout, not a camera model). No layout has been shown "
                                    "to train better; more views = more coverage / overlap and more images")
        # what the layout is for, how many views and how much they overlap, and a map of them
        self.layout_note = QLabel("")
        self.layout_note.setWordWrap(True)
        self.layout_note.setStyleSheet("color: gray;")
        self.view_preview = ViewPreview()
        self.rig_preview = RigPreview()  # the same views as cameras in 3D (p124)
        self._source = "360" if self._erp else "fisheye" if fisheye else "pinhole"
        self._cameras = []
        if modelled and not self._erp:  # a fisheye's views are checked against its lens
            try:
                self._cameras = [c for c in read_cameras_full(scene.model_dir).values() if c.model in FISHEYES]
            except (OSError, ValueError):
                self._cameras = []
        self._fill_layouts("pinhole")
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
        crow.addWidget(self.views_edit)
        self._views_line = QWidget()  # in a box: a form row sizes a word-wrapped label by its narrow size hint
        sl = QVBoxLayout(self._views_line)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.views_summary)
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
        pics = QHBoxLayout()
        pics.setContentsMargins(0, 0, 0, 0)
        pics.addWidget(self.view_preview, 1)
        pics.addWidget(self.rig_preview)
        vb.addLayout(pics)
        # the files: fields for Custom, the preset's values as text for a preset
        self.out = QLineEdit(str(default_dir))
        self.out_fixed = _PathLabel()
        self.pattern = QComboBox()
        for label, _ in self.PATTERNS:
            self.pattern.addItem(label)
        self.names_fixed = QLabel()
        self.names_fixed.setWordWrap(True)
        self.empty = QCheckBox("Also empty masks")
        self.empty.setToolTip("Also write a mask for the images without Objects (all white: nothing ignored there)")
        self._colours = QWidget()
        cl = QHBoxLayout(self._colours)
        cl.setContentsMargins(0, 0, 0, 0)
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
        if objects is not None:
            what = QVBoxLayout()
            what.addLayout(self._bars_lay)
            add = QHBoxLayout()
            add.addWidget(self.add_bar_btn)
            add.addStretch(1)
            what.addLayout(add)
            main.addWidget(_section(f"{next(number)}  What", what))
        if scene is not None:
            self._where_form = QFormLayout()
            self._where_form.addRow("For", self.target)
            self._where_form.addRow(self._note_box)
            self._where_form.addRow("Output", self._out_row)
            self._where_form.addRow("Dataset", self._dataset_row)
            self._where_form.addRow("Cameras", self._cam_row)
            self._where_form.addRow(self._views_line)
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
        self.out.textChanged.connect(lambda _t: self._run_check())
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

    # --- the masks, as bars --------------------------------------------------------------------------

    def _add_row(self, bar: MaskBar, at: Optional[int] = None) -> _BarRow:
        row = _BarRow(bar, self._objects)
        row.changed.connect(self._run_check)
        row.removed.connect(self._remove_row)
        row.duplicated.connect(self._duplicate_row)
        at = len(self._bar_rows) if at is None else at
        self._bar_rows.insert(at, row)
        self._bars_lay.insertWidget(at, row)
        return row

    def _free_name(self, start: str) -> str:
        used = {r.name.text().strip() for r in self._bar_rows}
        n = 2
        name = start
        while name in used:
            name, n = f"{start}{n}", n + 1
        return name

    def _new_bar(self) -> None:
        ids = tuple(oid for oid, _n, inc in self._objects if inc)
        self._add_row(MaskBar(self._free_name("set"), ids))
        self._after_bars_changed()

    def _duplicate_row(self, row: _BarRow) -> None:
        b = row.bar()
        self._add_row(MaskBar(self._free_name(f"{b.name or 'set'}_copy"), b.ids, b.invert, b.flipped, b.on),
                      self._bar_rows.index(row) + 1)
        self._after_bars_changed()

    def _remove_row(self, row: _BarRow) -> None:
        if len(self._bar_rows) < 2:
            return
        self._bar_rows.remove(row)
        self._bars_lay.removeWidget(row)
        row.deleteLater()
        self._after_bars_changed()

    def _after_bars_changed(self) -> None:
        self._run_check()
        if self.layout() is not None:
            QTimer.singleShot(0, lambda: self._fit_height(True))

    def bars(self) -> Tuple[MaskBar, ...]:
        """The bars as they are now (saved with the scene when the window closes, C-4)."""
        return tuple(r.bar() for r in self._bar_rows)

    def _on_rows(self) -> List[_BarRow]:
        """The bars the Export writes (one bar: always it)."""
        if len(self._bar_rows) == 1:
            return list(self._bar_rows)
        return [r for r in self._bar_rows if r.on.isChecked()]

    def _bar_folder(self, row: _BarRow) -> Path:
        base = Path(self.out.text().strip())
        name = row.name.text().strip()
        if len(self._bar_rows) == 1 or not name:
            return base
        return base.parent / f"{base.name}_{name}"

    def _refresh_bars(self) -> None:
        """Names on / off (C-7), colours from the preset (C-6), folders, name problems."""
        one = len(self._bar_rows) == 1
        p = self.preset()
        black = p.object_black if p is not None else False
        folders: dict = {}
        for r in self._bar_rows:
            folders.setdefault(self._bar_folder(r), []).append(r)
        problems = []
        for r in self._bar_rows:
            r.name.setEnabled(not one)
            r.remove.setEnabled(not one)
            r.on.setVisible(not one)
            r.set_default_invert(black)
            name = r.name.text().strip()
            bad = ""
            if not one and any(ch in name for ch in BAD_NAME):
                bad = f"“{name}” cannot be a folder name"
            elif not one and len(folders[self._bar_folder(r)]) > 1:
                bad = f"two masks go to {self._bar_folder(r).name}/: give them other names"
            r.name.setStyleSheet("border: 1px solid #d03030;" if bad else "")
            if bad and bad not in problems:
                problems.append(bad)
            inv = r.invert.isChecked()
            r.folder.setText(f"→ {self._bar_folder(r).name}/ · Objects {'black' if inv else 'white'}"
                             + ("" if one or r.on.isChecked() else " · off"))
            r.set_thumb(self._bar_preview(r.bar()), self._preview_frame)
        self.name_problem = "; ".join(problems)

    def _bar_preview(self, b: MaskBar) -> Optional[np.ndarray]:
        """The bar's mask on the preview frame as it is written: Objects white, black with Invert (0 / 255)."""
        if self._preview is None:
            return None
        key = (b.ids, tuple(sorted(b.flipped)))
        if key not in self._preview_cache:
            m = self._preview(b.ids, key[1])
            self._preview_cache[key] = (m if m is not None else np.zeros(self._preview_size, bool)).astype(np.uint8) * 255
        out = self._preview_cache[key]
        return 255 - out if b.invert or (b.invert is None and self._default_black()) else out

    def _default_black(self) -> bool:
        p = self.preset()
        return p.object_black if p is not None else False

    def dataset_root(self) -> Optional[Path]:
        """The new dataset's folder, or None when writing into the scene (or not a preset)."""
        if self.preset() is None or self._scene is None or not self.to_new.isChecked():
            return None
        text = self.dataset.text().strip()
        return Path(text) if text else None

    def _layouts(self, kind) -> dict:
        """The layouts listed for a conversion: a 360 source's (the whole sphere), a fisheye's (its lens)."""
        if kind == "pairs":  # a rig's moment covers the whole sphere
            return VIEW_LAYOUTS
        if kind != "pinhole":
            return {}
        return VIEW_LAYOUTS if self._erp else FISHEYE_LAYOUTS if self._fisheye else {}

    def _fill_layouts(self, kind) -> None:
        """The Layout list for *kind*, the one picked there last time chosen again (else its first)."""
        layouts = self._layouts(kind)
        if kind == self._layout_kind and self.view_layout.count():
            return
        if self._layout_kind is not None and self.view_layout.count():
            self._layout_pick[self._layout_kind] = self.view_layout.currentData()
        self._layout_kind = kind
        self.view_layout.blockSignals(True)
        self.view_layout.clear()
        for key, lay in layouts.items():
            self.view_layout.addItem(lay.label, key)
            self.view_layout.setItemData(self.view_layout.count() - 1, lay.purpose, Qt.ItemDataRole.ToolTipRole)
        self.view_layout.addItem("Custom", None)
        self.view_layout.setItemData(self.view_layout.count() - 1,
                                     "The yaw × pitch grid typed below: for a special rig or an experiment",
                                     Qt.ItemDataRole.ToolTipRole)
        i = self.view_layout.findData(self._layout_pick.get(kind, next(iter(layouts), None)))
        self.view_layout.setCurrentIndex(max(i, 0))
        self.view_layout.blockSignals(False)

    def _layout_key(self) -> Optional[str]:
        """The picked layout, None for the typed grid (Custom, or a source without layouts)."""
        if not self._layouts(self._layout_kind):
            return None
        return self.view_layout.currentData()

    def _kept_views(self, v: Views) -> int:
        """The views made per image: all of them, less a fisheye's views its lens cannot fill."""
        if not self._cameras or self._layout_kind == "pairs":
            return len(v.pairs())
        return sum(all(view_share(c, y, p, v.fov) >= MIN_VIEW_SHARE for c in self._cameras) for y, p in v.pairs())

    def _show_layout(self, on: bool) -> None:
        """The layout's purpose, its view count and overlap, and the map of the views (docs/specs/08 P4)."""
        self.layout_note.setVisible(on)
        self.view_preview.setVisible(on)
        self.rig_preview.setVisible(on)
        if not on:
            return
        v = Views(fov=float(self.fov.value()))
        key = self._layout_key()
        pairs = ALL_LAYOUTS[key].pairs() if key is not None else None
        if pairs is None:  # the typed grid
            def angles(field):
                try:
                    return tuple(float(t) for t in field.text().replace(";", ",").split(",") if t.strip())
                except ValueError:
                    return ()
            pairs = Views(yaws=angles(self.yaws) or (0.0,), pitches=angles(self.pitches) or (0.0,)).pairs()
        fov = v.fov
        lens = self._cameras if self._layout_kind == "pinhole" else []  # a rig's pair sees the whole sphere
        kept = [all(view_share(c, y, p, fov) >= MIN_VIEW_SHARE for c in lens) if lens else True for y, p in pairs]
        per = "moment" if self._layout_kind == "pairs" else "image"
        self.view_preview.set_views(pairs, fov, kept)
        self.rig_preview.set_views(pairs, fov, kept, "pairs" if self._layout_kind == "pairs" else self._source)
        if key is not None:
            lay = ALL_LAYOUTS[key]
            side, rings = lay.overlap(fov)
            ov = f"sideways {side:+.0f}°" + (f", between rings {rings:+.0f}°" if rings is not None else "")
            self.layout_note.setText(f"{lay.purpose}<br><b>{lay.count} views</b> per {per} at {fov:.0f}° · overlap {ov}")
        else:
            dropped = kept.count(False)
            self.layout_note.setText(
                f"<b>{kept.count(True)} views</b> per {per} at {fov:.0f}°"
                + (f" · {dropped} left out: the fisheye cannot fill them (gray)" if dropped else "")
                + ("" if lens else " · Custom: yaw × pitch as typed"))

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

        key = self._layout_key()
        if key is not None:
            v = Views(fov=float(self.fov.value()), size=self.side.value(), layout=ALL_LAYOUTS[key])
        else:
            v = Views(yaws=angles(self.yaws) or (0.0,), pitches=angles(self.pitches) or (0.0,),
                      fov=float(self.fov.value()), size=self.side.value())
        return Stitch(views=v) if kind == "pairs" else v

    def _pick_dataset(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "New dataset folder (an empty one)", self.dataset.text())
        if d:
            self.dataset.setText(d)

    def _show_folders(self) -> None:
        """A trainer reads one folder: say so when a mask goes to another one."""
        p = self.preset()
        base = Path(self.out.text().strip())
        other = [self._bar_folder(r).name for r in self._on_rows() if self._bar_folder(r) != base]
        if p is None or not other:
            self.folders.setText("")
            self._files_form.setRowVisible(self.folders, False)
            return
        self._files_form.setRowVisible(self.folders, True)
        self.folders.setText(f"{p.label} reads {p.folder}/ only: to train with "
                             + (f"{other[0]}/, rename it" if len(other) == 1
                                else f"one of {', '.join(o + '/' for o in other)}, rename that one")
                             + f" to {p.folder}/")

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
        for w in (self.out, self.pattern, self.empty):
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
            self.views_edit.setVisible(kind is not None)
            wf.setRowVisible(self._views_box, kind is not None and self._open["views"])
        self.views_edit.blockSignals(True)
        self.views_edit.setChecked(self._open["views"])
        self.views_edit.blockSignals(False)
        self.views_edit.setText("Hide ▴" if self._open["views"] else "Edit ▸")
        vf = self._views_form
        self._fill_layouts(kind)
        pin = kind in ("pinhole", "pairs")
        lists = pin and bool(self._layouts(kind))
        grid = pin and self._layout_key() is None
        vf.setRowVisible(self.view_layout, lists)
        vf.setRowVisible(self.yaws, grid)
        vf.setRowVisible(self.pitches, grid)
        vf.setRowVisible(self.fov, pin)
        vf.setRowVisible(self.side, kind is not None)
        self._show_layout(pin)
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
            self.empty.setChecked(p.every_image)
            self.names_fixed.setText(pattern + (" · every image" if p.every_image else " · images with a mask")
                                     + (" (as the masks there)" if follows else ""))
            self.note.setText(f"{p.note} {follows}Masks already there for these images (a.png or a.jpg.png) are "
                              f"moved to {p.folder}_backup_<time>/ first. Checked against: {p.verified}.")
            head = _first_sentence(p.note)
            self.note_head.setText(head)
            opened = self._open["note"] or not p.confirmed  # rules not confirmed: all of it, from the start
            self.note_head.setVisible(not opened)
            self.note.setVisible(opened)
            self.note_more.setVisible(p.confirmed)
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
        v = v.views if isinstance(v, Stitch) else v
        key = self._layout_key()
        where = (ALL_LAYOUTS[key].label if key is not None
                 else f"Yaw {self.yaws.text().strip()} · Pitch {self.pitches.text().strip()}")
        n = self._kept_views(v)
        per = "moment" if kind == "pairs" else "image"
        return f"{where} · FOV {self.fov.value()}° · Size {side} → <b>{n} view{'s' if n != 1 else ''}</b> per {per}"

    def _scene_style(self, p) -> Optional[str]:
        """Into the scene, for a trainer that reads either naming: how the masks there are named."""
        if not p.either_name or self._scene is None or self.dataset_root() is not None or self._check is None:
            return None
        return existing_style(self._scene.root / p.folder, self._check(p.pattern).keys)

    def _check_bar(self, pattern: str, b: MaskBar) -> ExportCheck:
        if b.flipped:
            return self._check(pattern, None if b.ids is None else list(b.ids), list(b.flipped))
        return self._check(pattern) if b.ids is None else self._check(pattern, list(b.ids))

    def _written(self, c: ExportCheck) -> int:
        """The files one mask writes."""
        written = len(c.with_mask) + len(c.empty) + (len(c.without_mask) if self.empty.isChecked() else 0)
        if self.dataset_root() is not None and self.empty.isChecked():
            written = c.images - self._excluded  # a new dataset holds the kept frames only
        v = self.views()
        if isinstance(v, Views):
            written *= self._kept_views(v)  # one mask per view (a fisheye's unfillable views are not made)
        elif isinstance(v, Stitch):  # one mask per moment, or per view of it (a moment with a ⊘ image is left out)
            written = len(self._groups) * (len(v.views.pairs()) if v.views is not None else 1)
        return written

    def _run_check(self) -> None:
        self._refresh_bars()
        self._show_folders()
        rows_on = self._on_rows()
        if self._check is None or not rows_on:
            if not rows_on:
                self.summary.setText("No mask is on: tick one above")
                self.problems.clear()
                self.problems.setVisible(False)
            self._set_button(None if rows_on else 0)
            return
        pattern = self.PATTERNS[self.pattern.currentIndex()][1]
        results = [(r, self._check_bar(pattern, r.bar())) for r in rows_on]
        results = [(r, c, self._written(c)) for r, c in results]
        c = results[0][1]
        self.check_result = c
        total = sum(w for _r, _c, w in results)

        def line(ok: bool, text: str) -> str:
            color = "#2a8a2a" if ok else "#d78200"
            return f"<span style='color: {color}'>{'✓' if ok else '⚠'}</span> {text}"

        many = len(results) > 1
        rows = [f"<b>{total:,}</b> file(s) will be written" + (f" in <b>{len(results)}</b> folders" if many else "")
                + f" for <b>{c.images:,}</b> image(s)"]
        if not many:
            missing = len(c.without_mask)
            rows += [
                line(missing == 0 or self.empty.isChecked(), f"Images without a mask: {missing}"
                     + ("" if missing == 0 else " (written all white: nothing ignored there)" if self.empty.isChecked()
                        else " (no file — see “Also write empty masks”)")),
                line(not c.empty, f"Empty masks: {len(c.empty)}"),
                line(not c.warning, f"Suspicious / failed frames (⚠ ✕): {len(c.warning)}"),
                line(not c.clashes, "File names: " + ("OK" if not c.clashes else f"{len(c.clashes)} clash(es)")),
            ]
        else:
            for r, cb, w in results:
                issues = [f"{len(cb.without_mask)} without a mask" for _ in (1,)
                          if cb.without_mask and not self.empty.isChecked()]
                issues += [f"{len(cb.empty)} empty" for _ in (1,) if cb.empty]
                issues += [f"{len(cb.warning)} ⚠ ✕" for _ in (1,) if cb.warning]
                issues += [f"{len(cb.clashes)} name clash(es)" for _ in (1,) if cb.clashes]
                rows.append(line(not issues, f"{self._bar_folder(r).name}/: {w:,} file(s)"
                                 + "".join(f" · {i}" for i in issues)))
        p = self.preset()
        if p is not None:  # a bar's colours against the trainer's (C-6): said, not changed
            for r, _c, _w in results:
                if r.invert.isChecked() != p.object_black:
                    mine = "black" if r.invert.isChecked() else "white"
                    rows.append(line(False, f"{self._bar_folder(r).name}/: Objects {mine} — {p.label} ignores the "
                                            f"{'black' if p.object_black else 'white'} parts, so these Objects are "
                                            "trained and the rest ignored"))
        if self.name_problem:
            rows.append(line(False, self.name_problem))
        rows += self._scene_rows(line)
        self.summary.setText("<br>".join(rows))
        self.problems.clear()
        found: dict = {}
        for r, cb, _w in results:
            reasons = (
                (set() if self.empty.isChecked() else set(cb.without_mask), "no mask → no file"),
                (set(cb.empty), "empty mask"),
                (set(cb.warning), "suspicious or failed (⚠ ✕)"),
                ({k for ks in cb.clashes for k in ks}, "file name clash"),
            )
            where = f"{self._bar_folder(r).name}/: " if many else ""
            for k in cb.problems:
                why = ", ".join(t for ks, t in reasons if k in ks)
                if why:  # only "no mask", and those are written all white: not listed
                    found.setdefault(k, []).append(where + why)
        index = {k: i for i, k in enumerate(c.keys)}
        for k in sorted(found, key=lambda k: index.get(k, 0)):
            self.problems.addItem(f"{index.get(k, 0) + 1}  {k}  —  {'; '.join(found[k])}")
            self.problems.item(self.problems.count() - 1).setData(Qt.ItemDataRole.UserRole, k)
        self.problems.setVisible(self.problems.count() > 0)
        self._set_button(total)
        if self.layout() is not None:
            QTimer.singleShot(0, self._fit_height)  # the summary may have more lines now

    def _set_button(self, written: Optional[int]) -> None:
        """Export N files → where (EX-12); nothing to write or a bad name: off."""
        rows = self._on_rows()
        root = self.dataset_root()
        to = (f"{len(rows)} folders" if len(rows) > 1
              else "new dataset" if root is not None
              else f"{self._bar_folder(rows[0]).name}/" if rows else "")
        count = "" if written is None else f" {written:,} file{'s' if written != 1 else ''}"
        self.export_btn.setText(f"Export{count} → {to}" if rows else "Export")
        self.export_btn.setEnabled(written != 0 and bool(rows) and not self.name_problem)

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
            what = (f"{len(self._groups)} moment(s) × {len(v.views.pairs())} pinhole views ({v.views.fov:.0f}°) "
                    "from camera pairs" if isinstance(v, Stitch) and v.views is not None
                    else f"{len(self._groups)} 360 image(s) stitched from camera pairs" if isinstance(v, Stitch)
                    else "one 360 image each" if isinstance(v, Erp)
                    else f"{self._kept_views(v)} pinhole views per image ({v.fov:.0f}°)" if v is not None
                    else "images/ linked, sparse/0/ filtered" if sc.model_dir is not None
                    else "images/ linked (no model)")
            rows.append(line(not why, why or f"New dataset: {root.name}/ — {what}"
                                              + (f", {self._excluded} ⊘ frame(s) left out" if self._excluded else "")))
        elif self._excluded:
            rows.append(line(False, f"{self._excluded} frame(s) are ⊘ excluded: that only applies to a New dataset"))
        odd = [m for m in sc.camera_models if m in p.unconfirmed_cameras]
        if self.views() is not None:
            v = self.views()
            to = ("EQUIRECTANGULAR (360)" if isinstance(v, Erp) or isinstance(v, Stitch) and v.views is None
                  else "PINHOLE views")
            rows.append(line(True, f"Cameras: {', '.join(sc.camera_models)} → {to}"))
        elif sc.camera_models:
            rows.append(line(not odd, "Cameras: " + ", ".join(sc.camera_models)
                             + (f" ({', '.join(odd)}: not confirmed for {p.label})" if odd else "")))
        c = getattr(self, "check_result", None)
        for out in dict.fromkeys(self._bar_folder(r) for r in self._on_rows()):
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
        """One export per bar that is on, each in its own folder."""
        jobs = []
        for r in self._on_rows():
            b = r.bar()
            jobs.append(ExportOptions(
                out_dir=self._bar_folder(r),
                name_pattern=self.PATTERNS[self.pattern.currentIndex()][1],
                invert=r.invert.isChecked(),
                include_empty=self.empty.isChecked(),
                backup=self.preset() is not None,
                object_ids=None if b.ids is None else list(b.ids),
                flipped=list(b.flipped),
                sky_edges=not self.sky_edges.isHidden() and self.sky_edges.isChecked(),
            ))
        return jobs

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
        ("Middle click (or double click) an image", "Open it, the picked images stay picked · Right click: what to do with the picks"),
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
