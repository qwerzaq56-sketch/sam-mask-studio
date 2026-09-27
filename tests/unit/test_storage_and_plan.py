from pathlib import Path

import cv2
import numpy as np
import pytest

from src.core.project import FrameState, FrameStatus, Point, Project, Source, freeze
from src.core.propagation import Direction, PropagationPlan, existing_targets, grade
from src.core.storage import ExportOptions, ProjectStore, export_final_masks, sidecar_dir


def mask(rows, shape=(10, 20)):
    a = np.zeros(shape, bool)
    a[rows, :] = True
    return freeze(a)


@pytest.fixture
def image_dir(tmp_path):
    d = tmp_path / "이미지"  # non-ASCII on purpose
    d.mkdir()
    return d


def test_sidecar_is_beside_image_dir(image_dir):
    assert sidecar_dir(image_dir) == image_dir.parent / "이미지.sms"


def test_save_load_roundtrip_and_incremental_writes(image_dir):
    keys = ["001.jpg", "002.jpg"]
    p = Project(keys)
    a = p.add_object("001.jpg", FrameState(points=(Point(3, 4, False),), box=(1, 2, 5, 6), base_mask=mask([1])), Source.SAM2_POINT)
    p.set_frame(a, "002.jpg", FrameState.from_mask(mask([2]), status=FrameStatus.WARNING))
    p.rename(a, "Player")
    store = ProjectStore(image_dir, 1024)
    assert store.save(p)
    assert not store.save(p)  # nothing changed

    p2 = ProjectStore(image_dir, 1024).load(keys)
    o = p2.get(a)
    assert o.name == "Player" and o.source == Source.SAM2_POINT
    assert o.frames["001.jpg"].points == (Point(3, 4, False),) and o.frames["001.jpg"].box == (1, 2, 5, 6)
    assert o.frames["002.jpg"].status == FrameStatus.WARNING
    assert np.array_equal(o.mask("001.jpg"), mask([1])) and np.array_equal(o.mask("002.jpg"), mask([2]))
    assert p2.next_id == p.next_id

    # Only the changed mask file is rewritten; removed objects' files disappear.
    f1, f2 = store.mask_path(a, "001.jpg"), store.mask_path(a, "002.jpg")
    t1 = f1.stat().st_mtime_ns
    p.set_frame(a, "002.jpg", FrameState.from_mask(mask([3])))
    store.save(p)
    assert f1.stat().st_mtime_ns == t1 and cv2.imdecode(np.fromfile(str(f2), np.uint8), 0)[3].all()
    p.remove_objects([a])
    store.save(p)
    assert not f1.parent.exists()


def test_export_upscales_inverts_and_names(image_dir, tmp_path):
    keys = ["001.jpg", "002.jpg"]
    p = Project(keys)
    p.add_object("001.jpg", FrameState.from_mask(mask([0])), Source.SAM2_POINT)
    out = tmp_path / "out"
    written = export_final_masks(p, image_dir, lambda k: (20, 40), ExportOptions(out, "{name}.png", invert=True))
    assert [w.name for w in written] == ["001.jpg.png"]
    img = cv2.imdecode(np.fromfile(str(written[0]), np.uint8), 0)
    assert img.shape == (20, 40) and img[0].max() == 0 and img[5].min() == 255
    written = export_final_masks(p, image_dir, lambda k: (20, 40), ExportOptions(out, include_empty=True))
    assert sorted(w.name for w in written) == ["001.png", "002.png"]


def test_plan_walks_outward_from_current_within_bounds():
    p = PropagationPlan(start=1, end=7, current=4, direction=Direction.BOTH)
    assert p.backward == [3, 2, 1] and p.forward == [5, 6, 7] and 4 not in p.targets
    assert p.window == (1, 7)
    f = PropagationPlan(1, 7, 4, Direction.FORWARD)
    assert f.backward == [] and f.forward == [5, 6, 7] and f.window == (4, 7)
    b = PropagationPlan(1, 7, 4, Direction.BACKWARD)
    assert b.forward == [] and b.window == (1, 4)
    with pytest.raises(ValueError):
        PropagationPlan(5, 7, 4, Direction.BOTH)


def test_grade_and_existing_targets():
    assert grade(np.zeros((4, 4), bool), 10) == FrameStatus.FAILED
    assert grade(np.ones((4, 4), bool), 16) == FrameStatus.PROPAGATED
    assert grade(np.ones((4, 4), bool), 100) == FrameStatus.WARNING
    keys = ["a", "b", "c", "d"]
    plan = PropagationPlan(0, 3, 1, Direction.BOTH)
    frames = {7: {"a": FrameState.from_mask(mask([0])), "b": FrameState.from_mask(mask([0]))}}
    assert existing_targets(frames, keys, plan) == ["a"]  # b is current, excluded
