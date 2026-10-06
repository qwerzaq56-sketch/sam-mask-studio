"""File > Batch Masking with Presets: the command line's ``probe`` and ``run`` (src/cli.py,
src/batchmask/) in a window.

Not part of the editing itself: it masks a whole folder the way the batch tool will, in a separate process
(``python -m src.cli``), so what it makes here is what the batch makes. The window only edits a preset's
settings, runs the command and shows its output and contact sheets. Masks already in the scene stop a run
before anything is written.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Callable, List, Optional

from PyQt6.QtCore import QProcess, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.batchmask.presets import (LensStep, MaskPreset, PersonStep, SkyStep, find_preset, list_presets, save_preset,
                                   split, user_dir)

ROOT = Path(__file__).resolve().parents[2]


def _browse(edit: QLineEdit, parent: QWidget, title: str) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(edit, 1)
    b = QPushButton("…")
    b.setFixedWidth(30)

    def pick():
        d = QFileDialog.getExistingDirectory(parent, title, edit.text() or str(Path.home()))
        if d:
            edit.setText(d)

    b.clicked.connect(pick)
    lay.addWidget(b)
    return w


class BatchMaskDialog(QDialog):
    """*images*: the folder to mask; *scene*: where ``masks/`` and ``sky_masks/`` go. *free_models*: unloads
    the main window's SAM models (they would hold the GPU memory the batch needs)."""

    def __init__(self, images: Optional[Path] = None, scene: Optional[Path] = None,
                 free_models: Optional[Callable[[], bool]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Masking with Presets")
        self.resize(1100, 760)
        self.free_models = free_models
        self.proc: Optional[QProcess] = None
        self._tmp = Path(tempfile.mkdtemp(prefix="sms_batch_"))
        self._probe_out: Optional[Path] = None

        left = QWidget()
        form = QVBoxLayout(left)

        top = QFormLayout()
        self.images = QLineEdit(str(images) if images else "")
        self.scene = QLineEdit(str(scene) if scene else "")
        top.addRow("Images", _browse(self.images, self, "Image folder"))
        self.recursive = QCheckBox("Sub-folders too (cam0/, cam1/), kept in the output")
        self.recursive.setChecked(images is not None and Path(images).is_dir()
                                  and any(p.is_dir() for p in Path(images).iterdir()))
        top.addRow("", self.recursive)
        top.addRow("Scene (output)", _browse(self.scene, self, "Scene folder: masks/ and sky_masks/ go in it"))
        form.addLayout(top)

        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.setToolTip("Built-in presets ship with the app; yours are in " + str(user_dir()))
        row.addWidget(QLabel("Preset"))
        row.addWidget(self.preset, 1)
        self.save_btn = QPushButton("Save as Preset…")
        self.save_btn.setToolTip("These settings as a preset of your own (the built-in ones stay as shipped)")
        self.save_btn.clicked.connect(self.save_as)
        row.addWidget(self.save_btn)
        form.addLayout(row)
        self.about = QLabel()
        self.about.setWordWrap(True)
        self.about.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addWidget(self.about)

        # people
        self.person_box = QGroupBox("People and what they carry (SAM3 prompts, GPU)")
        self.person_box.setCheckable(True)
        pf = QFormLayout(self.person_box)
        self.labels = QLineEdit()
        self.labels.setToolTip("Always masked. ';'-separated SAM3 text prompts. The words that find one rig's "
                               "selfie stick may not find another's: try them first")
        self.attach = QLineEdit()
        self.attach.setToolTip("Masked only where they touch the above (a worn bag, not one on a bench)")
        self.also = QLineEdit()
        self.also.setPlaceholderText("e.g. selfie stick; tripod; backpack")
        self.also.setToolTip("Try only: measured and outlined on the contact sheets, not put in the mask")
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.05, 0.95)
        self.threshold.setSingleStep(0.05)
        self.grow = QSpinBox()
        self.grow.setRange(0, 32)
        self.grow.setSuffix(" px at 1024")
        pf.addRow("Mask", self.labels)
        pf.addRow("Mask if touching", self.attach)
        pf.addRow("Also try", self.also)
        pf.addRow("Score at least", self.threshold)
        pf.addRow("Grow", self.grow)
        form.addWidget(self.person_box)

        self.lens_box = QGroupBox("Fisheye lens edge")
        self.lens_box.setCheckable(True)
        lf = QFormLayout(self.lens_box)
        self.margin = QDoubleSpinBox()
        self.margin.setRange(0, 20)
        self.margin.setSingleStep(0.5)
        self.margin.setSuffix(" % of the radius")
        self.radius = QDoubleSpinBox()
        self.radius.setRange(0, 200)
        self.radius.setSpecialValueText("found per camera folder")
        self.radius.setSuffix(" %")
        lf.addRow("Rim margin", self.margin)
        lf.addRow("Circle radius", self.radius)
        form.addWidget(self.lens_box)

        self.sky_box = QGroupBox("Sky (sky_masks/, white = sky)")
        self.sky_box.setCheckable(True)
        sf = QFormLayout(self.sky_box)
        self.sky_threshold = QDoubleSpinBox()
        self.sky_threshold.setRange(1, 99)
        self.sky_threshold.setSuffix(" %")
        self.sky_edges = QCheckBox("Edges at full resolution")
        sf.addRow("Threshold", self.sky_threshold)
        sf.addRow("", self.sky_edges)
        form.addWidget(self.sky_box)

        probe = QGroupBox("Try the prompts first")
        tf = QFormLayout(probe)
        self.frames = QSpinBox()
        self.frames.setRange(1, 64)
        self.frames.setValue(8)
        self.frames.setSuffix(" per camera folder")
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("optional: masks/ checked by hand (black = people)")
        self.inside = QSpinBox()
        self.inside.setRange(0, 100)
        self.inside.setValue(0)
        self.inside.setSpecialValueText("whole image")
        self.inside.setSuffix(" % circle")
        self.inside.setToolTip("Compare with the reference only inside this circle, when the reference also "
                               "blacks out the lens edge (90 for a fisheye)")
        tf.addRow("Frames", self.frames)
        tf.addRow("Reference", _browse(self.reference, self, "Masks checked by hand"))
        tf.addRow("Compare inside", self.inside)
        form.addWidget(probe)

        self.free = QCheckBox("Unload this window's SAM models first (frees the GPU; they load again later)")
        self.free.setChecked(free_models is not None)
        self.free.setVisible(free_models is not None)
        form.addWidget(self.free)
        self.existing = QComboBox()
        self.existing.addItem("Stop if masks are already there", "stop")
        self.existing.addItem("Keep masks already there, make the rest", "skip")
        form.addWidget(self.existing)
        buttons = QHBoxLayout()
        self.try_btn = QPushButton("Try Prompts")
        self.try_btn.setToolTip("SAM3 on a few frames: a table of what each prompt finds and contact sheets")
        self.try_btn.clicked.connect(self.try_prompts)
        self.run_btn = QPushButton("Run on the Folder")
        self.run_btn.clicked.connect(self.run)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop)
        self.cmd_btn = QPushButton("Copy Command")
        self.cmd_btn.setToolTip("The run as a command line, for the batch tool (with the preset saved first)")
        self.cmd_btn.clicked.connect(self.copy_command)
        for b in (self.try_btn, self.run_btn, self.stop_btn, self.cmd_btn):
            buttons.addWidget(b)
        form.addLayout(buttons)
        form.addStretch(1)

        right = QSplitter(Qt.Orientation.Vertical)
        self.sheet = QLabel("Contact sheets of Try Prompts show here.")
        self.sheet.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sheet_scroll = QScrollArea()
        self.sheet_scroll.setWidget(self.sheet)
        self.sheet_scroll.setWidgetResizable(True)
        sheet_box = QWidget()
        sb = QVBoxLayout(sheet_box)
        sb.setContentsMargins(0, 0, 0, 0)
        self.sheet_pick = QComboBox()
        self.sheet_pick.currentIndexChanged.connect(self._show_sheet)
        sb.addWidget(self.sheet_pick)
        sb.addWidget(self.sheet_scroll, 1)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        f = self.output.font()
        f.setFamily("Consolas")
        self.output.setFont(f)
        right.addWidget(sheet_box)
        right.addWidget(self.output)
        right.setSizes([480, 260])

        split_ = QSplitter()
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        split_.addWidget(scroll)
        split_.addWidget(right)
        split_.setSizes([440, 660])
        outer = QVBoxLayout(self)
        outer.addWidget(split_)

        self.preset.currentIndexChanged.connect(self._load)
        self._fill_presets()
        self._busy(False)

    # --- presets -----------------------------------------------------------------------
    def _fill_presets(self, select: Optional[str] = None) -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        for p in list_presets():
            self.preset.addItem(p.name + ("" if p.builtin else "  (yours)"), p.name)
        self.preset.blockSignals(False)
        i = self.preset.findData(select) if select else 0
        self.preset.setCurrentIndex(max(i, 0))
        self._load()

    def _load(self) -> None:
        name = self.preset.currentData()
        if not name:
            return
        p = find_preset(name)
        checked = ("Checked on:<br>" + "<br>".join(p.checked_on)) if p.checked_on else \
            "<b>Not checked on any data yet</b>: try the prompts on your frames before a whole run."
        self.about.setText(f"<b>{p.title or p.name}</b><br>{p.description}<br><i>{checked}</i><br>"
                           "<small>Prompts that fit the data a preset was checked on may not fit other scenes or "
                           "rigs: Try Prompts on a few frames first.</small>")
        person, lens, sky = p.person or PersonStep(), p.lens or LensStep(), p.sky or SkyStep()
        self.person_box.setChecked(p.person is not None)
        self.labels.setText("; ".join(person.labels))
        self.attach.setText("; ".join(person.attach))
        self.threshold.setValue(person.threshold)
        self.grow.setValue(person.grow)
        self._person_rest = person
        self.lens_box.setChecked(p.lens is not None)
        self.margin.setValue(lens.margin)
        self.radius.setValue(lens.radius or 0.0)
        self._lens_rest = lens
        self.sky_box.setChecked(p.sky is not None)
        self.sky_threshold.setValue(sky.threshold)
        self.sky_edges.setChecked(sky.edges)
        self._sky_rest = sky

    def current(self) -> MaskPreset:
        """The preset as the window shows it (the chosen one, edited)."""
        base = find_preset(self.preset.currentData())
        person = lens = sky = None
        if self.person_box.isChecked():
            person = PersonStep(**dict(asdict(self._person_rest), labels=split(self.labels.text()),
                                       attach=split(self.attach.text()), threshold=round(self.threshold.value(), 3),
                                       grow=self.grow.value()))
        if self.lens_box.isChecked():
            lens = LensStep(**dict(asdict(self._lens_rest), margin=self.margin.value(),
                                   radius=self.radius.value() or None))
        if self.sky_box.isChecked():
            sky = SkyStep(**dict(asdict(self._sky_rest), threshold=self.sky_threshold.value(),
                                 edges=self.sky_edges.isChecked()))
        p = MaskPreset(name=base.name, title=base.title, description=base.description, checked_on=list(base.checked_on),
                       person=person, lens=lens, sky=sky)
        if p != base:  # edited: what the base was checked on is not this
            p.checked_on = []
        return p

    def save_as(self) -> Optional[Path]:
        p = self.current()
        name, ok = QInputDialog.getText(self, "Save as Preset", "Name (letters, digits, - _ .):",
                                        text=p.name if not find_preset(p.name).builtin else f"{p.name}-mine")
        if not ok or not name.strip():
            return None
        p.name = name.strip()
        note, ok = QInputDialog.getText(self, "Save as Preset", "Checked on (what, and the result; may be empty):",
                                        text="; ".join(p.checked_on))
        if ok:
            p.checked_on = [note.strip()] if note.strip() else []
        try:
            try:
                path = save_preset(p)
            except FileExistsError:
                if QMessageBox.question(self, "Save as Preset", f"Replace your preset {p.name}?") != \
                        QMessageBox.StandardButton.Yes:
                    return None
                path = save_preset(p, overwrite=True)
        except ValueError as e:
            QMessageBox.warning(self, "Save as Preset", str(e))
            return None
        self._say(f"Saved {path}")
        self._fill_presets(p.name)
        return path

    def _preset_file(self) -> Path:
        path = self._tmp / "preset.json"
        p = self.current()
        p.name = "window"
        path.write_text(json.dumps(p.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    # --- running ----------------------------------------------------------------------
    def _folders(self, scene: bool) -> Optional[List[str]]:
        images = Path(self.images.text().strip())
        if not images.is_dir():
            QMessageBox.warning(self, "Batch Masking", f"Not a folder: {images}")
            return None
        out = []
        if scene:
            s = self.scene.text().strip()
            if not s:
                QMessageBox.warning(self, "Batch Masking", "Choose the scene folder the masks go to.")
                return None
            out = ["--out", s]
        return [str(images)] + (["--recursive"] if self.recursive.isChecked() else []) + out

    def run_args(self) -> Optional[List[str]]:
        f = self._folders(True)
        if f is None:
            return None
        args = ["run", f[0], "--preset", str(self._preset_file())] + f[1:]
        if self.existing.currentData() == "skip":
            args.append("--skip-existing")
        return args

    def probe_args(self) -> Optional[List[str]]:
        if not self.person_box.isChecked():
            QMessageBox.information(self, "Try Prompts", "Turn on the people step: the prompts are what is tried.")
            return None
        f = self._folders(False)
        if f is None:
            return None
        self._probe_out = self._tmp / f"probe{len(list(self._tmp.glob('probe*'))) + 1}"
        args = ["probe", f[0], "--preset", str(self._preset_file()), "--out", str(self._probe_out),
                "--frames", str(self.frames.value())] + f[1:]
        if self.also.text().strip():
            args += ["--also", "; ".join(split(self.also.text()))]
        if self.reference.text().strip():
            args += ["--reference", self.reference.text().strip()]
            if self.inside.value():
                args += ["--inside", str(self.inside.value())]
        return args

    def try_prompts(self) -> None:
        args = self.probe_args()
        if args:
            self._start(args)

    def run(self) -> None:
        args = self.run_args()
        if args:
            self._start(args)

    def copy_command(self) -> None:
        f = self._folders(True)
        if f is None:
            return
        name = self.preset.currentData()
        p = self.current()
        if find_preset(name) != p:
            QMessageBox.information(self, "Copy Command", "The settings are changed: save them as a preset first, "
                                    "so the command can name it.")
            path = self.save_as()
            if path is None:
                return
            name = path.stem
        cmd = [sys.executable, "-m", "src.cli", "run", f[0], "--preset", name] + f[1:]
        text = " ".join(f'"{c}"' if " " in c else c for c in cmd)
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self._say(f"Copied (run it in {ROOT}):\n{text}")

    def _start(self, args: List[str]) -> None:
        if self.proc is not None:
            return
        uses_gpu = args[0] == "probe" or self.person_box.isChecked()
        if uses_gpu and self.free.isChecked() and self.free_models is not None and self.free_models():
            self._say("Unloaded this window's SAM models (they load again when the window closes).")
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(ROOT))
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(lambda code, _status, a=args[0]: self._finished(a, code))
        self._say("$ python -m src.cli " + " ".join(args))
        self.proc.start(sys.executable, ["-m", "src.cli", *args])
        self._busy(True)

    def _read(self) -> None:
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            if "[debug" in line or "[info " in line:  # the engine's own log lines
                continue
            self._say(line)

    def _finished(self, what: str, code: int) -> None:
        self._say(f"({what} ended, exit code {code})")
        self.proc = None
        self._busy(False)
        if what == "probe" and self._probe_out is not None:
            sheets = sorted(self._probe_out.glob("sheet_*.jpg"))
            self.sheet_pick.blockSignals(True)
            self.sheet_pick.clear()
            for s in sheets:
                self.sheet_pick.addItem(s.name, str(s))
            self.sheet_pick.blockSignals(False)
            self._show_sheet()

    def _show_sheet(self) -> None:
        path = self.sheet_pick.currentData()
        if path:
            pm = QPixmap(path)
            self.sheet.setPixmap(pm)
            self.sheet.adjustSize()

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.kill()
            self._say("Stopped. Masks written so far stay; 'Keep masks already there' carries on.")

    def _busy(self, busy: bool) -> None:
        for b in (self.try_btn, self.run_btn, self.save_btn, self.cmd_btn, self.preset):
            b.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)

    def _say(self, text: str) -> None:
        self.output.appendPlainText(text)

    def done(self, r: int) -> None:
        if self.proc is not None:
            if QMessageBox.question(self, "Batch Masking", "A run is going on. Stop it and close?") != \
                    QMessageBox.StandardButton.Yes:
                return
            self.proc.kill()
            self.proc.waitForFinished(3000)
        shutil.rmtree(self._tmp, ignore_errors=True)  # the window's own preset copy and contact sheets
        super().done(r)
