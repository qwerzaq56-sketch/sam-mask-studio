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
    assert "Mode: Points" in win.work_bar.text()  # E: points (v0.4-p45)
    win.act_brush.trigger()  # D: the brush
    assert "Mode: Paint" in win.work_bar.text()
    win.edit_key()  # E: back to points (v0.4-p49)
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
    dlg._open_problem(dlg.problems.item(1))
    assert dlg.goto == s.keys[2]
    dlg.empty.setChecked(True)
    assert "<b>5</b> file(s)" in dlg.summary.text()
    assert dlg.problems.count() == 0  # written all white: not a problem any more (p24)


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
    assert win.act_preview_mode.shortcut().toString() == "X"  # V until p15 (Shift+X in p83 only)
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
    assert not op.move_btn.isEnabled()


def test_move_or_copy_a_into_b(qapp, win):
    """p11 Copy A -> B; p20: the button moves (A keeps the Object, loses the mask), ⚙ can copy."""
    import numpy as np

    a, b = _two_linked(win)
    s = win.session
    p = s.project
    k = s.keys
    A0, B0 = p.get(a).mask(k[0]).copy(), p.get(b).mask(k[0]).copy()
    win.objects_panel.select_ids([a, b])
    assert win.objects_panel.move_btn.isEnabled()
    win.objects_panel.move_btn.click()  # the defaults: Move, A -> B, Add, this image only
    settle(qapp)
    assert np.array_equal(p.get(b).mask(k[0]), A0 | B0) and k[2] not in p.get(b).frames
    assert p.get(a) is not None and k[0] not in p.get(a).frames and k[2] in p.get(a).frames  # A stays
    win.undo()
    assert np.array_equal(p.get(a).mask(k[0]), A0)  # one undo step
    win.transfer([a, b], move=False, replace=True, all_frames=True)  # Copy, Replace, every image
    B = p.get(b)
    assert np.array_equal(B.mask(k[0]), A0) and np.array_equal(B.mask(k[2]), A0)
    assert B.frame(k[2]).status.value == "propagated"  # the frame is copied as it is
    assert k[3] in B.frames  # where A has no mask, B keeps its own
    assert np.array_equal(p.get(a).mask(k[0]), A0)  # Copy: A keeps it
    win.undo()
    win.transfer([a, b], all_frames=True)  # Move everything: A is left empty, not removed
    assert p.get(a) is not None and not p.get(a).frames
    win.undo()
    win.choose = lambda title, text, groups, ok="OK": [1, 1, 0]  # ⚙: Copy, Replace, this image
    win.transfer_options([b, a])  # b selected first: b -> a
    assert np.array_equal(p.get(a).mask(k[0]), B0) and np.array_equal(p.get(b).mask(k[0]), B0)


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
    win.merge([a, b])  # the button (p17): Add at once
    m = p.objects[0]
    assert m.name == "A #1" and np.array_equal(m.mask(k[0]), A0 | B0) and len(p.objects) == 1
    win.undo()
    win.choose = lambda title, text, groups, ok="OK": [2]  # ⚙: Override with B
    win.merge_options([a, b])
    assert p.objects[0].name == "B #1" and len(p.objects) == 1
    win.undo()
    win.choose = lambda *a, **kw: None  # cancelled: nothing happens
    win.merge_options([a, b])
    assert len(p.objects) == 2


# --- p12: the open frame is a filled row / tile ------------------------------------


def test_open_frame_filled_reference_outlined(qapp, win):
    """p12 filled the open frame, p16 the reference; p19: open = filled, reference ◎ = orange frame."""
    from src.app.images_panel import CURRENT_FILL, REFERENCE_OUTLINE

    ip = win.images_panel
    win.names_btn.setChecked(False)  # IDs only: the row's right side is empty
    win.go_to(2)
    win.set_reference(1)
    settle(qapp)
    fl = ip.frame_list
    img = fl.viewport().grab().toImage()
    x = img.width() - 8  # the row's right side, inside the outline (the list may still be narrowing)
    rect = lambda row: fl.visualRect(fl.model().index(row, 0))  # noqa: E731
    assert img.pixelColor(x, rect(2).center().y()) == CURRENT_FILL  # open: filled
    assert img.pixelColor(x, rect(1).center().y()) != CURRENT_FILL  # ◎: not filled...
    assert img.pixelColor(rect(1).center().x(), rect(1).top() + 1) == REFERENCE_OUTLINE  # ...outlined
    assert img.pixelColor(x, rect(0).center().y()) != CURRENT_FILL
    strip = ip.list.viewport().grab().toImage()
    t1, t2 = ip.list.visualItemRect(ip.list.item(1)), ip.list.visualItemRect(ip.list.item(2))
    assert strip.pixelColor(t2.left() + 2, t2.top() + 2) == CURRENT_FILL
    assert strip.pixelColor(t1.right() - 20, t1.top() + 1) == REFERENCE_OUTLINE  # its right side: the strip scrolls
    win.set_reference(1)  # again: no reference, no frame
    settle(qapp)
    img = fl.viewport().grab().toImage()
    assert img.pixelColor(rect(1).center().x(), rect(1).top() + 1) != REFERENCE_OUTLINE


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
    assert win._zone_of(win.canvas) == "canvas" and win._zone_of(win._goto_fields[0]) is None
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
                win.act_shortcuts, win.act_duplicate, win.act_duplicate_all, win.act_move, win.act_merge):
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


# --- p15: keys and menu fixes (docs/backlog/ideas.md feedback) ------------------------


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
    """p45: E starts with points, D with the brush (it starts editing the selected Object)."""
    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    assert win.session.editing == ids[0] and not win.act_brush.isChecked() and not win.canvas.brush_mode
    win.edit_key()  # E again: done
    assert win.session.editing is None
    win.objects_panel.select_ids(ids)
    win.act_brush.trigger()  # D, not editing: edit with the brush
    assert win.session.editing == ids[0] and win.act_brush.isChecked() and win.canvas.brush_mode
    win.edit_key()  # E in the brush: points, still editing (v0.4-p49)
    assert win.session.editing == ids[0] and not win.act_brush.isChecked() and not win.canvas.brush_mode
    win.act_brush.trigger()  # D: the brush again
    win.act_brush.trigger()  # D in the brush: out of Edit
    assert win.session.editing is None and not win.act_brush.isChecked()


# --- p17: Objects panel (lock, no delete question, Copy / Merge at once, Ctrl+D) --------


def test_delete_asks_nothing_and_locked_objects_stay(qapp, win):
    ids = make_objects(win, 3)
    s = win.session
    p = s.project
    win.ask = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no question"))
    win.set_locked([ids[0]], True)
    assert p.get(ids[0]).locked
    op = win.objects_panel
    settle(qapp)
    assert not op.tree.findChild(type(op.merge_btn), f"delete_{ids[0]}").isEnabled()
    win.delete_objects(ids[:2])
    assert [o.id for o in p.objects] == [ids[0], ids[2]]  # the locked one stays
    win.undo()
    assert len(p.objects) == 3
    win.undo()  # the lock is one undo step too
    assert not p.get(ids[0]).locked
    win.set_locked(ids, True)
    assert op.unlock_all_btn.isEnabled() and not op.lock_all_btn.isEnabled()
    win.toggle_lock(ids)  # all locked: unlock
    assert not any(o.locked for o in p.objects)


def test_lock_is_saved(qapp, win):
    from src.core.storage import ProjectStore

    ids = make_objects(win, 2)
    win.set_locked([ids[1]], True)
    win.save(force=True)
    s = win.session
    again = ProjectStore(s.image_dir, s.max_side).load(list(s.keys))
    assert [o.locked for o in again.objects] == [False, True]


def test_merge_respects_locks_and_has_no_into(qapp, win):
    a, b = _two_linked(win)
    p = win.session.project
    win.set_locked([b], True)
    win.merge([a, b])  # Add would remove the locked B: refused
    assert [o.id for o in p.objects] == [a, b] and p.get(b).frames
    groups = []
    win.choose = lambda title, text, g, ok="OK": groups.extend(g) or None
    win.merge_options([a, b])
    assert len(groups[0][1]) == 3  # Add / Override A / Override B (Into A went to Move, p20)


def test_move_is_first_into_last_add_this_image(qapp, win):
    import numpy as np

    a, b = _two_linked(win)
    p = win.session.project
    k = win.session.keys
    c = make_objects(win, 1)[0]
    A0 = p.get(a).mask(k[0]).copy()
    op = win.objects_panel
    op.select_ids([a, c, b])
    assert op._pair() == [a, b] and op.move_btn.isEnabled()
    op.move_btn.click()
    settle(qapp)
    assert (p.get(b).mask(k[0]) >= A0).all() and k[2] not in p.get(b).frames  # Add, this image only
    assert p.get(a).mask(k[0]) is None and p.get(c).frames  # moved off A; the one in between untouched


def test_ctrl_d_over_the_objects_panel(qapp, win):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    ids = make_objects(win, 1)
    p = win.session.project
    win.activateWindow()
    qapp.processEvents()
    win.objects_panel.select_ids(ids)

    def ctrl_d(over, shift=False):
        win._over_objects_panel = lambda: over
        mods = Qt.KeyboardModifier.ControlModifier | (Qt.KeyboardModifier.ShiftModifier if shift else
                                                     Qt.KeyboardModifier.NoModifier)
        o = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_D, mods)
        k = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_D, mods)
        return win.eventFilter(win.canvas, o) and win.eventFilter(win.canvas, k)

    assert not ctrl_d(False) and len(p.objects) == 1  # elsewhere: nothing
    assert ctrl_d(True) and len(p.objects) == 2
    win.objects_panel.select_ids(ids)
    assert ctrl_d(True, shift=True) and len(p.objects) == 3


# --- p18: Solo / Hide Masks on the canvas ---------------------------------------------


def test_solo_and_hide_masks(qapp, win):
    from PyQt6.QtWidgets import QToolBar

    ids = make_objects(win, 3)
    colors = lambda: [o.color for o in win.canvas._overlays if o.style in ("normal", "faint", "edit")]  # noqa: E731
    p = win.session.project
    assert len(colors()) == 3
    win.objects_panel.select_ids([ids[1]])
    win.act_solo.trigger()
    assert colors() == [p.get(ids[1]).color]  # only the selected one
    win.toggle_edit(ids[2])
    assert sorted(colors()) == sorted([p.get(ids[1]).color, p.get(ids[2]).color])  # and the one in Edit
    win.act_hide_masks.trigger()
    assert colors() == []  # Hide: the plain image, the one in Edit too (p37)
    win.finish_editing()
    assert colors() == []
    win.act_hide_masks.trigger()
    win.act_solo.trigger()
    assert len(colors()) == 3
    tb = win.findChild(QToolBar, "main_toolbar").actions()
    assert win.act_solo in tb and win.act_hide_masks in tb


# --- p19: feedback on p16-p18 (lock look, frame colors, W / S over the canvas) ----------


def test_lock_cell_is_empty_until_locked(qapp, win):
    from src.app.objects_panel import LockButton

    ids = make_objects(win, 1)
    op = win.objects_panel
    settle(qapp)
    b = op.tree.findChild(LockButton, f"lock_{ids[0]}")
    assert b.text() == "" and op.lock_all_btn.text() == "Lock All" and op.unlock_all_btn.text() == "Unlock All"
    win.set_locked(ids, True)
    settle(qapp)
    assert b.isChecked() and b.text() == "🔒"
    win.set_locked(ids, False)
    settle(qapp)
    assert not b.isChecked() and b.text() == ""


def test_w_s_over_the_canvas_step_objects_and_wrap(qapp, win):
    from PyQt6.QtCore import Qt

    ids = make_objects(win, 3)
    win.activateWindow()
    qapp.processEvents()
    assert win._zone_of(win.canvas) == "canvas"
    op = win.objects_panel
    op.select_ids([ids[0]])
    assert _key(win, Qt.Key.Key_W, "canvas") and op.selected_ids() == [ids[2]]  # the top's previous: the bottom
    assert _key(win, Qt.Key.Key_S, "canvas") and op.selected_ids() == [ids[0]]  # the bottom's next: the top
    assert _key(win, Qt.Key.Key_S, "canvas") and op.selected_ids() == [ids[1]]
    # A, D and the arrows keep their meaning over the canvas
    for key in (Qt.Key.Key_A, Qt.Key.Key_D, Qt.Key.Key_Up, Qt.Key.Key_Right):
        assert not _key(win, key, "canvas")


# --- p21: Invert / Clear Mask while editing ----------------------------------------------


def test_invert_and_clear_only_while_editing(qapp, win):
    import numpy as np

    ids = make_objects(win, 1)
    s = win.session
    k = s.key
    m0 = s.project.get(ids[0]).mask(k).copy()
    assert win.act_invert.shortcut().toString() == "Ctrl+I"
    assert win.act_clear_mask.shortcut().toString() == "Ctrl+Backspace"
    win.act_invert.trigger()  # not editing: nothing
    assert np.array_equal(s.project.get(ids[0]).mask(k), m0)
    win.toggle_edit(ids[0])
    win.act_invert.trigger()
    assert np.array_equal(s.project.get(ids[0]).mask(k), ~m0)
    win.undo()
    assert np.array_equal(s.project.get(ids[0]).mask(k), m0)
    region = np.zeros(m0.shape, bool)
    region[:, : m0.shape[1] // 2] = True
    s.set_region(region)
    win.act_clear_mask.trigger()  # only inside the region
    after = s.project.get(ids[0]).mask(k)
    assert not (after & region).any() and np.array_equal(after & ~region, m0 & ~region)
    s.set_region(None)
    win.act_clear_mask.trigger()
    assert not s.project.get(ids[0]).mask(k).any()
    assert s.project.get(ids[0]) is not None  # the Object stays


# --- p22: Frame List columns -------------------------------------------------------------


def test_frame_list_rows_are_striped_with_column_rules(qapp, win):
    ip = win.images_panel
    fl = ip.frame_list
    assert fl.alternatingRowColors()
    win.go_to(0)
    settle(qapp)
    img = fl.viewport().grab().toImage()
    rect = fl.visualRect(fl.model().index(2, 0))  # a plain row (not open, not ◎)
    y = rect.center().y()
    row = [img.pixelColor(x, y) for x in range(rect.left(), min(rect.right(), 80))]
    background = row[1]
    assert sum(1 for c in row if c != background) >= 2  # text and at least one rule


# --- c1: COLMAP scenes (docs/specs/06-colmap.md) ------------------------------------------


def test_open_a_colmap_scene_and_load_its_masks(qapp, win, tmp_path):
    import cv2
    import numpy as np

    from tests.unit.test_colmap import make_scene

    root = make_scene(tmp_path / "scene", n=4)
    names = sorted(p.name for p in (root / "images").iterdir())
    h, w = cv2.imread(str(root / "images" / names[0])).shape[:2]
    masks = root / "masks"
    masks.mkdir()
    for name in names[:3]:  # COLMAP style, black = the object (mostly white)
        m = np.full((h, w), 255, np.uint8)
        m[5:25, 5:25] = 0
        cv2.imwrite(str(masks / f"{name}.png"), m)
    asked = []

    def choose(title, text, groups, ok="OK"):
        asked.append(groups)
        return [g[2] for g in groups]  # the suggested color

    win.choose = choose
    assert win.open_folder(root)  # the scene root: its images/ open
    s = win.session
    assert s.image_dir == root / "images" and win.scene is not None
    assert s.store.root == tmp_path / "scene.sms"  # beside the scene
    assert asked and asked[0][0][2] == 2  # mostly white: "Black = the object" suggested
    [o] = s.project.objects
    assert o.name.startswith("masks") and o.source.value == "IMPORTED"
    assert sorted(o.frames) == names[:3]
    m0 = o.mask(names[0])
    assert m0.any() and m0.mean() < 0.5  # the black square became the object
    assert not s.project.can_undo  # p33: the scene's masks open with it; Ctrl+Z does not take them away
    win.undo()
    assert len(s.project.objects) == 1
    win.offer_masks([masks], "Import Masks")  # File > Import Masks: an ordinary, undoable step
    assert len(s.project.objects) == 2
    win.undo()
    assert len(s.project.objects) == 1


def test_scene_mismatch_is_logged(qapp, win, tmp_path):
    from tests.unit.test_colmap import make_scene

    root = make_scene(tmp_path / "scene", n=3, model_names=["frame_000.png", "gone.png"])
    assert win.open_folder(root / "images")
    log = win.log_view.toPlainText()
    assert "1 image(s) in the model but not in images/: gone.png" in log
    assert "2 image(s) in images/ but not in the model" in log


# --- p24: export for a trainer, into the scene's masks/ (docs/specs/07-export-presets.md) ---


def test_export_preset_writes_the_scene_masks_with_a_backup(qapp, win, tmp_path):
    import cv2
    import numpy as np

    from src.app.dialogs import ExportDialog
    from src.core.storage import check_export
    from tests.unit.test_colmap import make_scene

    root = make_scene(tmp_path / "scene", n=3)
    names = sorted(p.name for p in (root / "images").iterdir())
    (root / "masks").mkdir()
    old = root / "masks" / f"{names[0]}.png"
    cv2.imwrite(str(old), np.full((8, 8), 7, np.uint8))  # an older mask that would be overwritten
    win.choose = lambda *a, **kw: None  # do not load the old masks as an Object
    assert win.open_folder(root)
    s = win.session
    s.start_new_object()
    s.click(30, 30)
    s.finish_editing()
    dlg = ExportDialog(tmp_path / "elsewhere", win, check=lambda pat: check_export(s.project, pat),
                       scene=win.scene, target="lichtfeld")
    assert dlg.preset().key == "lichtfeld" and not dlg.out.isEnabled()
    assert "Mask Mode" in dlg.note.text() and "moved to masks_backup_" in dlg.summary.text()
    opts = dlg.options()
    assert opts.out_dir == root / "masks" and opts.name_pattern == "{name}.png"
    assert opts.invert and opts.include_empty and opts.backup
    written = s.export(opts)
    assert sorted(p.name for p in written) == sorted(f"{n}.png" for n in names)  # every image
    [backup] = [d for d in root.iterdir() if d.name.startswith("masks_backup_")]
    assert (backup / old.name).is_file()  # the old file was moved, not lost
    m = cv2.imread(str(root / "masks" / f"{names[0]}.png"), cv2.IMREAD_GRAYSCALE)
    assert m.min() == 0 and m.max() == 255 and (m == 255).mean() > 0.5  # the Object black on white
    blank = cv2.imread(str(root / "masks" / f"{names[1]}.png"), cv2.IMREAD_GRAYSCALE)
    assert blank.min() == 255  # nothing to ignore there: all white
    dlg.target.setCurrentIndex(dlg.target.findData("custom"))
    assert dlg.out.isEnabled() and dlg.out.text() == str(tmp_path / "elsewhere") and not dlg.options().backup


def test_export_outside_a_scene_has_no_trainer_choice(qapp, win, tmp_path):
    from src.app.dialogs import ExportDialog

    dlg = ExportDialog(tmp_path / "out", win)
    assert dlg.target.count() == 1 and dlg.preset() is None and dlg.out.isEnabled()


# --- p25: mask sets, one folder each ------------------------------------------------------


def test_mask_sets_are_saved_undone_and_exported_to_their_folders(qapp, win, tmp_path):
    from pathlib import Path

    import cv2
    import numpy as np

    from src.app.dialogs import ExportDialog
    from src.core.storage import ProjectStore, check_export

    ids = make_objects(win, 2)
    s = win.session
    p = s.project
    k = s.key
    assert p.set_mask_set("people", [ids[0]]) and p.mask_sets == {"people": (ids[0],)}
    win.undo()
    assert p.mask_sets == {}
    win.redo()
    win.save(force=True)
    again = ProjectStore(s.image_dir, s.max_side).load(list(s.keys))
    assert again.mask_sets == {"people": (ids[0],)}
    base = tmp_path / "out"
    dlg = ExportDialog(base, win, check=lambda pat, ids=None: check_export(p, pat, ids), sets=p.mask_sets,
                       save_set=lambda n: p.set_mask_set(n, [o.id for o in p.objects if o.included]),
                       delete_set=lambda n: p.set_mask_set(n, None))
    dlg.mask.setCurrentIndex(dlg.mask.findData("people"))
    [job] = dlg.jobs()
    assert job.out_dir == tmp_path / "out_people" and job.object_ids == [ids[0]]
    assert "out_people/" in dlg.folders.text() and dlg.delete_set_btn.isEnabled()
    dlg.mask.setCurrentIndex(dlg.mask.findData(ExportDialog.EVERY))
    jobs = dlg.jobs()
    assert [j.out_dir for j in jobs] == [base, tmp_path / "out_people"] and jobs[0].object_ids is None
    for j in jobs:
        s.export(j)
    one = cv2.imread(str(tmp_path / "out_people" / f"{Path(k).stem}.png"), cv2.IMREAD_GRAYSCALE) > 0
    both = cv2.imread(str(base / f"{Path(k).stem}.png"), cv2.IMREAD_GRAYSCALE) > 0
    assert one.sum() < both.sum() and np.array_equal(one & both, one)  # the set holds one of the two Objects
    dlg.mask.setCurrentIndex(dlg.mask.findData("people"))
    dlg._remove_set()
    assert p.mask_sets == {} and dlg.mask.count() == 1


# --- p26: Spirula and Postshot presets ------------------------------------------------------


def test_spirula_shares_masks_postshot_gets_its_own_white_folder(qapp, win, tmp_path):
    from src.app.dialogs import ExportDialog
    from src.core.presets import preset
    from tests.unit.test_colmap import make_scene

    sp, ps, br = preset("spirula"), preset("postshot"), preset("brush")
    assert (sp.folder, sp.pattern, sp.object_black) == (br.folder, br.pattern, br.object_black)
    assert ps.folder == "masks_postshot" and not ps.object_black and ps.pattern == "{stem}.png"
    root = make_scene(tmp_path / "scene", n=2)
    win.choose = lambda *a, **kw: None
    assert win.open_folder(root)
    dlg = ExportDialog(tmp_path / "x", win, scene=win.scene, target="postshot")
    o = dlg.options()
    assert o.out_dir == root / "masks_postshot" and not o.invert and o.name_pattern == "{stem}.png"
    assert "Remove Occluders" in dlg.note.text()


# --- p27: points made while SAM2 loads are kept and run when it is ready ---------------------


def test_prompts_wait_for_sam2_and_run_when_it_is_ready(qapp, win):
    s = win.session
    eng = s.engine
    eng.sam2_ready = False
    s.defer_prompts = True
    win.new_object()
    win.on_click(30, 30, True)  # SAM2 still loading
    [o] = s.project.objects
    fs = o.frame(s.key)
    assert len(fs.points) == 1 and fs.mask is None and s.pending == {(o.id, s.key)}  # kept, shown, waiting
    assert "still loading" in win.log_view.toPlainText()
    win.on_click(40, 40, True)  # a second point while waiting
    assert len(s.project.get(o.id).frame(s.key).points) == 2
    eng.sam2_ready = True
    s.defer_prompts = False
    assert s.run_pending() == 1
    fs = s.project.get(o.id).frame(s.key)
    assert fs.mask is not None and fs.mask.any() and not s.pending


def test_prompts_waiting_on_another_image_run_when_it_opens(qapp, win):
    s = win.session
    s.engine.sam2_ready = False
    s.defer_prompts = True
    s.start_new_object()
    s.click(30, 30)
    s.finish_editing()
    oid, first = s.project.objects[0].id, s.key
    s.go_to(1)  # still loading: nothing runs
    s.engine.sam2_ready = True
    s.defer_prompts = False
    assert s.run_pending() == 0  # queued on another image
    s.go_to(0)
    assert s.project.get(oid).mask(first) is not None and not s.pending


# --- p28: exclude frames, export a new dataset (docs/specs/07 6) ----------------------------


def test_excluded_frames_and_a_new_dataset(qapp, win, tmp_path):
    import os

    from src.app.dialogs import ExportDialog
    from src.core.colmap import read_image_names_bin
    from src.core.storage import ProjectStore
    from tests.fakes import make_images
    from tests.unit.test_colmap_model import read_points_bin, write_bin

    root = tmp_path / "scene"
    make_images(root / "images", n=3)
    names = sorted(p.name for p in (root / "images").iterdir())
    write_bin(root / "sparse" / "0", names)
    assert win.open_folder(root)
    s = win.session
    s.start_new_object()
    s.click(30, 30)
    s.finish_editing()
    win.go_to(1)
    win.toggle_excluded()  # the second frame ⊘
    assert s.project.excluded == {names[1]}
    assert "⊘" in win.images_panel.list.item(1).text()
    win.save(force=True)
    assert ProjectStore(s.image_dir, s.max_side).load(list(s.keys)).excluded == {names[1]}
    dlg = ExportDialog(tmp_path / "x", win, scene=win.scene, target="brush", excluded=1)
    assert dlg.dataset_root() is None
    dlg.to_new.setChecked(True)
    new = tmp_path / "out_dataset"
    dlg.dataset.setText(str(new))
    assert dlg.dataset_root() == new and dlg.options().out_dir == new / "masks"
    win.run_export(dlg.jobs(), dataset=new)
    from tests.app.conftest import wait_until

    wait_until(qapp, lambda: not win._busy)
    assert sorted(p.name for p in (new / "images").iterdir()) == [names[0], names[2]]
    assert os.stat(new / "images" / names[0]).st_nlink >= 2 or (new / "images" / names[0]).is_file()
    assert read_image_names_bin(new / "sparse" / "0" / "images.bin") == [names[0], names[2]]
    assert read_points_bin(new / "sparse" / "0" / "points3D.bin") == {1: [1, 3]}
    assert sorted(p.name for p in (new / "masks").iterdir()) == [f"{names[0]}.png", f"{names[2]}.png"]
    assert read_image_names_bin(root / "sparse" / "0" / "images.bin") == names  # the scene is untouched
    win.toggle_excluded()  # again on the same frame: back in
    assert not s.project.excluded
    win.undo()
    assert s.project.excluded == {names[1]}


# --- p29: a 360 scene exported as pinhole views (docs/specs/08) ---------------------------------


def test_erp_scene_to_a_pinhole_dataset(qapp, win, tmp_path):
    from src.app.dialogs import ExportDialog
    from src.core.colmap import read_cameras_full
    from tests.app.conftest import wait_until
    from tests.unit.test_reproject import make_erp_scene

    root = tmp_path / "scene"
    make_erp_scene(root)
    win.choose = lambda *a, **kw: None
    assert win.open_folder(root)
    assert win.scene.camera_models == ["EQUIRECTANGULAR"]
    s = win.session
    s.start_new_object()
    s.click(60, 60)
    s.finish_editing()
    dlg = ExportDialog(tmp_path / "x", win, scene=win.scene, target="lichtfeld")
    assert dlg.views() is None  # into the scene: no conversion
    dlg.to_new.setChecked(True)
    new = tmp_path / "pin"
    dlg.dataset.setText(str(new))
    assert dlg.views() is None  # Keep the cameras: the dataset stays 360
    assert dlg.convert.findData("erp") < 0  # a 360 scene is not converted to 360
    dlg.convert.setCurrentIndex(dlg.convert.findData("pinhole"))
    assert dlg.view_layout.currentData() == "colmap12" and len(dlg.views().pairs()) == 12  # p57: COLMAP's layout
    assert "12 views" in dlg.layout_note.text() and len(dlg.view_preview._views) == 12  # p58: note + map
    dlg.view_layout.setCurrentIndex(dlg.view_layout.findData("rings16"))
    assert len(dlg.view_preview._views) == 16 and "overlap" in dlg.layout_note.text()
    dlg.view_layout.setCurrentIndex(dlg.view_layout.findData("colmap12"))
    assert not dlg.yaws.isVisibleTo(dlg)
    dlg.view_layout.setCurrentIndex(dlg.view_layout.findData(None))  # Custom: the yaw x pitch grid
    assert dlg.yaws.isVisibleTo(dlg)
    dlg.yaws.setText("0, 60, 120, 180, 240, 300")
    dlg.pitches.setText("0")
    dlg.side.setValue(64)
    v = dlg.views()
    assert len(v.pairs()) == 6 and v.size == 64
    win.run_export(dlg.jobs(), dataset=new, views=v)
    wait_until(qapp, lambda: not win._busy)
    assert len(list((new / "images").iterdir())) == 12 and len(list((new / "masks").iterdir())) == 12
    assert [c.model for c in read_cameras_full(new / "sparse" / "0").values()] == ["PINHOLE"]
    assert "Converted dataset" in win.log_view.toPlainText()


# --- p30: a fisheye scene to 360 or pinhole views --------------------------------------------------


def test_fisheye_scene_to_a_360_dataset(qapp, win, tmp_path):
    from src.app.dialogs import ExportDialog
    from src.core.colmap import read_cameras_full
    from src.core.reproject import Erp
    from tests.app.conftest import wait_until
    from tests.unit.test_reproject import make_fisheye_scene

    root = tmp_path / "fish"
    make_fisheye_scene(root)
    win.choose = lambda *a, **kw: None
    assert win.open_folder(root)
    dlg = ExportDialog(tmp_path / "x", win, scene=win.scene, target="brush")
    dlg.to_new.setChecked(True)
    new = tmp_path / "erp"
    dlg.dataset.setText(str(new))
    assert dlg.yaws.text() == "-45, 0, 45"  # a fisheye's default views
    dlg.convert.setCurrentIndex(dlg.convert.findData("erp"))
    assert isinstance(dlg.views(), Erp) and not dlg.yaws.isVisibleTo(dlg)
    win.run_export(dlg.jobs(), dataset=new, views=dlg.views())
    wait_until(qapp, lambda: not win._busy)
    assert [c.model for c in read_cameras_full(new / "sparse" / "0").values()] == ["EQUIRECTANGULAR"]
    assert len(list((new / "masks").iterdir())) == 2


# --- p31: a multi-camera scene's sub-folders (images/cam0/, images/cam1/) --------------------------


def test_scene_images_in_sub_folders(qapp, win, tmp_path):
    import cv2
    import numpy as np

    from src.app.dialogs import ExportDialog
    from src.app.images_panel import thumb_name
    from tests.fakes import make_images
    from tests.unit.test_colmap import write_model_bin

    root = tmp_path / "rig"
    for cam in ("cam0", "cam1"):
        make_images(root / "images" / cam, n=2)
    (root / "images" / "masks_old").mkdir()  # a mask folder among the images is not a camera
    cv2.imwrite(str(root / "images" / "masks_old" / "x.png"), np.zeros((4, 4), np.uint8))
    names = [f"{c}/frame_00{i}.png" for c in ("cam0", "cam1") for i in (0, 1)]
    write_model_bin(root / "sparse" / "0", names)
    win.choose = lambda *a, **kw: None
    assert win.open_folder(root)
    s = win.session
    assert s.keys == names  # relative, with the folder
    assert thumb_name(s.paths[0]) != thumb_name(s.paths[2])  # same file name, other camera
    s.start_new_object()
    s.click(30, 30)
    s.finish_editing()
    win.save(force=True)
    assert (s.store.mask_path(s.project.objects[0].id, names[0])).is_file()
    dlg = ExportDialog(tmp_path / "x", win, scene=win.scene, target="colmap")
    written = s.export(dlg.options())
    assert (root / "masks" / "cam0" / "frame_000.png.png") in written
    assert (root / "masks" / "cam1" / "frame_000.png.png").is_file()  # the other camera's own file
    assert "1 image(s) in images/ but not in the model" not in win.log_view.toPlainText()


# --- p32: dual fisheye stitched into 360 images --------------------------------------------------------


def test_dual_fisheye_scene_stitched_from_the_export(qapp, win, tmp_path):
    from src.app.dialogs import ExportDialog
    from src.core.colmap import read_cameras_full, read_image_names_bin
    from src.core.reproject import Stitch
    from tests.app.conftest import wait_until
    from tests.unit.test_reproject import make_dual_fisheye_scene

    root = tmp_path / "rig"
    make_dual_fisheye_scene(root, frames=3)
    win.choose = lambda *a, **kw: None
    assert win.open_folder(root)
    s = win.session
    assert s.keys[0] == "cam0/000.png" and len(s.keys) == 6
    win.go_to(s.keys.index("cam1/001.png"))
    win.toggle_excluded()  # one lens of the second moment: that moment is left out
    dlg = ExportDialog(tmp_path / "x", win, scene=win.scene, target="brush", excluded=1)
    dlg.to_new.setChecked(True)
    new = tmp_path / "pano"
    dlg.dataset.setText(str(new))
    i = dlg.convert.findData("stitch")
    assert i >= 0 and "3 moments" in dlg.convert.itemText(i)
    dlg.convert.setCurrentIndex(i)
    dlg.side.setValue(256)
    assert isinstance(dlg.views(), Stitch)
    win.run_export(dlg.jobs(), dataset=new, views=dlg.views())
    wait_until(qapp, lambda: not win._busy)
    assert read_image_names_bin(new / "sparse" / "0" / "images.bin") == ["000.jpg", "002.jpg"]
    assert [c.model for c in read_cameras_full(new / "sparse" / "0").values()] == ["EQUIRECTANGULAR"]
    assert sorted(p.name for p in (new / "masks").iterdir()) == ["000.jpg.png", "002.jpg.png"]


# --- p34: the selected Objects on many picked frames at once (clear, copy the mask) ------------------


def _pick(win, rows):
    lst = win.images_panel.list
    lst.clearSelection()
    for r in rows:
        lst.item(r).setSelected(True)


def test_clear_masks_on_picked_frames(qapp, win):
    a, b = _two_linked(win)
    s = win.session
    k = s.keys
    win.objects_panel.select_ids([a])
    _pick(win, [0, 2, 3])
    win.clear_picked_frames()
    assert not s.project.get(a).frames  # A's masks on 0 and 2 went
    assert sorted(s.project.get(b).frames) == [k[0], k[3]]  # B was not selected
    assert "Cleared 2 mask(s)" in win.log_view.toPlainText()
    win.undo()  # one step
    assert sorted(s.project.get(a).frames) == [k[0], k[2]]
    assert win.act_clear_frames in win.images_panel.frame_list.actions()  # right-click (back in p40)


def test_copy_mask_to_picked_frames_add_or_replace(qapp, win):
    import numpy as np

    from src.core.project import FrameStatus

    a, b = _two_linked(win)
    s = win.session
    k = s.keys
    win.go_to(0)
    win.objects_panel.select_ids([b])
    _pick(win, [0, 1, 3])
    win.stamp_picked_frames()  # Replace (default since p40)
    o = s.project.get(b)
    src = o.mask(k[0])
    assert np.array_equal(o.mask(k[1]), src) and o.frame(k[1]).status == FrameStatus.PROPAGATED
    assert np.array_equal(o.mask(k[3]), src)  # the same box: the union is that box
    win.undo()
    assert sorted(s.project.get(b).frames) == [k[0], k[3]]
    win.set_reference(2)  # the reference ◎ is the source, wherever the open image went
    win.go_to(2)
    win.objects_panel.select_ids([a])
    qapp.processEvents()
    win.go_to(3)  # picking frames opened one where A is not listed: A stays the Object to copy
    assert win.objects_panel.selected_ids() == []
    _pick(win, [0, 3])
    win.choose = lambda title, text, groups, ok="OK": [0]  # Options: Replace
    win.stamp_options()
    assert np.array_equal(s.project.get(a).mask(k[3]), s.project.get(a).mask(k[2]))
    assert "on " + k[2] in win.log_view.toPlainText()
    win.set_reference(2)  # off again
    win.objects_panel.select_ids([a])
    _pick(win, [3])  # only the source (no reference now: the open image) picked: nothing to copy to
    before = s.project.revision
    win.stamp_picked_frames()
    assert s.project.revision == before and "Pick the frames to copy to" in win.log_view.toPlainText()


# --- p35: propagation takes the selected Objects (the overwrite check only looks at them) -------------


def test_propagation_warns_only_about_the_selected_objects(qapp, win):
    from src.core.propagation import Direction

    a, b = _two_linked(win)  # A on 0 and 2, B on 0 and 3
    s = win.session
    k = s.keys
    win.go_to(0)
    asked = []
    win.ask = lambda title, text, ok: asked.append(text) or False  # answer "no": nothing runs
    win.objects_panel.select_ids([a])
    win.propagate(0, 3, Direction.FORWARD)
    assert asked and k[2] in asked[0] and k[3] not in asked[0]  # B's mask on 3 is not A's business
    asked.clear()
    win.objects_panel.select_ids([b])
    win.propagate(0, 3, Direction.FORWARD)
    assert k[3] in asked[0] and k[2] not in asked[0]
    asked.clear()
    win.objects_panel.select_ids([])
    win.objects_panel.last_selected = []  # none selected: every checked Object, as before
    win.propagate(0, 3, Direction.FORWARD)
    assert k[2] in asked[0] and k[3] in asked[0]


# --- p36: special Objects, made from settings (docs/specs/09-special-objects.md) ---------------------


def test_lens_edge_object_made_from_settings(qapp, win):
    from src.core.special import LENS_EDGE

    s = win.session
    win.add_special(LENS_EDGE)
    [o] = s.project.objects
    assert o.special is not None and o.name.startswith("Lens edge")
    assert o.id in win.objects_panel.listed_ids()  # listed although it has no mask yet
    sp = win.properties_panel.special
    assert sp.obj_id == o.id and win.properties_panel.tabs.currentIndex() == win.properties_panel.special_tab
    win.special_generate("all", 0, -1)
    o = s.project.get(o.id)
    assert len(o.frames) == len(s.keys) and len(o.special.keys) == len(s.keys)
    h, w = o.mask(s.keys[0]).shape
    assert o.mask(s.keys[0])[0, 0] and not o.mask(s.keys[0])[h // 2, w // 2]
    before = int(o.mask(s.keys[0]).sum())
    win.special_params(o.id, {"radius": 60})  # every frame follows the setting
    o = s.project.get(o.id)
    assert o.special.get("radius") == 60 and int(o.mask(s.keys[3]).sum()) > before
    assert o.mask(s.keys[3]) is o.mask(s.keys[0])  # p43: one mask per image size, shared
    win.toggle_edit(o.id)  # made from settings: not edited by hand
    assert s.editing is None and "Apply it" in win.log_view.toPlainText()
    win.special_apply()
    assert s.project.get(o.id).special is None
    win.undo()  # special again
    assert s.project.get(o.id).special is not None
    assert s.seeds(s.index, ids=[o.id]) == {}  # a special Object is not propagated


def test_sky_object_with_a_model_and_its_saved_settings(qapp, win, tmp_path):
    import numpy as np

    from src.core.special import SKY

    class TopHalf:  # stands in for the network: the upper half is sky
        runs = 0

        def probability(self, rgb):
            TopHalf.runs += 1
            p = np.zeros(rgb.shape[:2], np.uint8)
            p[: rgb.shape[0] // 2] = 230
            return p

    s = win.session
    win.add_special(SKY)
    [o] = s.project.objects
    model = win.settings.sky_checkpoint = str(tmp_path / "sky.onnx")
    win.special_generate("all", 0, -1)
    assert "sky model is not there" in win.log_view.toPlainText()  # warn -> log in tests
    keys = s.keys[1:4]  # (image 0 is all black: never sky, v0.4-p47)
    assert s.sky_missing(keys) == keys
    assert s.compute_sky(keys, TopHalf()) == 3 and not s.sky_missing(keys)
    win.images_panel.list.clearSelection()
    for r in range(1, 4):
        win.images_panel.list.item(r).setSelected(True)
    open(model, "wb").close()  # a model file exists (not used: every picked frame is already cached)
    win.special_generate("selected", 0, -1)
    o = s.project.get(o.id)
    assert sorted(o.frames) == sorted(keys) and TopHalf.runs == 3
    m = o.mask(keys[0])
    assert m[1, 1] and not m[-2, 1]
    win.special_params(o.id, {"threshold": 95})  # above the map everywhere: no sky
    assert not s.project.get(o.id).frames and s.project.get(o.id).special.keys == tuple(keys)
    win.special_params(o.id, {"threshold": 40, "grow": 4})
    win.save(force=True)
    from src.core.storage import ProjectStore

    back = ProjectStore(s.image_dir, s.max_side).load(list(s.keys))
    ob = back.get(o.id)
    assert ob.special is not None and ob.special.get("grow") == 4 and ob.special.keys == tuple(keys)


# --- p38: propagation shows each frame as it is done; Stop stays there, Cancel goes back ----------------


def test_propagation_live_view_stop_and_cancel(qapp, win):
    import threading

    from tests.app.conftest import wait_until
    from tests.app.test_v03_features import gated_propagate

    s = win.session
    pp = win.propagation_panel
    win.new_object()
    s.click(30, 30)  # on image 0
    win.finish_editing()
    oid = s.project.objects[0].id
    release, entered = threading.Event(), threading.Event()
    win.propagate_fn = gated_propagate(release, entered, after=2)
    pp.scope.setCurrentIndex(pp.scope.findData("all"))
    pp.run_btn.click()
    wait_until(qapp, entered.is_set)
    wait_until(qapp, lambda: win._live is not None and win._live[0] == 2)
    assert win.canvas._overlays and s.index == 0  # frame 2's new mask on the canvas; the open frame is unchanged
    pp.stop_btn.click()
    release.set()
    wait_until(qapp, lambda: win._busy is None)
    assert s.index == 2 and win._live is None  # Stop: stays on the last frame done
    assert len(s.project.get(oid).frames) == 3 and pp.resume_btn.isEnabled()

    release2, entered2 = threading.Event(), threading.Event()
    win.propagate_fn = gated_propagate(release2, entered2, after=1)
    pp.resume_btn.click()  # from frame 2 over 3, 4
    wait_until(qapp, entered2.is_set)
    pp.cancel_btn.click()
    release2.set()
    wait_until(qapp, lambda: win._busy is None)
    assert s.index == 2 and win._live is None  # Cancel: back to the frame that was open
    assert len(s.project.get(oid).frames) == 4 and not pp.resume_btn.isEnabled()  # frame 3 kept
    assert "Ctrl+Z" in pp.phase.text()
    win.undo()
    assert len(s.project.get(oid).frames) == 3
    order = [pp.stop_btn, pp.resume_btn, pp.cancel_btn]
    assert sorted(order, key=lambda b: b.x()) == order  # Stop / Resume / Cancel


# --- p39: into a scene, the export follows the masks already there and backs up per folder -------------


def test_scene_export_follows_existing_names_and_keeps_camera_folders(qapp, win, tmp_path):
    import cv2
    import numpy as np

    from src.app.dialogs import ExportDialog
    from src.core.storage import check_export
    from tests.unit.test_reproject import make_dual_fisheye_scene

    root = tmp_path / "rig"
    make_dual_fisheye_scene(root, frames=2)  # images/cam0/000.png, cam1/000.png, ...
    for cam in ("cam0", "cam1"):  # masks from another tool: a.png naming, same names in both cameras
        (root / "masks" / cam).mkdir(parents=True)
        for k in range(2):
            cv2.imwrite(str(root / "masks" / cam / f"{k:03d}.png"), np.full((8, 8), 10 + k, np.uint8))
    stale = root / "masks" / "cam0" / "000.png.png"  # and one left by an earlier export in the other naming
    cv2.imwrite(str(stale), np.full((8, 8), 99, np.uint8))
    win.choose = lambda *a, **kw: None
    assert win.open_folder(root)
    s = win.session
    dlg = ExportDialog(tmp_path / "x", win, check=lambda pat: check_export(s.project, pat),
                       scene=win.scene, target="spirula")
    opts = dlg.options()
    assert opts.name_pattern == "{stem}.png" and "follow the masks already" in dlg.note.text()
    assert "5 file(s) in masks/ will be moved" in dlg.summary.text()
    s.export(opts)
    for cam in ("cam0", "cam1"):
        assert sorted(p.name for p in (root / "masks" / cam).iterdir()) == ["000.png", "001.png"]  # replaced
        assert cv2.imread(str(root / "masks" / cam / "000.png"), cv2.IMREAD_GRAYSCALE).min() == 255
    [backup] = [d for d in root.iterdir() if d.name.startswith("masks_backup_")]
    kept = sorted(p.relative_to(backup).as_posix() for p in backup.rglob("*.png"))
    assert kept == ["cam0/000.png", "cam0/000.png.png", "cam0/001.png", "cam1/000.png", "cam1/001.png"]
    assert cv2.imread(str(backup / "cam1" / "001.png"), cv2.IMREAD_GRAYSCALE)[0, 0] == 11  # nothing overwritten
    colmap = ExportDialog(tmp_path / "x", win, check=lambda pat: check_export(s.project, pat),
                          scene=win.scene, target="colmap")
    assert colmap.options().name_pattern == "{name}.png"  # COLMAP reads a.jpg.png only


# --- p40: the Frame List: middle click opens a frame and keeps the picks; right click keeps them ---------


def test_middle_click_opens_a_frame_and_keeps_the_picks(qapp, win):
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtWidgets import QApplication

    s = win.session
    lst = win.images_panel.frame_list
    lst.selectionModel().clearSelection()
    for r in (1, 2):
        win.images_panel.list.item(r).setSelected(True)

    def press(button, row):
        pos = QPointF(lst.visualRect(lst.model().index(row, 0)).center())
        ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos, pos, button, button,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(lst.viewport(), ev)
        qapp.processEvents()

    press(Qt.MouseButton.MiddleButton, 4)
    assert s.index == 4 and win.images_panel.selected_rows() == [1, 2]  # opened, picks kept
    press(Qt.MouseButton.RightButton, 0)
    assert s.index == 4 and win.images_panel.selected_rows() == [1, 2]  # right click changes nothing


# --- p41: moving to another frame while editing keeps editing there ----------------------------------


def test_moving_frames_while_editing(qapp, win):
    from src.app.session import Mode

    ids = make_objects(win, 1)
    s = win.session
    p = win.properties_panel
    win.toggle_edit(ids[0])
    win.set_brush(True)
    assert win._tool == "paint"
    win.step(1)
    assert s.index == 1 and s.mode == Mode.EDIT and s.editing == ids[0] and win._tool == "paint"
    win.go_to(0)
    p.tool_btns["grow"].click()
    p.mode_paint_btn.click()  # Paint mode: everything picked, not written yet
    win.step(1)
    assert s.index == 0 and "not written in yet" in win.statusBar().currentMessage()
    win.a_key()  # nothing picked: nothing to lose
    win.step(1)
    assert s.index == 1 and s.editing == ids[0] and s.auto_tool is None


# --- p42: a drag left / right sets the brush size (Alt+right-drag until p83, now Ctrl+drag) ---------------


def test_ctrl_drag_sets_the_brush_size(qapp, win):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    c = win.canvas
    c.set_brush_size(30)
    ctrl = Qt.KeyboardModifier.ControlModifier
    start = QPoint(200, 200)
    QTest.mousePress(c, Qt.MouseButton.RightButton, ctrl, start)
    QTest.mouseMove(c, start + QPoint(20, 0))
    assert c.brush_size == 70 and c._mouse == start  # bigger to the right; the circle stays put
    QTest.mouseMove(c, start + QPoint(-10, 0))
    assert c.brush_size == 10
    QTest.mouseRelease(c, Qt.MouseButton.RightButton, ctrl, start + QPoint(-10, 0))
    assert c._size_drag is None and not win.session.editing_frame().points[1:]  # no negative point added


# --- p44: Ctrl+click adds / takes out the piece under the cursor, the rest of the mask stays ------------


def test_ctrl_click_adds_or_takes_out_a_piece(qapp, win):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    from tests.app.test_gui import canvas_pos

    ids = make_objects(win, 1)
    s = win.session
    win.toggle_edit(ids[0])
    win.set_brush(True)  # the brush is on: Ctrl+click works all the same
    before = s.editing_frame().mask.copy()
    fs0 = s.editing_frame()
    far = (70, 50)
    assert not before[far[1], far[0]]
    ctrl = Qt.KeyboardModifier.ControlModifier
    q = canvas_pos(win, *far)
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, ctrl, q)
    fs = s.editing_frame()
    assert fs.mask[far[1], far[0]] and (fs.mask | ~before).all()  # added, nothing lost
    assert fs.points == fs0.points and fs.edit is not None  # in the edit layer; the prompts unchanged
    QTest.mouseClick(win.canvas, Qt.MouseButton.RightButton, ctrl, q)
    assert not s.editing_frame().mask[far[1], far[0]]  # taken out again
    win.undo()
    assert s.editing_frame().mask[far[1], far[0]]  # one undo step each


# --- p48: an unchecked Object keeps its check box when the rows are made again ---------------------------


def test_unchecked_object_keeps_its_check_box(qapp, win):
    from PyQt6.QtCore import Qt

    ids = make_objects(win, 2)
    s = win.session
    s.project.set_included(ids[0], False)
    win.refresh()
    make_objects(win, 1)  # a new row: the list is made again
    from src.app.objects_panel import ID_ROLE

    tree = win.objects_panel.tree
    [item] = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
              if tree.topLevelItem(i).data(0, ID_ROLE) == ids[0]]
    assert item.data(1, Qt.ItemDataRole.CheckStateRole) is not None  # the box is drawn (column 1, after the eye)
    assert item.checkState(1) == Qt.CheckState.Unchecked


# --- p49: in an auto tool D = Paint <-> Fill, A = leave (cancel), F = apply (confirm); Q / H -------------


def test_auto_tool_keys_a_d_f_and_view_keys(qapp, win):
    ids = make_objects(win, 1)
    s = win.session
    p = win.properties_panel
    win.toggle_edit(ids[0])
    area0 = s.editing_frame().mask.sum()
    p.amount.setValue(2)
    p.tool_btns["grow"].click()
    assert s.auto_mode == "fill"
    win.act_brush.trigger()  # D: Paint mode, everything picked the first time
    assert s.auto_mode == "paint" and p.mode_paint_btn.isChecked() and win.canvas.brush_mode
    assert s.auto_taken().any()
    win.act_brush.trigger()  # D again in Paint: pick none (p55)
    assert s.auto_mode == "paint" and not s.auto_taken().any()
    win.act_auto_fill.trigger()  # S: Fill
    assert s.auto_mode == "fill" and s.auto_tool == "grow" and not win.canvas.brush_mode
    win.act_brush.trigger()  # D: Paint again, the picks as they were (none), not everything again
    assert s.auto_mode == "paint" and not s.auto_taken().any()
    win.act_brush.trigger()  # pick all
    win.act_apply_continue.trigger()  # G: apply and go on
    assert s.editing_frame().mask.sum() > area0 and s.auto_tool == "grow"
    area1 = s.editing_frame().mask.sum()
    win.act_auto_fill.trigger()  # S: Fill (the next result, all of it)
    win.act_go_reference.trigger()  # F (mouse off the frame lists): apply and close
    assert s.auto_tool is None and s.editing_frame().mask.sum() > area1 and s.editing == ids[0]
    area2 = s.editing_frame().mask.sum()
    p.tool_btns["grow"].click()
    win.act_leave_auto.trigger()  # A: leave, the result dropped
    assert s.auto_tool is None and s.editing_frame().mask.sum() == area2
    assert [a.toString() for a in win.act_solo.shortcuts()] == ["Q", "`"]
    assert win.act_hide_masks.shortcut().toString() == "H" and win.act_pick_all.shortcut().toString() == "Shift+A"


# --- p50: 👁 per Object (view only, apart from the Final Mask check box) ---------------------------------


def test_eye_hides_an_object_on_the_image_only(qapp, win):
    from src.app.objects_panel import EyeButton

    ids = make_objects(win, 2)
    s = win.session
    op = win.objects_panel

    def colors():
        return sorted(o.color for o in win.canvas._overlays)

    both = colors()
    eye = op.tree.findChild(EyeButton, f"eye_{ids[0]}")
    eye.click()
    qapp.processEvents()
    assert colors() == [s.project.get(ids[1]).color] and s.project.get(ids[0]).included  # still in the Final Mask
    win.toggle_edit(ids[0])  # the Object in Edit shows, 👁 or not (p52)
    assert s.project.get(ids[0]).color in colors()
    win.finish_editing()
    assert s.project.get(ids[0]).color not in colors()
    make_objects(win, 1)  # rows made again: it stays hidden
    assert not op.tree.findChild(EyeButton, f"eye_{ids[0]}").shown
    op.tree.findChild(EyeButton, f"eye_{ids[0]}").click()
    qapp.processEvents()
    assert len(colors()) == 3 and set(both) <= set(colors())
    assert "▾" in op.special_btn.text()


# --- p53: point layers inside an Object (docs/specs/10-prompt-layers.md) --------------------------------


def _imported(win):
    """An Object whose mask came without points (like an imported one): a box on the left of image 0."""
    import numpy as np

    from src.core.project import FrameState, Source

    s = win.session
    h, w = s.working_hw()
    m = np.zeros((h, w), bool)
    m[5:30, 5:30] = True
    oid = s.project.add_object(s.keys[0], FrameState.from_mask(m), Source.IMPORTED, "imported")
    win.refresh()
    return oid, m


def test_point_layers_add_and_take_out_pieces_keeping_the_mask(qapp, win):
    s = win.session
    oid, m = _imported(win)
    win.toggle_edit(oid)
    assert s.current_layer() == 1  # no points of its own: the first click makes Layer 1
    s.click(60, 40)
    fs = s.editing_frame()
    assert len(fs.layers) == 1 and fs.layers[0].points and fs.prompt_mask is fs.base_mask
    assert fs.mask[40, 60] and (fs.mask | ~m).all()  # the piece added, the mask kept
    assert s.engine.calls[-1][2] is False  # the layer's piece: its own prompts only, no seed
    s.toggle_layer_subtract()  # the same piece now taken out
    assert not s.editing_frame().mask[40, 60]
    s.toggle_layer_subtract()
    s.add_layer(subtract=True)
    s.click(10, 10)  # a subtract layer: the piece under the click goes
    fs = s.editing_frame()
    assert len(fs.layers) == 2 and not fs.mask[10, 10] and fs.mask[40, 60]
    s.select_layer(0)  # the Original: points refine the old mask as before (seeded)
    assert s.active_prompts() == ((), None)
    s.select_layer(2)
    s.remove_layer()
    assert s.current_layer() == 1 and s.editing_frame().mask[10, 10]
    painted = s.editing_frame().mask.copy()
    painted[50:55, 5:10] = True
    s.brush(painted)  # a hand edit on top of the layers
    s.delete_prompt(1, 0)  # the layer's only point (× in the list): its piece goes, the paint stays
    fs = s.editing_frame()
    assert not fs.mask[40, 60] and fs.mask[52, 7] and fs.mask[10, 10]
    win.undo()
    assert s.editing_frame().mask[40, 60]


def test_point_layers_are_saved_and_shown(qapp, win):
    from src.app.properties_panel import LAYER_ROLE
    from src.core.storage import ProjectStore

    s = win.session
    oid, _m = _imported(win)
    win.toggle_edit(oid)
    s.click(60, 40)
    s.click(62, 44, positive=False)
    win.refresh()
    tree = win.properties_panel.points
    assert tree.topLevelItemCount() == 2 and tree.topLevelItem(1).text(0) == "Layer 1 (+)"
    assert tree.topLevelItem(1).childCount() == 2 and tree.topLevelItem(1).font(0).bold()
    x = tree.itemWidget(tree.topLevelItem(1).child(1), 1)
    x.click()  # × on the negative point
    qapp.processEvents()
    assert len(s.editing_frame().layers[0].points) == 1
    win.properties_panel.add_layer_btn.click()
    qapp.processEvents()
    assert s.current_layer() == 2 and len(s.editing_frame().layers) == 2
    win.save(force=True)
    back = ProjectStore(s.image_dir, s.max_side).load(list(s.keys)).get(oid).frame(s.keys[0])
    fs = s.editing_frame()
    assert len(back.layers) == 2 and back.layers[0].points == fs.layers[0].points and back.layers[1].mask is None
    assert (back.mask == fs.mask).all()
    assert tree.topLevelItem(0).data(0, LAYER_ROLE) == 0


# --- p54: an export shows its progress -----------------------------------------------------------------


def test_export_shows_progress(qapp, win, tmp_path):
    from src.core.storage import ExportOptions
    from tests.app.conftest import wait_until

    make_objects(win, 1)
    seen = []
    win.run_export(ExportOptions(out_dir=tmp_path / "out", include_empty=True))
    bar = win._export_bar
    assert bar.isVisible()
    wait_until(qapp, lambda: (seen.append(bar.labelText()) or win._busy is None))
    assert not bar.isVisible() and len(list((tmp_path / "out").iterdir())) == len(win.session.keys)


# --- p56: the eye first in the row, a plain one-color icon --------------------------------------------


def test_eye_is_the_first_column(qapp, win):
    from src.app.objects_panel import EYE, NAME, EyeButton

    ids = make_objects(win, 1)
    tree = win.objects_panel.tree
    item = tree.topLevelItem(0)
    assert isinstance(tree.itemWidget(item, EYE), EyeButton) and EYE == 0
    assert item.text(NAME) == win.session.project.get(ids[0]).name and item.checkState(NAME) is not None
    eye = tree.itemWidget(item, EYE)
    assert eye.text() == "" and not eye.icon().isNull()  # drawn, not the color emoji
    assert tree.visualItemRect(item).left() <= eye.geometry().left() < 40



# --- p61: Invert as an auto tool, Apply to All Frames (Fill mode) ------------------------------------------


def test_invert_auto_tool_previews_then_flips(qapp, win):
    ids = make_objects(win, 1)
    s = win.session
    win.toggle_edit(ids[0])
    before = s.editing_frame().mask.copy()
    p = win.properties_panel
    p.tool_btns["invert"].click()
    assert s.auto_tool == "invert" and "Invert" in p.settings_box.title()
    added, removed = s.auto_changes()
    assert (added == ~before).all() and (removed == before).all()
    assert (s.editing_frame().mask == before).all()  # a preview until applied
    win.apply_and_leave_tool()
    assert (s.editing_frame().mask == ~before).all()
    win.undo()
    assert (s.editing_frame().mask == before).all()


def test_apply_to_all_frames_in_fill_mode_only(qapp, win):
    import numpy as np

    from src.core.project import FrameState, FrameStatus
    from tests.app.conftest import wait_until

    ids = make_objects(win, 1)
    s = win.session
    p = s.project
    k0, k2 = s.keys[0], s.keys[2]
    p.set_frame(ids[0], k2, FrameState.from_mask(p.get(ids[0]).mask(k0), status=FrameStatus.PROPAGATED))
    m0, m2 = p.get(ids[0]).mask(k0).copy(), p.get(ids[0]).mask(k2).copy()
    win.toggle_edit(ids[0])
    pp = win.properties_panel
    assert pp.apply_all_btn.isHidden() or not pp.apply_all_btn.isEnabled()  # no auto tool yet
    pp.tool_btns["invert"].click()
    assert not pp.apply_all_btn.isHidden() and pp.apply_all_btn.isEnabled()
    pp.mode_paint_btn.click()
    assert pp.apply_all_btn.isHidden()  # Paint mode: picks are per image
    pp.mode_fill_btn.click()
    asked = []
    win.choose = lambda title, text, groups, ok="OK": asked.append(groups[0][1]) or [0]  # All
    pp.apply_all_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    assert asked and "All: 2 frame(s)" in asked[0][0]
    o = p.get(ids[0])
    assert (o.mask(k0) == ~m0).all() and (o.mask(k2) == ~m2).all()
    assert o.mask(s.keys[1]) is None  # a frame without a mask stays empty
    assert o.frame(k2).edit is not None and o.frame(k2).status == FrameStatus.MANUAL
    win.undo()  # one undo step for all
    o = p.get(ids[0])
    assert (o.mask(k0) == m0).all() and (o.mask(k2) == m2).all()
    assert s.auto_tool == "invert"  # the tool stays on, its preview recomputed for the restored mask
    wait_until(qapp, lambda: s.auto_changes()[0] is not None and bool((s.auto_changes()[0] == ~m0).all()))
    assert np.array_equal(s.editing_frame().mask, m0)


# --- p62: Sky edges at full resolution on export ------------------------------------------------------------------


def test_export_dialog_offers_sky_edges_only_with_a_sky(qapp, win, tmp_path):
    from src.app.dialogs import ExportDialog

    plain = ExportDialog(tmp_path / "out", win)
    assert plain.sky_edges.isHidden() and not plain.options().sky_edges
    dlg = ExportDialog(tmp_path / "out", win, sky=True, sky_edges=True)
    assert not dlg.sky_edges.isHidden() and dlg.options().sky_edges
    dlg.sky_edges.setChecked(False)
    assert not dlg.options().sky_edges
    assert win.settings.export_sky_edges  # on by default


# --- p66: batch masking with presets (src/app/batch_mask_dialog.py) ---------------------------


def test_batch_mask_dialog_edits_a_preset_and_builds_the_commands(qapp, win, tmp_path, monkeypatch):
    import json

    from PyQt6.QtWidgets import QInputDialog

    from src.app.batch_mask_dialog import BatchMaskDialog
    from src.batchmask import presets as P

    monkeypatch.setenv(P.ENV, str(tmp_path / "mine"))
    assert win.act_batch_masks.text().startswith("&Batch Masking")
    d = BatchMaskDialog(win.session.image_dir, tmp_path / "scene")
    i = d.preset.findData("osmo360-selfie-stick")
    d.preset.setCurrentIndex(i)
    assert d.current() == P.find_preset("osmo360-selfie-stick") and d.current().checked_on
    assert "black pole" in d.labels.text() and d.lens_box.isChecked() and d.sky_box.isChecked()

    d.labels.setText("person, silver pole")
    d.lens_box.setChecked(False)
    p = d.current()
    assert p.person.labels == ["person", "silver pole"] and p.lens is None and not p.checked_on  # edited: unchecked

    args = d.run_args()
    assert args[:2] == ["run", str(win.session.image_dir)] and "--out" in args
    written = json.loads(open(args[args.index("--preset") + 1], encoding="utf-8").read())
    assert written["person"]["labels"] == ["person", "silver pole"] and written["lens"] is None
    d.also.setText("tripod")
    d.reference.setText(str(tmp_path))
    d.inside.setValue(90)
    pa = d.probe_args()
    assert pa[0] == "probe" and pa[pa.index("--also") + 1] == "tripod" and pa[pa.index("--inside") + 1] == "90"

    answers = iter([("silver", True), ("scene Y: 8 frames looked at", True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: next(answers))
    path = d.save_as()
    assert path == tmp_path / "mine" / "silver.json" and d.preset.currentData() == "silver"
    saved = P.find_preset("silver")
    assert saved.lens is None and saved.checked_on == ["scene Y: 8 frames looked at"]
    tmp = d._tmp
    d.done(0)
    assert not tmp.exists()


def test_by_color_auto_tool_redraws_the_edge(qapp, win):
    """p68: By Color decides the pixels near the mask's edge again by the image (a preview first). p97: Range only
    (the Auto ways are gone), here a brightness range."""
    ids = make_objects(win, 1)
    s = win.session
    win.toggle_edit(ids[0])
    before = s.editing_frame().mask.copy()
    p = win.properties_panel
    p.bright_use.setChecked(True)
    p.bright_lo.setValue(100)
    p.tool_btns["by_color"].click()
    assert s.auto_tool == "by_color" and "By Color" in p.settings_box.title()
    from tests.app.conftest import wait_until

    wait_until(qapp, lambda: s.auto_changes()[0] is not None)  # computed off the UI thread (reads the image)
    assert (s.editing_frame().mask == before).all()  # a preview until applied
    assert p.tool_settings()["bright_use"] and "color_basis" not in p.tool_settings()


def image_array(q, h, w):
    import numpy as np

    ptr = q.constBits()
    ptr.setsize(q.sizeInBytes())
    return np.frombuffer(ptr, np.uint8).reshape(h, q.bytesPerLine())[:, : 3 * w].reshape(h, w, 3).copy()  # q is freed after


def test_preview_style_cuts_the_image_out(qapp, win):
    """p69: C cycles Mask Preview's look: the mask, the image inside it, the image outside it (rest a checkerboard)."""
    import numpy as np

    from src.app.canvas import checkerboard

    make_objects(win, 1)
    c = win.canvas
    assert win.settings.preview_style == "mask"
    win.act_preview_style.trigger()
    assert win.settings.preview_style == "cutout" and c.preview_style == "cutout"
    assert not c.showing_final  # C only picks the style; V / Z show the preview
    final = win.session.project.final_mask(win.session.key)
    h, w = final.shape
    c._final = final  # what the canvas shows (it follows the project asynchronously)
    q = c._preview_image(h, w)
    ptr = q.constBits()
    ptr.setsize(q.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(h, q.bytesPerLine())[:, : 3 * w].reshape(h, w, 3)
    assert (arr[~final] == 0).all() and (arr[final] == c.image[final][:, :3]).all()  # p76: rest in mask black
    win.act_cutout_checker.trigger()  # the option: a checkerboard instead
    assert win.settings.cutout_fill == "checker" and c.cutout_fill == "checker"
    arr = image_array(c._preview_image(h, w), h, w)
    assert (arr[~final] == checkerboard(h, w)[~final]).all() and (arr[final] == c.image[final][:, :3]).all()
    win.act_cutout_checker.trigger()
    c.set_preview_style("outside")
    arr = image_array(c._preview_image(h, w), h, w)
    assert (arr[final] == 255).all() and (arr[~final] == c.image[~final][:, :3]).all()  # mask white inside
    c.set_preview_style("cutout")
    win.act_preview_style.trigger()
    assert c.preview_style == "mask" and "Mask" in win.act_preview_style.iconText()  # X: two states only
    # p84: X = Final <-> Object in black and white (from a cut-out: back to it); C = inside <-> outside (from
    # black and white: to the cut-out); each keeps its state
    assert win.act_preview_mode.shortcut().toString() == "X" and win.act_cutout_side.shortcut().toString() == "C"
    obj = win.settings.preview_object
    win.act_preview_mode.trigger()  # X in black and white: Final <-> Object
    assert c.preview_style == "mask" and win.settings.preview_object != obj
    win.act_cutout_side.trigger()  # C: to the cut-out (inside, kept)
    assert c.preview_style == "cutout"
    win.act_cutout_side.trigger()
    assert c.preview_style == "outside"
    win.act_preview_mode.trigger()  # X in a cut-out: back to black and white, Final / Object as it was
    assert c.preview_style == "mask" and win.settings.preview_object != obj
    win.act_cutout_side.trigger()  # C: back to the side kept
    assert c.preview_style == "outside"
    win.act_preview_mode.trigger()
    win.act_preview_mode.trigger()  # in black and white: the other mask again
    assert win.settings.preview_object == obj
    win.act_cutout_side.trigger()
    win.act_cutout_side.trigger()  # outside -> inside
    win.act_preview_style.trigger()  # the View menu's Mask / Cut Out
    win.act_cutout_side.trigger()
    assert c.preview_style == "cutout"
    win.act_cutout_side.trigger()
    assert c.preview_style == "outside" and win.settings.cutout_side == "outside"
    win.act_cutout_side.trigger()
    assert c.preview_style == "cutout"
    win.act_cutout_side.trigger()
    win.act_preview_style.trigger()
    assert c.preview_style == "mask"
    win.act_preview_style.trigger()
    assert c.preview_style == "outside"  # back to the side it had
    win.act_preview_style.trigger()


def test_by_color_range_with_picker_and_remove_only(qapp, win):
    """p70/p75: By Color > Range: colors picked on the image (Shift adds one) and / or a brightness range;
    the selection added, removed or replacing the mask."""
    from tests.app.conftest import wait_until

    ids = make_objects(win, 1)
    s, p, c = win.session, win.properties_panel, win.canvas
    win.toggle_edit(ids[0])
    before = s.editing_frame().mask.copy()
    p.tool_btns["by_color"].click()
    assert p.range_box.isVisibleTo(p)
    assert p.pick_btn.isChecked() and c.color_pick_mode  # p77: Range turns the picker on by itself
    assert "Esc" in p.pick_btn.text()  # p79: the button says it is picking and how to stop
    win.act_escape.trigger()  # the first Esc only stops picking
    assert not c.color_pick_mode and not p.pick_btn.isChecked() and p.pick_btn.text() == "Pick Color"
    assert s.editing is not None and p.tool_btns["by_color"].isChecked()
    p.pick_btn.setChecked(True)
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    points = list(s.editing_frame().points) if hasattr(s.editing_frame(), "points") else None
    QTest.mouseClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.rect().center())
    QTest.mouseDClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c.rect().center())
    if points is not None:
        assert list(s.editing_frame().points) == points  # no SAM point
    assert len(p.tool_settings()["color_samples"]) == 1
    p.tool_btns["object_fill"].click()
    assert not c.color_pick_mode
    p.tool_btns["by_color"].click()
    assert not c.color_pick_mode  # back in Range with a color picked: off, a click won't replace it (p92)
    p.pick_btn.click()
    assert c.color_pick_mode
    c.color_picked.emit((10, 20, 30), False)
    c.color_picked.emit((200, 200, 200), True)  # Shift: one more
    assert p.tool_settings()["color_samples"] == ((10, 20, 30), (200, 200, 200))
    c.color_picked.emit((50, 50, 50), False)  # a plain click starts over
    assert p.tool_settings()["color_samples"] == ((50, 50, 50),)
    p.color_use.setChecked(False)
    p.bright_use.setChecked(True)
    p.bright_lo.spin.setValue(0)
    p.bright_hi.spin.setValue(255)  # every pixel
    p.color_band.spin.setValue(5)
    p.color_band_on.setChecked(False)  # off: the whole image (p74)
    assert not p.color_band.isEnabled()
    import cv2
    import numpy as np

    g8 = cv2.cvtColor(np.ascontiguousarray(s.image[..., :3]), cv2.COLOR_RGB2GRAY)

    def result(action, lo, invert=False):
        """p81: A = what the filter catches, B = the rest; Add puts A in, Remove takes B out, Invert swaps."""
        p.color_action.setCurrentIndex(p.color_action.findData(action))
        p.bright_lo.spin.setValue(lo)
        p.color_invert.setChecked(invert)
        p._settings_timer.timeout.emit()
        A = g8 >= lo
        if invert:
            A = ~A
        want = {"both": A, "add": before | A, "remove": before & A}[action]
        wait_until(qapp, lambda: s.auto_changes()[0] is not None
                   and (((before | s.auto_changes()[0]) & ~s.auto_changes()[1]) == want).all())

    assert p.color_action.currentText() == "Add A & Remove B"
    for action in ("both", "add", "remove"):
        for invert in (False, True):
            result(action, 128, invert)
    result("both", 0)  # everything is A: nothing to remove
    assert not s.auto_changes()[1].any()
    result("remove", 0, invert=True)  # Invert: everything is B, all of the mask goes
    assert (s.auto_changes()[1] == before).all()
    for action, invert in (("both", False), ("add", True)):
        # p86: the preview paints A / B, not only the changes: every pixel is one of them (light where it
        # stays, dense where it changes), so pixels already in / out of the mask no longer look like neither
        result(action, 128, invert)
        wait_until(qapp, lambda: not win._auto_pending())  # the A / B shown belong to the result shown
        win.refresh()
        A = (g8 >= 128) != invert
        drawn = {st: [o.mask for o in c._overlays if o.style == st] for st in ("auto_a", "auto_b", "auto_add", "auto_sub")}
        assert all(len(v) == 1 for v in drawn.values())
        a_shown, b_shown = drawn["auto_a"][0] | drawn["auto_add"][0], drawn["auto_b"][0] | drawn["auto_sub"][0]
        assert (a_shown == A).all() and (b_shown == ~A).all()
        assert not (drawn["auto_a"][0] & drawn["auto_add"][0]).any() and not (drawn["auto_b"][0] & drawn["auto_sub"][0]).any()
    p.color_invert.setChecked(False)
    p.color_band_on.setChecked(True)  # p79: the Near edge area is shown (faint white, under the mask colors)
    p.color_band.spin.setValue(5)
    win.refresh()
    from src.core.refine import near_edge

    area = [o for o in c._overlays if o.style == "area"]
    assert len(area) == 1 and (area[0].mask == near_edge(s.auto_base(), 5)).all()
    p.color_band_on.setChecked(False)
    win.refresh()
    assert not [o for o in c._overlays if o.style == "area"]
    p.tool_btns["paint"].click()  # another tool: the picker stops
    assert not p.pick_btn.isChecked() and not c.color_pick_mode


def test_brush_with_hide_masks_keeps_the_mask(qapp, win):
    """p82: with Hide Masks on (and the cut-out preview outside), a brush stroke added to the mask: it used to
    start from an empty one (the hidden Object gave the canvas no mask), so the old mask was lost."""
    import numpy as np
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    from tests.app.test_gui import canvas_pos

    ids = make_objects(win, 1)
    s, c = win.session, win.canvas
    win.toggle_edit(ids[0])
    before = s.editing_frame().mask.copy()
    assert before.any()
    win.act_hide_masks.trigger()
    win.settings.cutout_side = "outside"
    win.act_preview_style.trigger()  # C: cut out, outside
    win.act_final.trigger()  # V: Mask Preview on
    assert c.preview_style == "outside" and c.showing_final
    assert not [o for o in c._overlays if o.style == "edit"]  # nothing drawn...
    assert c.edit_mask() is not None  # ...but the stroke still starts from the mask
    win.set_brush_tool("paint")
    c.set_brush_size(20)
    h, w = before.shape
    y, x = np.argwhere(~before)[0]
    QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, canvas_pos(win, x, y))
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, canvas_pos(win, x, y))
    qapp.processEvents()
    after = s.editing_frame().mask
    assert (after & before).sum() == before.sum()  # nothing of the old mask lost
    assert after[y, x]  # and the stroke added


def test_brush_down_to_one_pixel_and_ctrl_drag_sizes(qapp, win):
    """p83: the smallest brush paints one image pixel (it painted a 3 px disc); Ctrl+drag left / right sizes the
    brush, also while By Color's picker is on; a Ctrl+click still takes a piece of the image."""
    import numpy as np
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest

    from tests.app.test_gui import canvas_pos

    ids = make_objects(win, 1)
    s, c, p = win.session, win.canvas, win.properties_panel
    win.toggle_edit(ids[0])
    before = s.editing_frame().mask.copy()
    win.set_brush_tool("paint")
    c.set_brush_size(1)
    assert c.brush_size == 1 and c._brush_radius() == 0
    y, x = np.argwhere(~before)[len(np.argwhere(~before)) // 2]
    QTest.mousePress(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, canvas_pos(win, x, y))
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, canvas_pos(win, x, y))
    qapp.processEvents()
    assert (s.editing_frame().mask & ~before).sum() == 1  # one pixel
    p.tool_btns["by_color"].click()
    assert c.color_pick_mode
    ctrl = Qt.KeyboardModifier.ControlModifier
    pos = c.rect().center()
    c.set_brush_size(30)
    QTest.mousePress(c, Qt.MouseButton.LeftButton, ctrl, pos)
    QTest.mouseMove(c, pos + QPoint(20, 0))  # Ctrl+drag right: bigger (p83, was Alt+right-drag)
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, ctrl, pos + QPoint(20, 0))
    assert c.brush_size == 70 and p.tool_settings()["color_samples"] == ()  # sized, nothing picked
    p.tool_btns["paint"].click()
    segs = []
    c.segment_clicked.connect(lambda *a: segs.append(a))
    QTest.mousePress(c, Qt.MouseButton.LeftButton, ctrl, pos)
    QTest.mouseMove(c, pos + QPoint(-15, 0))  # left: smaller, and no piece of the image
    QTest.mouseRelease(c, Qt.MouseButton.LeftButton, ctrl, pos + QPoint(-15, 0))
    assert c.brush_size == 40 and not segs
    QTest.mouseClick(c, Qt.MouseButton.LeftButton, ctrl, pos)  # a Ctrl+click still takes a piece
    assert len(segs) == 1 and c.brush_size == 40


def test_toolbar_preview_buttons_follow_x_c_and_overlay_opacity(qapp, win):
    """p87: the toolbar's preview buttons are X (black and white: Final / Object) and C (cut out: inside / outside),
    the one for the look in use checked; the checkerboard background and the overlay opacity (a slider) are on it too."""
    from PyQt6.QtWidgets import QToolBar

    from src.app.canvas import Overlay, compose

    c = win.canvas
    tb = win.findChild(QToolBar, "main_toolbar").actions()
    assert win.act_preview_mode in tb and win.act_cutout_side in tb and win.act_cutout_checker in tb
    win.settings.preview_style, win.settings.cutout_side, win.settings.preview_object = "mask", "cutout", False
    win._show_preview_style()
    win._show_preview_mode()
    assert win.act_preview_mode.isChecked() and not win.act_cutout_side.isChecked()
    win.act_cutout_side.trigger()  # the C button: to the cut-out (inside, kept)
    assert c.preview_style == "cutout" and win.act_cutout_side.isChecked() and not win.act_preview_mode.isChecked()
    assert win.act_cutout_side.iconText() == "Cut Out: Inside"
    win.act_cutout_side.trigger()  # again: outside
    assert c.preview_style == "outside" and win.act_cutout_side.iconText() == "Cut Out: Outside"
    assert win.act_cutout_side.isChecked()
    win.act_preview_mode.trigger()  # the X button: back to black and white, still the Final Mask
    assert c.preview_style == "mask" and win.act_preview_mode.isChecked() and not win.settings.preview_object
    win.act_preview_mode.trigger()  # again: Final -> Object
    assert win.settings.preview_object and win.act_preview_mode.isChecked()
    win.act_cutout_checker.trigger()
    assert win.settings.cutout_fill == "checker" and win.act_cutout_checker.iconText() == "Checker"
    win.act_cutout_checker.trigger()
    assert win.settings.cutout_fill == "mask"
    import numpy as np

    m = np.ones((4, 4), bool)
    full = compose([Overlay(m, (255, 0, 0), "edit")], (4, 4))[0, 0, 3]
    win.overlay_opacity.setValue(50)
    assert win.settings.overlay_opacity == 50 and c.overlay_opacity == 0.5
    from PyQt6.QtWidgets import QSlider

    assert isinstance(win.overlay_opacity, QSlider) and win.overlay_label.text() == "Overlay 50 %"  # a slider
    assert compose([Overlay(m, (255, 0, 0), "edit")], (4, 4), opacity=c.overlay_opacity)[0, 0, 3] == round(full * 0.5)
    win.overlay_opacity.setValue(100)


def test_clicking_a_picked_color_removes_only_that_one(qapp, win):
    """By Color Range: each swatch is a link; clicking it drops that color, the others stay (p90, ui-issues 22)."""
    panel = win.properties_panel
    panel.set_samples([(10, 20, 30), (200, 210, 220), (90, 90, 90)])
    assert 'href="1"' in panel.swatches.text()
    panel.swatches.linkActivated.emit("1")
    assert panel.tool_settings()["color_samples"] == ((10, 20, 30), (90, 90, 90))
    assert "2 color(s)" in panel.swatches.text()
    panel.swatches.linkActivated.emit("0")
    panel.swatches.linkActivated.emit("0")
    assert panel.tool_settings()["color_samples"] == ()
    assert panel.swatches.text() == "No color picked"
    panel.remove_sample(5)  # a stale link does nothing


def test_auto_tool_shows_a_color_legend(qapp, win):
    """AT-2 (p91): with an auto tool on, the canvas lists the colors in use; none without one."""
    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    p = win.properties_panel
    assert win.canvas.legend == []
    p.tool_btns["grow"].click()
    assert [t for _c, _a, t in win.canvas.legend] == ["Adds", "Removes"]
    p.mode_paint_btn.click()
    assert [t for _c, _a, t in win.canvas.legend][-1] == "Not picked (Paint)"
    win.canvas.grab()  # draws without error
    win.escape()  # leave the tool
    assert win.canvas.legend == []


def test_picked_colors_undo_and_the_picker_stays_off_over_them(qapp, win):
    """p92: a change to the picked colors is an undo step; with colors picked, reopening By Color does not turn
    the picker on by itself (an unnoticed click replaced them)."""
    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    p = win.properties_panel
    p.tool_btns["by_color"].click()
    assert p.pick_btn.isChecked()  # nothing picked yet: on
    win.canvas.color_picked.emit((10, 20, 30), False)
    win.canvas.color_picked.emit((200, 210, 220), True)
    win.canvas.color_picked.emit((90, 90, 90), False)  # a plain click replaces both
    assert p.tool_settings()["color_samples"] == ((90, 90, 90),)
    win.undo()
    assert p.tool_settings()["color_samples"] == ((10, 20, 30), (200, 210, 220))
    win.redo()
    assert p.tool_settings()["color_samples"] == ((90, 90, 90),)
    win.undo()
    p.clear_colors_btn.click()
    win.undo()
    assert p.tool_settings()["color_samples"] == ((10, 20, 30), (200, 210, 220))
    win.escape()  # leave the tool, come back: colors kept, picker off
    p.tool_btns["by_color"].click()
    assert not p.pick_btn.isChecked()
    assert p.tool_settings()["color_samples"] == ((10, 20, 30), (200, 210, 220))


def test_picked_color_is_one_pixel(qapp, win):
    """p93: the picker takes the clicked pixel's color, not a 5×5 mean."""
    import numpy as np

    c = win.canvas
    img = np.zeros((20, 20, 3), np.uint8)
    img[10, 10] = (200, 100, 50)
    c.image = img
    assert c.sample_color(10.4, 10.7) == (200, 100, 50)
    assert c.sample_color(11, 10) == (0, 0, 0)


def test_edit_layer_tab_has_an_edit_button_in_step_with_the_object_list(qapp, win):
    """p94: the Edit Layer tab's Edit button starts / finishes editing the Object shown, like the list's button."""
    from PyQt6.QtWidgets import QPushButton

    ids = make_objects(win, 1)
    win.objects_panel.select_ids(ids)
    win.refresh()
    p = win.properties_panel
    row_btn = lambda: win.objects_panel.findChild(QPushButton, f"edit_{ids[0]}")  # noqa: E731
    assert p.edit_btn.isEnabled() and not p.edit_btn.isChecked()
    p.edit_btn.click()
    settle(qapp)
    assert win.session.editing == ids[0]
    assert p.edit_btn.isChecked() and row_btn().isChecked()
    row_btn().click()  # the list's button finishes: this one follows
    settle(qapp)
    assert win.session.editing is None and not p.edit_btn.isChecked()
    win.toggle_edit(ids[0])
    p.edit_btn.click()
    settle(qapp)
    assert win.session.editing is None and not row_btn().isChecked()


def test_alt_click_picks_the_mean_color(qapp, win):
    """p95: a click picks one pixel, Alt+click the 5×5 mean around it (Shift still adds)."""
    import numpy as np
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtTest import QTest

    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    c = win.canvas
    c.set_color_pick(True)
    got = []
    c.color_picked.connect(lambda col, add: got.append((col, add)))
    img = np.zeros_like(c.image)
    pos = c.rect().center()
    x, y = (int(v) for v in c.to_image(QPointF(pos)))
    img[y, x] = (250, 250, 250)
    c.image = img
    QTest.mouseClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QTest.mouseClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, pos)
    QTest.mouseClick(c, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier, pos)
    assert got[0] == ((250, 250, 250), False)
    assert got[1] == ((10, 10, 10), False)  # 250 / 25
    assert got[2] == ((10, 10, 10), True)


def test_original_view_while_picking_colors(qapp, win):
    """BC-P3: while picking, Original shows the photo alone; the button toggles, holding T turns it around until release, and it
    goes off with the picker."""
    import numpy as np
    from src.app import main_window as mw

    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    p, c = win.properties_panel, win.canvas
    assert not p.original_btn.isEnabled()
    win._original_key(True)  # not picking: nothing
    win._original_key(False)
    assert not c.original_view
    p.tool_btns["by_color"].click()
    assert p.pick_btn.isChecked() and p.original_btn.isEnabled()
    c.set_image(np.full_like(c.image, 77), reset_view=False)
    c.set_overlays([mw.Overlay(np.ones(c.image.shape[:2], bool), (255, 0, 0), "normal")])
    pos = c.rect().center()
    p.original_btn.click()
    assert c.original_view
    px = c.grab().toImage().pixelColor(pos)
    assert (px.red(), px.green(), px.blue()) == (77, 77, 77)  # no red over the photo
    p.original_btn.click()
    px = c.grab().toImage().pixelColor(pos)
    assert px.red() > px.green()  # the overlay is back
    win._original_key(True)  # p100: held = on, released = back off (a short tap too: no toggle)
    assert c.original_view
    win._original_key(False)
    assert not c.original_view and not p.original_btn.isChecked()
    p.original_btn.click()  # the button toggles; holding T then shows the masks until release
    win._original_key(True)
    assert not c.original_view
    win._original_key(False)
    assert c.original_view
    win.escape()  # the picker stops: Original goes with it
    assert not p.pick_btn.isChecked() and not p.original_btn.isChecked() and not c.original_view
    assert not p.original_btn.isEnabled()


def test_range_not_per_condition(qapp, win):
    """p97 (BC-P4 a): each Range condition has its own Not; Swap still flips A and B as a whole."""
    import numpy as np
    from src.app.session import range_selection

    img = np.zeros((2, 3, 3), np.uint8)
    img[:, 0] = (250, 250, 250)  # bright white cloud
    img[:, 1] = (230, 200, 60)  # bright yellow leaves
    img[:, 2] = (20, 40, 20)  # dark leaves
    base = {"color_samples": ((250, 250, 250),), "color_tol": 20, "color_use": True,
            "bright_range": (140, 255), "bright_use": True, "range_join": "and"}
    assert range_selection(img, base)[0].tolist() == [True, False, False]  # bright and cloud-colored
    leaves = range_selection(img, {**base, "color_not": True})  # bright, not the cloud's color
    assert leaves[0].tolist() == [False, True, False]
    dark = range_selection(img, {**base, "color_use": False, "bright_not": True})
    assert dark[0].tolist() == [False, False, True]
    assert range_selection(img, {**base, "color_not": True, "color_invert": True})[0].tolist() == [True, False, True]
    p = win.properties_panel
    p.color_not.setChecked(True)
    p.bright_not.setChecked(True)
    t = p.tool_settings()
    assert t["color_not"] and t["bright_not"] and p.color_invert.text() == "Swap A / B"
    assert t["range_join"] == "or"  # p101: two ways of catching the same thing add up by default
    p.range_join.setCurrentIndex(1)
    assert p.tool_settings()["range_join"] == "and"
    assert range_selection(img, {**base, "range_join": "or"})[0].tolist() == [True, True, False]  # bright or cloud


def test_right_click_leaves_a_color_out_and_overlaps_show(qapp, win):
    """p98 (BC-P4 b): right-click while picking = a color to leave out; its swatch removes just it; picked and
    left-out colors change in one undo step; pixels both claim are outlined and named in the legend."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtTest import QTest

    from tests.app.conftest import wait_until

    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    s, p, c = win.session, win.properties_panel, win.canvas
    p.tool_btns["by_color"].click()
    assert p.pick_btn.isChecked() and not p.color_tol_out.isEnabled()
    pos = c.rect().center()
    x, y = (int(v) for v in c.to_image(QPointF(pos)))
    out = tuple(int(v) for v in s.image[y, x, :3])
    near = tuple(min(255, v + 4) for v in out)
    QTest.mouseClick(c, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, pos)
    t = p.tool_settings()
    assert t["color_samples_out"] == (out,) and t["color_samples"] == ()
    assert s.color_samples_out == (out,) and p.color_tol_out.isEnabled()
    win.canvas.color_picked.emit(near, False)  # a picked color right next to it: they overlap
    assert s.color_samples == (near,) and s.color_samples_out == (out,)
    win.undo()
    assert s.color_samples == () and p.tool_settings()["color_samples_out"] == (out,)
    win.redo()
    p.color_band_on.setChecked(False)
    wait_until(qapp, lambda: any(o.style == "overlap" for o in c._overlays))
    assert any(text.startswith("Overlap") for _, _, text in c.legend)
    p.remove_sample("o0")
    assert s.color_samples_out == () and s.color_samples == (near,)
    p.clear_colors_btn.click()
    assert s.color_samples == () and s.color_samples_out == ()


def test_pick_marks_cover_warning_not_and_t_in_number_fields(qapp, win):
    """p99: the picked colors are marked where they were taken (− for left out, gone with the color); the color
    condition's share of the area is shown and warns near 100 %; Not waits for a picked color; T works with the
    keyboard in a number field."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QLineEdit

    from tests.app.conftest import wait_until

    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    s, p, c = win.session, win.properties_panel, win.canvas
    p.tool_btns["by_color"].click()
    assert not p.color_not.isEnabled()
    pos = c.rect().center()
    QTest.mouseClick(c, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QTest.mouseClick(c, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, pos + QPointF(20, 0).toPoint())
    assert p.color_not.isEnabled()
    labels = [m[3] for m in c.pick_marks]
    assert labels == ["1", "−1"]
    x, y = c.to_image(QPointF(pos))
    assert abs(c.pick_marks[0][0] - x) < 1e-6 and abs(c.pick_marks[0][1] - y) < 1e-6
    p.remove_sample("o0")
    assert [m[3] for m in c.pick_marks] == ["1"]
    p.color_tol.setValue(100)
    wait_until(qapp, lambda: "tells nothing apart" in p.color_cover.text())
    assert p.color_cover.isVisibleTo(p)
    spin = p.color_tol.spin  # the keyboard in a number field (or its inner editor): T still works there
    assert not win._typing_text(spin) and not win._typing_text(spin.findChild(QLineEdit))
    assert win._typing_text(QLineEdit())  # a text box keeps its T
    win._original_key(True)
    assert c.original_view
    win._original_key(False)
    p.clear_colors_btn.click()
    assert c.pick_marks == []


def test_apply_to_frames_picked_in_the_frame_list(qapp, win):
    """p103: Apply to Frames on just the frames picked in the Frame List (a range or a few); the rest untouched."""
    from src.core.project import FrameState, FrameStatus
    from tests.app.conftest import wait_until

    ids = make_objects(win, 1)
    s = win.session
    p = s.project
    k0, k1, k2 = s.keys[:3]
    for k in (k1, k2):
        p.set_frame(ids[0], k, FrameState.from_mask(p.get(ids[0]).mask(k0), status=FrameStatus.PROPAGATED))
    m = {k: p.get(ids[0]).mask(k).copy() for k in (k0, k1, k2)}
    win.toggle_edit(ids[0])
    pp = win.properties_panel
    pp.tool_btns["invert"].click()
    assert pp.apply_all_btn.text() == "Apply to Frames…"
    lst = win.images_panel.list
    lst.clearSelection()
    for row in (1, 2):
        lst.item(row).setSelected(True)
    asked = []
    win.choose = lambda title, text, groups, ok="OK": asked.append(groups[0]) or [1]  # the picked ones
    pp.apply_all_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    assert asked[0][2] == 1 and "2 frame(s) with a mask (of 2 picked" in asked[0][1][1]  # picked: the default
    o = p.get(ids[0])
    assert (o.mask(k0) == m[k0]).all()  # not picked: untouched
    assert (o.mask(k1) == ~m[k1]).all() and (o.mask(k2) == ~m[k2]).all()
    win.undo()
    assert (p.get(ids[0]).mask(k1) == m[k1]).all()
    lst.clearSelection()
    win.choose = lambda title, text, groups, ok="OK": [1]  # nothing picked: nothing happens, a hint
    pp.apply_all_btn.click()
    assert win._busy is None and (p.get(ids[0]).mask(k1) == m[k1]).all()
