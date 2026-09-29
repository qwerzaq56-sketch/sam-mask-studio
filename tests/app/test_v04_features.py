"""v0.4: the GPT review follow-ups (one section per phase, so each can be reverted with it)."""

from tests.app.test_gui import folder, win  # noqa: F401  (fixtures)
from tests.app.test_v03_features import make_objects, settle


# --- p1: the work bar and the clearer names ----------------------------------


def test_work_bar_shows_frame_object_and_mode(qapp, win):
    ids = make_objects(win, 1)
    s = win.session
    text = win.work_bar.text()
    assert f"Frame 1 / {len(s.keys)}" in text and "Object: —" in text and "Mode: View" in text
    win.toggle_edit(ids[0])
    assert "Mode: Paint" in win.work_bar.text()  # Edit starts with the brush (v0.4-p15)
    win.act_brush.trigger()  # D: back to points
    text = win.work_bar.text()
    assert s.project.get(ids[0]).name in text and "(SAM2)" in text and "Mode: Points" in text
    win.set_brush_tool("fill_holes")
    assert "Mode: Auto · Fill Holes (Fill)" in win.work_bar.text()
    win.set_brush_tool("paint")
    assert "Mode: Paint" in win.work_bar.text()
    win.escape()
    win.escape()
    win.go_to(1)
    assert "Frame 2 /" in win.work_bar.text()


def test_renamed_buttons(qapp, win):
    make_objects(win, 1)
    assert win.act_changes.text() == "Show Changes"
    assert win.properties_panel.recompute_btn.text().replace("&&", "&") == "Apply & Continue"
    oid = win.session.project.objects[0].id
    from PyQt6.QtWidgets import QPushButton

    assert win.objects_panel.tree.findChild(QPushButton, f"edit_{oid}").text() == "Points"


# --- p2: frame marks per Object, colors, counts, [ / ] ------------------------


def _set_status(win, oid, key, status):
    import dataclasses

    p = win.session.project
    p.set_frame(oid, key, dataclasses.replace(p.get(oid).frame(key), status=status))


def test_marks_counts_and_problem_navigation(qapp, win):
    from src.core.project import FrameStatus

    ids = make_objects(win, 2)  # both on image 0 (★)
    s = win.session
    k0, k2 = s.keys[0], s.keys[2]
    p = s.project
    p.set_frame(ids[0], k2, p.get(ids[0]).frame(k0))
    _set_status(win, ids[0], k2, FrameStatus.WARNING)
    win.refresh()
    panel = win.images_panel
    assert panel.status_mark(2) == "⚠" and panel.status_mark(0) == "★"
    assert "⚠1" in panel._summaries[0].text() and "★1" in panel._summaries[0].text()
    assert panel.list.item(2).foreground().color().name() == "#d78200"
    win.step_problem(1)
    assert s.index == 2
    win.step_problem(1)  # wraps around to the only problem again
    assert s.index == 2

    # one-Object marks: only Object 2 (on image 0 only) -> – everywhere else
    win.go_to(0)
    win.objects_panel.select_ids([ids[1]])
    win.marks_btn.setChecked(True)
    win.refresh()
    assert win.shown_object_id() == ids[1]
    assert panel.status_mark(0) == "★" and panel.status_mark(2) == "–"
    assert "–4" in panel._summaries[0].text()
    win.step_problem(1)
    assert s.index == 1  # the next image without the Object
    win.marks_btn.setChecked(False)
    assert win.settings.marks_one_object is False


# --- p3: the check before Export ----------------------------------------------


def test_check_export_counts_and_clashes(qapp, win):
    import dataclasses

    import numpy as np

    from src.core.project import FrameState, FrameStatus
    from src.core.storage import check_export

    ids = make_objects(win, 1)
    p = win.session.project
    k = win.session.keys
    fs = p.get(ids[0]).frame(k[0])
    p.set_frame(ids[0], k[1], dataclasses.replace(fs, status=FrameStatus.WARNING))
    p.set_frame(ids[0], k[2], FrameState.from_mask(np.zeros_like(fs.mask), status=FrameStatus.FAILED))
    c = check_export(p)
    assert c.images == len(k)
    assert c.with_mask == [k[0], k[1]] and c.empty == [k[2]] and c.without_mask == k[3:]
    assert c.warning == [k[1], k[2]] and c.clashes == []
    assert c.problems == k[1:]
    p.image_keys = list(p.image_keys) + ["frame_000.jpg"]  # frame_000.png + .jpg -> the same {stem}.png
    assert check_export(p, "{stem}.png").clashes == [[k[0], "frame_000.jpg"]]
    assert check_export(p, "{name}.png").clashes == []


def test_export_dialog_shows_the_check_and_opens_a_problem(qapp, win):
    from src.app.dialogs import ExportDialog
    from src.core.storage import check_export

    make_objects(win, 1)
    s = win.session
    dlg = ExportDialog(win.session.image_dir, win, check=lambda pat: check_export(s.project, pat))
    text = dlg.summary.text()
    assert "Images without a mask: 4" in text and "for <b>5</b> image(s)" in text
    assert dlg.problems.count() == 4
    dlg.empty.setChecked(True)
    assert "<b>5</b> file(s)" in dlg.summary.text()
    dlg._open_problem(dlg.problems.item(1))
    assert dlg.goto == s.keys[2]


# --- p4: foldable Settings / Layer sections -------------------------------------


def test_edit_layer_sections_fold_and_remember(qapp, win):
    from src.app.settings import Settings

    pp = win.properties_panel
    assert pp.layer_box.is_open() and pp.settings_box.is_open()
    pp.layer_box.header.click()
    assert not pp.layer_box.is_open() and pp.layer_box.body.isHidden()
    assert Settings.load(win.settings_path).layer_section_open is False
    pp.layer_box.header.click()
    assert pp.layer_box.is_open() and not pp.layer_box.body.isHidden()
    pp.settings_box.setTitle("Grow settings")
    assert pp.settings_box.title() == "Grow settings"


# --- fix: a folded Frame List starts narrow ---------------------------------------


def test_folded_frame_list_starts_narrow(qapp, folder, tmp_path):
    import time

    from src.app.main_window import MainWindow
    from src.app.settings import Settings
    from tests.app.test_gui import FakeEngine, fake_propagate

    w = MainWindow(
        settings=Settings(sam2_checkpoint=str(tmp_path / "none.pt"), frame_list_names=False),
        engine=FakeEngine(),
        propagate_fn=fake_propagate,
        settings_path=tmp_path / "config.json",
    )
    w.resize(1200, 800)
    w.show()
    for _ in range(20):
        qapp.processEvents()
        time.sleep(0.01)
    try:
        assert not w.names_btn.isChecked()
        assert w._list_dock.width() < 150
        assert w._list_summary.isHidden()  # folded: no wrapped counts (the strip keeps them)
        w.names_btn.setChecked(True)
        assert not w._list_summary.isHidden() and not w._list_summary.wordWrap()
    finally:
        w._autosave.stop()
        w.close()


# --- UI audit bugs: buttons never squeezed to nothing -----------------------------


def test_batch_and_detection_buttons_keep_their_width(qapp, win):
    import time

    win.tabs.setCurrentWidget(win.batch_panel)
    for _ in range(10):
        qapp.processEvents()
        time.sleep(0.01)
    bp = win.batch_panel
    assert bp.batch_btn.width() >= bp.batch_btn.sizeHint().width() - 2  # was 0 next to the prompt
    assert bp.stop_btn.isHidden() or bp.stop_btn.width() > 30
    win.tabs.setCurrentWidget(win.detection_panel)
    qapp.processEvents()
    assert win.detection_panel.detect_btn.width() > 30


# --- UI audit polish: nothing empty or jumping --------------------------------------


def test_empty_states_and_steady_panel_widths(qapp, win):
    import time

    from PyQt6.QtWidgets import QDockWidget

    def pump():
        for _ in range(10):
            qapp.processEvents()
            time.sleep(0.01)

    pp = win.properties_panel
    assert pp.tabs.isHidden() and not pp.hint.isHidden()  # nothing selected: only the how-to
    assert win.propagation_panel.run_view.isHidden()  # no run yet: no progress / lists
    assert win.batch_panel.progress.isHidden() and win.batch_panel.results.isHidden()
    ids = make_objects(win, 1)
    pump()
    widths = [d.width() for d in win.findChildren(QDockWidget)]
    win.toggle_edit(ids[0])
    pp.tabs.setCurrentIndex(pp.layer_tab)
    win.set_brush_tool("object_fill")
    win.set_region_mode(True)
    pump()
    assert not pp.tabs.isHidden()
    assert [d.width() for d in win.findChildren(QDockWidget)] == widths  # a long work bar never pushes docks
    assert win.canvas.banner == ""


# --- p8: , / . keyframes, F reference, R Show Changes, V Mask Preview mode ---------


def test_keyframe_and_reference_keys(qapp, win):
    import dataclasses

    from src.core.project import FrameStatus

    ids = make_objects(win, 1)  # ★ on image 0
    s = win.session
    p = s.project
    fs = p.get(ids[0]).frame(s.keys[0])
    p.set_frame(ids[0], s.keys[3], fs)  # ★ on 3
    p.set_frame(ids[0], s.keys[2], dataclasses.replace(fs, status=FrameStatus.PROPAGATED))  # ✓ is not a keyframe
    win.refresh()
    win.step_keyframe(1)
    assert s.index == 3
    win.step_keyframe(1)  # none later: stays
    assert s.index == 3
    win.step_keyframe(-1)
    assert s.index == 0
    win.go_to_reference()  # no reference yet: stays
    assert s.index == 0
    win.set_reference(4)
    win.go_to(1)
    win.go_to_reference()
    assert s.index == 4
    assert win.act_changes.shortcut().toString() == "R"


def test_mask_preview_final_or_object(qapp, win):
    import numpy as np

    ids = make_objects(win, 2)
    s = win.session
    assert win.act_final.text() == "Mask Preview"
    assert win.act_preview_mode.shortcut().toString() == "X"  # V until v0.4-p15 (V is now Mask Preview)
    assert win.act_preview_mode.text() == "Toggle Final / Object Mask"  # the menu name
    final = s.project.final_mask(s.key)
    assert np.array_equal(win.canvas._final, final) and win.canvas._final_label == "FINAL MASK"
    win.objects_panel.select_ids([ids[0]])
    win.refresh()
    win.act_preview_mode.trigger()
    assert win.settings.preview_object and win.act_preview_mode.iconText() == "Preview: Object"  # the toolbar
    one = s.project.get(ids[0])
    assert win.canvas._final is one.mask(s.key) and win.canvas._final_label == one.name
    assert not np.array_equal(win.canvas._final, final)  # the other Object is left out
    win.act_preview_mode.trigger()
    assert not win.settings.preview_object and win.canvas._final_label == "FINAL MASK"


# --- p9: Enter makes the current image the reference -----------------------------


def test_enter_sets_the_reference(qapp, win):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    win.activateWindow()
    win.canvas.setFocus()
    qapp.processEvents()
    enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    win.go_to(2)
    assert win.eventFilter(win.canvas, enter)
    assert win._reference == 2
    win.go_to(0)
    win.go_to_reference()
    assert win.session.index == 2
    assert win.eventFilter(win.canvas, enter)  # again on the reference: back to none
    assert win._reference is None


# --- p10: every auto tool starts in Fill mode --------------------------------------


def test_auto_tool_starts_in_fill_mode(qapp, win):
    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    s = win.session
    p = win.properties_panel
    p.tool_btns["grow"].click()
    p.mode_paint_btn.click()
    assert s.auto_mode == "paint" and win.canvas.brush_mode
    p.tool_btns["shrink"].click()  # another auto tool: back to Fill
    assert s.auto_mode == "fill" and p.mode_fill_btn.isChecked() and not win.canvas.brush_mode
    p.mode_paint_btn.click()
    win.escape()
    p.tool_btns["grow"].click()  # after leaving too
    assert s.auto_mode == "fill"


# --- p11: Duplicate (this image / all), Copy A → B, Merge Add / Override ------------


def _box_mask(shape, x0, x1):
    import numpy as np

    m = np.zeros(shape, bool)
    m[10:30, x0:x1] = True
    return m


def _two_linked(win):
    """A on images 0 and 2 (x 0..20), B on images 0 and 3 (x 10..40): they overlap on image 0."""
    from src.core.project import FrameState, FrameStatus, Source

    s = win.session
    p = s.project
    shape = s.working_hw()
    k = s.keys
    a = p.add_object(k[0], FrameState.from_mask(_box_mask(shape, 0, 20)), Source.SAM2_POINT, "A")
    p.set_frame(a, k[2], FrameState.from_mask(_box_mask(shape, 0, 20), status=FrameStatus.PROPAGATED))
    b = p.add_object(k[0], FrameState.from_mask(_box_mask(shape, 10, 40)), Source.SAM2_POINT, "B")
    p.set_frame(b, k[3], FrameState.from_mask(_box_mask(shape, 10, 40), status=FrameStatus.PROPAGATED))
    win.refresh()
    return a, b


def test_duplicate_this_image_or_every_linked_mask(qapp, win):
    a, _b = _two_linked(win)
    s = win.session
    p = s.project
    op = win.objects_panel
    op.select_ids([a])
    op.dup_btn.click()
    settle(qapp)
    copy = p.objects[1]
    assert copy.name == "A #1 (copy)" and list(copy.frames) == [s.keys[0]]  # this image only
    assert op.selected_ids() == [copy.id]
    op.select_ids([a])
    op.dup_all_btn.click()
    settle(qapp)
    assert sorted(p.objects[1].frames) == [s.keys[0], s.keys[2]]  # every linked mask
    win.go_to(1)  # A has no mask here: nothing to copy
    n = len(p.objects)
    win.duplicate([a])
    assert len(p.objects) == n
    assert not op.copy_btn.isEnabled()


def test_copy_a_into_b_add_or_replace(qapp, win):
    import numpy as np

    a, b = _two_linked(win)
    s = win.session
    p = s.project
    k = s.keys
    A0, B0 = p.get(a).mask(k[0]).copy(), p.get(b).mask(k[0]).copy()
    win.objects_panel.select_ids([a, b])
    assert win.objects_panel.copy_btn.isEnabled()
    win.objects_panel.copy_btn.click()  # the defaults: A -> B, Add, this image only
    settle(qapp)
    assert np.array_equal(p.get(b).mask(k[0]), A0 | B0)
    assert k[2] not in p.get(b).frames and np.array_equal(p.get(a).mask(k[0]), A0)  # A is untouched
    win.undo()
    win.copy_into([a, b], replace=True, all_frames=True)
    B = p.get(b)
    assert np.array_equal(B.mask(k[0]), A0) and np.array_equal(B.mask(k[2]), A0)
    assert B.frame(k[2]).status.value == "propagated"  # the frame is copied as it is
    assert k[3] in B.frames  # where A has no mask, B keeps its own
    win.undo()
    win.choose = lambda title, text, groups, ok="OK": [1, 1, 0]  # B -> A, Replace, this image
    win.copy_into([a, b])
    assert np.array_equal(p.get(a).mask(k[0]), B0)


def test_merge_add_or_override(qapp, win):
    import numpy as np

    a, b = _two_linked(win)
    s = win.session
    p = s.project
    k = s.keys
    A0, B0 = p.get(a).mask(k[0]).copy(), p.get(b).mask(k[0]).copy()
    win.merge([a, b], "override_a")
    m = p.objects[0]
    assert m.name == "A #1" and np.array_equal(m.mask(k[0]), A0)  # A wins where both have a mask
    assert sorted(m.frames) == [k[0], k[2], k[3]]  # elsewhere each keeps its own
    win.undo()
    win.merge([a, b], "override_b")
    m = p.objects[0]
    assert m.name == "B #1" and np.array_equal(m.mask(k[0]), B0)
    win.undo()
    win.choose = lambda title, text, groups, ok="OK": [0]  # the dialog: Add
    win.merge([a, b])
    m = p.objects[0]
    assert m.name == "A #1" and np.array_equal(m.mask(k[0]), A0 | B0) and len(p.objects) == 1
    win.undo()
    win.choose = lambda *a, **kw: None  # cancelled: nothing happens
    win.merge([a, b])
    assert len(p.objects) == 2


# --- p12: the open frame is a filled row / tile ------------------------------------


def test_open_frame_row_and_tile_are_filled(qapp, win):
    from src.app.images_panel import CURRENT_FILL

    ip = win.images_panel
    win.names_btn.setChecked(False)  # IDs only: the row's right side is empty
    win.go_to(2)
    settle(qapp)
    fl = ip.frame_list
    img = fl.viewport().grab().toImage()
    x = img.width() - 4  # the row's right end (the list may still be narrowing after the fold)
    assert img.pixelColor(x, fl.visualRect(fl.model().index(2, 0)).center().y()) == CURRENT_FILL
    assert img.pixelColor(x, fl.visualRect(fl.model().index(1, 0)).center().y()) != CURRENT_FILL
    strip = ip.list.viewport().grab().toImage()
    t = ip.list.visualItemRect(ip.list.item(2))
    assert strip.pixelColor(t.left() + 2, t.top() + 2) == CURRENT_FILL


# --- p13: hover keys (W A S D / arrows move in the list under the mouse) --------------


def _key(win, key, zone):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    win._hover_zone = lambda: zone
    over = QKeyEvent(QEvent.Type.ShortcutOverride, key, Qt.KeyboardModifier.NoModifier)
    press = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    handled = win.eventFilter(win.canvas, over)
    if handled:
        assert over.isAccepted()  # so the menu shortcut (A, D, S, arrows) does not fire
        assert win.eventFilter(win.canvas, press)
    return handled


def test_hover_keys_move_in_the_list_under_the_mouse(qapp, win):
    from PyQt6.QtCore import Qt

    ids = make_objects(win, 3)
    s = win.session
    win.activateWindow()
    win.canvas.setFocus()
    qapp.processEvents()
    assert win._zone_of(win.images_panel.frame_list.viewport()) == "frames"
    assert win._zone_of(win.images_panel.list.viewport()) == "frames"
    assert win._zone_of(win.objects_panel.tree.viewport()) == "objects"
    assert win._zone_of(win.canvas) is None and win._zone_of(win._goto_fields[0]) is None
    for key, want in ((Qt.Key.Key_D, 1), (Qt.Key.Key_S, 2), (Qt.Key.Key_Right, 3), (Qt.Key.Key_W, 2),
                      (Qt.Key.Key_A, 1), (Qt.Key.Key_Up, 0)):
        assert _key(win, key, "frames")
        assert s.index == want
    win.objects_panel.select_ids([ids[0]])
    assert _key(win, Qt.Key.Key_S, "objects")
    assert win.objects_panel.selected_ids() == [ids[1]]
    assert _key(win, Qt.Key.Key_D, "objects") and win.objects_panel.selected_ids() == [ids[2]]
    assert _key(win, Qt.Key.Key_W, "objects") and win.objects_panel.selected_ids() == [ids[1]]
    assert s.index == 0  # the frame stays
    # elsewhere: not taken, so A / D / S and the arrows keep their menu shortcuts
    assert not _key(win, Qt.Key.Key_D, None) and not _key(win, Qt.Key.Key_Right, None)
    assert not _key(win, Qt.Key.Key_W, None)


def test_hover_keys_through_the_real_key_path(qapp, win):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    make_objects(win, 1)
    s = win.session
    win.activateWindow()
    win.canvas.setFocus()
    qapp.processEvents()
    win._hover_zone = lambda: "frames"
    QTest.keyClick(win.canvas, Qt.Key.Key_D)  # over a list: next frame, not the Paint brush
    assert s.index == 1 and not win.act_brush.isChecked()
    win._hover_zone = lambda: None
    QTest.keyClick(win.canvas, Qt.Key.Key_Right)  # elsewhere: the arrows as before
    assert s.index == 2
    QTest.keyClick(win.canvas, Qt.Key.Key_W)  # ...and W does nothing
    assert s.index == 2


# --- p14: menus hold every command and its key ------------------------------------


def test_menus_hold_every_command(qapp, win):
    from PyQt6.QtWidgets import QToolBar

    bar = win.menuBar()
    names = [a.text().replace("&", "") for a in bar.actions()]
    assert names == ["File", "Edit", "View", "Go", "Help"]

    def walk(menu):
        for a in menu.actions():
            if a.menu() is not None:
                yield from walk(a.menu())
            else:
                yield a

    entries = [a for top in bar.actions() for a in walk(top.menu())]
    for act in (win.act_open, win.act_save, win.act_export, win.act_settings, win.act_undo, win.act_redo,
                win.act_new, win.act_edit, win.act_delete, win.act_escape, win.act_brush, win.act_pick_all,
                win.act_final, win.act_preview_mode, win.act_outline, win.act_changes, win.act_prev_frame,
                win.act_next_frame, win.act_prev_object, win.act_next_object, win.act_prev_problem,
                win.act_next_problem, win.act_prev_key, win.act_next_key, win.act_go_reference,
                win.act_shortcuts, win.act_duplicate, win.act_duplicate_all, win.act_copy_into, win.act_merge):
        assert act in entries, act.text()
    hints = " ".join(a.text() for a in entries)
    assert "\tEnter" in hints and "\tZ (hold)" in hints and "W A S D" in hints
    tb = win.findChild(QToolBar, "main_toolbar").actions()
    assert win.act_open not in tb and win.act_undo not in tb and win.act_settings not in tb
    assert win.act_final in tb and win.act_brush in tb and win.act_changes in tb
    # every key in the F1 list is a menu entry's key (or a note in a menu)
    shown = {a.shortcut().toString() for a in entries} | {a.text().split("\t")[1] for a in entries if "\t" in a.text()}
    for key in ("Ctrl+O", "Ctrl+S", "Ctrl+E", "Ctrl+Z", "N", "E", "Del", "Esc", "D", "A", "X", "V", "O", "R",
                "Left", "Right", "Up", "Down", "[", "]", ",", ".", "F", "F1", "Enter", "Space"):
        assert key in shown, key


# --- p15: keys and menu fixes (docs/ideas.md feedback) ------------------------


def test_preview_keys_swapped_and_toggles_do_not_repeat(qapp, win):
    assert win.act_final.shortcut().toString() == "V" and win.act_preview_mode.shortcut().toString() == "X"
    for a in (win.act_final, win.act_preview_mode, win.act_brush, win.act_outline, win.act_changes):
        assert not a.autoRepeat(), a.text()  # held: one toggle
    assert win.act_next_frame.autoRepeat()  # moving still repeats
    assert not hasattr(win, "act_focus")  # no S: F goes to ◎, ⌖ scrolls


def test_space_over_a_frame_list_sets_the_reference(qapp, win):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    win.activateWindow()
    qapp.processEvents()
    win.go_to(2)

    def space(zone):
        win._hover_zone = lambda: zone
        over = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        return win.eventFilter(win.canvas, over) and win.eventFilter(win.canvas, press)

    assert not space(None) and win._reference is None  # the canvas keeps Space (pan)
    assert space("frames") and win._reference == 2


def test_paint_button_starts_with_everything_picked(qapp, win):
    from tests.app.test_v03_features import holes_object

    s = holes_object(win)
    p = win.properties_panel
    p.fill_area.setValue(5)
    p.tool_btns["fill_holes"].click()
    added = s.auto_changes()[0]
    p.mode_paint_btn.click()
    assert s.auto_mode == "paint" and added.any() and (s.auto_taken() == added).all()


def test_edit_starts_with_the_brush(qapp, win):
    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    assert win.act_brush.isChecked() and win.canvas.brush_mode
    win.edit_key()  # E again: done
    assert win.session.editing is None and not win.act_brush.isChecked()
