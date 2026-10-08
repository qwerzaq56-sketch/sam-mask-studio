"""Export masks as bars (plan Export 9): per bar Invert, per Object ⇆ (flipped), saved with the scene."""
import cv2
import numpy as np

from src.core.project import FrameState, MaskBar, Project, Source, freeze
from src.core.storage import ExportOptions, ProjectStore, check_export, export_final_masks, full_mask


def rows(r, shape=(10, 20)):
    a = np.zeros(shape, bool)
    a[r, :] = True
    return freeze(a)


def two_objects():
    """person: rows 0-2 on both images; lens: rows 7-9 on 001 only."""
    p = Project(["001.jpg", "002.jpg"])
    person = p.add_object("001.jpg", FrameState.from_mask(rows(slice(0, 3))), Source.SAM2_POINT)
    p.set_frame(person, "002.jpg", FrameState.from_mask(rows(slice(0, 3))))
    lens = p.add_object("001.jpg", FrameState.from_mask(rows(slice(7, 10))), Source.SAM2_POINT)
    return p, person, lens


def read(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), 0)


def test_flipped_object_is_the_outside_of_it_then_the_union():
    p, person, lens = two_objects()
    size = lambda k: (10, 20)
    # the intermediates, made apart from the code under test
    person_m = np.zeros((10, 20), bool)
    person_m[0:3] = True
    lens_m = np.zeros((10, 20), bool)
    lens_m[7:10] = True
    lens_outside = ~lens_m
    want_001 = person_m | lens_outside  # rows 0-6 on, 7-9 off
    got = full_mask(p, "001.jpg", size, [person, lens], flipped=[lens])
    assert np.array_equal(got, want_001)
    assert got[:7].all() and not got[7:].any()
    # 002: the lens has no mask there, so all of 002 is outside it
    assert full_mask(p, "002.jpg", size, [person, lens], flipped=[lens]).all()
    # not flipped: the plain union, as before
    assert np.array_equal(full_mask(p, "001.jpg", size, [person, lens]), person_m | lens_m)
    # a flipped id that is not in the bar does nothing
    assert np.array_equal(full_mask(p, "001.jpg", size, [person], flipped=[lens]), person_m)
    # working resolution (the check) agrees
    assert np.array_equal(p.final_mask("001.jpg", [person, lens], [lens]), want_001)
    assert p.final_mask("002.jpg", [person, lens], [lens]).all()
    assert p.keys_with_masks(ids=[lens], flipped=[lens]) == ["001.jpg", "002.jpg"]
    assert p.keys_with_masks(ids=[lens]) == ["001.jpg"]


def test_export_writes_the_bar_invert_after_the_flip(tmp_path):
    p, person, lens = two_objects()
    out = tmp_path / "masks"
    written = export_final_masks(p, tmp_path, lambda k: (20, 40),
                                 ExportOptions(out, "{name}.png", invert=True, object_ids=[person, lens],
                                               flipped=[lens]))
    assert [w.name for w in written] == ["001.jpg.png", "002.jpg.png"]
    a = read(written[0])  # rows 0-6 (x2 up) are the mask -> black after Invert; the lens rows white
    assert a.shape == (20, 40) and a[:14].max() == 0 and a[14:].min() == 255
    assert read(written[1]).max() == 0  # all mask -> all black
    # the check counts the same
    c = check_export(p, "{name}.png", [person, lens], [lens])
    assert c.with_mask == ["001.jpg", "002.jpg"] and not c.without_mask
    # an Object that covers the whole image, flipped: an empty mask
    full = p.add_object("001.jpg", FrameState.from_mask(rows(slice(0, 10))), Source.SAM2_POINT)
    c = check_export(p, "{name}.png", [full], [full])
    assert c.empty == ["001.jpg"] and c.with_mask == ["002.jpg"]


def test_bars_default_from_the_old_sets_and_save_with_the_scene(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    p, person, lens = two_objects()
    p.set_mask_set("people", [person])
    assert p.bars_or_default() == (MaskBar(), MaskBar("people", (person,), on=False))
    assert not p.set_mask_bars(p.bars_or_default())  # nothing new
    bars = (MaskBar("", None, True), MaskBar("lens", (person, lens), False, (lens,), True))
    assert p.set_mask_bars(bars)
    store = ProjectStore(images, 1024)
    store.save(p)
    q = store.load(["001.jpg", "002.jpg"])
    assert q.mask_bars == bars
    p.undo()
    assert p.mask_bars == () and p.bars_or_default()[1].name == "people"
