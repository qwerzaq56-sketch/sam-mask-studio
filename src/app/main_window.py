"""Main window: wires the Session to the canvas and panels (spec 01 §5 layout).

Toolbar (Open, Save, Undo, Redo, Export, Final Mask preview, Brush,
Outline + width, Edit Changes) ·
left Objects + Images · center canvas · right Properties · bottom
Prompt/Detection, Propagation and Logs tabs · status bar with the mode.

SAM2 clicks run on the UI thread (they are fast once the image embedding
exists); model loading, SAM3 detection, export and propagation run in
``QThread`` workers. The window never mutates the project directly: every
action goes through ``Session`` and then ``refresh()`` redraws all views.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QToolBar,
)

from src.app.canvas import Canvas, Overlay
from src.app.detection_panel import DetectionPanel, candidate_color
from src.app.dialogs import ExportDialog, SettingsDialog
from src.app.images_panel import ImagesPanel
from src.app.objects_panel import ObjectsPanel
from src.app.propagation_panel import PropagationPanel
from src.app.properties_panel import PropertiesPanel
from src.app.session import Mode, Session
from src.app.settings import DEFAULT_PATH, Settings
from src.app.workers import PropagationWorker, Task
from src.core.propagation import Direction
from src.core.storage import default_export_dir
from src.logging_config import get_logger

logger = get_logger(__name__)


def default_engine_factory(settings: Settings):
    from src.engine.inference import InferenceEngine

    return InferenceEngine(settings.sam2_checkpoint, settings.sam3_checkpoint or None)


def default_propagate():
    from src.engine.video import propagate

    return propagate


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings: Optional[Settings] = None,
        engine=None,
        engine_factory: Callable = default_engine_factory,
        propagate_fn: Optional[Callable] = None,
        settings_path: Path = DEFAULT_PATH,
    ):
        super().__init__()
        self.settings = settings or Settings.load(settings_path)
        self.settings_path = settings_path
        self.engine_factory = engine_factory
        self.propagate_fn = propagate_fn
        self.session = Session(engine, max_side=self.settings.max_side)
        self._tasks: List[Task] = []
        self._prop_worker: Optional[PropagationWorker] = None
        self._discard = False  # the running batch/propagation was cancelled: drop its results
        self._job = ""  # "batch" | "propagation" while _prop_worker runs
        self._busy: Optional[str] = None  # a long job that locks navigation/editing
        self._loading_models = False

        self.setWindowTitle("SAM Mask Studio")
        self.resize(1500, 950)
        self._build_ui()
        self._build_actions()
        self._connect()

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(self.settings.autosave_ms)
        self._autosave.timeout.connect(lambda: self.save(background=True))
        self._save_task: Optional[Task] = None
        self.refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.canvas = Canvas()
        self.setCentralWidget(self.canvas)

        self.objects_panel = ObjectsPanel()
        self.images_panel = ImagesPanel()
        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self.objects_panel)
        left.addWidget(self.images_panel)
        left.setSizes([550, 350])
        left_dock = self._dock("Objects / Images", left, Qt.DockWidgetArea.LeftDockWidgetArea)

        self.properties_panel = PropertiesPanel()
        right_dock = self._dock("Properties", self.properties_panel, Qt.DockWidgetArea.RightDockWidgetArea)

        self.detection_panel = DetectionPanel()
        self.propagation_panel = PropagationPanel()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.detection_panel, "Prompt / Detection")
        self.tabs.addTab(self.propagation_panel, "Propagation")
        self.tabs.addTab(self.log_view, "Logs")
        bottom_dock = self._dock(
            "Prompt / Detection / Propagation / Logs", self.tabs, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.resizeDocks([left_dock, right_dock], [330, 320], Qt.Orientation.Horizontal)
        self.resizeDocks([bottom_dock], [280], Qt.Orientation.Vertical)

        self.mode_label = QLabel()
        self.image_label = QLabel()
        self.model_label = QLabel()
        sb = self.statusBar()
        sb.addWidget(self.mode_label, 1)
        sb.addPermanentWidget(self.image_label)
        sb.addPermanentWidget(self.model_label)

    def _dock(self, title: str, widget, area) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName(title)
        d.setWidget(widget)
        d.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(area, d)
        return d

    def _action(self, text: str, slot, shortcuts=(), tip: str = "", checkable: bool = False) -> QAction:
        a = QAction(text, self)
        if shortcuts:
            a.setShortcuts([QKeySequence(s) for s in shortcuts])
        a.setToolTip(f"{tip or text} ({', '.join(shortcuts)})" if shortcuts else (tip or text))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _build_actions(self) -> None:
        self.act_open = self._action("Open", self.choose_folder, ["Ctrl+O"], "Open an image folder")
        self.act_save = self._action(
            "Save", lambda: self.save(force=True), ["Ctrl+S"], "Save the project (also autosaved)"
        )
        self.act_undo = self._action("Undo", self.undo, ["Ctrl+Z"])
        self.act_redo = self._action("Redo", self.redo, ["Ctrl+Y", "Ctrl+Shift+Z"])
        self.act_export = self._action("Export", self.export, ["Ctrl+E"], "Export Final Mask PNGs")
        self.act_final = self._action(
            "Preview Final Mask", self.toggle_final, ["F"], "Show the Final Mask (hold Alt to peek)", True
        )
        self.act_brush = self._action(
            "Brush",
            self.set_brush,
            ["B"],
            "Brush editing on the edited Object: drag = add, Ctrl+drag = subtract, Ctrl+wheel = size",
            True,
        )
        self.act_outline = self._action(
            "Outline", self.set_outline, ["O"], "White outline around the edited mask", True
        )
        self.act_outline.setChecked(self.settings.outline_visible)
        self.outline_width = QDoubleSpinBox()
        self.outline_width.setRange(0.5, 8.0)
        self.outline_width.setSingleStep(0.5)
        self.outline_width.setDecimals(1)
        self.outline_width.setSuffix(" px")
        self.outline_width.setValue(self.settings.outline_width)
        self.outline_width.setToolTip("Outline width in screen pixels")
        self.outline_width.valueChanged.connect(lambda _v: self.set_outline(self.act_outline.isChecked()))
        self.act_changes = self._action(
            "Edit Changes",
            self.set_show_changes,
            tip="Tint what the edit layer added (green) and removed (red)",
            checkable=True,
        )
        self.act_changes.setChecked(self.settings.show_edit_changes)
        self.act_settings = self._action("Settings", self.show_settings)
        tb = QToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        for a in (self.act_open, self.act_save, self.act_undo, self.act_redo, self.act_export):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_final)
        tb.addAction(self.act_brush)
        tb.addSeparator()
        tb.addAction(self.act_outline)
        tb.addWidget(self.outline_width)
        tb.addAction(self.act_changes)
        tb.addSeparator()
        tb.addAction(self.act_settings)
        self.addToolBar(tb)
        self.canvas.set_outline(self.settings.outline_visible, self.settings.outline_width)

        def key(seq, slot):
            QShortcut(QKeySequence(seq), self, slot)

        key("Delete", self.delete_key)
        key("Escape", self.finish_editing)
        key("N", self.new_object)
        key("E", self.edit_key)
        for seq in ("Left", "A", "PgUp"):
            key(seq, lambda: self.step(-1))
        for seq in ("Right", "D", "PgDown"):
            key(seq, lambda: self.step(1))

    def _connect(self) -> None:
        c = self.canvas
        c.clicked.connect(self.on_click)
        c.box_drawn.connect(lambda x0, y0, x1, y1: self._prompt(lambda: self.session.drag_box((x0, y0, x1, y1))))
        c.point_picked.connect(self.on_point_selected)
        c.object_picked.connect(self.on_object_picked)
        c.brush_finished.connect(self.on_brush)
        c.brush_size_changed.connect(lambda px: self.properties_panel.set_brush_size(px))

        o = self.objects_panel
        o.include_toggled.connect(lambda oid, on: self._do(lambda: self.session.project.set_included(oid, on)))
        o.renamed.connect(lambda oid, name: self._do(lambda: self.session.project.rename(oid, name)))
        o.edit_requested.connect(self.toggle_edit)
        o.new_requested.connect(self.new_object)
        o.merge_requested.connect(self.merge)
        o.duplicate_requested.connect(lambda ids: self._do(lambda: self.session.project.duplicate(ids)))
        o.delete_requested.connect(self.delete_objects)
        o.remove_frame_requested.connect(lambda oid: self._do(lambda: self.session.remove_frame(oid)))
        o.variant_selected.connect(lambda oid, i: self._do(lambda: self.session.select_variant(i, oid)))
        o.selection_changed.connect(lambda _ids: self.refresh())

        p = self.properties_panel
        p.variant_selected.connect(self.on_properties_variant)
        p.point_selected.connect(self.on_point_selected)
        p.delete_point_requested.connect(lambda: self._prompt(self.session.delete_point))
        p.clear_points_requested.connect(lambda: self._prompt(self.session.clear_points))
        p.clear_box_requested.connect(lambda: self._prompt(self.session.clear_box))
        p.finish_requested.connect(self.finish_editing)
        p.brush_toggled.connect(self.set_brush)
        p.refine_requested.connect(lambda area: self._layer(lambda: self.session.refine(area), "Refined"))
        p.apply_layer_requested.connect(lambda: self._layer(self.session.apply_edit, "Edit layer applied"))
        p.delete_layer_requested.connect(lambda: self._layer(self.session.discard_edit, "Edit layer deleted"))

        d = self.detection_panel
        d.detect_requested.connect(self.detect)
        d.checks_changed.connect(self.on_detection_checks)
        d.add_requested.connect(lambda: self._do(self.session.add_checked_detections))
        d.clear_requested.connect(lambda: self._do(self.session.clear_detections))
        d.batch_requested.connect(self.run_batch)
        d.batch_stop_requested.connect(lambda: self.stop_job(discard=False))
        d.batch_cancel_requested.connect(lambda: self.stop_job(discard=True))
        d.navigate_requested.connect(self.go_to)

        pp = self.propagation_panel
        pp.propagate_requested.connect(self.propagate)
        pp.stop_requested.connect(lambda: self.stop_job(discard=False))
        pp.cancel_requested.connect(lambda: self.stop_job(discard=True))
        pp.navigate_requested.connect(self.go_to)
        self.images_panel.navigate_requested.connect(self.go_to)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def log(self, message: str) -> None:
        self.log_view.appendPlainText(f"{time.strftime('%H:%M:%S')}  {message}")
        self.statusBar().showMessage(message, 6000)

    def ask(self, title: str, text: str, ok: str) -> bool:
        """Confirm dialog; tests replace this."""
        box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=self)
        yes = box.addButton(ok, QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return box.clickedButton() is yes

    def warn(self, text: str) -> None:
        self.log(text)
        QMessageBox.warning(self, "SAM Mask Studio", text)

    def _do(self, fn) -> None:
        """Run a Session/Project change and redraw."""
        fn()
        self.session.sync()
        self.refresh()

    def _prompt(self, fn) -> None:
        """Run a change that may need SAM2; report instead of raising when it is not ready."""
        try:
            fn()
        except RuntimeError as e:
            self.log(str(e) + (" Loading…" if self._loading_models else ""))
        self.refresh()

    def shown_object_id(self) -> Optional[int]:
        """The Object shown in Properties: the one in Edit, else a single selected row."""
        if self.session.editing is not None:
            return self.session.editing
        ids = self.objects_panel.selected_ids()
        return ids[0] if len(ids) == 1 else None

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        s = self.session
        key = s.key
        project = s.project
        busy = self._busy is not None

        self._update_overlays()
        self.canvas.set_final(project.final_mask(key) if key else None)

        fs = s.editing_frame()
        self.canvas.set_prompts(fs.points if fs else (), s.selected_point, fs.box if fs else None)
        editing_obj = project.get(s.editing) if s.editing is not None else None
        mode = s.effective_mode
        if s.mode == Mode.EDIT and editing_obj is not None:
            banner = f"Editing: {editing_obj.name}" + ("  ·  BRUSH" if self.canvas.brush_mode else "")
        elif s.mode == Mode.NEW_OBJECT:
            banner = "New Object: click or drag a box"
        elif mode == Mode.NEW_OBJECT:
            banner = "Click or drag a box to create the first Object"
        else:
            banner = ""
        if mode != Mode.EDIT and self.canvas.brush_mode:
            self.set_brush(False, redraw=False)
        self.canvas.set_mode(mode, banner)

        self.objects_panel.set_objects(project.objects, key, s.editing)
        shown = project.get(self.shown_object_id()) if self.shown_object_id() is not None else None
        self.properties_panel.show_frame(
            shown,
            shown.frame(key) if (shown and key) else None,
            s.selected_point if shown is editing_obj else None,
            s.image,
            new_mode=s.mode == Mode.NEW_OBJECT,
            editing=shown is not None and shown is editing_obj,
        )
        self.detection_panel.set_detections(s.detections, s.detection_checked)
        self.images_panel.update_marks(project)
        self.images_panel.set_current(s.index)
        self.propagation_panel.set_current(s.index)

        has_folder = key is not None
        self.act_undo.setEnabled(project.can_undo and not busy)
        self.act_redo.setEnabled(project.can_redo and not busy)
        self.act_save.setEnabled(has_folder)
        self.act_export.setEnabled(has_folder and not busy)
        self.act_brush.setEnabled(s.mode == Mode.EDIT and not busy)
        for w in (self.canvas, self.objects_panel, self.properties_panel, self.images_panel):
            w.setEnabled(has_folder and not busy)
        self.detection_panel.setEnabled(has_folder)
        self.detection_panel.set_busy(busy)  # locks its own controls while busy; batch Cancel stays usable
        self.propagation_panel.run_btn.setEnabled(has_folder and not busy)

        mode_text = {
            Mode.IDLE: "Ready — use an Object's Edit, + New Object from Points (N), or a SAM3 prompt",
            Mode.NEW_OBJECT: "NEW OBJECT — left click or drag a box on the image (Esc cancels)",
            Mode.EDIT: "EDIT — left: positive · right: negative · drag: box · B: brush · Delete: point · Esc: finish",
        }[s.mode]
        if mode == Mode.NEW_OBJECT and s.mode == Mode.IDLE:
            mode_text = "No Objects yet — left click or drag a box to create the first one, or use a SAM3 prompt"
        if s.mode == Mode.EDIT and self.canvas.brush_mode:
            mode_text = "BRUSH — drag: add · Ctrl+drag: subtract · Ctrl+wheel: size · wheel: zoom · B: brush off"
        self.mode_label.setText(self._busy or mode_text)
        self.image_label.setText(f"{s.index + 1}/{len(s.keys)}  {key}" if has_folder else "")
        eng = s.engine
        self.model_label.setText(
            "SAM2 loading…"
            if self._loading_models
            else ("SAM2 ✓" if eng is not None and eng.sam2_ready else "SAM2 ✕")
            + ("  SAM3 ✓" if eng is not None and eng.sam3_ready else "")
        )
        if s.store is not None and not s.store.is_saved(project):
            self._autosave.start()

    def _update_overlays(self) -> None:
        """Hand the canvas the mask layers of the current image (Objects, edit layer, candidates)."""
        s = self.session
        key = s.key
        overlays: List[Overlay] = []
        edit_layer = None
        for o in s.project.objects:
            m = o.mask(key) if key else None
            if m is None:
                continue
            if o.id == s.editing:
                edit_layer = Overlay(m, o.color, "edit")
            else:
                overlays.append(Overlay(m, o.color, "normal" if o.included else "faint"))
        if edit_layer is not None:
            overlays.append(edit_layer)
            layer = s.editing_frame().edit if s.editing_frame() is not None else None
            if layer is not None and self.settings.show_edit_changes:  # what the hand edits changed
                overlays.append(Overlay(layer.add, (80, 255, 120), "layer_add"))
                overlays.append(Overlay(layer.sub, (255, 60, 60), "layer_sub"))
        for i, (det, on) in enumerate(zip(s.detections, s.detection_checked, strict=True)):
            overlays.append(Overlay(det.mask, candidate_color(i), "candidate" if on else "candidate_off"))
        self.canvas.set_overlays(overlays)

    # ------------------------------------------------------------------
    # Folder / navigation / saving
    # ------------------------------------------------------------------

    def choose_folder(self) -> None:
        start = self.settings.last_dir or ""
        d = QFileDialog.getExistingDirectory(self, "Open image folder", start)
        if d:
            self.open_folder(Path(d))

    def open_folder(self, folder: Path) -> bool:
        if self._busy:
            return False
        self.save()
        self.session.max_side = self.settings.max_side
        try:
            n = self.session.open_folder(folder)
        except (OSError, ValueError) as e:
            self.warn(str(e))
            return False
        self.settings.last_dir = str(folder)
        self.settings.save(self.settings_path)
        self.images_panel.set_images(self.session.keys)
        self.propagation_panel.set_images(self.session.keys)
        self.detection_panel.set_image_count(len(self.session.keys))
        self.canvas.set_image(self.session.image)
        self.setWindowTitle(f"SAM Mask Studio — {folder}")
        loaded = len(self.session.project.objects)
        self.log(f"Opened {folder} ({n} images" + (f", {loaded} saved Objects)" if loaded else ")"))
        self.ensure_models()
        self.refresh()
        return True

    def go_to(self, index: int) -> None:
        if self._busy or index is None:
            return
        self.save(background=True)
        try:
            moved = self.session.go_to(index)
        except ValueError as e:
            self.warn(str(e))
            return
        if moved:
            self.canvas.set_image(self.session.image)
        self.refresh()

    def step(self, delta: int) -> None:
        if self.session.key is not None:
            self.go_to(max(0, min(len(self.session.keys) - 1, self.session.index + delta)))

    def save(self, force: bool = False, background: bool = False) -> None:
        """Write the project's changes; *background* writes the PNGs off the UI thread.

        Autosave runs in the background (the first save after a batch or a
        propagation can be thousands of masks); explicit saves, navigation and
        closing write directly, after any background save has finished;
        moving to another image saves in the background too.
        """
        self._autosave.stop()
        store = self.session.store
        if store is None:
            return
        running = self._save_task
        if running is not None and running.isRunning():
            if background:
                self._autosave.start()  # try again once the current write is done
                return
            running.wait()
        try:
            job = store.prepare(self.session.project, force=force)
        except OSError as e:
            self.log(f"Save failed: {e}")
            return
        if job is None:
            return
        if not background:
            try:
                job.run()
                if force:
                    self.log("Saved")
            except OSError as e:
                store.failed(job)
                self.log(f"Save failed: {e}")
            return

        def failed(msg):
            store.failed(job)
            self.log(f"Save failed: {msg}")

        task = Task(job.run)
        self._save_task = task
        task.failed.connect(failed)
        task.start()

    def closeEvent(self, event):
        if self._prop_worker is not None and self._prop_worker.isRunning():
            if not self.ask("Propagation running", "Cancel the running propagation and quit?", "Quit"):
                event.ignore()
                return
            self._prop_worker.cancel()
            self._prop_worker.wait(10000)
        for t in self._tasks:
            t.wait(10000)
        self.save()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    def _start(self, task: Task, done, failed=None) -> Task:
        self._tasks.append(task)

        def cleanup():
            if task in self._tasks:
                self._tasks.remove(task)

        task.done.connect(done)
        task.failed.connect(failed or self.warn)
        task.finished.connect(cleanup)
        task.start()
        return task

    def ensure_models(self) -> None:
        """Create the engine and load SAM2 in the background (SAM3 loads on first Detect)."""
        s = self.session
        if self._loading_models or (s.engine is not None and s.engine.sam2_ready):
            return
        ckpt = Path(self.settings.sam2_checkpoint)
        if not ckpt.is_file():
            self.log(f"SAM2 checkpoint not found: {ckpt} — set it in Settings")
            return
        self._loading_models = True
        engine = s.engine

        def load():
            e = engine or self.engine_factory(self.settings)
            e.load_sam2()
            return e

        def done(e):
            self._loading_models = False
            s.engine = e
            if s.image is not None:
                e.set_image(s.image)
            self.log(f"SAM2 loaded on {getattr(e, 'device', '?')}")
            self.refresh()

        def failed(msg):
            self._loading_models = False
            self.warn(f"Could not load SAM2: {msg}")
            self.refresh()

        self._start(Task(load), done, failed)
        self.refresh()

    # ------------------------------------------------------------------
    # Canvas / editing
    # ------------------------------------------------------------------

    def on_click(self, x: float, y: float, positive: bool) -> None:
        if self.session.effective_mode == Mode.NEW_OBJECT and not positive:
            self.log("A new Object starts from a positive (left) click or a box")
            return
        self._prompt(lambda: self.session.click(x, y, positive))

    def set_brush(self, on: bool, redraw: bool = True) -> None:
        """Turn Brush editing on/off (only possible while an Object is in Edit)."""
        on = bool(on) and self.session.mode == Mode.EDIT and not self._busy
        self.canvas.set_brush_mode(on)
        self.act_brush.setChecked(on)
        self.properties_panel.set_brush(on)
        self.properties_panel.set_brush_size(self.canvas.brush_size)
        if on:
            self.canvas.setFocus()
        if redraw:
            self.refresh()

    def set_outline(self, on: bool) -> None:
        self.settings.outline_visible = bool(on)
        self.settings.outline_width = float(self.outline_width.value())
        self.canvas.set_outline(self.settings.outline_visible, self.settings.outline_width)
        self.settings.save(self.settings_path)

    def set_show_changes(self, on: bool) -> None:
        self.settings.show_edit_changes = bool(on)
        self.settings.save(self.settings_path)
        self._update_overlays()

    def _layer(self, fn, message: str) -> None:
        """Run an edit-layer change on the edited Object and report whether it did anything."""
        if fn():
            self.log(message)
        self.session.sync()
        self.refresh()

    def on_point_selected(self, index: int) -> None:
        self.session.select_point(index)
        self.refresh()

    def on_object_picked(self, x: float, y: float) -> None:
        key = self.session.key
        for o in reversed(self.session.project.objects):
            m = o.mask(key) if key else None
            if m is not None and 0 <= int(y) < m.shape[0] and 0 <= int(x) < m.shape[1] and m[int(y), int(x)]:
                self.objects_panel.select_ids([o.id])
                break
        else:
            self.objects_panel.select_ids([])
        self.refresh()

    def on_brush(self, mask) -> None:
        self._do(lambda: self.session.brush(mask))

    def on_properties_variant(self, index: int) -> None:
        oid = self.shown_object_id()
        if oid is not None:
            self._do(lambda: self.session.select_variant(index, oid))

    def new_object(self) -> None:
        if self.session.key is None or self._busy:
            return
        self.session.start_new_object()
        self.canvas.setFocus()
        self.refresh()

    def toggle_edit(self, oid: int) -> None:
        if self.session.editing == oid:
            self.session.finish_editing()
        else:
            self.session.edit(oid)
            self.canvas.setFocus()
        self.refresh()

    def edit_key(self) -> None:
        ids = self.objects_panel.selected_ids()
        if self.session.editing is not None:
            self.finish_editing()
        elif len(ids) == 1:
            self.toggle_edit(ids[0])
        elif len(self.session.project.objects) == 1:
            self.toggle_edit(self.session.project.objects[0].id)

    def finish_editing(self) -> None:
        self.session.finish_editing()
        self.refresh()

    def delete_key(self) -> None:
        if self.session.mode == Mode.EDIT and self.session.selected_point is not None:
            self._prompt(self.session.delete_point)
        elif self.objects_panel.selected_ids():
            self.delete_objects(self.objects_panel.selected_ids())

    def delete_objects(self, ids: List[int]) -> None:
        objs = [o for o in self.session.project.objects if o.id in set(ids)]
        if not objs:
            return
        text = (
            f'Delete "{objs[0].name}"?'
            if len(objs) == 1
            else f"Delete {len(objs)} Objects?\n\n" + "\n".join(o.name for o in objs)
        )
        text += (
            "\n\nIts masks on every image are removed too."
            if len(objs) == 1
            else "\n\nTheir masks on every image are removed too."
        )
        if self.ask("Delete Object", text, "Delete"):
            self._do(lambda: self.session.delete_objects(ids))

    def merge(self, ids: List[int]) -> None:
        if len(ids) < 2:
            self.log("Select two or more Object rows to merge (Ctrl/Shift-click)")
            return
        new = self.session.merge(ids)
        if new is not None:
            self.objects_panel.select_ids([new])
            self.log(f"Merged into {self.session.project.get(new).name}")
        self.refresh()

    def undo(self) -> None:
        if not self._busy:
            self._do(self.session.undo)

    def redo(self) -> None:
        if not self._busy:
            self._do(self.session.redo)

    def toggle_final(self, on: bool) -> None:
        self.canvas.set_final_preview(on)

    # ------------------------------------------------------------------
    # SAM3 detection
    # ------------------------------------------------------------------

    def detect(self, labels) -> None:
        """SAM3 on the current image, one prompt per label (``["person", "car"]`` or ``"person, car"``)."""
        from src.core.prompts import split_labels

        labels = split_labels(labels) if isinstance(labels, str) else list(labels)
        s = self.session
        if s.key is None or self._busy or not labels:
            return
        engine = s.engine
        if engine is None:
            self.warn("Models are not loaded yet (check the SAM2 checkpoint in Settings).")
            return
        text = ", ".join(labels)
        image = s.image
        self._busy = f"SAM3: detecting {text}…"
        self.detection_panel.set_busy(
            True, f"SAM3: detecting {text}…" + ("" if engine.sam3_ready else " (loading SAM3 first)")
        )

        def run():
            if not engine.sam3_ready:
                engine.load_sam3()
            return engine.detect_many(image, labels)

        def done(dets):
            self._busy = None
            s.set_detections(dets)
            counts = ", ".join(f"{lb} {sum(1 for d in dets if d.label == lb)}" for lb in labels)
            self.detection_panel.set_busy(False, f"{len(dets)} candidate(s) — {counts}. Check the ones to keep")
            self.log(f"SAM3 {counts}")
            self.refresh()

        def failed(msg):
            self._busy = None
            self.detection_panel.set_busy(False, "Detection failed")
            self.refresh()
            self.warn(f"SAM3 detection failed: {msg}")

        self._start(Task(run), done, failed)
        self.refresh()

    def on_detection_checks(self, checked: List[bool]) -> None:
        """Checking candidates only changes their overlays: redraw the canvas, nothing else."""
        self.session.detection_checked = list(checked)
        self._update_overlays()

    def run_batch(self, labels: List[str], scope: str, start: int, end: int, threshold: float) -> None:
        """Batch masking: SAM3 over many images, one Object per label (spec: prompt-based bulk masking)."""
        from src.engine.batch import batch_detect, summarize

        s = self.session
        if s.key is None or self._busy or not labels:
            return
        engine = s.engine
        if engine is None:
            self.warn("Models are not loaded yet (check the SAM2 checkpoint in Settings).")
            return
        indices = s.batch_indices(scope, start, end, self.images_panel.selected_rows())
        if not indices:
            self.warn(
                "No images to process"
                + (" — select images in the Images list (Ctrl/Shift-click)." if scope == "selected" else ".")
            )
            return
        paths, max_side = list(s.paths), s.max_side
        s.finish_editing()
        text = ", ".join(labels)
        self._busy = f"SAM3 batch: {text} on {len(indices)} image(s)…"
        self.detection_panel.set_busy(True, self._busy + ("" if engine.sam3_ready else " (loading SAM3 first)"))
        self.detection_panel.batch_begin(len(indices))
        self.log(f"Batch masking {text} on {len(indices)} image(s), min score {threshold:.2f}")

        def run(cancel, progress):
            if not engine.sam3_ready:
                engine.load_sam3()
            return batch_detect(engine, paths, indices, labels, max_side, threshold, cancel=cancel, progress=progress)

        def on_frame(idx, hits):
            found = any(h.mask is not None for h in hits.values())
            self.detection_panel.batch_frame(idx, f"{s.keys[idx]}   {summarize(hits)}", found)

        def finish(results, outcome):
            self._busy = None
            self._prop_worker = None
            if self._discard:
                self._discard = False
                self.detection_panel.set_busy(False)
                self.detection_panel.batch_end(f"Cancelled: nothing added ({len(results)} image(s) discarded)")
                self.log("Batch masking cancelled — results discarded")
                self.refresh()
                return
            made = s.apply_batch(results) if results else {}
            names = ", ".join(s.project.get(oid).name for oid in made.values())
            found = sum(1 for hits in results.values() if any(h.mask is not None for h in hits.values()))
            msg = f"{outcome}: {len(results)} image(s) processed, {found} with detections" + (
                f" → {names}" if names else " — nothing above the score threshold"
            )
            self.detection_panel.set_busy(False)
            self.detection_panel.batch_end(msg)
            (self.warn if outcome.startswith("Failed") else self.log)(
                msg + (" — Ctrl+Z undoes the whole batch" if made else "")
            )
            self.refresh()

        w = PropagationWorker(run, self)
        w.frame_done.connect(on_frame)
        w.finished_ok.connect(lambda results, stopped: finish(results, "Stopped" if stopped else "Done"))
        w.failed.connect(lambda msg, partial: finish(partial, f"Failed: {msg}"))
        self._discard = False
        self._job = "batch"
        self._prop_worker = w
        w.start()
        self.refresh()

    # ------------------------------------------------------------------
    # Propagation
    # ------------------------------------------------------------------

    def propagate(self, start: int, end: int, direction: Direction) -> None:
        s = self.session
        if s.key is None or self._busy:
            return
        if not (start <= s.index <= end):
            self.warn("The Current image must lie within Start ~ End.")
            return
        plan = s.plan(start, end, direction)
        if not plan.targets:
            self.warn("Nothing to propagate: the range has no images in that direction.")
            return
        seeds = s.seeds()
        if not seeds:
            self.warn("Check at least one Object that has a mask on the Current image.")
            return
        existing = s.overwrite_targets(plan, seeds)
        if existing:
            shown = "\n".join(existing[:15]) + (f"\n… and {len(existing) - 15} more" if len(existing) > 15 else "")
            if not self.ask(
                "Existing masks found",
                f"Existing masks found.\n\n{shown}\n\nOverwrite existing propagated masks?",
                "Overwrite",
            ):
                return
        propagate = self.propagate_fn or default_propagate()
        ckpt, paths, max_side = self.settings.sam2_checkpoint, list(s.paths), s.max_side

        s.finish_editing()
        self._busy = "Propagating…"
        names = [(oid, s.project.get(oid).name) for oid in seeds]
        self.propagation_panel.begin(plan, names)
        self.tabs.setCurrentWidget(self.propagation_panel)
        self.log(
            f"Propagating {len(seeds)} Object(s) from {s.key} over {len(plan.targets)} image(s) ({direction.value})"
        )

        def run(cancel, progress):
            return propagate(ckpt, paths, plan, seeds, max_side, cancel=cancel, progress=progress)

        w = PropagationWorker(run, self)
        w.progress.connect(self.propagation_panel.on_progress)
        w.frame_done.connect(lambda idx, masks: self.propagation_panel.on_frame(idx, list(masks)))
        w.finished_ok.connect(
            lambda results, stopped: self._propagation_done(results, seeds, "Stopped" if stopped else "Done")
        )
        w.failed.connect(lambda msg, partial: self._propagation_done(partial, seeds, f"Failed: {msg}"))
        self._discard = False
        self._job = "propagation"
        self._prop_worker = w
        w.start()
        self.refresh()

    def _propagation_done(self, results, seeds, outcome: str) -> None:
        self._busy = None
        self._prop_worker = None
        if self._discard:
            self._discard = False
            self.propagation_panel.finish({}, f"Cancelled: nothing changed ({len(results)} frame(s) discarded)")
            self.log("Propagation cancelled — results discarded")
            self.refresh()
            return
        statuses = self.session.apply_propagation(results, seeds) if results else {}
        bad = sum(1 for st in statuses.values() if st.value in ("warning", "failed"))
        msg = f"{outcome}: {len(statuses)} image(s) updated" + (f", {bad} need a look (⚠/✕)" if bad else "")
        self.propagation_panel.finish(statuses, msg)
        if outcome.startswith("Failed"):
            self.warn(msg)
        else:
            self.log(msg + (" — Ctrl+Z undoes the whole propagation" if statuses else ""))
        self.refresh()

    def stop_job(self, discard: bool) -> None:
        """Stop the running batch / propagation after its current step.

        Stop keeps what is done (one undo step); Cancel (*discard*) drops it all.
        """
        w = self._prop_worker
        if w is None or not w.isRunning():
            return
        self._discard = discard
        w.cancel()
        if self._job == "batch":
            self.detection_panel.batch_stopping()
        else:
            self.propagation_panel.stopping()
        self.log("Cancelling — results will be discarded…" if discard else "Stopping — keeping the results so far…")

    def cancel_propagation(self) -> None:
        self.stop_job(discard=True)

    # ------------------------------------------------------------------
    # Export / settings
    # ------------------------------------------------------------------

    def export(self) -> None:
        s = self.session
        if s.image_dir is None or self._busy:
            return
        if not s.project.keys_with_masks():
            self.warn("Nothing to export: no checked Object has a mask yet.")
            return
        dlg = ExportDialog(default_export_dir(s.image_dir), self)
        if dlg.exec() != ExportDialog.DialogCode.Accepted:
            return
        self.run_export(dlg.options())

    def run_export(self, options) -> None:
        self.save()
        self._busy = "Exporting…"

        def done(paths):
            self._busy = None
            self.log(f"Exported {len(paths)} mask(s) to {options.out_dir}")
            self.refresh()

        def failed(msg):
            self._busy = None
            self.refresh()
            self.warn(f"Export failed: {msg}")

        self._start(Task(lambda: self.session.export(options)), done, failed)
        self.refresh()

    def show_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() != SettingsDialog.DialogCode.Accepted:
            return
        old = (self.settings.sam2_checkpoint, self.settings.sam3_checkpoint)
        dlg.apply(self.settings)
        self.settings.save(self.settings_path)
        if (
            old != (self.settings.sam2_checkpoint, self.settings.sam3_checkpoint)
            and not self._busy
            and not self._loading_models
        ):
            eng = self.session.engine
            if eng is not None and hasattr(eng, "release"):
                eng.release()
            self.session.engine = None
            self.ensure_models()
        self.refresh()
