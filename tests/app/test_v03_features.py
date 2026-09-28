"""v0.3: responsiveness and UX fixes (one section per change, so each can be reverted with it)."""

import threading
import time

import pytest

from PyQt6.QtCore import Qt
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
    getattr(win.detection_panel, button).click()
    assert not win.detection_panel.stop_btn.isEnabled()
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

    region = np.zeros((200, 200), bool)
    region[:, 100:] = True
    half = within(region, seed > 0, grown)
    assert half[100, 150] and not half[100, 50]


def test_region_painted_with_brush_limits_the_tools(qapp, win):
    import numpy as np

    from tests.app.test_gui import canvas_pos

    s = win.session
    win.new_object()
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 30, 30))
    t = s.editing_frame().mask.copy()
    t[25, 25] = t[35, 35] = False  # two holes, one on each side
    s.brush(t)
    win.refresh()
    win.properties_panel.region_btn.click()  # paint the region: turns the brush on
    assert win.canvas.paint_region and win.canvas.brush_mode
    win.canvas.set_brush_size(40)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 36, 36))
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=canvas_pos(win, 36, 36))
    qapp.processEvents()
    assert s.region is not None and s.region[35, 35] and not s.region[25, 25]
    assert s.editing_frame().mask.sum() == t.sum()  # painting the region left the mask alone
    win.properties_panel.refine_area.setValue(5)
    win.properties_panel.fill_btn.click()
    m = s.editing_frame().mask
    assert m[35, 35] and not m[25, 25]  # only the hole inside the region
    win.properties_panel.clear_region_btn.click()
    assert s.region is None and "whole mask" in win.properties_panel.scope_label.text()
    win.properties_panel.fill_btn.click()
    assert s.editing_frame().mask[25, 25]
    win.finish_editing()
    assert not win.canvas.paint_region and s.region is None


def test_object_fill_button(qapp, win):
    s = win.session
    win.new_object()
    s.click(40, 30)
    before = s.editing_frame().mask.sum()
    win.refresh()
    win.properties_panel.object_fill_btn.click()
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
