"""People masks from SAM3 detections (src/core/people.py) and the ``person`` command (src/cli.py)."""

import json
from dataclasses import dataclass

import cv2
import numpy as np
import pytest

from src import cli
from src.core.people import people_mask, touching


@dataclass
class Det:
    label: str
    score: float
    mask: np.ndarray


def box(shape, y0, y1, x0, x1):
    m = np.zeros(shape, bool)
    m[y0:y1, x0:x1] = True
    return m


def test_people_pole_and_the_bag_they_carry():
    s = (100, 100)
    dets = [
        Det("person", 0.9, box(s, 10, 50, 40, 60)),
        Det("black pole", 0.8, box(s, 50, 100, 48, 52)),
        Det("bag", 0.6, box(s, 30, 40, 60, 70)),  # worn: touches the person
        Det("bag", 0.7, box(s, 80, 90, 5, 15)),  # left on a bench
        Det("person", 0.2, box(s, 0, 5, 0, 5)),  # too unsure
    ]
    m = people_mask(dets, s, grow=0)
    assert m[20, 50] and m[90, 50] and m[35, 65]
    assert not m[85, 10] and not m[2, 2]
    grown = people_mask(dets, s, grow=2)
    assert grown[20, 38] and not m[20, 38]
    assert not people_mask([], s).any()
    assert not touching(np.zeros(s, bool), box(s, 0, 5, 0, 5)).any()


class FakeEngine:
    device = "fake"
    released = False

    def detect_many(self, image, labels):
        h, w = image.shape[:2]
        out = []
        if "person" in labels:
            out.append(Det("person", 0.9, box((h, w), h // 4, h // 2, w // 3, w // 2)))
        if "black pole" in labels:
            out.append(Det("black pole", 0.8, box((h, w), h // 2, h, w // 3 + 2, w // 3 + 6)))
        return out

    def release(self):
        FakeEngine.released = True


@pytest.fixture
def frames(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_engine", lambda model, device: FakeEngine())
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 7.0)
    model = tmp_path / "sam3.pt"
    model.write_bytes(b"x")
    images = tmp_path / "images" / "cam0"
    images.mkdir(parents=True)
    for i in range(2):
        cv2.imencode(".jpg", np.full((400, 400, 3), 120, np.uint8))[1].tofile(str(images / f"{i:05d}.jpg"))
    return images.parent, model


def read(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), 0) > 127


def test_person_writes_black_people_and_combines_with_the_lens(frames, tmp_path):
    images, model = frames
    out = tmp_path / "people"
    rep = tmp_path / "p.json"
    assert cli.main(["person", str(images), "--out", str(out), "--recursive", "--model", str(model),
                     "--report", str(rep)]) == 0
    m = read(out / "cam0" / "00000.jpg.png")
    assert m.shape == (400, 400) and not m[150, 150] and not m[300, 140] and m[20, 20]  # black = people, pole
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["written"] == 2 and r["frames"]["cam0/00000.jpg"]["found"] == {"person": 1, "black pole": 1}
    assert FakeEngine.released

    lens = tmp_path / "masks"
    assert cli.main(["lens", str(images), "--out", str(lens), "--recursive", "--radius", "80", "--margin", "0",
                     "--and-with", str(out)]) == 0
    both = read(lens / "cam0" / "00000.jpg.png")
    assert not both[150, 150] and not both[5, 5] and both[200, 300]  # person out, corner out, the rest kept


def test_person_waits_for_a_busy_gpu(frames, tmp_path, monkeypatch):
    images, model = frames
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 2.0)
    out = tmp_path / "people"
    with pytest.raises(SystemExit, match="GPU memory"):
        cli.main(["person", str(images), "--out", str(out), "--recursive", "--model", str(model)])
    assert not out.exists()
    assert cli.main(["person", str(images), "--out", str(out), "--recursive", "--model", str(model),
                     "--gpu-anyway", "--invert"]) == 0
    assert read(out / "cam0" / "00000.jpg.png")[150, 150]  # --invert: white = people


def test_keyframe_indices_and_pieces():
    assert cli.keyframe_indices(7, 3) == [0, 3, 6]
    assert cli.keyframe_indices(8, 3) == [0, 3, 6, 7]
    assert cli.keyframe_indices(1, 5) == [0]
    m = box((100, 100), 10, 30, 10, 30) | box((100, 100), 60, 90, 60, 70)
    m[0, 99] = True  # a speck
    pieces = cli.mask_pieces(m)
    assert sorted(pieces) == [1, 2] and not any(p[0, 99] for p in pieces.values())


class ShiftEngine(FakeEngine):
    """A person whose place follows the frame's brightness: each frame's mask is told apart."""
    calls = []
    order = []

    def detect_many(self, image, labels):
        h, w = image.shape[:2]
        x = int(image[0, 0, 0]) // 10  # frames are 10 * i bright
        ShiftEngine.calls.append(x)
        return [Det("person", 0.9, box((h, w), 10, 30, 10 * x, 10 * x + 8))] if "person" in labels else []

    def release(self):
        ShiftEngine.order.append("release")


def test_person_keyframes_propagate_between(tmp_path, monkeypatch):
    from tests.fakes import fake_propagate

    ShiftEngine.calls, ShiftEngine.order = [], []
    monkeypatch.setattr(cli, "_engine", lambda model, device: ShiftEngine())
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 7.0)
    plans = []

    def prop(ckpt, paths, plan, seeds, max_side, device="cuda", **kw):
        ShiftEngine.order.append("sam2")
        plans.append((plan.start, plan.current, plan.end, len(paths), ckpt))
        yield from fake_propagate(ckpt, paths, plan, seeds, max_side, device)

    images = tmp_path / "images"
    for cam, n in (("cam0", 7), ("cam1", 3)):
        (images / cam).mkdir(parents=True)
        for i in range(n):
            cv2.imencode(".jpg", np.full((200, 200, 3), 10 * i, np.uint8))[1].tofile(str(images / cam / f"{i:05d}.jpg"))
    out = tmp_path / "people"
    rep = cli.person_folder(images, out, recursive=True, labels=["person"], attach=[], grow=0, max_side=200,
                            keyframes=3, propagate=prop, log=lambda s: None)
    assert sorted(ShiftEngine.calls) == [0, 0, 2, 3, 6]  # SAM3 on the keyframes only: cam0 0 3 6, cam1 0 2
    assert ShiftEngine.order[0] == "release" and ShiftEngine.order.count("sam2") == 5  # SAM3 gone before SAM2
    assert (0, 0, 3, 7) == plans[0][:4] and plans[1][:3] == (0, 3, 6) and plans[0][4] == str(cli.SAM2_MODEL)
    assert rep["written"] == 10 and rep["keyframe_count"] == 5 and rep["settings"]["keyframes"] == 3
    f1 = rep["frames"]["cam0/00001.jpg"]
    assert f1["from_keyframes"] == 2 and "found" in rep["frames"]["cam0/00003.jpg"]
    m1 = read(out / "cam0" / "00001.jpg.png")  # black = people: keyframe 0's place and keyframe 3's
    assert not m1[20, 4] and not m1[20, 34] and m1[20, 64] and m1[100, 100]
    m3 = read(out / "cam0" / "00003.jpg.png")  # a keyframe keeps its own mask only
    assert not m3[20, 34] and m3[20, 4]


def test_person_keyframes_union_adds_propagation_to_every_frame(tmp_path, monkeypatch):
    from tests.fakes import fake_propagate

    ShiftEngine.calls, ShiftEngine.order = [], []
    monkeypatch.setattr(cli, "_engine", lambda model, device: ShiftEngine())
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 7.0)
    images = tmp_path / "images"
    for cam, n in (("cam0", 7), ("cam1", 3)):
        (images / cam).mkdir(parents=True)
        for i in range(n):
            cv2.imencode(".jpg", np.full((200, 200, 3), 10 * i, np.uint8))[1].tofile(str(images / cam / f"{i:05d}.jpg"))
    out = tmp_path / "people"
    rep = cli.person_folder(images, out, recursive=True, labels=["person"], attach=[], grow=0, max_side=200,
                            keyframes=3, union=True, propagate=fake_propagate, log=lambda s: None)
    assert sorted(ShiftEngine.calls) == [0, 0, 1, 1, 2, 2, 3, 4, 5, 6]  # SAM3 on every frame
    assert rep["written"] == 10 and rep["keyframe_count"] == 5 and rep["settings"]["union"] is True
    f1 = rep["frames"]["cam0/00001.jpg"]
    assert f1["from_keyframes"] == 2 and "found" in f1 and f1["added"] > 0
    m1 = read(out / "cam0" / "00001.jpg.png")  # black = people: its own place (10) and keyframes 0 and 3's
    assert not m1[20, 14] and not m1[20, 4] and not m1[20, 34] and m1[20, 64]
    m3 = read(out / "cam0" / "00003.jpg.png")  # a keyframe keeps its own mask only
    assert not m3[20, 34] and m3[20, 4] and m3[20, 14]


class CartEngine(FakeEngine):
    """A person standing still; a cart touching them in the frames of CART (frames are 10 * i bright)."""
    CART = {1, 2, 3, 4, 5, 6, 11}  # pulled along over 1..6, brushed past in 11 alone
    calls = []

    def detect_many(self, image, labels):
        h, w = image.shape[:2]
        x = int(image[0, 0, 0]) // 10
        CartEngine.calls.append(x)
        out = [Det("person", 0.9, box((h, w), 50, 150, 50, 90))] if "person" in labels else []
        if "cart" in labels and x in CartEngine.CART:
            out.append(Det("cart", 0.8, box((h, w), 100, 150, 95, 140)))  # 5 px from the person
        return out


@pytest.mark.parametrize("union", [False, True])
def test_person_steady_keeps_a_pulled_cart_not_one_brushed_past(tmp_path, monkeypatch, union):
    from tests.fakes import fake_propagate

    CartEngine.calls = []
    monkeypatch.setattr(cli, "_engine", lambda model, device: CartEngine())
    images = tmp_path / "images" / "cam0"
    images.mkdir(parents=True)
    for i in range(13):
        cv2.imencode(".jpg", np.full((200, 200, 3), 10 * i, np.uint8))[1].tofile(str(images / f"{i:05d}.jpg"))
    out = tmp_path / "people"
    rep = cli.person_folder(images.parent, out, recursive=True, labels=["person"], attach=[], steady=["cart"],
                            steady_frames=3, grow=0, max_side=200, log=lambda s: None,
                            **({"keyframes": 4, "union": True, "propagate": fake_propagate} if union else {}))
    assert sorted(CartEngine.calls) == list(range(13))  # SAM3 once a frame, the neighbours ahead kept
    assert rep["settings"]["steady"] == ["cart"] and rep["settings"]["steady_frames"] == 3
    for i in (1, 4, 6):  # 3 or more of the 5 frames around touch: masked (black)
        assert not read(out / "cam0" / f"{i:05d}.jpg.png")[120, 120], i
    m11 = read(out / "cam0" / "00011.jpg.png")  # one frame only: kept as scene (union: keyframes 8, 12 have none)
    assert m11[120, 120] and not m11[100, 70]
    assert rep["frames"]["cam0/00011.jpg"]["found"]["cart not steady"] == 1
    assert "cart" not in rep["frames"]["cam0/00011.jpg"]["found"]


def test_person_union_needs_keyframes(frames, tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["person", str(frames), "--out", str(tmp_path / "o"), "--union"])


def test_person_keyframes_skip_existing_frames(tmp_path, monkeypatch):
    from tests.fakes import fake_propagate

    ShiftEngine.calls, ShiftEngine.order = [], []
    monkeypatch.setattr(cli, "_engine", lambda model, device: ShiftEngine())
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 7.0)
    images = tmp_path / "images"
    images.mkdir()
    for i in range(5):
        cv2.imencode(".jpg", np.full((100, 100, 3), 10 * i, np.uint8))[1].tofile(str(images / f"{i:05d}.jpg"))
    out = tmp_path / "people"
    out.mkdir()
    for i in (1, 2, 3):  # what lies between the keyframes is done already
        cv2.imencode(".png", np.full((100, 100), 255, np.uint8))[1].tofile(str(out / f"{i:05d}.jpg.png"))
    runs = []

    def prop(*a, **kw):
        runs.append(1)
        yield from fake_propagate(*a, **kw)

    rep = cli.person_folder(images, out, labels=["person"], attach=[], max_side=100, keyframes=4,
                            existing="skip", propagate=prop, log=lambda s: None)
    assert rep["written"] == 2 and not runs  # keyframes 0 and 4 written, no SAM2 for frames already there
    assert read(out / "00002.jpg.png").all()  # untouched


def test_person_keyframes_option(frames, tmp_path, monkeypatch):
    from tests.fakes import fake_propagate

    images, model = frames
    monkeypatch.setattr(cli, "_default_propagate", lambda: fake_propagate)
    out = tmp_path / "people"
    rep = tmp_path / "p.json"
    assert cli.main(["person", str(images), "--out", str(out), "--recursive", "--model", str(model),
                     "--keyframes", "5", "--report", str(rep)]) == 0
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["settings"]["keyframes"] == 5 and r["keyframe_count"] == 2 and r["written"] == 2
    assert not read(out / "cam0" / "00001.jpg.png")[150, 150]


def test_split_people_tells_the_photographer_apart():
    from src.core.people import split_people

    s = (100, 100)
    dets = [
        Det("person", 0.9, box(s, 30, 60, 40, 60)),  # holds the pole
        Det("black pole", 0.8, box(s, 60, 100, 48, 52)),
        Det("bag", 0.6, box(s, 40, 50, 60, 66)),  # theirs
        Det("person", 0.9, box(s, 20, 40, 5, 15)),  # someone walking by
        Det("bag", 0.6, box(s, 30, 36, 15, 20)),  # theirs
        Det("hand", 0.7, box(s, 0, 4, 45, 55)),  # fingers on the lens rim
        Det("hand", 0.7, box(s, 25, 30, 7, 12)),  # the passer-by's own hand, covered by them
        Det("hand", 0.7, box(s, 50, 55, 82, 87)),  # a hand no person covers
    ]
    me, others = split_people(dets, s, hands=("hand",))
    assert me[45, 50] and me[80, 50] and me[45, 63] and me[1, 50]
    assert not me[30, 10] and not me[33, 17] and not me[52, 84]
    assert others[30, 10] and others[33, 17] and others[52, 84] and not others[45, 50]
    assert not (me & others).any()
    # no pole found: the person reaching the bottom is the photographer
    me, others = split_people([Det("person", 0.9, box(s, 50, 100, 30, 70)), Det("person", 0.9, box(s, 10, 30, 5, 15))],
                              s, hands=())
    assert me[90, 50] and others[20, 10] and not me[20, 10]
    # as one mask, the same as people_mask
    assert ((me | others) == people_mask([Det("person", 0.9, box(s, 50, 100, 30, 70)),
                                          Det("person", 0.9, box(s, 10, 30, 5, 15))], s, grow=0)).all()


class SplitEngine(FakeEngine):
    asked = []

    def detect_many(self, image, labels):
        SplitEngine.asked.append(tuple(labels))
        h, w = image.shape[:2]
        out = super().detect_many(image, labels)
        if "person" in labels:  # someone far from the pole, top right
            out.append(Det("person", 0.9, box((h, w), h // 8, h // 4, 3 * w // 4, 7 * w // 8)))
        return out


def test_person_split_writes_the_others_apart(frames, tmp_path, monkeypatch):
    images, model = frames
    monkeypatch.setattr(cli, "_engine", lambda model, device: SplitEngine())
    SplitEngine.asked = []
    out, rest, rep = tmp_path / "people", tmp_path / "others", tmp_path / "p.json"
    assert cli.main(["person", str(images), "--out", str(out), "--recursive", "--model", str(model),
                     "--split", str(rest), "--report", str(rep)]) == 0
    assert "hand" in SplitEngine.asked[0]
    m = read(out / "cam0" / "00000.jpg.png")
    o = read(rest / "cam0" / "00000.jpg.png")
    assert not m[150, 150] and not m[300, 140] and m[75, 325]  # the photographer and the pole only
    assert not o[75, 325] and o[150, 150] and o[300, 140]  # black = the one walking by
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["settings"]["split"] == str(rest) and r["settings"]["hands"] == ["hand"]
    assert r["frames"]["cam0/00000.jpg"]["others"] > 0
    with pytest.raises(SystemExit, match="already in"):  # an existing others folder is never overwritten
        cli.main(["person", str(images), "--out", str(tmp_path / "p2"), "--recursive", "--model", str(model),
                  "--split", str(rest)])
    assert cli.main(["person", str(images), "--out", str(tmp_path / "p3"), "--recursive", "--model", str(model),
                     "--split", str(tmp_path / "o3"), "--hands", ""]) == 0
    assert "hand" not in SplitEngine.asked[-1]


def test_person_split_with_keyframes_propagates_both(tmp_path, monkeypatch):
    from tests.fakes import fake_propagate

    class TwoEngine(FakeEngine):
        def detect_many(self, image, labels):
            h, w = image.shape[:2]
            return [Det("person", 0.9, box((h, w), 10, 40, 40, 60)), Det("black pole", 0.8, box((h, w), 40, 100, 48, 52)),
                    Det("person", 0.9, box((h, w), 10, 20, 80, 90))]

    monkeypatch.setattr(cli, "_engine", lambda model, device: TwoEngine())
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 7.0)
    images = tmp_path / "images"
    images.mkdir()
    for i in range(5):
        cv2.imencode(".jpg", np.full((100, 100, 3), 100, np.uint8))[1].tofile(str(images / f"{i:05d}.jpg"))
    out, rest = tmp_path / "people", tmp_path / "others"
    rep = cli.person_folder(images, out, labels=["person", "black pole"], attach=[], grow=0, max_side=100,
                            keyframes=4, propagate=fake_propagate, split=rest, hands=(), log=lambda s: None)
    assert rep["written"] == 5 and rep["frames"]["00002.jpg"]["from_keyframes"] == 2
    m, o = read(out / "00002.jpg.png"), read(rest / "00002.jpg.png")
    assert not m[20, 50] and not m[70, 50] and m[15, 85]  # propagated, still apart
    assert not o[15, 85] and o[20, 50]
