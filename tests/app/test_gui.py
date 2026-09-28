import numpy as np
import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest

from src.app.main_window import MainWindow
from src.app.session import Mode
from src.app.settings import Settings
from src.core.project import FrameStatus
from src.core.propagation import Direction
from src.core.storage import ExportOptions, sidecar_dir
from tests.app.conftest import wait_until
from tests.fakes import FakeEngine, fake_propagate, make_images


@pytest.fixture
def folder(tmp_path):
    make_images(tmp_path / "images", n=5)
    return tmp_path / "images"


@pytest.fixture
def win(qapp, folder, tmp_path):
    w = MainWindow(
        settings=Settings(sam2_checkpoint=str(tmp_path / "none.pt")),
        engine=FakeEngine(),
        propagate_fn=fake_propagate,
        settings_path=tmp_path / "config.json",
    )
    w.ask = lambda *a: True
    w.warn = w.log
    w.resize(1200, 800)
    w.show()
    assert w.open_folder(folder)
    qapp.processEvents()
    yield w
    w._autosave.stop()
    w.close()


def canvas_pos(win, x, y) -> QPoint:
    return win.canvas.to_widget(x, y).toPoint()


def click(win, x, y, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
    QTest.mouseClick(win.canvas, button, mods, canvas_pos(win, x, y))


def test_first_click_creates_object_then_idle_clicks_create_nothing(win):
    assert win.canvas.mode == Mode.NEW_OBJECT  # no Objects yet: a click starts the first one
    click(win, 20, 20)
    assert len(win.session.project.objects) == 1 and win.session.mode == Mode.EDIT
    win.finish_editing()
    assert win.canvas.mode == Mode.IDLE
    click(win, 60, 40)
    assert len(win.session.project.objects) == 1
    assert win.canvas.isEnabled() and win.image_label.text().startswith("1/5")


def test_new_object_from_points_by_mouse(win):
    win.new_object()
    assert win.canvas.mode == Mode.NEW_OBJECT
    click(win, 30, 30)
    s = win.session
    assert len(s.project.objects) == 1 and s.mode == Mode.EDIT
    obj = s.project.objects[0]
    tree = win.objects_panel.tree
    assert tree.topLevelItem(0).text(0) == obj.name
    assert tree.topLevelItem(0).childCount() == 3  # Variant rows under the Object
    assert win.properties_panel.variants.count() == 3
    assert win.canvas.banner == f"Editing: {obj.name}"
    # right click = negative point on the same Object
    click(win, 34, 30, Qt.MouseButton.RightButton)
    fs = s.editing_frame()
    assert [p.positive for p in fs.points] == [True, False]


def test_select_point_on_canvas_and_delete_it(win):
    win.new_object()
    click(win, 30, 30)
    click(win, 60, 40)
    click(win, 60, 40)  # clicking a drawn point selects it instead of adding one
    s = win.session
    assert len(s.editing_frame().points) == 2 and s.selected_point == 1
    assert win.properties_panel.selected_point() == 1
    win.delete_key()
    assert len(s.editing_frame().points) == 1 and s.editing_frame().points[0].x == pytest.approx(30, abs=1)


def test_box_drag_creates_object(win):
    win.new_object()
    a, b = canvas_pos(win, 10, 10), canvas_pos(win, 40, 30)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(win.canvas, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(win.canvas, b)
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    fs = win.session.editing_frame()
    assert fs is not None and fs.box is not None and fs.mask[20, 20]


def test_brush_paints_edited_object(win):
    win.new_object()
    click(win, 30, 30)
    p = canvas_pos(win, 70, 50)
    shift = Qt.KeyboardModifier.ShiftModifier
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, shift, p)
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, shift, p)
    fs = win.session.editing_frame()
    assert fs.mask[50, 70] and len(fs.points) == 1 and fs.edit is not None  # Shift stroke -> edit layer


def test_variant_rows_in_objects_panel_select_variant(win):
    win.new_object()
    click(win, 30, 30)
    win.finish_editing()
    oid = win.session.project.objects[0].id
    win.objects_panel.variant_selected.emit(oid, 2)
    fs = win.session.project.get(oid).frame(win.session.key)
    assert fs.selected == 2
    assert win.objects_panel.tree.topLevelItem(0).child(2).text(0).startswith("●")


def test_detect_add_selected_as_objects(win, qapp):
    win.detect("person")
    wait_until(qapp, lambda: win._busy is None)
    assert win.detection_panel.tree.topLevelItemCount() == 1
    win.detection_panel.item(1).setCheckState(0, Qt.CheckState.Unchecked)
    qapp.processEvents()
    assert win.session.detection_checked == [True, False]
    win.detection_panel.add_btn.click()
    qapp.processEvents()
    assert [o.name for o in win.session.project.objects] == ["person #1"]
    assert win.detection_panel.tree.topLevelItemCount() == 0


def test_comma_prompt_detects_each_label_grouped(win, qapp):
    win.detection_panel.prompt.setText("person, car ,  tripod")
    win.detection_panel.detect_btn.click()
    wait_until(qapp, lambda: win._busy is None)
    tree = win.detection_panel.tree
    assert [tree.topLevelItem(i).text(0) for i in range(3)] == ["person  (2)", "car  (2)", "tripod  (2)"]
    tree.topLevelItem(1).setCheckState(0, Qt.CheckState.Unchecked)  # the label row unchecks its group
    qapp.processEvents()
    assert win.session.detection_checked == [True, True, False, False, True, True]
    win.detection_panel.add_btn.click()
    qapp.processEvents()
    assert [o.name for o in win.session.project.objects] == ["person #1", "person #2", "tripod #1", "tripod #2"]


def test_brush_mode_layer_apply_and_delete(win, qapp):
    win.new_object()
    click(win, 30, 30)
    s = win.session
    prompt = s.editing_frame().mask.copy()
    win.act_brush.trigger()
    assert win.canvas.brush_mode and win.properties_panel.brush_btn.isChecked()
    size0 = win.canvas.brush_size
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QWheelEvent

    ev = QWheelEvent(QPointF(canvas_pos(win, 40, 40)), QPointF(), QPoint(), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
    qapp.sendEvent(win.canvas, ev)
    assert win.canvas.brush_size > size0 and win.canvas.zoom == 1.0  # Ctrl+wheel = size
    ev = QWheelEvent(QPointF(canvas_pos(win, 40, 40)), QPointF(), QPoint(), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    qapp.sendEvent(win.canvas, ev)
    assert win.canvas.zoom > 1.0  # the wheel zooms, brush on or not
    win.canvas.set_zoom(1.0)

    # plain drag = add, and it goes to the layer (points stay)
    p = canvas_pos(win, 70, 50)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    fs = s.editing_frame()
    assert fs.mask[50, 70] and fs.points and fs.edit is not None
    assert "Layer: +" in win.properties_panel.layer_label.text()
    # Alt+drag = subtract
    q = canvas_pos(win, 30, 30)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, q)
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, q)
    assert not s.editing_frame().mask[30, 30]
    # a right click with the brush on adds no point
    n = len(s.editing_frame().points)
    click(win, 10, 10, Qt.MouseButton.RightButton)
    assert len(s.editing_frame().points) == n
    # Delete Layer -> back to the point mask
    win.properties_panel.delete_layer_btn.click()
    qapp.processEvents()
    assert s.editing_frame().edit is None and np.array_equal(s.editing_frame().mask, prompt)
    win.undo()
    assert s.editing_frame().edit is not None
    # Apply Layer -> the edited mask becomes the main mask
    win.properties_panel.apply_layer_btn.click()
    qapp.processEvents()
    fs = s.editing_frame()
    assert fs.edit is None and fs.points == () and fs.mask[50, 70] and not fs.mask[30, 30]
    # leaving Edit turns the brush off
    win.finish_editing()
    assert not win.canvas.brush_mode and not win.act_brush.isChecked()


def test_refine_button(win, qapp):
    win.new_object()
    click(win, 30, 30)
    s = win.session
    t = s.editing_frame().mask.copy()
    t[30, 30] = False
    s.brush(t)
    win.refresh()
    win.properties_panel.refine_area.setValue(10)
    win.properties_panel.mode_fill_btn.click()
    win.properties_panel.tool_btns["fill_holes"].click()  # Fill mode: a preview...
    win.properties_panel.tool_btns["fill_holes"].click()  # ...written in when the tool closes
    assert s.editing_frame().mask[30, 30]


def test_batch_masking_all_images(win, qapp):
    win.detection_panel.prompt.setText("person, none")
    win.detection_panel.threshold.setValue(0.7)
    win.detection_panel.batch_btn.click()  # scope defaults to All images
    wait_until(qapp, lambda: win._busy is None)
    s = win.session
    assert [o.name for o in s.project.objects] == ["person #1"]
    person = s.project.objects[0]
    assert len(person.frames) == 5 and person.frames[s.keys[0]].mask[10, 10]
    assert not person.frames[s.keys[0]].mask[30, 10]  # 0.6 detection below threshold
    res = win.detection_panel.results
    assert res.count() == 5 and res.item(2).text().startswith("✓")
    res.itemClicked.emit(res.item(3))
    assert s.index == 3
    win.undo()
    assert s.project.objects == []


def test_batch_selected_images(win, qapp):
    lst = win.images_panel.list
    lst.clearSelection()
    lst.item(1).setSelected(True)
    lst.item(3).setSelected(True)
    win.run_batch(["person"], "selected", 0, -1, 0.5)
    wait_until(qapp, lambda: win._busy is None)
    person = win.session.project.objects[0]
    assert sorted(person.frames) == [win.session.keys[1], win.session.keys[3]]


def test_rename_include_duplicate_merge_delete(win, qapp):
    for x in (20, 60):
        win.new_object()
        click(win, x, 30)
    win.finish_editing()
    s = win.session
    a, b = (o.id for o in s.project.objects)
    win.objects_panel.renamed.emit(a, "Player")
    assert s.project.get(a).name == "Player"
    item = win.objects_panel.tree.topLevelItem(1)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    qapp.processEvents()
    assert not s.project.get(b).included
    assert s.project.final_mask(s.key)[30, 20] and not s.project.final_mask(s.key)[30, 60]
    win.objects_panel.select_ids([a])
    win.objects_panel.dup_btn.click()
    qapp.processEvents()
    assert len(s.project.objects) == 3
    win.objects_panel.select_ids([a, b])
    win.objects_panel.merge_btn.click()
    qapp.processEvents()
    assert len(s.project.objects) == 2 and "Player" in s.project.objects[0].name
    win.objects_panel.select_ids([s.project.objects[0].id])
    win.delete_key()
    assert len(s.project.objects) == 1
    win.undo()
    assert len(s.project.objects) == 2


def test_final_preview_toggle(win):
    win.act_final.trigger()
    assert win.canvas.showing_final
    win.act_final.trigger()
    assert not win.canvas.showing_final


def test_propagation_end_to_end(win, qapp):
    s = win.session
    win.go_to(2)
    win.new_object()
    click(win, 30, 30)
    win.propagate(0, 4, Direction.BOTH)
    wait_until(qapp, lambda: win._busy is None)
    oid = s.project.objects[0].id
    obj = s.project.get(oid)
    assert all(obj.frame(k).status == FrameStatus.PROPAGATED for k in s.keys if k != s.key)
    assert obj.frame(s.key).status == FrameStatus.MANUAL  # the reference is untouched
    texts = [win.propagation_panel.frames.item(i).text() for i in range(5)]
    assert texts[2].endswith("★") and texts[0].endswith("✓")
    assert win.propagation_panel.bars["Backward"][1].value() == 2
    assert win.propagation_panel.bars["Forward"][1].value() == 2
    assert "Complete" in win.propagation_panel.objects.item(0).text()
    win.propagation_panel.frames.itemClicked.emit(win.propagation_panel.frames.item(4))
    assert s.index == 4
    win.undo()
    assert s.project.get(oid).frame(s.keys[4]) is None


def test_propagation_needs_current_in_range(win):
    win.go_to(3)
    win.new_object()
    click(win, 30, 30)
    win.propagate(0, 2, Direction.BOTH)
    assert win._busy is None and len(win.session.project.objects[0].frames) == 1


def test_navigation_and_autosave_reload(win, qapp, folder, tmp_path):
    win.new_object()
    click(win, 30, 30)
    win.step(1)
    assert win.session.index == 1 and win.session.mode == Mode.IDLE
    win._save_task.wait()  # written in the background on image change
    assert (sidecar_dir(folder) / "project.json").is_file()
    marks = [win.images_panel.list.item(i).text()[0] for i in range(2)]
    assert marks == ["★", " "]
    win.run_export(ExportOptions(out_dir=tmp_path / "out"))
    wait_until(qapp, lambda: win._busy is None)
    out = tmp_path / "out" / "frame_000.png"
    assert out.is_file()
    import cv2

    m = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
    assert m.shape == (60, 80) and m[30, 30] == 255 and np.count_nonzero(m) > 0
