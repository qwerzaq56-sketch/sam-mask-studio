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
