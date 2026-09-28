"""v0.2 features: first-Object click, multi-label prompts, edit layer, batch masking."""

import numpy as np
import pytest

from src.app.session import Mode, Session
from src.core.project import Source
from src.core.prompts import split_labels
from src.core.refine import fill_holes_and_specks
from src.core.storage import ProjectStore
from src.engine.batch import batch_detect, summarize
from tests.fakes import FakeEngine, make_images


@pytest.fixture
def session(tmp_path):
    make_images(tmp_path / "imgs", n=5)
    s = Session(FakeEngine(), max_side=1024)
    s.open_folder(tmp_path / "imgs")
    return s


# --- 3) the very first Object comes from a plain click -------------------------


def test_first_click_creates_object_when_there_are_none(session):
    assert session.mode == Mode.IDLE and session.effective_mode == Mode.NEW_OBJECT
    oid = session.click(30, 30)
    assert oid is not None and session.mode == Mode.EDIT
    session.finish_editing()
    assert session.effective_mode == Mode.IDLE
    assert session.click(50, 30) is None and len(session.project.objects) == 1  # later: never silent


def test_first_object_by_box_and_negative_click_does_nothing(session):
    assert session.click(30, 30, positive=False) is None
    assert session.drag_box((10, 10, 40, 30)) is not None
    assert session.project.objects[0].source == Source.SAM2_BOX


def test_auto_new_again_after_all_objects_deleted(session):
    oid = session.click(30, 30)
    session.delete_objects([oid])
    assert session.effective_mode == Mode.NEW_OBJECT


# --- 4) comma separated prompts ------------------------------------------------


def test_split_labels():
    assert split_labels(" person, car ,tripod ") == ["person", "car", "tripod"]
    assert split_labels("사람，자동차、삼각대; Person\nperson") == ["사람", "자동차", "삼각대", "Person"]
    assert split_labels("  ,, ") == []
    assert split_labels("traffic   light") == ["traffic light"]


def test_detect_many_groups_by_label(session):
    dets = session.engine.detect_many(session.image, ["person", "car"])
    assert [d.label for d in dets] == ["person", "person", "car", "car"]


# --- 5) edit layer ---------------------------------------------------------------


def edited(session):
    session.click(30, 30)  # disc r=10 (best variant)
    return session.editing_frame()


def test_brush_goes_to_layer_and_delete_restores_prompt_mask(session):
    fs = edited(session)
    prompt = fs.mask.copy()
    target = prompt.copy()
    target[0:5, 0:5] = True  # add
    target[30, 30] = False  # remove
    assert session.brush(target)
    fs = session.editing_frame()
    assert fs.edit is not None and fs.edit.added == 25 and fs.edit.removed == 1
    assert np.array_equal(fs.mask, target) and np.array_equal(fs.prompt_mask, prompt)
    assert fs.points  # prompts are kept
    assert session.project.final_mask(session.key)[0, 0]
    assert session.discard_edit()
    assert session.editing_frame().edit is None and np.array_equal(session.editing_frame().mask, prompt)


def test_layer_survives_new_points(session):
    edited(session)
    t = session.editing_frame().mask.copy()
    t[0:5, 0:5] = True
    session.brush(t)
    session.click(60, 40)  # SAM2 re-runs; the hand edit stays on top
    fs = session.editing_frame()
    assert len(fs.points) == 2 and fs.edit is not None and fs.mask[0, 0] and fs.mask[40, 60]


def test_apply_makes_edited_mask_the_main_mask(session):
    edited(session)
    t = session.editing_frame().mask.copy()
    t[0:5, 0:5] = True
    session.brush(t)
    assert session.apply_edit()
    fs = session.editing_frame()
    assert fs.edit is None and fs.points == () and np.array_equal(fs.mask, t) and np.array_equal(fs.base_mask, t)
    session.click(60, 40)  # refines from the applied mask (seed)
    assert session.engine.calls[-1][2] is True and session.editing_frame().mask[0, 0]


def test_brush_back_to_prompt_mask_clears_layer_and_undo(session):
    fs = edited(session)
    prompt = fs.mask.copy()
    t = prompt.copy()
    t[0:5, 0:5] = True
    session.brush(t)
    session.brush(prompt)  # erased back to exactly the prompt mask
    assert session.editing_frame().edit is None
    session.undo()
    assert session.editing_frame().edit is not None


def test_refine_fills_holes_and_removes_specks(session):
    edited(session)
    t = session.editing_frame().mask.copy()
    t[30, 30] = False  # a 1-px hole inside the disc
    t[2, 70] = True  # a 1-px speck far away
    session.brush(t)
    assert session.refine(max_area=20)
    m = session.editing_frame().mask
    assert m[30, 30] and not m[2, 70]
    assert session.editing_frame().edit is None  # refine brought it back to the prompt mask exactly


def test_fill_holes_keeps_big_holes_border_and_the_object():
    m = np.zeros((40, 40), bool)
    m[5:35, 5:35] = True
    m[10:30, 10:30] = False  # big hole (400 px) — a ring, kept
    m[7, 7] = False  # small hole
    out = fill_holes_and_specks(m, 50)
    assert out[7, 7] and not out[20, 20]
    tiny = np.zeros((40, 40), bool)
    tiny[1, 1] = True  # the whole object is smaller than max_area: kept
    assert fill_holes_and_specks(tiny, 50)[1, 1]


def test_layer_is_saved_and_reloaded(session, tmp_path):
    edited(session)
    t = session.editing_frame().mask.copy()
    t[0:5, 0:5] = True
    session.brush(t)
    oid, key = session.editing, session.key
    session.save(force=True)
    p = ProjectStore(session.image_dir, 1024).load(session.keys)
    fs = p.get(oid).frame(key)
    assert fs.edit is not None and fs.edit.added == 25 and np.array_equal(fs.mask, t)
    assert not fs.prompt_mask[0, 0]


def test_mask_is_cached_identity(session):
    edited(session)
    t = session.editing_frame().mask.copy()
    t[0, 0] = True
    session.brush(t)
    fs = session.editing_frame()
    assert fs.mask is fs.mask and not fs.mask.flags.writeable


# --- 1) batch masking --------------------------------------------------------------


def test_batch_indices(session):
    assert session.batch_indices("all") == [0, 1, 2, 3, 4]
    assert session.batch_indices("range", 3, 1) == [1, 2, 3]
    assert session.batch_indices("selected", selected=[4, 0, 4, 9]) == [0, 4]
    assert session.batch_indices("current") == [0]


def test_batch_detect_threshold_and_one_object_per_label(session):
    idx = session.batch_indices("range", 1, 3)
    results = dict(
        batch_detect(session.engine, session.paths, idx, ["person", "car", "none"], 1024, threshold=0.7)
    )
    assert sorted(results) == [1, 2, 3]
    hit = results[1]["person"]
    assert hit.count == 1 and hit.best_score == pytest.approx(0.95)  # the 0.6 one is below threshold
    assert summarize(results[1]) == "person 1 · car 1 · none 0"
    made = session.apply_batch(results)
    assert set(made) == {"person", "car"}  # a label found nowhere creates no Object
    person = session.project.get(made["person"])
    assert person.source == Source.SAM3_BATCH and person.name == "person #1"
    assert sorted(person.frames) == [session.keys[i] for i in idx]
    assert all(fs.status.value == "propagated" for fs in person.frames.values())
    session.undo()
    assert session.project.objects == []


def test_batch_low_threshold_merges_all_instances(session):
    results = dict(batch_detect(session.engine, session.paths, [0], ["person"], 1024, threshold=0.5))
    assert results[0]["person"].count == 2
    m = results[0]["person"].mask
    assert m[10, 10] and m[30, 10]  # both instances in one mask


def test_batch_cancel(session):
    calls = iter([False, True])
    out = list(batch_detect(session.engine, session.paths, [0, 1, 2], ["a"], 1024, 0.5, cancel=lambda: next(calls)))
    assert [i for i, _ in out] == [0]
