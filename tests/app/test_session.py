import numpy as np
import pytest

from src.app.session import Mode, Session
from src.core.project import FrameStatus, Source
from src.core.propagation import Direction
from src.core.storage import ExportOptions
from tests.fakes import FakeEngine, fake_propagate, make_images


@pytest.fixture
def session(tmp_path):
    make_images(tmp_path / "images", n=5)
    s = Session(FakeEngine())
    s.open_folder(tmp_path / "images")
    return s


def test_open_folder_sets_first_image_and_engine(session):
    assert session.keys == [f"frame_{i:03d}.png" for i in range(5)]
    assert session.index == 0 and session.image.shape == (60, 80, 3)
    assert session.engine.image is session.image


def test_idle_click_never_creates_an_object_once_objects_exist(session):
    assert session.click(10, 10) is None  # not even the first one
    session.start_new_object()
    session.click(10, 10)
    session.finish_editing()
    assert session.click(40, 40) is None
    assert len(session.project.objects) == 1


def test_new_object_from_point_then_edit_and_delete_point(session):
    session.start_new_object()
    oid = session.click(20, 20)
    assert session.mode == Mode.EDIT and session.editing == oid
    obj = session.project.get(oid)
    assert obj.source == Source.SAM2_POINT and len(obj.frame(session.key).variants) == 3
    session.click(60, 40)
    session.click(62, 42, positive=False)
    fs = session.editing_frame()
    assert [p.positive for p in fs.points] == [True, True, False]
    assert not fs.mask[42, 62] and fs.mask[20, 20]

    session.select_point(2)
    assert session.delete_point()  # the negative point goes, SAM2 re-runs on the rest
    fs = session.editing_frame()
    assert len(fs.points) == 2 and fs.mask[42, 62] and session.selected_point is None
    assert session.engine.calls[-1][0] == fs.points


def test_new_object_negative_click_is_ignored(session):
    session.start_new_object()
    assert session.click(5, 5, positive=False) is None
    assert session.project.objects == [] and session.mode == Mode.NEW_OBJECT


def test_box_creates_object_and_clear_points(session):
    session.start_new_object()
    oid = session.drag_box((30, 40, 10, 5))
    fs = session.editing_frame()
    assert session.project.get(oid).source == Source.SAM2_BOX and fs.box == (10, 5, 30, 40)
    session.click(70, 50)
    assert session.clear_points()
    fs = session.editing_frame()
    assert fs.points == () and fs.box is None and fs.mask is None


def test_variant_select_and_brush(session):
    session.start_new_object()
    oid = session.click(40, 30)
    small = session.editing_frame().variants[2].mask
    session.select_variant(2)
    assert session.project.get(oid).mask(session.key) is small
    painted = np.zeros((60, 80), bool)
    painted[0:5, 0:5] = True
    session.brush(painted)
    fs = session.editing_frame()
    # the stroke is an edit layer on top of the kept point prompt
    assert len(fs.points) == 1 and fs.mask.sum() == 25 and fs.prompt_mask is small and fs.edit is not None
    session.apply_edit()  # baked in: becomes the prior for later clicks
    session.select_layer(0)  # the Original (by default a point layer on top, v0.4-p53)
    session.click(70, 50)
    assert session.engine.calls[-1][2] is True and session.editing_frame().mask[0, 0]


def test_undo_past_creation_leaves_edit_mode(session):
    session.start_new_object()
    session.click(20, 20)
    session.undo()
    assert session.project.objects == [] and session.mode == Mode.IDLE and session.editing is None


def test_navigation_leaves_edit_and_keeps_detections_per_image(session):
    session.set_detections(session.engine.detect("person"))
    session.detection_checked[0] = False
    session.start_new_object()
    session.click(20, 20)
    assert session.step(1) and session.index == 1
    assert session.mode == Mode.IDLE and session.detections == []
    session.step(-1)
    assert len(session.detections) == 2 and session.detection_checked == [False, True]


def test_select_variant_of_any_object_without_edit(session):
    session.start_new_object()
    oid = session.click(40, 30)
    session.cancel_mode()
    session.select_variant(1, oid)
    fs = session.project.get(oid).frame(session.key)
    assert fs.selected == 1 and fs.mask is fs.variants[1].mask


def test_add_checked_detections(session):
    session.set_detections(session.engine.detect("person"))
    session.detection_checked[1] = False
    ids = session.add_checked_detections()
    assert len(ids) == 1 and session.project.get(ids[0]).name == "person #1"
    assert session.detections == []
    # a SAM3 Object is refined with SAM2 using its detection as the prior
    session.edit(ids[0])
    session.select_layer(0)  # the Original (by default a point layer on top, v0.4-p53)
    session.click(70, 50)
    fs = session.editing_frame()
    assert fs.mask[10, 10] and fs.mask[50, 70] and session.engine.calls[-1][2] is True


def test_editing_on_another_image_creates_that_frame(session):
    session.start_new_object()
    oid = session.click(20, 20)
    session.step(1)
    session.edit(oid)
    assert session.editing_frame() is None
    session.click(30, 30)
    assert session.project.get(oid).mask(session.key)[30, 30]


def test_propagation_flow(session):
    session.start_new_object()
    a = session.click(20, 20)
    session.start_new_object()
    b = session.click(60, 40)
    session.project.set_included(b, False)  # unchecked Objects do not propagate
    session.go_to(2)
    session.edit(a)
    session.click(20, 20)  # Object a now has a reference mask on image 2
    plan = session.plan(0, 4, Direction.BOTH)
    seeds = session.seeds()
    assert list(seeds) == [a]
    assert session.overwrite_targets(plan, seeds) == ["frame_000.png"]
    results = dict(fake_propagate("", session.paths, plan, seeds, 1024))
    assert sorted(results) == [0, 1, 3, 4]
    results[4] = {a: np.zeros((60, 80), bool)}
    status = session.apply_propagation(results, seeds)
    assert status[1] == FrameStatus.PROPAGATED and status[4] == FrameStatus.FAILED
    assert session.project.get(a).frame("frame_003.png").status == FrameStatus.PROPAGATED
    assert session.project.get(b).frame("frame_003.png") is None
    session.undo()  # one undo step for the whole propagation
    assert session.project.get(a).frame("frame_003.png") is None


def test_autosave_reload_and_export(session, tmp_path):
    session.start_new_object()
    session.click(20, 20)
    assert session.save()
    again = Session(FakeEngine())
    again.open_folder(tmp_path / "images")
    assert len(again.project.objects) == 1
    written = again.export(ExportOptions(out_dir=tmp_path / "out"))
    assert [p.name for p in written] == ["frame_000.png"]
