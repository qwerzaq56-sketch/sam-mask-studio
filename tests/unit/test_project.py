import numpy as np
import pytest

from src.core.project import (
    Detection,
    FrameState,
    FrameStatus,
    Point,
    Project,
    Source,
    Variant,
    freeze,
    mask_box,
)


def m(rows, shape=(8, 8)):
    a = np.zeros(shape, bool)
    for r in rows:
        a[r, :] = True
    return freeze(a)


KEYS = ["a.jpg", "b.jpg", "c.jpg"]


def test_freeze_is_readonly_bool():
    raw = np.array([[0, 255]], np.uint8)
    f = freeze(raw)
    assert f.dtype == bool and not f.flags.writeable and f.tolist() == [[False, True]]
    with pytest.raises(ValueError):
        f[0, 0] = True


def test_frame_mask_prefers_selected_variant_then_base():
    base = m([0])
    fs = FrameState(base_mask=base)
    assert fs.mask is base
    v1, v2 = Variant(m([1]), 0.9), Variant(m([2]), 0.5)
    fs = FrameState(base_mask=base, variants=(v1, v2), selected=1)
    assert fs.mask is v2.mask


def test_add_and_final_mask_respects_included():
    p = Project(KEYS)
    a = p.add_object("a.jpg", FrameState.from_mask(m([0])), Source.SAM2_POINT)
    b = p.add_object("a.jpg", FrameState.from_mask(m([1])), Source.SAM2_POINT)
    assert p.final_mask("a.jpg").sum() == 16
    p.set_included(b, False)
    assert p.final_mask("a.jpg").sum() == 8
    assert p.final_mask("b.jpg") is None
    assert [o.name for o in p.objects] == ["Object #1", "Object #2"] and a != b


def test_detections_become_named_objects_in_one_undo_step():
    p = Project(KEYS)
    dets = [Detection("person", 0.9, m([0]), mask_box(m([0]))), Detection("person", 0.8, m([3]), (0, 3, 7, 3))]
    ids = p.add_detections("a.jpg", dets)
    assert [p.get(i).name for i in ids] == ["person #1", "person #2"]
    assert all(p.get(i).source == Source.SAM3_DETECTION for i in ids)
    p.undo()
    assert p.objects == []
    p.redo()
    assert len(p.objects) == 2


def test_merge_unions_per_frame_and_replaces_originals():
    p = Project(KEYS)
    a = p.add_object("a.jpg", FrameState.from_mask(m([0])), Source.SAM2_POINT)
    b = p.add_object("a.jpg", FrameState.from_mask(m([1])), Source.SAM2_POINT)
    p.set_frame(a, "b.jpg", FrameState.from_mask(m([2]), status=FrameStatus.PROPAGATED))
    p.set_frame(b, "c.jpg", FrameState.from_mask(m([3]), status=FrameStatus.PROPAGATED))
    mid = p.merge([a, b])
    merged = p.get(mid)
    assert [o.id for o in p.objects] == [mid]
    assert merged.mask("a.jpg").sum() == 16  # A ∪ B
    assert merged.mask("b.jpg").sum() == 8  # only A there
    assert merged.mask("c.jpg").sum() == 8  # only B there
    assert merged.frames["a.jpg"].status == FrameStatus.MANUAL
    assert merged.frames["b.jpg"].status == FrameStatus.PROPAGATED
    assert merged.source == Source.MERGED and merged.name == "Object #1 + Object #2"
    p.undo()
    assert {o.id for o in p.objects} == {a, b}


def test_duplicate_is_independent():
    p = Project(KEYS)
    a = p.add_object("a.jpg", FrameState(points=(Point(1, 1),), base_mask=m([0])), Source.SAM2_POINT)
    (c,) = p.duplicate([a])
    assert p.objects[1].id == c and p.get(c).frames["a.jpg"].points == (Point(1, 1),)
    p.set_frame(c, "a.jpg", FrameState.from_mask(m([5])))
    assert p.get(a).mask("a.jpg").sum() == 8 and p.get(a).mask("a.jpg")[0].all()


def test_select_variant_and_rename_are_undoable():
    p = Project(KEYS)
    fs = FrameState(variants=(Variant(m([0]), 0.9), Variant(m([1, 2]), 0.4)))
    a = p.add_object("a.jpg", fs, Source.SAM2_POINT)
    p.select_variant(a, "a.jpg", 1)
    assert p.get(a).mask("a.jpg").sum() == 16
    p.rename(a, "Player")
    assert p.get(a).name == "Player"
    p.undo()
    p.undo()
    assert p.get(a).name == "Object #1" and p.get(a).frames["a.jpg"].selected == 0


def test_undo_snapshots_share_arrays():
    p = Project(KEYS)
    a = p.add_object("a.jpg", FrameState.from_mask(m([0])), Source.SAM2_POINT)
    before = p.get(a).mask("a.jpg")
    p.set_frames({a: {"b.jpg": FrameState.from_mask(m([1])), "c.jpg": FrameState.from_mask(m([2]))}})
    p.undo()
    assert p.get(a).mask("a.jpg") is before and "b.jpg" not in p.get(a).frames


def test_keys_with_masks_in_sequence_order():
    p = Project(KEYS)
    a = p.add_object("c.jpg", FrameState.from_mask(m([0])), Source.SAM2_POINT)
    p.set_frame(a, "a.jpg", FrameState.from_mask(m([0])))
    assert p.keys_with_masks() == ["a.jpg", "c.jpg"]
