"""Main window: wires the Session to the canvas and panels (spec 01 §5 layout).

Menu bar (File, Edit, View, Go, Help: every command and its key, see
docs/design/menu-design.md) · toolbar with the often-used view / tool toggles (Mask
Preview + mode, Brush, Outline + width, Show Changes) ·
left Objects + Images · center canvas · right Properties · bottom
Prompt/Detection, Propagation and Logs tabs · status bar with the mode.

SAM2 clicks run on the UI thread (they are fast once the image embedding
exists); model loading, SAM3 detection, export and propagation run in
``QThread`` workers. The window never mutates the project directly: every
action goes through ``Session`` and then ``refresh()`` redraws all views.
"""

from __future__ import annotations

import html
import time
from pathlib import Path
from typing import Callable, List, Optional

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QAction, QCursor, QKeySequence
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
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
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolBar,
    QToolButton,
)

from src.app.canvas import Canvas, Overlay
from src.app.batch_panel import BatchPanel
from src.app.detection_panel import DetectionPanel, candidate_color
from src.app.dialogs import ExportDialog, OptionsDialog, SettingsDialog, ShortcutsDialog
from src.app.images_panel import ImagesPanel
from src.app.objects_panel import ObjectsPanel
from src.app.propagation_panel import PropagationPanel
from src.app.properties_panel import AUTO_TOOLS, PropertiesPanel
from src.app.session import Mode, Session
from src.app.ui_util import DockTitleBar
from src.app.settings import DEFAULT_PATH, Settings
from src.app.workers import PropagationWorker, Task
from src.core.project import FrameStatus, Source
from src.core.propagation import Direction, PropagationPlan
from src.core.colmap import find_scene, matched, scene_root, white_share
from src.core.colmap_model import build_dataset, dataset_blocker
from src.core.reproject import MaskJob, Stitch, Views, convert, stitch_to_erp
from src.core.storage import check_export, default_export_dir, full_mask
from src.logging_config import get_logger

logger = get_logger(__name__)


AUTO_ADD_COLOR = (255, 40, 220)  # magenta: an auto tool adds these pixels
AUTO_SUB_COLOR = (130, 60, 255)  # purple: ...and removes these

SOURCE_SHORT = {  # how an Object was made, in the work bar
    Source.SAM3_DETECTION: "SAM3",
    Source.SAM3_BATCH: "SAM3 batch",
    Source.SAM2_POINT: "SAM2",
    Source.SAM2_BOX: "SAM2 box",
    Source.MERGED: "merged",
    Source.DUPLICATE: "copy",
}


# Keys that move while the mouse is over a list (see MainWindow.eventFilter): -1 = back, +1 = on
HOVER_KEYS = {
    Qt.Key.Key_W: -1, Qt.Key.Key_A: -1, Qt.Key.Key_Up: -1, Qt.Key.Key_Left: -1,
    Qt.Key.Key_S: 1, Qt.Key.Key_D: 1, Qt.Key.Key_Down: 1, Qt.Key.Key_Right: 1,
}


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
        self.scene = None  # the COLMAP scene the open folder belongs to (src/core/colmap.py)
        self._pinned: Optional[List[int]] = None  # the pinned Frame List selection (Selection scope)
        # a stopped propagation: (plan, object ids, frames done), and plans queued by Resume
        self._last_prop: Optional[tuple] = None
        self._prop_queue: List[tuple] = []
        self._tool = ""  # the Edit Layer tool in use ("" = none)
        self._auto_gen = 0  # newest auto-tool computation; older results are dropped
        self._auto_shown = 0  # the computation whose result is on screen
        self._goto_fields: List[QLineEdit] = []  # Frame List, frame strip
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
        # the work bar over the canvas: which frame, which Object, which tool - at a glance
        self.work_bar = QLabel()
        self.work_bar.setObjectName("work_bar")
        self.work_bar.setTextFormat(Qt.TextFormat.RichText)
        self.work_bar.setStyleSheet("#work_bar { padding: 3px 8px; font-weight: 600; border-bottom: 1px solid palette(mid); }")
        # a long line is clipped, never widening the canvas (that pushed the side panels around)
        self.work_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.work_bar.setMinimumWidth(50)
        center = QWidget()
        cb = QVBoxLayout(center)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(0)
        cb.addWidget(self.work_bar)
        cb.addWidget(self.canvas, 1)
        self.setCentralWidget(center)

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
        self.tabs.setUsesScrollButtons(False)  # a narrow column elides the tab names instead of hiding tabs
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
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
        list_box = QWidget()  # the list with its Go-to / Focus row underneath
        lb = QVBoxLayout(list_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.setSpacing(2)
        lb.addWidget(self.images_panel.frame_list, 1)
        self._list_summary = self.images_panel.summary_label()  # ★ ✓ ⚠ ✕ counts (hidden when folded)
        lb.addWidget(self._list_summary)
        lb.addLayout(self._frame_tools())
        strip_row = self._frame_tools()  # and under the strip, with its own counts
        strip_row.addWidget(self.images_panel.summary_label())
        self.images_panel.layout().addLayout(strip_row)
        list_dock = self._dock("Frame List", list_box, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.splitDockWidget(list_dock, left_dock, Qt.Orientation.Horizontal)
        self.names_btn = QToolButton()  # left of the close button: fold the file names away
        self.names_btn.setText("Aa")
        self.names_btn.setCheckable(True)
        self.names_btn.setAutoRaise(True)
        self.names_btn.setToolTip("Show the file names (off: only IDs and marks, a narrow list)")
        self.names_btn.toggled.connect(self.set_frame_names)
        self.marks_btn = QToolButton()  # the marks for the shown Object only
        self.marks_btn.setText("1")
        self.marks_btn.setCheckable(True)
        self.marks_btn.setAutoRaise(True)
        self.marks_btn.setToolTip(
            "Marks for the selected Object only: – where it has no mask (off: every Object)"
        )
        self.marks_btn.toggled.connect(self.set_marks_one_object)
        self._list_title = DockTitleBar(list_dock, [self.marks_btn, self.names_btn])
        list_dock.setTitleBarWidget(self._list_title)
        self._list_dock = list_dock
        self._docks = (list_dock, left_dock, right_dock, frames_dock)  # View > Panels
        # the frame strip spans only the canvas: the side docks keep the full height
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self._dock_sizes = ([list_dock, left_dock, right_dock], [210, 380, 380], [frames_dock], [190])
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
        h_sizes = [self._list_width(), *h_sizes[1:]]  # the Frame List starts folded or not, as last time
        budget = int(self.width() * 0.55)  # a small window: the side panels share at most ~55%, the canvas keeps the rest
        if sum(h_sizes) > budget:
            scale = budget / sum(h_sizes)
            h_sizes = [max(d.minimumSizeHint().width(), int(w * scale)) for d, w in zip(h_docks, h_sizes)]
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
        a.setStatusTip(tip or text)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _hint(self, menu, text: str, key: str, slot=None):
        """A menu entry that shows a key handled elsewhere (Enter, Z held, hover keys) without binding it.

        With *slot* it runs that when picked from the menu; without, it is a grayed-out note.
        """
        a = menu.addAction(f"{text}\t{key}")
        if slot is None:
            a.setEnabled(False)
        else:
            a.triggered.connect(slot)
        return a

    def _build_actions(self) -> None:
        # --- File / Edit: less used, in the menu bar (docs/design/menu-design.md) -------------
        self.act_open = self._action("&Open Folder…", self.choose_folder, ["Ctrl+O"], "Open an image folder")
        self.act_import_masks = self._action(
            "&Import Masks from Folder…", self.choose_mask_folder,
            tip="A folder of mask images (a.jpg.png or a.png) as a new Object",
        )
        self.act_save = self._action(
            "&Save", lambda: self.save(force=True), ["Ctrl+S"], "Save the project (also autosaved)"
        )
        self.act_export = self._action("&Export Final Masks…", self.export, ["Ctrl+E"], "Export Final Mask PNGs")
        self.act_settings = self._action("Se&ttings…", self.show_settings, tip="Checkpoints, working resolution")
        self.act_quit = self._action("&Quit", self.close)  # no key: too easy to hit next to Ctrl+Z / Ctrl+A
        self.act_undo = self._action("&Undo", self.undo, ["Ctrl+Z"])
        self.act_redo = self._action("&Redo", self.redo, ["Ctrl+Y", "Ctrl+Shift+Z"])
        self.act_new = self._action("&New Object from Points", self.new_object, ["N"],
                                    "Then click (or drag a box) on the image")
        self.act_edit = self._action("&Edit Points / Finish", self.edit_key, ["E"],
                                     "Edit the selected Object with SAM2 points; again: finish")
        self.act_delete = self._action("&Delete", self.delete_key, ["Delete"],
                                       "The selected point, else the selected Objects")
        self.act_escape = self._action("Leave Tool / Finish Editing", self.escape, ["Esc"],
                                       "Leave the tool (drops an auto tool's result), then finish editing")
        # whole-mask edits: easy while editing (a key), otherwise not bound at all (docs/design/ux-principles.md 7)
        self.act_invert = self._action(
            "Invert Mask", lambda: self.mask_edit("invert"), ["Ctrl+I"],
            "The edited Object's mask on this image, flipped (inside the region, if any). Only while editing",
        )
        self.act_clear_mask = self._action(
            "Clear Mask", lambda: self.mask_edit("clear"), ["Ctrl+Backspace"],
            "Empty the edited Object's mask on this image (inside the region, if any). Only while editing",
        )
        self.act_pick_all = self._action("Auto Tool: Pick All / None", self.a_key, ["A"],
                                         "Fill mode -> Paint mode with everything picked; Paint mode: all / none")
        # Ctrl+D / Ctrl+Shift+D only with the mouse over the Objects panel (eventFilter): shown, not bound
        self.act_duplicate = self._action(
            "Duplicate (this image)\tCtrl+D", lambda: self.duplicate(self.objects_panel.selected_ids()),
            tip="Copy the selected Objects' mask on this image only (Ctrl+D with the mouse over Objects)",
        )
        self.act_duplicate_all = self._action(
            "Duplicate All (every linked mask)\tCtrl+Shift+D",
            lambda: self.duplicate(self.objects_panel.selected_ids(), all_frames=True),
            tip="Copy the selected Objects with their masks on every image (Ctrl+Shift+D with the mouse over Objects)",
        )
        self.act_move = self._action(
            "Move A → B", lambda: self.transfer(self.objects_panel._pair()),
            tip="Move the first selected Object's mask on this image into the last selected (Add)",
        )
        self.act_transfer_options = self._action(
            "Move / Copy (Options)…", lambda: self.transfer_options(self.objects_panel._pair()),
            tip="Move or Copy · Add / Replace · this image / every image",
        )
        self.act_merge = self._action(
            "Merge", lambda: self.merge(self.objects_panel.selected_ids()),
            tip="Fuse the selected Objects into one (the union)",
        )
        self.act_merge_options = self._action(
            "Merge (Options)…", lambda: self.merge_options(self.objects_panel.selected_ids()),
            tip="Add, or Override with A / B",
        )
        self.act_lock = self._action(
            "Lock / Unlock", lambda: self.toggle_lock(self.objects_panel.selected_ids()),
            tip="Locked Objects cannot be deleted",
        )
        self.act_lock_all = self._action(
            "Lock All", lambda: self.set_locked([o.id for o in self.session.project.objects], True)
        )
        self.act_unlock_all = self._action(
            "Unlock All", lambda: self.set_locked([o.id for o in self.session.project.objects], False)
        )

        # --- View / tool toggles: used all the time, also on the toolbar ------------------
        self.act_final = self._action(
            "Mask Preview",
            self.toggle_final,
            ["V"],
            "Show the mask in black and white (hold Z to peek; editing keeps working)",
            True,
        )
        # what Mask Preview shows: the Final Mask (every checked Object) or the selected Object's mask
        self.act_preview_mode = self._action("Toggle Final / Object Mask", self.toggle_preview_mode, ["X"])
        self._show_preview_mode()
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
            "Show Changes",
            self.set_show_changes,
            ["R"],
            tip="Tint what the edit layer added (green) and removed (red)",
            checkable=True,
        )
        self.act_changes.setChecked(self.settings.show_edit_changes)
        # which Objects the canvas colors: all, only the selected / edited ones (Solo), or none (Hide)
        self.act_solo = self._action(
            "Solo", lambda _on: self._update_overlays(),
            tip="Color only the selected Objects (and the one in Edit) on the canvas", checkable=True,
        )
        self.act_hide_masks = self._action(
            "Hide Masks", lambda _on: self._update_overlays(),
            tip="No Object colors on the canvas (the Object in Edit still shows)", checkable=True,
        )
        for a in (self.act_final, self.act_preview_mode, self.act_brush, self.act_outline, self.act_changes,
                  self.act_pick_all, self.act_edit, self.act_new, self.act_solo, self.act_hide_masks,
                  self.act_invert, self.act_clear_mask):
            a.setAutoRepeat(False)  # held down: one toggle, not a flicker

        # --- Go: moving between frames and Objects ----------------------------------------
        self.act_prev_frame = self._action("&Previous Frame", lambda: self.step(-1), ["Left", "PgUp"],
                                           "Not while editing")
        self.act_next_frame = self._action("&Next Frame", lambda: self.step(1), ["Right", "PgDown"],
                                           "Not while editing")
        self.act_prev_object = self._action("Previous Object", lambda: self.step_object(-1), ["Up"],
                                            "The previous Object with a mask on this image (Edit follows)")
        self.act_next_object = self._action("Next Object", lambda: self.step_object(1), ["Down"],
                                            "The next Object with a mask on this image (Edit follows)")
        self.act_prev_problem = self._action("Previous Problem (⚠ ✕)", lambda: self.step_problem(-1), ["["])
        self.act_next_problem = self._action("Next Problem (⚠ ✕)", lambda: self.step_problem(1), ["]"])
        self.act_prev_key = self._action("Previous Keyframe ★", lambda: self.step_keyframe(-1), [","])
        self.act_next_key = self._action("Next Keyframe ★", lambda: self.step_keyframe(1), ["."])
        self.act_go_reference = self._action("Go to Reference ◎", self.go_to_reference, ["F"],
                                             "The propagation reference (the double-clicked image)")
        self.act_exclude = self._action(
            "Exclude from Dataset / Include", self.toggle_excluded,
            tip="The picked frames (or this one) are left out of a new dataset (⊘); again: back in. "
                "The source scene is never changed",
        )
        self.act_shortcuts = self._action("&Keyboard Shortcuts", self.show_shortcuts, ["F1"])

        # --- the menu bar: every command, with its key -----------------------------------
        mb = self.menuBar()
        m = mb.addMenu("&File")
        for a in (self.act_open, self.act_import_masks, self.act_save, self.act_export, None, self.act_settings, None,
                  self.act_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = mb.addMenu("&Edit")
        for a in (self.act_undo, self.act_redo, None, self.act_new, self.act_edit, self.act_delete,
                  self.act_escape):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        tools = m.addMenu("Tools")
        tools.addAction(self.act_brush)
        tools.addAction(self.act_invert)
        tools.addAction(self.act_clear_mask)
        tools.addAction(self.act_pick_all)
        self._hint(tools, "Auto Tool: Apply && Continue", "Enter", self.reapply_tool)
        self._hint(tools, "Leave the Active Auto Tool", "its button again")
        objects = m.addMenu("Objects")
        for a in (self.act_duplicate, self.act_duplicate_all, None, self.act_move, self.act_transfer_options,
                  self.act_merge, self.act_merge_options, None, self.act_lock, self.act_lock_all,
                  self.act_unlock_all):
            objects.addSeparator() if a is None else objects.addAction(a)
        m = mb.addMenu("&View")
        for a in (self.act_final, self.act_preview_mode):
            m.addAction(a)
        self._hint(m, "Peek at Mask Preview", "Z (hold)")
        for a in (self.act_outline, self.act_changes, None, self.act_solo, self.act_hide_masks):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        panels = m.addMenu("Panels")
        for d in self._docks:
            panels.addAction(d.toggleViewAction())
        m = mb.addMenu("&Go")
        for a in (self.act_prev_frame, self.act_next_frame, self.act_prev_object, self.act_next_object, None,
                  self.act_prev_problem, self.act_next_problem, self.act_prev_key, self.act_next_key, None,
                  self.act_go_reference):
            m.addSeparator() if a is None else m.addAction(a)
        m.addAction(self.act_exclude)
        self._hint(m, "Set Current Frame as Reference ◎", "Enter",
                   lambda: self.session.key is not None and self.set_reference(self.session.index))
        self._hint(m, "Mouse over a frame list: Set as Reference ◎", "Space")
        m.addSeparator()
        self._hint(m, "Mouse over a frame list: frames", "W A S D / arrows")
        self._hint(m, "Mouse over the Objects list: Objects", "W A S D / arrows")
        self._hint(m, "Mouse over the image: Objects", "W / S")
        m = mb.addMenu("&Help")
        m.addAction(self.act_shortcuts)

        # --- the toolbar: only what is toggled all the time while working ---------------------
        tb = QToolBar("Main")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.addAction(self.act_final)
        tb.addAction(self.act_preview_mode)
        tb.addAction(self.act_brush)
        tb.addSeparator()
        tb.addAction(self.act_outline)
        tb.addWidget(self.outline_width)
        tb.addSeparator()
        tb.addAction(self.act_changes)
        tb.addSeparator()
        tb.addAction(self.act_solo)
        tb.addAction(self.act_hide_masks)
        self.addToolBar(tb)
        self.names_btn.setChecked(self.settings.frame_list_names)
        self.images_panel.set_names_visible(self.settings.frame_list_names)
        self._list_title.set_compact(not self.settings.frame_list_names)
        self._list_summary.setVisible(self.settings.frame_list_names)
        self.marks_btn.setChecked(self.settings.marks_one_object)
        pp = self.properties_panel  # the foldable Edit Layer sections remember their state
        for box, name in ((pp.settings_box, "tool_settings_open"), (pp.layer_box, "layer_section_open")):
            box.set_open(getattr(self.settings, name))
            box.toggled_open.connect(lambda on, n=name: self._remember(n, on))
        self.canvas.set_outline(self.settings.outline_visible, self.settings.outline_width)

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
        o.merge_options_requested.connect(self.merge_options)
        o.duplicate_requested.connect(self.duplicate)
        o.duplicate_all_requested.connect(lambda ids: self.duplicate(ids, all_frames=True))
        o.transfer_requested.connect(lambda ids, move: self.transfer(ids, move=move))
        o.transfer_options_requested.connect(self.transfer_options)
        o.lock_requested.connect(self.set_locked)
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

    def choose(self, title: str, text: str, groups, ok: str = "OK") -> Optional[List[int]]:
        """Radio-choice dialog: the picked index per group, None when cancelled; tests replace this."""
        dlg = OptionsDialog(title, text, groups, ok, self)
        return dlg.choice() if dlg.exec() == OptionsDialog.DialogCode.Accepted else None

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

        fs = s.editing_frame()
        self.canvas.set_prompts(fs.points if fs else (), s.selected_point, fs.box if fs else None)
        editing_obj = project.get(s.editing) if s.editing is not None else None
        mode = s.effective_mode
        if s.mode != Mode.EDIT and (self._tool or self.canvas.brush_mode):
            self.set_brush_tool("", redraw=False)
        if s.auto_stale() and not self._auto_pending():
            QTimer.singleShot(0, self._auto_refresh)  # the mask changed (undo, a click): recompute
        if s.mode != Mode.EDIT and self.canvas.region_mode:
            self.set_region_mode(False, redraw=False)
        self.canvas.set_region(s.region)
        self.properties_panel.set_region(s.region)
        self.canvas.set_mode(mode)  # what is being edited is on the work bar (no banner on the image)

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
        self.images_panel.set_excluded(project.excluded)
        self.images_panel.update_marks(project, self.marks_object())
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
            Mode.IDLE: "Ready — use an Object's Points button (E), + New Object from Points (N), or a SAM3 prompt",
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
        self.work_bar.setText(self.work_status())
        self.image_label.setText(f"{s.index + 1}/{len(s.keys)}  {key}" if has_folder else "")
        eng = s.engine
        self.model_label.setText(
            (f"SAM2 loading… ({len(s.pending)} waiting)" if s.pending else "SAM2 loading…")
            if self._loading_models
            else ("SAM2 ✓" if eng is not None and eng.sam2_ready else "SAM2 ✕")
            + ("  SAM3 ✓" if eng is not None and eng.sam3_ready else "")
        )
        if s.store is not None and not s.store.is_saved(project):
            self._autosave.start()

    def work_status(self) -> str:
        """The work bar's text: Frame n / N · file │ Object: name (source) │ Mode: what the image does now."""
        s = self.session
        if s.key is None:
            return "No folder open — File ▸ Open (Ctrl+O)"
        sep = "&nbsp;&nbsp;│&nbsp;&nbsp;"
        frame = f"Frame {s.index + 1} / {len(s.keys)}"
        name = f"<span style='font-weight: 400; color: gray'>{html.escape(s.key)}</span>"  # last: clipped first
        ids = self.objects_panel.selected_ids()
        oid = self.shown_object_id()
        o = s.project.get(oid) if oid is not None else None
        if o is not None:
            r, g, b = o.color
            src = SOURCE_SHORT.get(o.source, o.source.value)
            obj = f"<span style='color: rgb({r},{g},{b})'>■</span> {html.escape(o.name)} ({src})"
        elif len(ids) > 1:
            obj = f"{len(ids)} selected"
        else:
            obj = "—"
        if self._busy:
            mode = self._busy
        elif self.picking():
            mode = "Select on Image"
        elif s.mode == Mode.NEW_OBJECT:
            mode = "New Object"
        elif s.mode == Mode.EDIT:
            tool = self._tool
            if tool in AUTO_TOOLS:
                mode = f"Auto · {tool.replace('_', ' ').title()} ({s.auto_mode.title()})"
            elif tool:
                mode = tool.replace("_", " ").title()
            else:
                mode = "Points"
            if self.canvas.region_mode:
                mode += " + Region"
        else:
            mode = "View"
        return f"{frame}{sep}Object: {obj}{sep}Mode: {html.escape(mode)}{sep}{name}"

    def _colored_ids(self) -> Optional[set]:
        """The Objects the canvas colors besides the one in Edit: None = all (Solo: the selected, Hide: none)."""
        if self.act_hide_masks.isChecked():
            return set()
        if self.act_solo.isChecked():
            return set(self.objects_panel.selected_ids())
        return None

    def _update_overlays(self) -> None:
        """Hand the canvas the mask layers of the current image (Objects, edit layer, candidates)."""
        s = self.session
        key = s.key
        self._update_preview_mask()
        overlays: List[Overlay] = []
        edit_layer = None
        shown = self._colored_ids()
        for o in s.project.objects:
            m = o.mask(key) if key else None
            if m is None:
                continue
            if o.id == s.editing:
                edit_layer = Overlay(m, o.color, "edit")
            elif shown is None or o.id in shown:
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
        folder = Path(folder)
        if scene_root(folder) == folder:
            folder = folder / "images"  # a COLMAP scene: its images/ (docs/specs/06-colmap.md)
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
        self.scene = find_scene(folder)
        self.setWindowTitle(f"SAM Mask Studio — {folder}" + (" (COLMAP scene)" if self.scene else ""))
        loaded = len(self.session.project.objects)
        self.log(f"Opened {folder} ({n} images" + (f", {loaded} saved Objects)" if loaded else ")"))
        if self.scene is not None:
            self._report_scene(self.scene)
        self.ensure_models()
        self.refresh()
        if self.scene is not None and not loaded and self.scene.mask_dirs:
            self.offer_masks(self.scene.mask_dirs, "Masks in this COLMAP scene", undoable=False)
        return True

    def _report_scene(self, scene) -> None:
        """The scene's model in the log: counts, camera models, images that do not match."""
        self.log(scene.summary() + (f" · cameras: {', '.join(scene.camera_models)}" if scene.camera_models else ""))
        files, model = set(self.session.keys), set(scene.image_names)
        for what, names in (("in the model but not in images/", model - files),
                            ("in images/ but not in the model", files - model)):
            if names and model:
                shown = ", ".join(sorted(names)[:5]) + (" …" if len(names) > 5 else "")
                self.log(f"⚠ {len(names)} image(s) {what}: {shown}")

    def offer_masks(self, folders, title: str, undoable: bool = True) -> List[int]:
        """Ask which mask folders to load as Objects and which color is the object in each.
        *undoable* False (a scene's masks, as it opens): they are where Ctrl+Z starts, not a step of it."""
        keys = list(self.session.keys)
        groups, found = [], []
        for d in folders:
            n = len(matched(d, keys))
            if not n:
                continue
            share = white_share(d, keys)
            black = share is not None and share > 0.5  # mostly white: the object is probably black
            groups.append((f"{d.name}/ — masks for {n} of {len(keys)} images",
                           ["Skip", "White = the object", "Black = the object"], 2 if black else 1))
            found.append(d)
        if not found:
            self.log("No masks matching these images (a.jpg.png or a.png)")
            return []
        how = "Ctrl+Z undoes it" if undoable else "they open with the scene, Ctrl+Z does not remove them"
        picked = self.choose(title, f"Load mask folders as Objects (one Object per folder; {how}).",
                             groups, "Load")
        if picked is None:
            return []
        chosen = [(d, p == 2) for d, p in zip(found, picked) if p]
        if not chosen:
            return []

        def progress(done, total):
            if done % 50 == 0 or done == total:
                self.statusBar().showMessage(f"Loading masks {done} / {total}…")
                QApplication.processEvents()

        ids = self.session.import_masks(chosen, progress)
        if not undoable:
            self.session.project.forget_history()
        self._select_new(ids)
        for oid in ids:
            o = self.session.project.get(oid)
            self.log(f"Loaded {o.name}: masks on {len(o.frames)} image(s)")
        return ids

    def choose_mask_folder(self) -> None:
        if self.session.image_dir is None:
            return
        start = str(self.scene.root if self.scene else self.session.image_dir.parent)
        d = QFileDialog.getExistingDirectory(self, "Mask folder to load as an Object", start)
        if d:
            self.offer_masks([Path(d)], "Import Masks")

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
        if t in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            hover = self._hover_step(event)
            if hover is not None:
                if t == QEvent.Type.ShortcutOverride:
                    event.accept()  # not the menu shortcut (A, D, S, arrows): the key press comes here instead
                    return True
                zone, delta = hover
                if zone == "frames":
                    self.step(delta)
                else:  # the Objects list or the canvas: the list's rows
                    self.step_object(delta, self.objects_panel.listed_ids())
                return True
        if (
            t in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
            and event.key() == Qt.Key.Key_D
            and event.modifiers() in (Qt.KeyboardModifier.ControlModifier,
                                      Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            and not isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox, QPlainTextEdit))
            and self.isActiveWindow()
            and self._over_objects_panel()
        ):
            if t == QEvent.Type.KeyPress and not event.isAutoRepeat():
                every = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self.duplicate(self.objects_panel.selected_ids(), all_frames=every)  # Ctrl+D / Ctrl+Shift+D
            event.accept()
            return True
        if (
            t in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
            and event.key() == Qt.Key.Key_Space
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
            and self.session.key is not None
            and not isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox, QPlainTextEdit))
            and self.isActiveWindow()
            and self._hover_zone() == "frames"
        ):
            if t == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self.set_reference(self.session.index)  # Space over a frame list = Enter (canvas: Space pans)
            event.accept()
            return True
        if (
            t == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.session.auto_tool is not None
            and not isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox, QPlainTextEdit))
            and self.isActiveWindow()
        ):
            self.reapply_tool()  # Enter = Apply & Continue
            return True
        if (
            t == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
            and self.session.key is not None
            and not isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox, QPlainTextEdit))
            and self.isActiveWindow()
        ):
            if not event.isAutoRepeat():  # held: set once, not toggled back and forth
                self.set_reference(self.session.index)  # Enter (no auto tool) = the current image is the reference ◎
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

    def _hover_zone(self) -> Optional[str]:
        """The list under the mouse: ``frames`` (Frame List, Frames strip), ``objects`` or None."""
        return self._zone_of(QApplication.widgetAt(QCursor.pos()))

    def _over_objects_panel(self) -> bool:
        """The mouse is over the Objects panel (its list or its buttons)."""
        w = QApplication.widgetAt(QCursor.pos())
        while w is not None:
            if w is self.objects_panel:
                return True
            w = w.parentWidget()
        return False

    def _zone_of(self, w) -> Optional[str]:
        ip = self.images_panel
        while w is not None:
            if w is ip.frame_list or w is ip.list:
                return "frames"
            if w is self.objects_panel.tree:
                return "objects"
            if w is self.canvas:
                return "canvas"
            w = w.parentWidget()
        return None

    def _hover_step(self, event) -> Optional[tuple]:
        """With the mouse over a list, W A S D and the arrows move in it: (zone, -1 | +1); else None.
        Over the canvas W / S step through the Objects list.

        Only plain keys (Shift / Ctrl+arrows keep extending the list selection),
        never while typing, and elsewhere A, D, S and the arrows keep their usual meaning.
        """
        delta = HOVER_KEYS.get(event.key())
        if delta is None or event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            return None
        if isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox, QPlainTextEdit)):
            return None
        if not self.isActiveWindow():
            return None
        zone = self._hover_zone()
        if zone == "canvas" and event.key() not in (Qt.Key.Key_W, Qt.Key.Key_S):
            return None  # over the canvas only W / S (A, D and the arrows keep their meaning there)
        return (zone, delta) if zone is not None else None

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
        s.defer_prompts = True  # points / boxes made meanwhile are kept and run when SAM2 is ready
        engine = s.engine

        def load():
            e = engine or self.engine_factory(self.settings)
            e.load_sam2()
            return e

        def done(e):
            self._loading_models = False
            s.defer_prompts = False
            s.engine = e
            if s.image is not None:
                e.set_image(s.image)
            self.log(f"SAM2 loaded on {getattr(e, 'device', '?')}")
            n = s.run_pending()
            if n:
                self.log(f"Applied the points made while SAM2 was loading ({n} mask(s))")
            self.refresh()

        def failed(msg):
            self._loading_models = False
            s.defer_prompts = False
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
        waiting = bool(self.session.pending)
        self._prompt(lambda: self.session.click(x, y, positive))
        if self.session.pending and not waiting:
            self.log("SAM2 is still loading: the points are kept and the mask appears when it is ready")

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
        new_auto = tool in AUTO_TOOLS and tool != self._tool
        self._tool = tool
        auto = tool in AUTO_TOOLS
        self.session.set_auto_tool(tool if auto else None)
        if new_auto and self.session.auto_mode != "fill":  # every auto tool starts in Fill mode
            self.session.set_auto_mode("fill")
            self.properties_panel._set_mode("fill")
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

    def _frame_tools(self) -> QHBoxLayout:
        """The row under a frame view: Go to ID (type + Enter) and Focus (S)."""
        goto = QLineEdit()
        goto.setPlaceholderText("Go to ID")
        goto.setToolTip("Type an image ID and press Enter to open it")
        goto.setMinimumWidth(30)  # it may get narrow with the folded Frame List
        goto.setMaximumWidth(90)
        goto.returnPressed.connect(lambda: self.goto_frame(goto))
        focus = QToolButton()
        focus.setText("⌖")
        focus.setAutoRaise(True)
        focus.setToolTip("Focus: scroll to the current frame")
        focus.clicked.connect(self.focus_frame)
        self._goto_fields.append(goto)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(goto, 1)
        row.addWidget(focus)
        row.addStretch(1)
        return row

    def focus_frame(self) -> None:
        """⌖: scroll the frame list and strip to the current frame."""
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

    def _list_width(self, names: Optional[bool] = None) -> int:
        """The Frame List column width: with the file names, or folded to the IDs and marks."""
        if names is None:
            names = self.images_panel.names_visible
        return 210 if names else 80

    def set_frame_names(self, on: bool) -> None:
        """Frame List: file names on, or folded to the IDs and marks (the column narrows)."""
        self.images_panel.set_names_visible(on)
        self._list_title.set_compact(not on)  # folded: no title / float button, the rest never clipped
        self._list_summary.setVisible(on)  # folded: the counts would wrap; the Frames strip still has them
        self.resizeDocks([self._list_dock], [self._list_width(on)], Qt.Orientation.Horizontal)
        self.settings.frame_list_names = bool(on)
        self.settings.save(self.settings_path)

    def _remember(self, name: str, value) -> None:
        setattr(self.settings, name, value)
        self.settings.save(self.settings_path)

    def marks_object(self) -> Optional[int]:
        """The Object the frame marks are for (None: every Object)."""
        return self.shown_object_id() if self.settings.marks_one_object else None

    def set_marks_one_object(self, on: bool) -> None:
        self.settings.marks_one_object = bool(on)
        self.settings.save(self.settings_path)
        self.images_panel.update_marks(self.session.project, self.marks_object())

    def step_problem(self, step: int) -> None:
        """[ / ]: the previous / next image marked ⚠ or ✕ (and – with the one-Object marks)."""
        if self.session.key is None:
            return
        i = self.images_panel.problem_frame(self.session.index, step)
        if i is None:
            self.log("No ⚠ / ✕ images" + (" / images without this Object" if self.marks_object() is not None else ""))
            return
        self.go_to(i)
        self.focus_frame()

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
            if mode == "paint":
                self.session.pick_everything()  # like A: what Fill showed stays picked, Alt+drag takes parts out
        self.refresh()

    def close_tool(self, apply: bool = False) -> None:
        """End an auto tool; only Apply & Close writes its result in (every other way out drops it)."""
        if self.session.auto_tool is None:
            return
        tool = self.session.auto_tool
        if self.session.close_auto(apply):
            self.log(f"{tool.replace('_', ' ').title()} applied")
        self._auto_gen += 1  # drop a computation still running

    def mask_edit(self, what: str) -> None:
        """Ctrl+I invert / Ctrl+Backspace clear the edited mask on this image (one undo step).

        Only while editing; outside Edit the mask is emptied from the Object's [···] menu
        (Remove mask on this image), so a stray key never wipes a mask.
        """
        s = self.session
        if s.editing is None or self._busy:
            self.log("Invert / Clear Mask work while editing an Object (E); "
                     "outside Edit: [···] > Remove mask on this image")
            return
        self.close_tool()  # an auto tool's pending result is dropped first
        done = s.invert_mask() if what == "invert" else s.clear_mask()
        if done:
            where = " inside the region" if s.region is not None else ""
            self.log(("Mask inverted" if what == "invert" else "Mask cleared") + where + " (Ctrl+Z undoes it)")
        self.refresh()

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

    def step_object(self, delta: int, ids: Optional[List[int]] = None) -> None:
        """Up / Down: the previous / next Object with a mask on this image (Edit follows it).

        *ids*: the Objects to step through instead (hovering the list: its rows, Show all included).
        """
        s = self.session
        key = s.key
        if key is None or self._busy:
            return
        if ids is None:
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
            self.refresh()  # the row's Points button springs back
            return
        self.close_tool()
        if self.session.editing == oid:
            self.session.finish_editing()
        else:
            self.session.edit(oid)
            self.canvas.setFocus()
            self.set_brush(True, redraw=False)  # Edit starts with the brush (D / E again leave it)
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

    def _select_new(self, ids: List[int]) -> None:
        """Select Objects just made: their rows exist only after a refresh."""
        self.refresh()
        self.objects_panel.select_ids(ids)

    def delete_key(self) -> None:
        if self.session.mode == Mode.EDIT and self.session.selected_point is not None:
            self._prompt(self.session.delete_point)
        elif self.objects_panel.selected_ids():
            self.delete_objects(self.objects_panel.selected_ids())

    def delete_objects(self, ids: List[int]) -> None:
        """Delete at once (Ctrl+Z undoes it); locked Objects stay (docs/design/ux-principles.md 1)."""
        objs = [o for o in self.session.project.objects if o.id in set(ids)]
        if not objs or self._busy:
            return
        locked = [o.name for o in objs if o.locked]
        gone = self.session.delete_objects(ids)
        self.refresh()
        if gone:
            self.log(f"Deleted {len(gone)} Object(s) (Ctrl+Z undoes it)"
                     + (f" · locked, kept: {', '.join(locked)}" if locked else ""))
        elif locked:
            self.log(f"Locked, not deleted: {', '.join(locked)} (🔓 to unlock)")

    def set_locked(self, ids: List[int], locked: bool) -> None:
        changed = self.session.set_locked(ids, locked)
        self.refresh()
        if changed:
            self.log(f"{'Locked' if locked else 'Unlocked'} {len(changed)} Object(s)")

    def toggle_lock(self, ids: List[int]) -> None:
        """Lock the selected Objects, or unlock them when all of them are locked."""
        objs = [o for o in (self.session.project.get(i) for i in ids) if o is not None]
        if objs:
            self.set_locked(ids, not all(o.locked for o in objs))

    def merge(self, ids: List[int], how: str = "add") -> None:
        """Fuse the selected Objects into one (docs/specs/05). *how*: ``add`` (union, the first
        selected's name), ``override_a`` (the first selected wins where both have a mask, and names
        it), ``override_b`` (the last selected wins). The originals are removed."""
        ids = list(dict.fromkeys(ids))
        objs = [o for o in (self.session.project.get(i) for i in ids) if o is not None]
        if len(objs) < 2 or self._busy:
            self.log("Select two or more Object rows to merge (Ctrl/Shift-click)")
            return
        order = [o.id for o in (reversed(objs) if how == "override_b" else objs)]
        blocked = self.session.project.merge_blocked(order)
        if blocked:
            self.log(f"Locked, not merged: {', '.join(o.name for o in blocked)} (🔓 to unlock)")
            return
        new = self.session.merge(order, "add" if how == "add" else "override")
        if new is not None:
            self._select_new([new])
            self.log(f"Merged into {self.session.project.get(new).name}" + ("" if how == "add" else " (override)"))
        self.refresh()

    def merge_options(self, ids: List[int]) -> None:
        """⚙ next to Merge: how to merge."""
        objs = [o for o in (self.session.project.get(i) for i in dict.fromkeys(ids)) if o is not None]
        if len(objs) < 2:
            self.log("Select two or more Object rows to merge (Ctrl/Shift-click)")
            return
        a, b = objs[0], objs[-1]
        two = len(objs) == 2
        picked = self.choose(
            "Merge Objects",
            f"Merge {len(objs)} Objects into one; the originals are removed (Ctrl+Z undoes it). "
            f"A = “{a.name}” (selected first), B = “{b.name}”.",
            [("Where more than one has a mask", [
                f"Add: the union of the masks, named “{a.name}”",
                f"Override with A: “{a.name}” wins" + ("" if two else " (then the next selected)"),
                f"Override with B: “{b.name}” wins" + ("" if two else " (then the one before)"),
            ], 0)],
            "Merge",
        )
        if picked is not None:
            self.merge([o.id for o in objs], ("add", "override_a", "override_b")[picked[0]])

    def duplicate(self, ids: List[int], all_frames: bool = False) -> None:
        """Duplicate: the selected Objects' mask on this image only; *all_frames*: every linked mask."""
        if not ids or self._busy:
            return
        new = self.session.duplicate(ids, all_frames)
        if new:
            self._select_new(new)
            self.log(f"Duplicated {len(new)} Object(s)"
                     + (" with every linked mask" if all_frames else " (this image's mask only)"))
        else:
            self.log("Nothing duplicated: no mask on this image (Duplicate All copies every image)")
        self.refresh()

    def transfer(self, ids: List[int], move: bool = True, replace: bool = False, all_frames: bool = False) -> None:
        """Move (or Copy) Object A's mask (the first id) into B (the last), docs/specs/05:
        added to B's mask (*replace*: B's becomes A's), on this image or (*all_frames*) on every
        image where A has a mask. Move takes it off A; A stays (empty if nothing is left)."""
        ids = list(dict.fromkeys(ids))
        objs = [o for o in (self.session.project.get(i) for i in (ids[:1] + ids[-1:])) if o is not None]
        verb = "moved" if move else "copied"
        if len(ids) < 2 or len(objs) < 2 or self._busy:
            self.log(f"Select two Objects: the first selected is {verb} into the last selected")
            return
        a, b = objs
        changed = self.session.copy_into(a.id, b.id, replace, all_frames, move=move)
        if changed:
            self.objects_panel.select_ids([b.id])
            self.log(f"{verb.title()} “{a.name}” into “{b.name}” on {len(changed)} image(s)"
                     f" ({'Replace' if replace else 'Add'})")
        else:
            self.log(f"Nothing {verb}: “{a.name}” has no mask" + ("" if all_frames else " on this image"))
        self.refresh()

    def transfer_options(self, ids: List[int]) -> None:
        """⚙ next to Move: Move / Copy, Add / Replace, this image / every image (the direction stays
        first → last; the button's defaults are not changed by what is picked here)."""
        ids = list(dict.fromkeys(ids))
        objs = [o for o in (self.session.project.get(i) for i in (ids[:1] + ids[-1:])) if o is not None]
        if len(ids) < 2 or len(objs) < 2:
            self.log("Select two Objects: the first selected goes into the last selected")
            return
        a, b = objs
        picked = self.choose(
            "Move / Copy Object into Another",
            f"From “{a.name}” (selected first) into “{b.name}” (selected last).",
            [
                ("Action", ["Move: taken off A (A stays, empty where moved)", "Copy: A keeps its mask"], 0),
                ("B's mask", ["Add: A's mask is added to B's (union)", "Replace: B's mask becomes A's"], 0),
                ("Images", ["This image only", "Every image where A has a mask"], 0),
            ],
            "OK",
        )
        if picked is not None:
            self.transfer([a.id, b.id], move=picked[0] == 0, replace=picked[1] == 1, all_frames=picked[2] == 1)

    def undo(self) -> None:
        if not self._busy:
            self._do(self.session.undo)

    def redo(self) -> None:
        if not self._busy:
            self._do(self.session.redo)

    def toggle_final(self, on: bool) -> None:
        self.canvas.set_final_preview(on)

    def toggle_preview_mode(self) -> None:
        """X: Mask Preview shows the Final Mask <-> the selected Object's mask."""
        self.settings.preview_object = not self.settings.preview_object
        self.settings.save(self.settings_path)
        self._show_preview_mode()
        self._update_preview_mask()
        self.canvas.update()

    def _show_preview_mode(self) -> None:
        """The toolbar button names the mode in use; the menu entry keeps its command name."""
        one = self.settings.preview_object
        self.act_preview_mode.setIconText("Preview: Object" if one else "Preview: Final")
        self.act_preview_mode.setToolTip(
            "Mask Preview shows the selected Object's mask (X: switch to the Final Mask)" if one
            else "Mask Preview shows the Final Mask, every checked Object (X: switch to the selected Object)"
        )

    def _update_preview_mask(self) -> None:
        """The mask Mask Preview shows: the Final Mask, or the selected / edited Object's mask."""
        s = self.session
        key = s.key
        if key is None:
            self.canvas.set_final(None)
        elif not self.settings.preview_object:
            self.canvas.set_final(s.project.final_mask(key), "FINAL MASK")
        else:
            oid = self.shown_object_id()
            o = s.project.get(oid) if oid is not None else None
            self.canvas.set_final(o.mask(key) if o is not None else None,
                                  o.name if o is not None else "NO OBJECT SELECTED")

    def step_keyframe(self, step: int) -> None:
        """, / .: the nearest earlier / later keyframe (★: a mask edited there, a propagation source).

        With the Frame List's one-Object marks on, only the selected Object's ★ count.
        """
        s = self.session
        if s.key is None:
            return
        only = self.marks_object()
        keys = set()
        for o in s.project.objects:
            if only is not None and o.id != only:
                continue
            keys.update(k for k, fs in o.frames.items() if fs.mask is not None and fs.status == FrameStatus.MANUAL)
        idx = [i for i, k in enumerate(s.keys) if k in keys]
        target = (max((i for i in idx if i < s.index), default=None) if step < 0
                  else min((i for i in idx if i > s.index), default=None))
        if target is None:
            self.log(f"No keyframe (★) {'before' if step < 0 else 'after'} this image")
            return
        self.go_to(target)
        self.focus_frame()

    def go_to_reference(self) -> None:
        """F: the propagation reference (◎, the double-clicked image)."""
        if self._reference is None:
            self.log("No reference yet: double-click an image to make it the reference (◎)")
            return
        self.go_to(self._reference)
        self.focus_frame()

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
                + (" — select images in the Frame List (Ctrl/Shift-click)." if scope == "selected" else ".")
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

    def toggle_excluded(self) -> None:
        """⊘: leave the picked frames (else the current one) out of a new dataset, or take them back."""
        s = self.session
        if s.key is None:
            return
        rows = self.images_panel.selected_rows() or [s.index]
        keys = [s.keys[i] for i in rows]
        out = not all(k in s.project.excluded for k in keys)
        changed = s.project.set_excluded(keys, out)
        if changed:
            self.log(f"{'Excluded' if out else 'Included again'}: {len(changed)} frame(s) (⊘ = not in a new dataset; "
                     f"{len(s.project.excluded)} excluded in all)")
        self.refresh()

    def set_pinned(self, on: bool) -> None:
        self._pinned = self.images_panel.selected_rows() if on else None
        self.refresh()

    def propagate(self, start: int, end: int, direction: Direction, scope: str = "range") -> None:
        """Propagate the checked Objects from the reference image over *scope*:
        ``selection`` (Frame List, or the pinned one) · ``range`` (start..end) · ``all``."""
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
                self.warn("Select the images to propagate to in the Frame List (Shift/Ctrl-click), or pin them.")
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
        project = s.project
        dlg = ExportDialog(
            default_export_dir(s.image_dir), self,
            check=lambda pattern, ids=None: check_export(project, pattern, ids),
            scene=self.scene, target=self.settings.export_target if self.scene else "custom",
            sets=project.mask_sets,
            save_set=lambda name: project.set_mask_set(name, [o.id for o in project.objects if o.included]),
            delete_set=lambda name: project.set_mask_set(name, None),
            excluded=len(project.excluded),
        )
        if dlg.exec() != ExportDialog.DialogCode.Accepted:
            if dlg.goto is not None and dlg.goto in s.keys:  # picked in the check list: open it
                self.go_to(s.keys.index(dlg.goto))
                self.focus_frame()
            return
        if self.scene is not None:
            self.settings.export_target = dlg.target.currentData()
            self.settings.save(self.settings_path)
        p = dlg.preset()
        if p is not None:
            self.log(f"Export for {p.label}: {p.note}")
        root = dlg.dataset_root()
        if root is not None:
            why = dataset_blocker(root)
            if why:
                self.warn(why)
                return
        self.run_export(dlg.jobs(), dataset=root, views=dlg.views())

    def run_export(self, jobs, dataset: Optional[Path] = None, views=None) -> None:
        """Write one export or several (a list: the Final Mask and mask sets, each to its folder).

        *dataset*: first build a new dataset there (images linked, the model without the ⊘ frames),
        and write the masks of the kept frames only.
        """
        jobs = jobs if isinstance(jobs, list) else [jobs]
        s = self.session
        self.save()
        self._busy = "Exporting…"
        keep = [k for k in s.keys if k not in s.project.excluded] if dataset is not None else None
        report = []

        def work():
            if views is not None:  # converted cameras: images, masks and model together (docs/specs/08)
                masks = [MaskJob(o.out_dir, o.name_pattern, o.invert, o.include_empty,
                                 lambda k, ids=o.object_ids: full_mask(s.project, k, s.original_size, ids))
                         for o in jobs]
                if isinstance(views, Stitch):  # a moment with a ⊘ image is left out whole
                    groups = [g for g in self.scene.rig_groups() if not any(k in s.project.excluded for k in g)]
                    report.append(stitch_to_erp(s.image_dir, self.scene.model_dir, dataset, groups, views.width, masks))
                else:
                    report.append(convert(s.image_dir, self.scene.model_dir, dataset, keep, views, masks))
                return [sorted(o.out_dir.iterdir()) for o in jobs]
            if dataset is not None:
                report.append(build_dataset(s.image_dir, self.scene.model_dir, dataset, keep))
            return [s.export(o, keys=keep) for o in jobs]

        def done(paths):
            self._busy = None
            if report and views is not None:
                r = report[0]
                self.log(f"Converted dataset {dataset}: {r.images_in} image(s) → {r.views_out} "
                         f"{'pinhole view(s)' if isinstance(views, Views) else '360 image(s)'} {r.side} px wide, "
                         f"3D points {r.points_kept} kept / {r.points_dropped} removed"
                         + (f"; not converted: {', '.join(r.skipped[:5])}" if r.skipped else ""))
            elif report:
                r = report[0]
                self.log(f"New dataset {dataset}: {r.model.images_kept} image(s) ({r.linked} linked, {r.copied} copied), "
                         f"{r.model.images_dropped} left out, 3D points {r.model.points_kept} kept / "
                         f"{r.model.points_dropped} removed"
                         + (f"; not carried over: {', '.join(r.model.skipped_files)}" if r.model.skipped_files else ""))
            for opts, written in zip(jobs, paths):
                self.log(f"Exported {len(written)} mask(s) to {opts.out_dir}")
            self.refresh()

        def failed(msg):
            self._busy = None
            self.refresh()
            self.warn(f"Export failed: {msg}")

        self._start(Task(work), done, failed)
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
