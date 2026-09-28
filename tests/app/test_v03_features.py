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
