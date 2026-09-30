"""v0.3: responsiveness and UX fixes (one section per change, so each can be reverted with it)."""

import threading
import time

import pytest

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QPushButton

from tests.app.conftest import wait_until
from tests.app.test_gui import folder, win  # noqa: F401  (fixtures)


def settle(qapp, n: int = 5) -> None:
    for _ in range(n):
        qapp.processEvents()
        time.sleep(0.005)


def slow_click(qapp, widget, pos) -> None:
    """A real click: the event loop runs between press and release."""
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=pos)
    settle(qapp)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=pos)
    settle(qapp)


def make_objects(win, n: int) -> list:
    s = win.session
    for i in range(n):
        s.start_new_object()
        s.click(10 + 15 * i, 20)
        s.finish_editing()
    win.refresh()
    return [o.id for o in s.project.objects]


# --- Objects panel: a row button works on the first click --------------------


def test_row_button_on_unselected_row_works_first_click(qapp, win):
    ids = make_objects(win, 3)
    tree = win.objects_panel.tree
    slow_click(qapp, tree.viewport(), tree.visualItemRect(tree.topLevelItem(0)).center())
    assert win.objects_panel.selected_ids() == [ids[0]]
    edit = tree.findChild(QPushButton, f"edit_{ids[2]}")
    slow_click(qapp, edit, edit.rect().center())  # its press selects row 2; the click must still land
    assert win.session.editing == ids[2]


# --- Display: thin white outline (on/off, width) and edit-change tints --------


def test_outline_options_and_edit_change_tints(qapp, win):
    make_objects(win, 1)
    oid = win.session.project.objects[0].id
    win.toggle_edit(oid)
    painted = win.session.editing_frame().mask.copy()
    painted[50:55, 70:75] = True
    win.on_brush(painted)
    styles = lambda: [o.style for o in win.canvas._overlays]  # noqa: E731
    assert "layer_add" not in styles()  # tints are off by default
    assert win.act_changes.shortcut().toString() == "R"
    win.act_changes.trigger()
    assert "layer_add" in styles() and win.settings.show_edit_changes
    assert win.canvas.outline_visible and win.canvas.outline_width == 1.0
    win.outline_width.setValue(2.5)
    win.act_outline.trigger()
    assert not win.canvas.outline_visible and win.canvas.outline_width == 2.5
    win.canvas.grab()  # paints without error


# --- Batch masking: Stop keeps the images done, Cancel discards the run -------


@pytest.mark.parametrize("button, kept", [("stop_btn", 2), ("cancel_btn", 0)])
def test_batch_stop_keeps_and_cancel_discards(qapp, win, button, kept):
    engine = win.session.engine
    gate, entered = threading.Event(), threading.Event()
    real = engine.detect_many
    seen = []

    def gated(image, labels):
        seen.append(1)
        if len(seen) == 2:  # image 1 waits until the button is pressed
            entered.set()
            gate.wait(5)
        return real(image, labels)

    engine.detect_many = gated
    win.run_batch(["person"], "all", 0, -1, 0.5)
    wait_until(qapp, entered.is_set)
    getattr(win.batch_panel, button).click()
    assert not win.batch_panel.stop_btn.isEnabled()
    gate.set()
    wait_until(qapp, lambda: win._busy is None)
    objs = win.session.project.objects
    assert len(seen) == 2  # nothing ran after the button
    if kept:
        assert len(objs) == 1 and len(objs[0].frames) == kept
    else:
        assert objs == [] and not win.session.project.can_undo


# --- Autosave writes in the background ------------------------------------------


def test_background_autosave_and_failed_job_is_rewritten(qapp, win):
    from src.core.storage import ProjectStore

    make_objects(win, 2)
    win.save(background=True)
    assert win._save_task is not None
    win._save_task.wait()
    store = win.session.store
    again = ProjectStore(store.image_dir, store.max_side).load(win.session.keys)
    assert [o.name for o in again.objects] == [o.name for o in win.session.project.objects]

    # a job that fails leaves the project unsaved, so the next save writes it all again
    oid = win.session.project.objects[0].id
    win.session.remove_frame(oid)
    job = store.prepare(win.session.project)
    store.failed(job)
    assert not store.is_saved(win.session.project)
    job2 = store.prepare(win.session.project)
    assert {k for k in job2.written_keys} >= set(job.written_keys)


# --- Edit layer tools: Fill Holes / Remove Specks / Object Fill, limited to a region ---


def test_refine_tools_are_separate_and_grow_to_edges():
    import cv2
    import numpy as np

    from src.core.refine import fill_holes, grow_to_edges, remove_specks, within

    m = np.zeros((60, 60), bool)
    m[10:40, 10:40] = True
    m[20, 20] = False  # hole
    m[50, 50] = True  # speck
    assert fill_holes(m, 5)[20, 20] and fill_holes(m, 5)[50, 50]
    assert not remove_specks(m, 5)[50, 50] and not remove_specks(m, 5)[20, 20]

    img = np.full((200, 200, 3), (40, 60, 80), np.uint8)
    cv2.circle(img, (100, 100), 60, (220, 200, 90), -1)
    truth = np.zeros((200, 200), np.uint8)
    cv2.circle(truth, (100, 100), 60, 1, -1)
    seed = np.zeros((200, 200), np.uint8)
    cv2.circle(seed, (100, 100), 45, 1, -1)
    grown = grow_to_edges(img, seed > 0, 25)
    assert grown.sum() > 0.97 * truth.sum() and not (grown & ~(truth > 0)).any()
    assert not grow_to_edges(img, seed > 0, 5)[100, 38]  # growth is capped at max_grow

    # sensitivity: a background gradient toward the object's color is taken more readily when higher
    rng = np.random.default_rng(0)
    ramp = np.zeros((200, 200, 3), np.float32)
    ramp[:] = np.linspace(60, 220, 200)[None, :, None]
    left = np.zeros((200, 200), bool)
    left[60:140, 20:60] = True
    ramp[left] = 60
    ramp = np.clip(ramp + rng.normal(0, 12, ramp.shape), 0, 255).astype(np.uint8)
    sizes = [grow_to_edges(ramp, left, 60, s).sum() for s in (10, 50, 90)]
    assert sizes[0] <= sizes[1] <= sizes[2] and sizes[0] < sizes[2]

    region = np.zeros((200, 200), bool)
    region[:, 100:] = True
    half = within(region, seed > 0, grown)
    assert half[100, 150] and not half[100, 50]


def holes_object(win):
    """An Object in Edit whose mask has a 1-px hole at (25, 25) and one at (35, 35)."""
    s = win.session
    win.new_object()
    s.click(30, 30)
    t = s.editing_frame().mask.copy()
    t[25, 25] = t[35, 35] = False
    s.brush(t)
    win.refresh()
    return s


def test_region_box_limits_the_fill(qapp, win):
    from tests.app.test_gui import canvas_pos

    s = holes_object(win)
    p = win.properties_panel
    p.fill_area.setValue(5)
    p.region_btn.click()
    assert win.canvas.region_mode
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 31, 31))
    QTest.mouseMove(win.canvas, canvas_pos(win, 45, 45))
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 45, 45))
    assert s.region is not None and s.region[35, 35] and not s.region[25, 25]
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 40, 40))
    QTest.mouseMove(win.canvas, canvas_pos(win, 45, 45))
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, canvas_pos(win, 45, 45))
    assert s.region[35, 35] and not s.region[42, 42]  # Alt+drag cut a box out
    assert len(s.editing_frame().points) == 1  # region drags never make a SAM2 box

    p.mode_fill_btn.click()
    p.tool_btns["fill_holes"].click()  # Fill: a preview inside the region
    added, _ = s.auto_changes()
    assert added[35, 35] and not added[25, 25]
    p.clear_region_btn.click()  # the preview follows the region
    assert s.region is None and "whole mask" in p.scope_label.text()
    added, _ = s.auto_changes()
    assert added[25, 25] and added[35, 35]
    p.recompute_btn.click()  # Apply & Continue
    oid = s.project.objects[0].id
    assert s.project.get(oid).mask(s.key)[25, 25]
    win.finish_editing()
    assert not win.canvas.region_mode and s.region is None


def test_fill_preview_is_applied_by_fill_again(qapp, win):
    s = win.session
    win.new_object()
    s.click(30, 30)
    t = s.editing_frame().mask.copy()
    t[25, 25] = False  # 1 px hole
    t[34:36, 34:36] = False  # 4 px hole
    s.brush(t)
    win.refresh()
    p = win.properties_panel
    p.fill_area.setValue(1)
    p.mode_fill_btn.click()
    p.tool_btns["fill_holes"].click()
    assert "Will apply: +1 px" in p.preview_label.text()
    assert not s.editing_frame().mask[25, 25]  # only a preview so far
    p.fill_area.setValue(10)  # a setting moves the preview
    wait_until(qapp, lambda: "+5 px" in p.preview_label.text())
    assert any(o.style == "auto_add" for o in win.canvas._overlays)  # tinted magenta

    win.escape()  # Esc drops the preview and leaves the tool (Edit stays)
    assert not s.editing_frame().mask[25, 25] and s.auto_tool is None and s.editing is not None
    p.tool_btns["fill_holes"].click()
    p.tool_btns["fill_holes"].click()  # the active tool again = Esc: dropped, left
    assert not s.editing_frame().mask[25, 25] and s.auto_tool is None
    assert not p.tool_btns["fill_holes"].isChecked() and s.editing is not None
    p.tool_btns["fill_holes"].click()
    p.recompute_btn.click()  # Apply & Continue
    m = s.editing_frame().mask
    assert m[25, 25] and m[35, 35] and s.auto_tool == "fill_holes" and p.tool_btns["fill_holes"].isChecked()
    win.undo()  # one undo step
    m = s.editing_frame().mask
    assert not m[25, 25] and not m[35, 35]
    win.escape()
    win.escape()
    assert s.editing is None  # with no tool on, Esc finishes editing


def test_each_apply_adds_one_more_and_leaving_drops(qapp, win):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QKeyEvent

    s = win.session
    win.new_object()
    s.click(40, 30)
    win.refresh()
    p = win.properties_panel
    p.amount.setValue(2)
    area0 = s.editing_frame().mask.sum()
    p.tool_btns["grow"].click()
    p.recompute_btn.click()  # Apply & Continue
    win.activateWindow()
    enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    assert win.eventFilter(win.canvas, enter)  # Enter = apply once more
    area2 = s.editing_frame().mask.sum()
    assert area2 > area0 and s.auto_tool == "grow"
    p.tool_btns["shrink"].click()  # another tool drops the pending Grow preview
    assert s.editing_frame().mask.sum() == area2 and s.auto_tool == "shrink"

    win.a_key()  # Fill mode: A enters Paint mode with everything picked
    assert s.auto_mode == "paint" and p.mode_paint_btn.isChecked() and win.canvas.brush_mode
    assert (s.auto_taken() == s.auto_changes()[1]).all()
    win.set_brush_tool("paint")  # switching tools (the Paint button) drops the picks too
    assert s.editing_frame().mask.sum() == area2 and s.auto_tool is None
    p.tool_btns["shrink"].click()  # a new auto tool starts in Fill mode (v0.4-p10)
    assert s.auto_mode == "fill" and p.mode_fill_btn.isChecked() and not win.canvas.brush_mode
    p.mode_paint_btn.click()  # Paint mode: everything picked, like A (v0.4-p15)
    assert s.auto_mode == "paint" and (s.auto_taken() == s.auto_changes()[1]).all()
    win.a_key()  # Paint mode: A toggles none...
    assert not s.auto_taken().any()
    win.a_key()  # ...and all
    assert s.auto_taken().any()
    win.a_key()
    assert not s.auto_taken().any()
    p.apply_auto_btn.click()  # Apply & Close with nothing picked: no change, tool closed
    assert s.auto_tool is None and s.editing_frame().mask.sum() == area2 and p.apply_auto_btn.text() == "Apply && Close"
    p.mode_fill_btn.click()



def test_mode_switch_keeps_the_same_area(qapp, win):
    s = holes_object(win)
    p = win.properties_panel
    p.fill_area.setValue(5)
    assert p.mode == "fill" and p.mode_fill_btn.isChecked()  # Fill is the default
    p.tool_btns["fill_holes"].click()
    added, _ = s.auto_changes()
    styles = lambda: {o.style: o.mask for o in win.canvas._overlays}  # noqa: E731
    assert (styles()["auto_add"] == added).all() and not styles()["guide"].any()  # all of it, green
    p.mode_paint_btn.click()  # the same area, now gray until picked
    win.a_key()  # Paint starts with everything picked (v0.4-p15): A = none
    assert win.canvas.brush_mode and (styles()["guide"] == added).all() and not styles()["auto_add"].any()
    assert not s.editing_frame().mask[25, 25]  # switching writes nothing
    p.mode_fill_btn.click()
    assert (styles()["auto_add"] == added).all() and not win.canvas.brush_mode


def test_object_fill_computes_in_the_background(qapp, win):
    s = win.session
    win.new_object()
    s.click(40, 30)
    before = s.editing_frame().mask.sum()
    win.refresh()
    p = win.properties_panel
    p.mode_fill_btn.click()
    p.tool_btns["object_fill"].click()
    assert not p.settings_box.isHidden() and "Object Fill" in p.settings_box.title()
    wait_until(qapp, lambda: "Computing" not in p.preview_label.text() and p.preview_label.text() != "")
    assert s.editing_frame().mask.sum() >= before  # never shrinks (a flat test image may not grow)


# --- Merge keeps the name of the first Object selected --------------------------


def test_merge_uses_first_selected_name(qapp, win):
    ids = make_objects(win, 3)
    win.session.project.rename(ids[2], "Tripod")
    win.refresh()
    tree = win.objects_panel.tree
    tree.topLevelItem(2).setSelected(True)  # picked first
    tree.topLevelItem(0).setSelected(True)
    tree.topLevelItem(1).setSelected(True)
    assert win.objects_panel.selected_ids() == [ids[2], ids[0], ids[1]]
    win.objects_panel.merge_btn.click()
    settle(qapp)
    assert [o.name for o in win.session.project.objects] == ["Tripod"]


def test_paint_mode_picks_parts_and_applies_them_on_exit(qapp, win):
    from tests.app.test_gui import canvas_pos

    s = holes_object(win)
    p = win.properties_panel
    p.fill_area.setValue(5)
    p.tool_btns["fill_holes"].click()  # starts in Fill mode...
    p.mode_paint_btn.click()  # ...then Paint
    win.a_key()  # Paint starts with everything picked (v0.4-p15): A = none
    assert win.canvas.brush_mode and win.canvas.brush_tool == "fill_holes" and not p.brush_btn.isChecked()
    styles = lambda: {o.style: o.mask for o in win.canvas._overlays}  # noqa: E731
    assert styles()["guide"][25, 25] and styles()["guide"][35, 35]  # both holes, gray
    win.canvas.set_brush_size(40)  # a few image px: covers the hole whatever the rounding

    def stroke(x, y, mods=Qt.KeyboardModifier.NoModifier):
        QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, mods, canvas_pos(win, x, y))
        assert win.canvas._tool_area is not None  # the area shows while dragging
        QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, mods, canvas_pos(win, x, y))
        qapp.processEvents()

    stroke(35, 35)
    assert styles()["auto_add"][35, 35] and styles()["guide"][25, 25]  # picked: green; the rest gray
    assert not s.editing_frame().mask[35, 35]  # nothing written before leaving the tool
    stroke(25, 25)
    stroke(25, 25, Qt.KeyboardModifier.AltModifier)  # Alt+drag unpicks: back to gray
    assert styles()["guide"][25, 25] and not styles()["auto_add"][25, 25]
    p.recompute_btn.click()  # Apply & Continue
    m = s.editing_frame().mask
    assert m[35, 35] and not m[25, 25]
    win.set_brush_tool("paint")  # the Paint button (D in an auto tool is Paint <-> Fill, v0.4-p49)
    assert win.canvas.brush_tool == "paint" and p.brush_btn.isChecked() and p.brush_btn.text() == "Paint"


# --- Final Mask preview: X toggles it, editing works inside it; Restore brush ----


def test_final_preview_toggle_and_editing_in_it(qapp, win):
    from PyQt6.QtGui import QKeySequence

    from tests.app.test_gui import canvas_pos

    assert win.act_final.shortcut() == QKeySequence("V")  # X until v0.4-p15
    s = win.session
    win.new_object()
    s.click(30, 30)
    win.refresh()
    win.act_final.trigger()
    assert win.canvas.showing_final
    win.act_brush.trigger()
    win.canvas.set_brush_size(10)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 70, 50))
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 70, 50))
    qapp.processEvents()
    assert s.editing_frame().mask[50, 70]  # painted while the Final Mask was shown
    assert win.canvas._final[50, 70]  # and the preview shows it
    win.canvas.grab()
    win.act_final.trigger()
    assert not win.canvas.showing_final


@pytest.mark.parametrize(
    "mode, added_px, removed_px",  # afterwards: is the added pixel on? is the removed pixel on?
    [("added", False, False), ("removed", True, True), ("both", False, True)],
)
def test_restore_brush_modes(qapp, win, mode, added_px, removed_px):
    import numpy as np

    from tests.app.test_gui import canvas_pos

    s = win.session
    win.new_object()
    s.click(30, 30)
    prompt = s.editing_frame().mask.copy()
    t = prompt.copy()
    t[48:53, 68:73] = True  # added
    t[28:33, 28:33] = False  # removed
    s.brush(t)
    win.refresh()
    p = win.properties_panel
    p.restore_mode.setCurrentIndex(p.restore_mode.findData(mode))
    p.tool_btns["restore"].click()
    win.canvas.set_brush_size(800)  # one dab covers everything
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 50, 40))
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 50, 40))
    qapp.processEvents()
    m = s.editing_frame().mask
    assert m[50, 70] == added_px and m[30, 30] == removed_px
    if mode == "both":
        assert np.array_equal(m, prompt) and s.editing_frame().edit is None


# --- Region Box changes are undoable, in order with the mask edits --------------


def test_region_changes_undo_and_redo_in_order(qapp, win):
    s = win.session
    win.new_object()
    s.click(30, 30)  # project step A
    s.add_region_box((0, 0, 20, 20))  # region R1
    t = s.editing_frame().mask.copy()
    t[50, 70] = True
    s.brush(t)  # project step B
    s.add_region_box((40, 40, 60, 50))  # region R2
    win.refresh()
    assert win.act_undo.isEnabled()
    win.undo()
    assert s.region[10, 10] and not s.region[45, 50]  # R2 undone
    win.undo()
    assert not s.editing_frame().mask[50, 70] and s.region is not None  # B undone, R1 stays
    win.undo()
    assert s.region is None and s.editing_frame() is not None  # R1 undone, A stays
    win.redo()
    assert s.region[10, 10]
    win.redo()
    assert s.editing_frame().mask[50, 70]
    win.redo()
    assert s.region[45, 50]
    win.properties_panel.clear_region_btn.click()
    assert s.region is None
    win.undo()
    assert s.region[45, 50]  # Clear Region is undoable too
    oid = s.editing
    win.finish_editing()
    win.undo()  # after leaving Edit, Ctrl+Z goes to the mask edits, not old regions
    assert s.region is None and not s.project.get(oid).mask(s.key)[50, 70]



def test_z_held_peeks_and_the_wheel_leaves_sliders_alone(qapp, win):
    from PyQt6.QtCore import QEvent, QPoint, QPointF
    from PyQt6.QtGui import QKeyEvent, QWheelEvent

    win.activateWindow()
    win.canvas.setFocus()
    press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.NoModifier)
    release = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Z, Qt.KeyboardModifier.NoModifier)
    assert win.eventFilter(win.canvas, press) and win.canvas.showing_final and not win.act_final.isChecked()
    win.eventFilter(win.canvas, release)
    assert not win.canvas.showing_final
    ctrl_z = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert not win.eventFilter(win.canvas, ctrl_z)  # Ctrl+Z stays Undo

    field = win.properties_panel.grow
    before = field.value()
    wheel = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    p = win.properties_panel
    win.toggle_edit(make_objects(win, 1)[0])  # the tabs show only with an Object
    p.tabs.setCurrentIndex(p.layer_tab)
    win.resize(1200, 500)  # short enough for the Edit Layer tab to scroll
    qapp.processEvents()
    bar = p.tabs.currentWidget().verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    assert win.eventFilter(field.slider, wheel) is True
    assert field.value() == before  # the slider keeps its value...
    down = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    win.eventFilter(field.spin, down)
    assert bar.value() > 0  # ...and the panel scrolls instead
    assert not win.eventFilter(bar, down)  # the scroll bar itself is left alone


def test_help_shortcuts_window_and_apply_button(qapp, win):
    from src.app.dialogs import SHORTCUTS, ShortcutsDialog

    assert win.act_shortcuts.shortcut().toString() == "F1"
    keys = {k for _, items in SHORTCUTS for k, _ in items}
    assert {"X", "Z (hold)", "Ctrl+Z", "Alt+drag"} <= keys
    ShortcutsDialog(win).close()

    s = holes_object(win)
    p = win.properties_panel
    p.fill_area.setValue(5)
    assert not p.apply_auto_btn.isEnabled()
    p.mode_paint_btn.click()
    p.tool_btns["fill_holes"].click()
    assert p.apply_auto_btn.isEnabled()
    win.a_key()  # pick everything
    p.apply_auto_btn.click()  # writes the picks in and leaves the tool
    m = s.editing_frame().mask
    assert m[25, 25] and m[35, 35] and s.auto_tool is None and not p.apply_auto_btn.isEnabled()
    p.mode_fill_btn.click()



def test_restore_is_live_while_dragging(qapp, win):
    from tests.app.test_gui import canvas_pos

    s = win.session
    win.new_object()
    s.click(30, 30)
    t = s.editing_frame().mask.copy()
    t[48:53, 68:73] = True
    s.brush(t)
    win.refresh()
    win.properties_panel.tool_btns["restore"].click()
    win.canvas.set_brush_size(40)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 70, 50))
    assert not win.canvas._stroke_mask[50, 70]  # already restored on screen while dragging
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 70, 50))
    assert not s.editing_frame().mask[50, 70]


# --- Sliders, separate sizes, Grow / Shrink, A = pick all / none ------------------


def test_grow_and_shrink_mask():
    import numpy as np

    from src.core.refine import grow_mask, shrink_mask

    m = np.zeros((50, 50), bool)
    m[20:30, 20:30] = True
    assert grow_mask(m, 3)[20, 17] and not grow_mask(m, 3)[20, 15] and grow_mask(m, 3).sum() > m.sum()
    s = shrink_mask(m, 2)
    assert s[25, 25] and not s[21, 25] and s.sum() == 6 * 6
    edge = np.zeros((50, 50), bool)
    edge[:, :10] = True  # runs off the left border: that side is not an edge
    assert shrink_mask(edge, 2)[25, 0] and not shrink_mask(edge, 2)[25, 8]


def test_slider_field_and_separate_sizes(qapp, win):
    p = win.properties_panel
    p.fill_area.setValue(50)
    p.speck_area.spin.setValue(7)  # typing in the box moves the slider
    assert p.tool_settings()["fill_area"] == 50 and p.tool_settings()["speck_area"] == 7
    p.fill_area.slider.setValue(p.fill_area.slider.maximum())
    assert p.fill_area.value() == 100_000
    p.grow.slider.setValue(0)
    assert p.grow.value() == 1


def test_grow_shrink_tools_share_amount_and_a_toggles_picks(qapp, win):
    s = win.session
    win.new_object()
    s.click(40, 30)
    win.refresh()
    p = win.properties_panel
    p.amount.setValue(2)
    p.tool_btns["grow"].click()
    added, removed = s.auto_changes()
    assert added.any() and not removed.any()
    p.tool_btns["shrink"].click()  # applies Grow (Fill mode), then Shrink by the same amount
    added, removed = s.auto_changes()
    assert removed.any() and not added.any() and p.settings_stack.currentIndex() == p._pages["grow"]
    p.mode_paint_btn.click()
    win.a_key()  # Paint starts with everything picked (v0.4-p15): A = none
    assert not s.auto_taken().any()
    win.a_key()  # A: everything picked
    assert (s.auto_taken() == removed).all()
    win.a_key()  # A again: nothing picked
    assert not s.auto_taken().any()
    idx = s.index
    win.escape()
    win.a_key()  # with no auto tool, A does nothing (A / D never change image)
    assert s.index == idx


def test_brush_circle_is_green_over_the_final_mask(qapp, win):
    from PyQt6.QtCore import QPointF

    win.new_object()
    win.session.click(30, 30)
    win.refresh()
    win.act_brush.trigger()
    win.act_final.trigger()
    win.canvas._mouse = QPointF(100, 100)
    img = win.canvas.grab().toImage()
    r = win.canvas.brush_size / 2
    greens = [img.pixelColor(int(100 + r * c), int(100 + r * s)) for c, s in ((1, 0), (0, 1), (-1, 0), (0, -1))]
    assert any(c.green() > 150 and c.red() < 150 for c in greens)


def test_alt_turns_the_brush_circle_and_region_box_red(qapp, win, monkeypatch):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication

    win.new_object()
    win.session.click(30, 30)
    win.refresh()
    win.act_brush.trigger()
    win.canvas._mouse = QPointF(100, 100)
    r = win.canvas.brush_size / 2

    def circle_colors():
        import math

        img = win.canvas.grab().toImage()
        return [img.pixelColor(round(100 + r * math.cos(a / 18 * math.pi)), round(100 + r * math.sin(a / 18 * math.pi)))
                for a in range(36)]

    reddish = lambda cs: sum(c.red() > c.green() + 80 for c in cs)  # noqa: E731
    assert reddish(circle_colors()) == 0
    monkeypatch.setattr(QApplication, "keyboardModifiers", staticmethod(lambda: Qt.KeyboardModifier.AltModifier))
    assert reddish(circle_colors()) >= 5


def test_paint_mode_picks_are_undoable(qapp, win):
    from tests.app.test_gui import canvas_pos

    s = holes_object(win)
    p = win.properties_panel
    p.fill_area.setValue(5)
    p.tool_btns["fill_holes"].click()  # starts in Fill mode...
    p.mode_paint_btn.click()  # ...then Paint
    win.a_key()  # Paint starts with everything picked (v0.4-p15): A = none
    win.canvas.set_brush_size(40)  # a few image px: covers the hole whatever the rounding

    def stroke(x, y, mods=Qt.KeyboardModifier.NoModifier):
        QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, mods, canvas_pos(win, x, y))
        QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, mods, canvas_pos(win, x, y))
        qapp.processEvents()

    taken = lambda: s.auto_taken()  # noqa: E731
    stroke(35, 35)
    stroke(25, 25)
    assert taken()[35, 35] and taken()[25, 25]
    win.undo()
    assert taken()[35, 35] and not taken()[25, 25]
    win.undo()
    assert not taken().any() and s.auto_tool == "fill_holes"
    win.redo()
    assert taken()[35, 35] and not taken()[25, 25]
    win.a_key()  # pick all: one step
    stroke(35, 35, Qt.KeyboardModifier.AltModifier)  # unpick: one step
    win.undo()
    assert taken()[35, 35] and taken()[25, 25]
    win.undo()
    assert taken()[35, 35] and not taken()[25, 25]

    p.recompute_btn.click()  # Apply & Continue
    assert s.editing_frame().mask[35, 35]
    win.undo()
    assert not s.editing_frame().mask[35, 35] and not s.auto_taken().any()
    p.mode_fill_btn.click()



def test_arrows_step_objects_and_points_drag_or_double_click(qapp, win):
    from tests.app.test_gui import canvas_pos

    s = win.session
    ids = make_objects(win, 3)
    s.go_to(1)
    s.start_new_object()
    s.click(60, 40)  # a 4th Object only on image 1
    s.finish_editing()
    s.go_to(0)
    win.refresh()
    win.objects_panel.select_ids([ids[0]])
    win.step_object(1)
    assert win.objects_panel.selected_ids() == [ids[1]]
    win.step_object(1)  # the 4th has no mask here: skipped
    assert win.objects_panel.selected_ids() == [ids[2]]
    win.step_object(1)  # past the last: back to the first (v0.4-p19)
    assert win.objects_panel.selected_ids() == [ids[0]]
    win.step_object(-1)
    assert win.objects_panel.selected_ids() == [ids[2]]
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 75, 55))  # empty space
    assert win.objects_panel.selected_ids() == [ids[2]]  # keeps the selection
    tree = win.objects_panel.tree
    tree.collapseAll()  # leave empty space below the rows
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.viewport().rect().bottomLeft() + QPoint(5, -5))
    assert win.objects_panel.selected_ids() == []  # empty space in the panel clears it

    win.toggle_edit(ids[0])
    win.step_object(1)  # Edit follows
    assert s.editing == ids[1]
    win.step(1)
    assert s.index == 1 and s.editing == ids[1]  # editing goes on on the next image (v0.4-p41)
    win.step(-1)

    s.click(20, 40)  # a second point
    win.refresh()
    pts = s.editing_frame().points
    q = canvas_pos(win, pts[1].x, pts[1].y)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=q)
    QTest.mouseMove(win.canvas, q + QPoint(40, 20))
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=q + QPoint(40, 20))
    moved = s.editing_frame().points[1]
    assert (moved.x, moved.y) != (pts[1].x, pts[1].y) and len(s.editing_frame().points) == 2
    q = canvas_pos(win, moved.x, moved.y)
    QTest.mouseDClick(win.canvas, Qt.MouseButton.LeftButton, pos=q)
    assert len(s.editing_frame().points) == 1


def test_apply_row_restore_tints_and_d_for_paint(qapp, win):
    from PyQt6.QtGui import QKeySequence

    from tests.app.test_gui import canvas_pos

    assert win.act_brush.shortcut() == QKeySequence("D")
    s = holes_object(win)
    p = win.properties_panel
    assert not p.recompute_btn.isEnabled()
    p.fill_area.setValue(5)
    p.tool_btns["fill_holes"].click()
    guide_or_fill = [o for o in win.canvas._overlays if o.style in ("guide", "auto_add")]
    assert guide_or_fill
    p.recompute_btn.click()  # Apply & Continue: written in, the tool stays
    assert s.editing_frame().mask[25, 25] and s.auto_tool == "fill_holes"
    p.apply_auto_btn.click()  # Apply & Close
    assert s.auto_tool is None

    # Restore keeps the Edit Changes tints while painting, trimmed live
    t = s.editing_frame().mask.copy()
    t[48:53, 68:73] = True
    s.brush(t)
    win.act_changes.trigger()
    win.refresh()
    p.tool_btns["restore"].click()
    win.canvas.set_brush_size(30)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 70, 50))
    tints = [o for o in win.canvas._group_layers("edit") if o.style == "layer_add"]
    assert tints and not tints[0].mask[50, 70]  # restored under the brush: no longer green
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 70, 50))
    win.act_changes.trigger()


def test_mode_buttons_only_switch(qapp, win):
    s = holes_object(win)
    p = win.properties_panel
    p.fill_area.setValue(5)
    p.tool_btns["fill_holes"].click()
    p.mode_fill_btn.click()  # the active mode again: nothing is applied
    assert not s.editing_frame().mask[25, 25] and s.auto_mode == "fill" and p.mode_fill_btn.isChecked()
    p.mode_paint_btn.click()
    p.mode_paint_btn.click()
    assert not s.editing_frame().mask[25, 25] and s.auto_mode == "paint" and p.mode_paint_btn.isChecked()
    p.mode_fill_btn.click()


# --- Phase 3: detections — separate Batch tab, preview, add modes, viewport picking ---


@pytest.mark.parametrize(
    "how, names",
    [("each", ["person #1", "person #2", "car #1", "car #2"]), ("merged", ["person #1"]),
     ("per_label", ["person #1", "car #1"])],
)
def test_add_detections_each_merged_per_prompt(qapp, win, how, names):
    win.detection_panel.prompt.setText("person, car")
    win.detection_panel.detect_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    s = win.session
    assert len(s.detections) == 4
    {"each": win.detection_panel.add_btn, "merged": win.detection_panel.merge_btn,
     "per_label": win.detection_panel.per_label_btn}[how].click()
    qapp.processEvents()
    assert [o.name for o in s.project.objects] == names and s.detections == []
    if how == "merged":
        m = s.project.objects[0].mask(s.key)
        assert m[10, 10] and m[30, 10] and m[10, 35]  # every candidate in one mask
    win.undo()
    assert s.project.objects == []  # one undo step


def test_select_on_image_add_toggle_remove_and_no_edit(qapp, win):
    from tests.app.test_gui import canvas_pos

    s = win.session
    oid = make_objects(win, 1)[0]
    win.detection_panel.prompt.setText("person, car")
    win.detection_panel.detect_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    d = win.detection_panel
    assert d.select_btn.isChecked() and win.canvas.candidates_pickable  # on after the detection
    cands = lambda: [o for o in win.canvas._overlays if o.style.startswith("candidate")]  # noqa: E731
    d.preview_btn.click()  # Preview off: nothing shown, nothing to pick
    assert cands() == [] and not win.canvas.candidates_pickable
    d.preview_btn.click()
    d.none_btn.click()
    qapp.processEvents()
    assert s.detection_checked == [False] * 4

    shift, ctrl = Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.ControlModifier
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 10, 10))  # click = add
    assert s.detection_checked == [True, False, False, False]
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 10, 10))  # add again: stays
    assert s.detection_checked[0]
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, shift, canvas_pos(win, 10, 10))  # Shift = toggle
    assert not s.detection_checked[0]
    # a drag that only grazes the car column (x 30..50) still adds both cars
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 29, 2))
    QTest.mouseMove(win.canvas, canvas_pos(win, 31, 40))
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 31, 40))
    assert s.detection_checked == [False, False, True, True]
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, ctrl, canvas_pos(win, 35, 30))  # Ctrl = remove
    assert s.detection_checked == [False, False, True, False]
    outlines = [o for o in win.canvas._overlays if o.style == "candidate_off"]
    assert len(outlines) == 3  # unchecked ones stay visible (outline drawn in paint)
    win.canvas.grab()

    win.toggle_edit(oid)  # Edit is blocked while Select on Image is on
    assert s.editing is None and s.project.objects[0].id == oid
    win.new_object()
    assert s.mode.value == "idle"
    d.add_btn.click()  # adding closes the list: Select on Image turns off, Edit works again
    qapp.processEvents()
    assert not d.select_btn.isChecked()
    win.toggle_edit(oid)
    assert s.editing == oid



def test_batch_tab_has_its_own_prompt(qapp, win):
    assert win.tabs.indexOf(win.batch_panel) >= 0 and win.tabs.indexOf(win.detection_panel) >= 0
    win.detection_panel.prompt.setText("car")
    win.batch_panel.prompt.setText("person")
    win.batch_panel.batch_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    assert [o.name for o in win.session.project.objects] == ["person #1"]
    assert win.detection_panel.prompt.text() == "car"


# --- Phase 4: Objects without a mask here are hidden; linked Objects are marked -----


def test_objects_list_hides_empty_and_marks_linked(qapp, win):
    import numpy as np

    from src.core.project import FrameState

    s = win.session
    a, b = make_objects(win, 2)  # both on image 0
    s.project.set_frame(b, s.keys[1], FrameState.from_mask(np.ones((60, 80), bool)))  # b also on image 1
    s.go_to(1)
    s.start_new_object()
    c = s.click(40, 30)  # only on image 1
    s.finish_editing()
    win.refresh()
    panel = win.objects_panel
    rows = lambda: [panel.tree.topLevelItem(i).data(0, 0x0100) for i in range(panel.tree.topLevelItemCount())]  # noqa: E731
    assert rows() == [b, c] and panel.shown_label.text() == "2 of 3 shown"
    link = {panel.tree.topLevelItem(i).data(0, 0x0100): panel.tree.topLevelItem(i).text(1) for i in range(2)}
    assert link == {b: "🔗 2", c: ""}
    panel.show_all.setChecked(True)
    assert rows() == [a, b, c] and panel.shown_label.text() == ""
    panel.show_all.setChecked(False)
    win.toggle_edit(a)  # editing an Object with no mask here keeps it listed
    assert a in rows()
    win.finish_editing()
    assert a not in rows()


# --- Propagation: reference by double-click, Selection / Range / All, Pin, Resume -----


def test_plan_over_picked_frames_skips_the_others():
    from src.core.propagation import Direction, PropagationPlan

    p = PropagationPlan.of_frames([7, 1, 9, 4], reference=5, direction=Direction.BOTH)
    assert p.sequence == [1, 4, 5, 7, 9] and p.backward == [4, 1] and p.forward == [7, 9]
    assert PropagationPlan(1, 4, 2, Direction.BOTH).sequence == [1, 2, 3, 4]  # a range still works


def gated_propagate(release, entered, after: int):
    """fake_propagate that blocks after *after* frames until *release* is set."""
    from tests.fakes import fake_propagate

    def run(*a, cancel=None, **kw):
        for n, item in enumerate(fake_propagate(*a, cancel=cancel, **kw)):
            if n == after:
                entered.set()
                release.wait(5)
                if cancel and cancel():
                    return
            yield item

    return run


def test_reference_selection_pin_and_all(qapp, win):
    s = win.session
    pp = win.propagation_panel
    win.go_to(1)
    win.new_object()
    s.click(30, 30)
    win.finish_editing()
    win.go_to(0)
    lst = win.images_panel.list
    lst.itemDoubleClicked.emit(lst.item(1))  # image 1 is the reference now
    assert win._reference == 1 and "◎" in pp.reference.text() and "◎" in lst.item(1).text()
    assert lst.item(1).text().split()[0] == "2"  # rows start with their image ID
    lst.clearSelection()
    for i in (3, 4):
        lst.item(i).setSelected(True)
    pp.pin_btn.click()  # pin images 3, 4
    assert win._pinned == [3, 4] and pp.pin_label.text().startswith("Pinned: 4–5 (2 image(s))")
    assert lst.item(3).background().color() == __import__("src.app.images_panel", fromlist=["x"]).PIN_COLOR
    assert "📌" in lst.item(3).text().splitlines()[0] and "📌" not in lst.item(2).text()
    lst.clearSelection()  # the pin survives
    assert pp.scope_value() == "selection"
    pp.run_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    obj = s.project.objects[0]
    assert set(k for k, fs in obj.frames.items()) == {s.keys[1], s.keys[3], s.keys[4]}  # 2 skipped
    pp.scope.setCurrentIndex(pp.scope.findData("all"))
    win.ask = lambda *a: True
    pp.run_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    assert len(s.project.objects[0].frames) == 5


def test_stop_then_cancel_or_resume(qapp, win):
    import threading

    s = win.session
    pp = win.propagation_panel
    win.new_object()
    s.click(30, 30)  # on image 0
    win.finish_editing()
    release, entered = threading.Event(), threading.Event()
    win.propagate_fn = gated_propagate(release, entered, after=2)
    pp.scope.setCurrentIndex(pp.scope.findData("all"))
    pp.run_btn.click()
    wait_until(qapp, entered.is_set)
    pp.stop_btn.click()
    assert pp.cancel_btn.isEnabled()  # Cancel still works after Stop
    release.set()
    wait_until(qapp, lambda: win._busy is None)
    obj = s.project.objects[0]
    assert len(obj.frames) == 3 and pp.resume_btn.isEnabled()  # 0 + frames 1, 2
    win.propagate_fn = __import__("tests.fakes", fromlist=["fake_propagate"]).fake_propagate
    pp.resume_btn.click()  # continues from frame 2 over 3, 4
    wait_until(qapp, lambda: win._busy is None)
    assert len(s.project.objects[0].frames) == 5 and not pp.resume_btn.isEnabled()

    release2, entered2 = threading.Event(), threading.Event()
    win.propagate_fn = gated_propagate(release2, entered2, after=1)
    win.ask = lambda *a: True
    pp.run_btn.click()
    wait_until(qapp, entered2.is_set)
    pp.stop_btn.click()
    pp.cancel_btn.click()  # Stop, then Cancel: the frames done are kept (p38), nothing to resume
    release2.set()
    wait_until(qapp, lambda: win._busy is None)
    assert "Cancelled" in pp.phase.text() and not pp.resume_btn.isEnabled()


def test_id_ranges_and_range_scope_by_ids(qapp, win):
    from src.core.propagation import format_ids, parse_id_range

    assert parse_id_range("5 ~ 45", 50) == (4, 44) and parse_id_range("45-5", 50) == (4, 44)
    assert parse_id_range("7", 50) == (6, 6)
    for bad in ("", "a~b", "0~3", "3~99"):
        with pytest.raises(ValueError):
            parse_id_range(bad, 50)
    assert format_ids([2, 3, 4, 11, 13, 14]) == "3–5, 12, 14–15"

    s = win.session
    pp = win.propagation_panel
    win.go_to(2)
    win.new_object()
    s.click(30, 30)
    win.finish_editing()
    pp.scope.setCurrentIndex(pp.scope.findData("range"))
    assert (pp.start_edit.text(), pp.end_edit.text()) == ("1", "5") and pp.ref_hint.text().startswith("Double")
    pp.start_edit.setText("4")  # IDs 2..4 = images 1..3 (either order), reference 2 (ID 3)
    pp.end_edit.setText("2")
    pp.run_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    assert set(s.project.objects[0].frames) == {s.keys[1], s.keys[2], s.keys[3]}
    pp.end_edit.setText("12")
    pp.run_btn.click()
    assert "1 to 5" in pp.phase.text()  # an out-of-range ID is reported, nothing runs

    from src.core.propagation import parse_id_list

    assert parse_id_list("1-4, 35 ,23", 40) == [0, 1, 2, 3, 22, 34]
    with pytest.raises(ValueError):
        parse_id_list("1-4, 99", 40)
    pp.scope.setCurrentIndex(pp.scope.findData("custom"))
    pp.custom_edit.setText("5, 1")  # IDs 1 and 5 around the reference (ID 3)
    win.ask = lambda *a: True
    pp.run_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    assert {s.keys[0], s.keys[4]} <= set(s.project.objects[0].frames)



def test_frame_list_follows_the_strip_and_thumbnails_are_cached(qapp, win, tmp_path):
    from PyQt6.QtCore import QItemSelectionModel

    ip = win.images_panel
    fl = ip.frame_list
    assert fl.model() is ip.list.model() and fl.selectionModel() is ip.list.selectionModel()
    # picking in the list shows in the strip, and the list rows are one line
    fl.selectionModel().select(fl.model().index(3, 0), QItemSelectionModel.SelectionFlag.Select)
    assert 3 in ip.selected_rows()
    fl.setCurrentIndex(fl.model().index(2, 0))
    qapp.processEvents()
    assert win.session.index == 2  # the list navigates too
    fl.doubleClicked.emit(fl.model().index(4, 0))
    assert win._reference == 4
    assert fl.sizeHintForRow(0) < 40  # one text line, no thumbnail
    # thumbnails: all read while idle, and cached next to the project
    cache = win.session.store.root / "thumbs"
    wait_until(qapp, lambda: len(list(cache.glob("*.jpg"))) == 5, timeout=5)  # the whole folder, while idle
    wait_until(qapp, lambda: not ip._load_timer.isActive(), timeout=5)
    view = next(a.menu() for a in win.menuBar().actions() if a.text().replace("&", "") == "View")
    panels = next(a.menu() for a in view.actions() if a.menu() is not None and a.text() == "Panels")
    toggles = panels.actions()
    assert any(a.text().replace("&", "") == "Frame List" for a in toggles)
    assert all(a.isEnabled() for a in toggles)  # each dock can be hidden / shown
    frame_list = next(a for a in toggles if a.text().replace("&", "") == "Frame List")
    frame_list.trigger()
    assert not fl.isVisibleTo(win)
    frame_list.trigger()
    assert fl.isVisibleTo(win)


def test_frame_list_names_fold_away(qapp, win):
    ip = win.images_panel
    assert win.names_btn.isChecked() and ip.names_visible  # names shown by default
    win.names_btn.click()
    assert not ip.names_visible and not win.settings.frame_list_names
    opt_text = lambda: (lambda o: (ip._delegate.initStyleOption(o, ip.frame_list.model().index(0, 0)), o.text)[1])(  # noqa: E731
        __import__("PyQt6.QtWidgets", fromlist=["QStyleOptionViewItem"]).QStyleOptionViewItem()
    )
    assert opt_text().strip() == "1"  # only the ID (and marks)
    assert ip.frame_list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    win.names_btn.click()
    assert "frame_000.png" in opt_text()
    bar = win._list_dock.titleBarWidget()
    assert win.names_btn.parent() is bar  # in the Frame List title bar


def test_focus_and_goto_frames(qapp, win):
    from PyQt6.QtGui import QKeySequence
    from PyQt6.QtWidgets import QLineEdit

    ip = win.images_panel
    assert not hasattr(win, "act_focus")  # v0.4-p15: no S key (the ⌖ button and F remain)
    gotos = win._goto_fields
    assert len(gotos) == 2 and all(isinstance(g, QLineEdit) for g in gotos)  # under the list and the strip
    assert not win._list_dock.titleBarWidget().findChildren(QLineEdit)  # not in the title bar
    gotos[1].setText("4")
    gotos[1].returnPressed.emit()
    assert win.session.index == 3 and gotos[1].text() == ""
    gotos[0].setText("99")
    gotos[0].returnPressed.emit()
    assert win.session.index == 3  # out of range: nothing happens
    ip.list.horizontalScrollBar().setValue(0)
    win.focus_frame()  # ⌖
    item_rect = ip.list.visualItemRect(ip.list.item(3))
    assert ip.list.viewport().rect().intersects(item_rect)
