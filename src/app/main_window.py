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

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollBar,
    QSplitter,
    QTabWidget,
    QToolBar,
    QToolButton,
)

from src.app.canvas import Canvas, Overlay
from src.app.batch_panel import BatchPanel
from src.app.detection_panel import DetectionPanel, candidate_color
from src.app.dialogs import ExportDialog, SettingsDialog, ShortcutsDialog
from src.app.images_panel import ImagesPanel
from src.app.objects_panel import ObjectsPanel
from src.app.propagation_panel import PropagationPanel
from src.app.properties_panel import AUTO_TOOLS, PropertiesPanel
from src.app.session import Mode, Session
from src.app.ui_util import DockTitleBar
from src.app.settings import DEFAULT_PATH, Settings
from src.app.workers import PropagationWorker, Task
from src.core.propagation import Direction, PropagationPlan
from src.core.storage import default_export_dir
from src.logging_config import get_logger

logger = get_logger(__name__)


AUTO_ADD_COLOR = (255, 40, 220)  # magenta: an auto tool adds these pixels
AUTO_SUB_COLOR = (130, 60, 255)  # purple: ...and removes these


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
        self._reference: Optional[int] = None  # propagation reference (double-clicked image); None = current
        self._pinned: Optional[List[int]] = None  # the pinned Images-list selection (Selection scope)
        # a stopped propagation: (plan, object ids, frames done), and plans queued by Resume
        self._last_prop: Optional[tuple] = None
        self._prop_queue: List[tuple] = []
        self._tool = ""  # the Edit Layer tool in use ("" = none)
        self._auto_gen = 0  # newest auto-tool computation; older results are dropped
        self._auto_shown = 0  # the computation whose result is on screen
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
        QApplication.instance().installEventFilter(self)  # Space = peek at the Final Mask
        self._save_task: Optional[Task] = None
        self.refresh()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.canvas = Canvas()
        self.setCentralWidget(self.canvas)

        # Layout: left = Objects over the Prompt / Batch / Propagation / Logs tabs;
        # center = canvas; right = Properties; bottom = the frames as a thumbnail strip.
        self.objects_panel = ObjectsPanel()
        self.images_panel = ImagesPanel()

        self.properties_panel = PropertiesPanel()

        self.detection_panel = DetectionPanel()
        self.propagation_panel = PropagationPanel()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.tabs = QTabWidget()
        self.batch_panel = BatchPanel()
        self.tabs.addTab(self.detection_panel, "Prompt / Detection")
        self.tabs.addTab(self.batch_panel, "Batch")
        self.tabs.addTab(self.propagation_panel, "Propagation")
        self.tabs.addTab(self.log_view, "Logs")
        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self.objects_panel)
        left.addWidget(self.tabs)
        left.setSizes([330, 520])
        left_dock = self._dock("Objects / Prompt / Propagation", left, Qt.DockWidgetArea.LeftDockWidgetArea)
        right_dock = self._dock("Properties", self.properties_panel, Qt.DockWidgetArea.RightDockWidgetArea)
        frames_dock = self._dock("Frames", self.images_panel, Qt.DockWidgetArea.BottomDockWidgetArea)
        # the one-line frame list: a narrow column left of the Objects (same model / selection as the strip)
        list_dock = self._dock("Frame List", self.images_panel.frame_list, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.splitDockWidget(list_dock, left_dock, Qt.Orientation.Horizontal)
        self.names_btn = QToolButton()  # left of the close button: fold the file names away
        self.names_btn.setText("Aa")
        self.names_btn.setCheckable(True)
        self.names_btn.setAutoRaise(True)
        self.names_btn.setToolTip("Show the file names (off: only IDs and marks, a narrow list)")
        self.names_btn.toggled.connect(self.set_frame_names)
        list_tools = self._frame_tools()
        self._list_goto = list_tools[0]  # hidden while the names are folded: the column is narrow then
        list_dock.setTitleBarWidget(DockTitleBar(list_dock, [*list_tools, self.names_btn]))
        frames_dock.setTitleBarWidget(DockTitleBar(frames_dock, self._frame_tools()))
        self._list_dock = list_dock
        view_menu = self.menuBar().addMenu("&View")
        for d in (list_dock, left_dock, right_dock, frames_dock):
            view_menu.addAction(d.toggleViewAction())
        # the frame strip spans only the canvas: the side docks keep the full height
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self._dock_sizes = ([list_dock, left_dock, right_dock], [210, 380, 380], [frames_dock], [150])
        self._size_docks()

        self.mode_label = QLabel()
        self.image_label = QLabel()
        self.model_label = QLabel()
        sb = self.statusBar()
        sb.addWidget(self.mode_label, 1)
        sb.addPermanentWidget(self.image_label)
        sb.addPermanentWidget(self.model_label)

    def _size_docks(self) -> None:
        h_docks, h_sizes, v_docks, v_sizes = self._dock_sizes
        self.resizeDocks(h_docks, h_sizes, Qt.Orientation.Horizontal)
        self.resizeDocks(v_docks, v_sizes, Qt.Orientation.Vertical)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_docks_sized", False):  # sizes set before the first show can be lost
            self._docks_sized = True
            QTimer.singleShot(0, self._size_docks)

    def _dock(self, title: str, widget, area) -> QDockWidget:
        d = QDockWidget(title, self)
        d.setObjectName(title)
        d.setWidget(widget)
        # closable too: Qt disables a dock's View-menu toggle when it cannot be closed
        d.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
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
            "Preview Final Mask",
            self.toggle_final,
            ["X"],
            "Show the Final Mask (hold Z to peek; editing keeps working)",
            True,
        )
        self.act_brush = self._action(
            "Brush",
            self.set_brush,
            ["D"],
            "Brush editing on the edited Object: drag = add, Alt+drag = subtract, Ctrl+wheel = size",
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
            ["F"],
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
        tb.addSeparator()
        tb.addAction(self.act_changes)
        tb.addSeparator()
        tb.addAction(self.act_settings)
        self.addToolBar(tb)
        help_menu = self.menuBar().addMenu("&Help")
        self.act_shortcuts = help_menu.addAction("Keyboard Shortcuts")
        self.act_shortcuts.setShortcut(QKeySequence("F1"))
        self.act_shortcuts.triggered.connect(self.show_shortcuts)
        self.names_btn.setChecked(self.settings.frame_list_names)
        self.images_panel.set_names_visible(self.settings.frame_list_names)
        self._list_goto.setVisible(self.settings.frame_list_names)
        self.canvas.set_outline(self.settings.outline_visible, self.settings.outline_width)

        def key(seq, slot):
            QShortcut(QKeySequence(seq), self, slot)

        key("Delete", self.delete_key)
        key("Escape", self.escape)
        key("N", self.new_object)
        key("E", self.edit_key)
        for seq in ("Left", "PgUp"):
            key(seq, lambda: self.step(-1))
        key("A", self.a_key)
        for seq in ("Right", "PgDown"):
            key(seq, lambda: self.step(1))
        key("S", self.focus_frame)
        key("Up", lambda: self.step_object(-1))
        key("Down", lambda: self.step_object(1))

    def _connect(self) -> None:
        c = self.canvas
        c.clicked.connect(self.on_click)
        c.box_drawn.connect(lambda x0, y0, x1, y1: self._prompt(lambda: self.session.drag_box((x0, y0, x1, y1))))
        c.point_picked.connect(self.on_point_selected)
        c.point_moved.connect(lambda i, x, y: self._prompt(lambda: self.session.move_point(i, x, y)))
        c.point_deleted.connect(lambda i: self._prompt(lambda: self.session.delete_point(i)))
        c.object_picked.connect(self.on_object_picked)
        c.brush_finished.connect(self.on_brush)
        c.region_box.connect(self.on_region_box)
        c.tool_stroke.connect(self.on_tool_stroke)
        c.tool_target_fn = self._tool_target
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
        p.brush_tool_selected.connect(self.set_brush_tool)
        p.auto_mode_changed.connect(self.set_auto_mode)
        p.auto_apply_requested.connect(self.apply_and_leave_tool)
        p.auto_recompute_requested.connect(self.reapply_tool)
        p.auto_settings_changed.connect(self._auto_refresh)
        p.region_mode_toggled.connect(self.set_region_mode)
        p.clear_region_requested.connect(lambda: self.on_region(None))
        p.apply_layer_requested.connect(lambda: self._layer(self.session.apply_edit, "Edit layer applied"))
        p.delete_layer_requested.connect(lambda: self._layer(self.session.discard_edit, "Edit layer deleted"))

        d = self.detection_panel
        d.detect_requested.connect(self.detect)
        d.checks_changed.connect(self.on_detection_checks)
        d.add_requested.connect(lambda how: self._do(lambda: self.session.add_checked_detections(how)))
        d.clear_requested.connect(lambda: self._do(self.session.clear_detections))
        d.preview_toggled.connect(lambda _on: self.refresh())
        d.select_toggled.connect(self.set_picking)
        b = self.batch_panel
        b.batch_requested.connect(self.run_batch)
        b.batch_stop_requested.connect(lambda: self.stop_job(discard=False))
        b.batch_cancel_requested.connect(lambda: self.stop_job(discard=True))
        b.navigate_requested.connect(self.go_to)
        c.candidates_clicked.connect(self.on_candidates_clicked)
        c.candidates_boxed.connect(self.on_candidates_boxed)

        pp = self.propagation_panel
        pp.propagate_requested.connect(lambda a, b, d, scope: self.propagate(a, b, d, scope))
        pp.pin_toggled.connect(self.set_pinned)
        pp.resume_requested.connect(self.resume_propagation)
        self.images_panel.reference_requested.connect(self.set_reference)
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
            banner = f"Editing: {editing_obj.name}"
            if self.canvas.brush_mode:
                banner += "  ·  " + self.canvas.brush_tool.replace("_", " ").upper()
            elif self.canvas.region_mode:
                banner += "  ·  REGION BOX"
        elif s.mode == Mode.NEW_OBJECT:
            banner = "New Object: click or drag a box"
        elif self.picking():
            banner = "Select on Image: click / drag = add · Shift = toggle · Ctrl = remove"
        else:
            banner = ""
        if s.mode != Mode.EDIT and (self._tool or self.canvas.brush_mode):
            self.set_brush_tool("", redraw=False)
        if s.auto_stale() and not self._auto_pending():
            QTimer.singleShot(0, self._auto_refresh)  # the mask changed (undo, a click): recompute
        if s.mode != Mode.EDIT and self.canvas.region_mode:
            self.set_region_mode(False, redraw=False)
        self.canvas.set_region(s.region)
        self.properties_panel.set_region(s.region)
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
        if not s.detections and self.detection_panel.select_btn.isChecked():
            self.detection_panel.select_btn.blockSignals(True)  # nothing left to pick (added / discarded)
            self.detection_panel.select_btn.setChecked(False)
            self.detection_panel.select_btn.blockSignals(False)
        self.images_panel.set_reference(self._reference)  # before the marks: they draw the ◎
        self.images_panel.update_marks(project)
        self.images_panel.set_current(s.index)
        ref = self._reference if self._reference is not None else s.index
        self.propagation_panel.set_reference(ref, self._reference is not None)
        self.propagation_panel.set_pinned(self._pinned)
        self.images_panel.set_pinned(self._pinned)

        has_folder = key is not None
        self.act_undo.setEnabled(s.can_undo and not busy)
        self.act_redo.setEnabled(s.can_redo and not busy)
        self.act_save.setEnabled(has_folder)
        self.act_export.setEnabled(has_folder and not busy)
        self.act_brush.setEnabled(s.mode == Mode.EDIT and not busy)
        for w in (self.canvas, self.objects_panel, self.properties_panel, self.images_panel,
                  self.images_panel.frame_list):
            w.setEnabled(has_folder and not busy)
        self.detection_panel.setEnabled(has_folder)
        self.detection_panel.set_busy(busy)
        self.batch_panel.setEnabled(has_folder)
        self.batch_panel.set_busy(busy)  # locks its own controls while busy; Stop / Cancel stay usable
        self.propagation_panel.run_btn.setEnabled(has_folder and not busy)

        mode_text = {
            Mode.IDLE: "Ready — use an Object's Edit, + New Object from Points (N), or a SAM3 prompt",
            Mode.NEW_OBJECT: "NEW OBJECT — left click or drag a box on the image (Esc cancels)",
            Mode.EDIT: "EDIT — left: positive · right: negative · drag: box · D: brush · Delete: point · Esc: finish",
        }[s.mode]
        if self.picking():
            mode_text = "SELECT ON IMAGE — click / drag: add · Shift: toggle · Ctrl: remove · Edit is off meanwhile"
        if s.mode == Mode.EDIT and self.canvas.brush_mode:
            mode_text = "BRUSH — drag: add · Alt+drag: subtract · Ctrl+wheel: size · wheel: zoom · D: brush off"
            if self.canvas.brush_tool != "paint":
                mode_text = (
                    f"{self.canvas.brush_tool.replace('_', ' ').upper()} BRUSH — drag over the area,"
                    " release to apply · Ctrl+wheel: size · wheel: zoom"
                )
        if s.mode == Mode.EDIT and self.canvas.region_mode:
            mode_text = "REGION BOX — drag: add a box to the region · Alt+drag: remove a box"
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
            added, removed = s.auto_changes()
            if layer is not None and self.settings.show_edit_changes:  # what the hand edits changed
                overlays.append(Overlay(layer.add, (80, 255, 120), "layer_add"))
                overlays.append(Overlay(layer.sub, (255, 60, 60), "layer_sub"))
            if added is not None:  # the auto tool (on top): taken parts magenta / purple, the rest gray
                taken = s.auto_taken()
                overlays.append(Overlay((added | removed) & ~taken, (55, 55, 60), "guide"))  # dark gray
                # own colors, so they are never confused with the edit layer's green / red
                overlays.append(Overlay(added & taken, AUTO_ADD_COLOR, "auto_add"))
                overlays.append(Overlay(removed & taken, AUTO_SUB_COLOR, "auto_sub"))
            if s.auto_tool is not None and not self._auto_pending():
                if added is None:
                    self.properties_panel.set_preview(0, 0, 0, 0)
                else:
                    taken = s.auto_taken()
                    self.properties_panel.set_preview(
                        int((added & taken).sum()), int((removed & taken).sum()), int(added.sum()), int(removed.sum())
                    )
        preview = self.detection_panel.preview_btn.isChecked()
        for i, (det, on) in enumerate(zip(s.detections, s.detection_checked, strict=True)):
            if preview:
                overlays.append(Overlay(det.mask, candidate_color(i), "candidate" if on else "candidate_off"))
        self.canvas.candidates_pickable = preview and self.picking()
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
        self.images_panel.set_images(
            self.session.keys, self.session.paths, self.session.store.root / "thumbs" if self.session.store else None
        )
        self.propagation_panel.set_images(self.session.keys)
        self._reference, self._pinned, self._last_prop, self._prop_queue = None, None, None, []
        self.propagation_panel.set_resumable(False)
        self.batch_panel.set_image_count(len(self.session.keys))
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
        if self.session.mode == Mode.EDIT and index != self.session.index:
            self.log("Finish editing (Esc) before moving to another image")
            self.images_panel.set_current(self.session.index)
            return
        self.close_tool()
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

    def eventFilter(self, obj, event):
        """App-wide: Z held (no modifiers, not in a text box) shows the Final Mask; the wheel
        over a slider / number box scrolls the panel instead of changing the value."""
        t = event.type()
        if (
            t == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.session.auto_tool is not None
            and not isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox, QPlainTextEdit))
            and self.isActiveWindow()
        ):
            self.reapply_tool()  # Enter = Apply & Recompute
            return True
        if (
            t in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
            and event.key() == Qt.Key.Key_Z
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            focus = QApplication.focusWidget()
            typing = isinstance(focus, (QLineEdit, QAbstractSpinBox, QPlainTextEdit))
            if not typing and self.isActiveWindow():
                if not event.isAutoRepeat():
                    self.canvas.set_final_peek(t == QEvent.Type.KeyPress)
                return True
        if (
            t == QEvent.Type.Wheel
            and isinstance(obj, (QAbstractSlider, QAbstractSpinBox))
            and not isinstance(obj, QScrollBar)  # scroll areas scroll through their scroll bars
        ):
            area = obj.parentWidget()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parentWidget()
            if area is not None:
                QApplication.sendEvent(area.verticalScrollBar(), event)  # the panel scrolls instead
            return True
        return super().eventFilter(obj, event)

    def show_shortcuts(self) -> None:
        ShortcutsDialog(self).exec()

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
        self.images_panel.shutdown()
        QApplication.instance().removeEventFilter(self)
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
        """Turn the Paint brush on/off (only possible while an Object is in Edit)."""
        self.set_brush_tool("paint" if on else "", redraw)

    def set_brush_tool(self, tool: str, redraw: bool = True) -> None:
        """Pick the Edit Layer tool ("" = none): paint | restore | object_fill | fill_holes | remove_specks.

        Auto tools compute their result right away: Fill mode writes it in (and
        keeps it live while settings move), Brush mode shows it as a gray guide.
        """
        on = bool(tool) and self.session.mode == Mode.EDIT and not self._busy
        tool = tool if on else ""
        if tool and tool == self._tool and tool in AUTO_TOOLS:
            tool = ""  # the active auto tool again = Esc: drop its result and leave it
        if tool != self._tool:
            self.close_tool()
        self._tool = tool
        auto = tool in AUTO_TOOLS
        self.session.set_auto_tool(tool if auto else None)
        if on:
            self.canvas.set_brush_tool(tool)
            if self.canvas.region_mode and not auto:
                self.set_region_mode(False, redraw=False)
        self.canvas.set_brush_mode(on and (not auto or self.session.auto_mode == "paint"))
        self.act_brush.setChecked(tool == "paint")
        self.properties_panel.set_brush_tool(tool)
        if auto:
            self._auto_refresh(redraw=False)
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

    def _frame_tools(self) -> list:
        """Goto (type an ID + Enter) and Focus buttons for a frame dock's title bar."""
        goto = QLineEdit()
        goto.setPlaceholderText("Go to ID")
        goto.setToolTip("Type an image ID and press Enter to open it")
        goto.setMinimumWidth(56)
        goto.setMaximumWidth(72)
        goto.returnPressed.connect(lambda: self.goto_frame(goto))
        focus = QToolButton()
        focus.setText("⌖")
        focus.setAutoRaise(True)
        focus.setToolTip("Scroll to the current frame (S)")
        focus.clicked.connect(self.focus_frame)
        return [goto, focus]

    def focus_frame(self) -> None:
        """S: scroll the frame list and strip to the current frame."""
        self.images_panel.focus_current()

    def goto_frame(self, field: QLineEdit) -> None:
        text = field.text().strip()
        n = len(self.session.keys)
        if not text.isdigit() or not 1 <= int(text) <= n:
            self.log(f"Go to: type an image ID from 1 to {n}")
            return
        field.clear()
        self.go_to(int(text) - 1)
        self.focus_frame()
        self.canvas.setFocus()

    def set_frame_names(self, on: bool) -> None:
        """Frame List: file names on, or folded to the IDs and marks (the column narrows)."""
        self.images_panel.set_names_visible(on)
        self._list_goto.setVisible(on)  # folded: the strip's Go-to field remains
        self.resizeDocks([self._list_dock], [210 if on else 80], Qt.Orientation.Horizontal)
        self.settings.frame_list_names = bool(on)
        self.settings.save(self.settings_path)

    def set_show_changes(self, on: bool) -> None:
        self.settings.show_edit_changes = bool(on)
        self.settings.save(self.settings_path)
        self._update_overlays()

    def set_region_mode(self, on: bool, redraw: bool = True) -> None:
        """A drag on the image sets the auto-tool region (box) instead of a SAM2 box or a stroke."""
        on = bool(on) and self.session.mode == Mode.EDIT and not self._busy
        if on and self._tool and self._tool not in AUTO_TOOLS:
            self.set_brush_tool("", redraw=False)
        self.canvas.set_region_mode(on)
        self.properties_panel.set_region_mode(on)
        if on:
            self.canvas.setFocus()
        if redraw:
            self.refresh()

    def on_region(self, region) -> None:
        self.session.set_region(region)
        self._auto_refresh()

    def on_region_box(self, x0: float, y0: float, x1: float, y1: float, subtract: bool) -> None:
        self.session.add_region_box((x0, y0, x1, y1), subtract)
        self._auto_refresh()

    def set_auto_mode(self, mode: str) -> None:
        """Fill <-> Paint with the tool on (same result; Paint shows the unpicked parts in gray)."""
        if mode == self.session.auto_mode:
            return  # the mode already in use: nothing to switch
        self.session.set_auto_mode(mode)
        if self.session.auto_tool:
            self.canvas.set_brush_mode(mode == "paint")
        self.refresh()

    def close_tool(self, apply: bool = False) -> None:
        """End an auto tool; only Apply & Close writes its result in (every other way out drops it)."""
        if self.session.auto_tool is None:
            return
        tool = self.session.auto_tool
        if self.session.close_auto(apply):
            self.log(f"{tool.replace('_', ' ').title()} applied")
        self._auto_gen += 1  # drop a computation still running

    def a_key(self) -> None:
        """A: in an auto tool's Paint mode pick all / none of the result (A / D never change image)."""
        s = self.session
        if s.auto_tool is None:
            return
        if s.auto_mode == "fill":  # into Paint mode with everything picked: then Alt+drag takes parts out
            s.set_auto_mode("paint")
            self.properties_panel._set_mode("paint")
            self.canvas.set_brush_mode(True)
            s.pick_everything()
            self.refresh()
        elif s.pick_all():
            self._update_overlays()

    def reapply_tool(self) -> None:
        """Write the auto tool's result in (Fill: all of it, Paint: the picks) and show the next one."""
        tool = self.session.auto_tool
        if tool is not None and self.session.apply_auto():
            self.log(f"{tool.replace('_', ' ').title()} applied")
        self.properties_panel.set_brush_tool(self._tool)  # the button stays on
        self._auto_refresh()  # recompute from the new mask

    def apply_and_leave_tool(self) -> None:
        self.close_tool(True)
        self.set_brush_tool("")

    def escape(self) -> None:
        """Esc: first leave the tool (dropping a Fill preview), then finish editing."""
        if self._tool:
            self.close_tool(apply=False)
            self.set_brush_tool("")
        else:
            self.finish_editing()

    def _auto_refresh(self, redraw: bool = True) -> None:
        """Recompute the auto tool's result (Object Fill off the UI thread) and show / apply it."""
        s = self.session
        tool = s.auto_tool
        base = s.auto_base() if tool else None
        if tool is None or base is None:
            if redraw:
                self.refresh()
            return
        settings = self.properties_panel.tool_settings()
        settings.pop("restore", None)
        self._auto_gen += 1
        gen = self._auto_gen
        target = s.auto_cached(tool, base, settings)
        if target is None and tool != "object_fill":
            target = s.auto_compute(tool, base, **settings)  # fast enough to stay on the UI thread
        if target is not None:
            self._auto_done(gen, base, target, redraw)
            return
        self.properties_panel.set_preview(0, 0, busy=True)
        self._start(Task(lambda: s.auto_compute(tool, base, **settings)), lambda t: self._auto_done(gen, base, t))

    def _auto_pending(self) -> bool:
        return self._auto_gen != self._auto_shown

    def _auto_done(self, gen: int, base, target, redraw: bool = True) -> None:
        if gen != self._auto_gen or self.session.auto_tool is None:
            return  # a newer setting or another tool took over
        self._auto_shown = gen
        self.session.auto_apply(base, target)
        if redraw:
            self.refresh()
        else:
            self._update_overlays()

    def on_tool_stroke(self, tool: str, area, unpick: bool = False) -> None:
        """An auto tool's Paint-mode stroke was released: pick (Alt: unpick) that part of the result."""
        if tool in AUTO_TOOLS and self.session.pick(area, unpick):
            self._update_overlays()

    def _tool_target(self, tool: str):
        """For a live Restore stroke: the edited mask with the edit layer undone (per the mode box)."""
        return self.session.tool_result(tool, restore=self.properties_panel.tool_settings()["restore"])

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
                break  # empty space keeps the selection (the Objects panel's empty space clears it)
        self.refresh()

    def step_object(self, delta: int) -> None:
        """Up / Down: the previous / next Object with a mask on this image (Edit follows it)."""
        s = self.session
        key = s.key
        if key is None or self._busy:
            return
        ids = [o.id for o in s.project.objects if o.mask(key) is not None]
        oid = self.objects_panel.move_selection(ids, delta)
        if oid is None:
            return
        self.objects_panel.select_ids([oid])
        if s.mode == Mode.EDIT and s.editing != oid and not self.picking():
            self.close_tool(apply=False)
            self.set_brush_tool("", redraw=False)
            s.edit(oid)
        self.refresh()

    def on_brush(self, mask) -> None:
        self._do(lambda: self.session.brush(mask))

    def on_properties_variant(self, index: int) -> None:
        oid = self.shown_object_id()
        if oid is not None:
            self._do(lambda: self.session.select_variant(index, oid))

    def new_object(self) -> None:
        if self._no_edit_while_picking():
            return
        self.close_tool()
        if self.session.key is None or self._busy:
            return
        self.session.start_new_object()
        self.canvas.setFocus()
        self.refresh()

    def toggle_edit(self, oid: int) -> None:
        if self.session.editing != oid and self._no_edit_while_picking():
            self.refresh()  # the row's Edit button springs back
            return
        self.close_tool()
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
        self.close_tool()
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
            if dets:
                self.detection_panel.select_btn.setChecked(True)  # pick them on the image right away
            self.refresh()

        def failed(msg):
            self._busy = None
            self.detection_panel.set_busy(False, "Detection failed")
            self.refresh()
            self.warn(f"SAM3 detection failed: {msg}")

        self._start(Task(run), done, failed)
        self.refresh()

    def picking(self) -> bool:
        """Select on Image is on (and there are Detections to pick)."""
        return self.detection_panel.select_btn.isChecked() and bool(self.session.detections)

    def set_picking(self, on: bool) -> None:
        """Select on Image: clicks pick Detections; Edit is left and blocked meanwhile."""
        if on and self.session.mode != Mode.IDLE:
            self.close_tool()
            self.session.finish_editing()
        self.refresh()

    def _no_edit_while_picking(self) -> bool:
        if self.picking():
            self.log("Turn off Select on Image (Detection tab) to edit Objects")
            return True
        return False

    def on_candidates_clicked(self, x: float, y: float, op: str) -> None:
        """Click = add the candidate under the cursor, Shift = toggle it, Ctrl = remove it."""
        i = self.session.detection_at(x, y)
        if i is not None and self.session.check_detections([i], op):
            self.refresh()

    def on_candidates_boxed(self, x0: float, y0: float, x1: float, y1: float, op: str) -> None:
        """Drag = add every candidate the box touches, Shift = toggle them, Ctrl = remove them."""
        s = self.session
        if s.check_detections(s.detections_in_box((x0, y0, x1, y1)), op):
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
        self.batch_panel.set_busy(True, self._busy + ("" if engine.sam3_ready else " (loading SAM3 first)"))
        self.batch_panel.batch_begin(len(indices))
        self.log(f"Batch masking {text} on {len(indices)} image(s), min score {threshold:.2f}")

        def run(cancel, progress):
            if not engine.sam3_ready:
                engine.load_sam3()
            return batch_detect(engine, paths, indices, labels, max_side, threshold, cancel=cancel, progress=progress)

        def on_frame(idx, hits):
            found = any(h.mask is not None for h in hits.values())
            self.batch_panel.batch_frame(idx, f"{s.keys[idx]}   {summarize(hits)}", found)

        def finish(results, outcome):
            self._busy = None
            self._prop_worker = None
            if self._discard:
                self._discard = False
                self.batch_panel.set_busy(False)
                self.batch_panel.batch_end(f"Cancelled: nothing added ({len(results)} image(s) discarded)")
                self.log("Batch masking cancelled — results discarded")
                self.refresh()
                return
            made = s.apply_batch(results) if results else {}
            names = ", ".join(s.project.get(oid).name for oid in made.values())
            found = sum(1 for hits in results.values() if any(h.mask is not None for h in hits.values()))
            msg = f"{outcome}: {len(results)} image(s) processed, {found} with detections" + (
                f" → {names}" if names else " — nothing above the score threshold"
            )
            self.batch_panel.set_busy(False)
            self.batch_panel.batch_end(msg)
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

    def set_reference(self, index: int) -> None:
        """Double-clicked image: propagation starts from it (double-click it again to go back to current)."""
        self._reference = None if index == self._reference else index
        self.refresh()

    def set_pinned(self, on: bool) -> None:
        self._pinned = self.images_panel.selected_rows() if on else None
        self.refresh()

    def propagate(self, start: int, end: int, direction: Direction, scope: str = "range") -> None:
        """Propagate the checked Objects from the reference image over *scope*:
        ``selection`` (Images list, or the pinned one) · ``range`` (start..end) · ``all``."""
        s = self.session
        if s.key is None or self._busy:
            return
        ref = self._reference if self._reference is not None else s.index
        if scope == "all":
            plan = PropagationPlan(0, len(s.keys) - 1, ref, direction)
        elif scope in ("selection", "custom"):
            if scope == "custom":
                picked = self.propagation_panel.custom_ids
            else:
                picked = self._pinned if self._pinned is not None else self.images_panel.selected_rows()
            if not [i for i in picked if i != ref]:
                self.warn("Select the images to propagate to in the Images list (Shift/Ctrl-click), or pin them.")
                return
            plan = PropagationPlan.of_frames(picked, ref, direction)
        else:
            if not (start <= ref <= end):
                self.warn("The reference image must lie within Start ~ End.")
                return
            plan = s.plan(start, end, direction, reference=ref)
        if not plan.targets:
            self.warn("Nothing to propagate: no images in that direction.")
            return
        seeds = s.seeds(ref)
        if not seeds:
            self.warn(f"Check at least one Object that has a mask on the reference image ({s.keys[ref]}).")
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
        self._prop_queue = []
        self._run_propagation(plan, seeds)

    def _run_propagation(self, plan: PropagationPlan, seeds) -> None:
        s = self.session
        propagate = self.propagate_fn or default_propagate()
        ckpt, paths, max_side = self.settings.sam2_checkpoint, list(s.paths), s.max_side

        self.close_tool()
        s.finish_editing()
        self._busy = "Propagating…"
        names = [(oid, s.project.get(oid).name) for oid in seeds]
        self.propagation_panel.begin(plan, names)
        self.tabs.setCurrentWidget(self.propagation_panel)
        self.log(
            f"Propagating {len(seeds)} Object(s) from {s.keys[plan.current]} over {len(plan.targets)} image(s) "
            f"({plan.direction.value})"
        )
        self._last_prop = (plan, list(seeds), set())
        self.propagation_panel.set_resumable(False)

        def run(cancel, progress):
            return propagate(ckpt, paths, plan, seeds, max_side, cancel=cancel, progress=progress)

        w = PropagationWorker(run, self)
        w.progress.connect(self.propagation_panel.on_progress)
        w.frame_done.connect(lambda idx, masks: self.propagation_panel.on_frame(idx, list(masks)))
        w.frame_done.connect(lambda idx, _masks: self._last_prop[2].add(idx))
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
        if outcome == "Done" and self._prop_queue:
            self.refresh()
            self._run_next_queued()  # Resume: the other direction
            return
        resumable = outcome != "Done" and bool(self._remaining_plans())
        self.propagation_panel.set_resumable(resumable)
        if resumable:
            self.log("Resume continues from the last frame reached")
        self.refresh()

    def _remaining_plans(self) -> List[tuple]:
        """After a stop: per direction, (plan over the frames left, object ids), starting at the last frame done."""
        if self._last_prop is None:
            return []
        plan, ids, done = self._last_prop
        out = []
        for targets, direction in ((plan.backward, Direction.BACKWARD), (plan.forward, Direction.FORWARD)):
            left = [i for i in targets if i not in done]
            if not left:
                continue
            reached = [i for i in targets if i in done]  # targets run outward, so the last one is the edge
            start = reached[-1] if reached else plan.current
            out.append((PropagationPlan.of_frames(left, start, direction), ids))
        return out

    def resume_propagation(self) -> None:
        """Continue a stopped propagation: each direction from the last frame it reached."""
        if self._busy:
            return
        self._prop_queue = self._remaining_plans()
        self._run_next_queued()

    def _run_next_queued(self) -> None:
        while self._prop_queue:
            plan, ids = self._prop_queue.pop(0)
            seeds = self.session.seeds(plan.current, ids=ids)
            if seeds:
                self._run_propagation(plan, seeds)
                return
            self.log(f"Nothing to resume from {self.session.keys[plan.current]}: no masks there")
        self.propagation_panel.set_resumable(False)
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
            self.batch_panel.batch_stopping()
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
