"""The window-less command line (src/cli.py)."""

import json

import cv2
import numpy as np
import pytest

import src.core.special as special
from src import cli


class FakeSky:
    """Bright pixels are sky (the real model needs its weights)."""

    def __init__(self, path):
        pass

    def probability(self, rgb):
        return (rgb.mean(axis=2) > 120).astype(np.uint8) * 255


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.setattr(special, "SkyModel", FakeSky)
    images = tmp_path / "이미지"
    for cam in ("cam0", "cam1"):
        (images / cam).mkdir(parents=True)
        for i in range(2):
            rgb = np.full((240, 320, 3), (40, 80, 40), np.uint8)
            rgb[:100] = (170, 195, 235)
            cv2.imencode(".jpg", rgb[..., ::-1])[1].tofile(str(images / cam / f"{i:05d}.jpg"))
    model = tmp_path / "skyseg.onnx"
    model.write_bytes(b"x")
    return images, model


def read(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), 0)


def test_sky_writes_full_size_masks_per_camera_folder(scene, tmp_path):
    images, model = scene
    out = tmp_path / "sky_masks"
    report = tmp_path / "r" / "report.json"
    code = cli.main(["sky", str(images), "--out", str(out), "--recursive", "--model", str(model),
                     "--report", str(report)])
    assert code == 0
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.png"))
    assert files == ["cam0/00000.jpg.png", "cam0/00001.jpg.png", "cam1/00000.jpg.png", "cam1/00001.jpg.png"]
    m = read(out / "cam0" / "00000.jpg.png")
    assert m.shape == (240, 320) and m[:90].min() == 255 and m[110:].max() == 0  # white = sky
    r = json.loads(report.read_text(encoding="utf-8"))
    assert r["written"] == 4 and not r["failed"] and r["settings"]["full_resolution_edges"]


def test_sky_never_replaces_masks_unless_asked(scene, tmp_path):
    images, model = scene
    out = tmp_path / "m"
    base = ["sky", str(images / "cam0"), "--out", str(out), "--model", str(model), "--names", "stem", "--invert"]
    assert cli.main(base) == 0
    assert sorted(p.name for p in out.iterdir()) == ["00000.png", "00001.png"]
    assert read(out / "00000.png")[:90].max() == 0  # --invert: black = sky
    (out / "00000.png").write_bytes(b"mine")
    with pytest.raises(SystemExit, match="already in"):
        cli.main(base)
    assert (out / "00000.png").read_bytes() == b"mine"
    assert cli.main(base + ["--skip-existing"]) == 0 and (out / "00000.png").read_bytes() == b"mine"
    assert cli.main(base + ["--overwrite"]) == 0 and read(out / "00000.png") is not None


def test_sky_reports_a_bad_image_and_goes_on(scene, tmp_path):
    images, model = scene
    (images / "cam0" / "00002.jpg").write_bytes(b"not an image")
    out = tmp_path / "m"
    assert cli.main(["sky", str(images / "cam0"), "--out", str(out), "--model", str(model)]) == 1
    assert len(list(out.iterdir())) == 2


# --- lens -----------------------------------------------------------------------------------------------------------


def fisheye(path, center, radius, size=(300, 300)):
    """A lit disc (noisy scene colours) on black, like a fisheye frame."""
    rng = np.random.default_rng(len(str(path)))
    img = rng.integers(60, 220, (size[0], size[1], 3), dtype=np.uint8)
    yy, xx = np.mgrid[:size[0], :size[1]]
    img[(xx + 0.5 - center[0]) ** 2 + (yy + 0.5 - center[1]) ** 2 >= radius ** 2] = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", img)[1].tofile(str(path))


@pytest.fixture
def rig(tmp_path):
    images = tmp_path / "images"
    for i in range(3):
        fisheye(images / "cam0" / f"{i:05d}.png", (150, 140), 120)  # 10 px above the middle
        fisheye(images / "cam1" / f"{i:05d}.png", (155, 150), 110)
    return images


def test_lens_finds_each_cameras_circle_and_pulls_it_in(rig, tmp_path):
    out = tmp_path / "masks"
    report = tmp_path / "lens.json"
    assert cli.main(["lens", str(rig), "--out", str(out), "--recursive", "--margin", "0",
                     "--report", str(report)]) == 0
    r = json.loads(report.read_text(encoding="utf-8"))
    c0, c1 = r["circles"]["cam0"], r["circles"]["cam1"]
    assert abs(c0["radius"] - 80) < 2 and abs(c0["cy"] + 6.7) < 1.5  # 120 of 150 px; 10 px up
    assert abs(c1["radius"] - 73.3) < 2 and abs(c1["cx"] - 3.3) < 1.5
    m0 = read(out / "cam0" / "00000.png.png") > 127
    assert m0[140, 150] and m0[140, 255] and not m0[140, 275] and not m0[5, 5]  # white = inside
    m1 = read(out / "cam1" / "00000.png.png") > 127
    assert not m1[150, 270]  # cam1's smaller circle
    assert r["written"] == 6

    pulled = tmp_path / "pulled"
    assert cli.main(["lens", str(rig), "--out", str(pulled), "--recursive"]) == 0  # default margin 2 %
    p0 = read(pulled / "cam0" / "00000.png.png") > 127
    assert p0.sum() < m0.sum() and not p0[140, 267]


def test_lens_given_circle_inverted_and_combined_with_people(rig, tmp_path):
    people = tmp_path / "people"
    keep = np.full((300, 300), 255, np.uint8)
    keep[100:150, 100:150] = 0  # a person: ignored
    people.mkdir()
    cv2.imencode(".png", keep)[1].tofile(str(people / "00000.png.png"))
    out = tmp_path / "masks"
    assert cli.main(["lens", str(rig / "cam0"), "--out", str(out), "--and-with", str(people),
                     "--radius", "50", "--margin", "0"]) == 0
    m = read(out / "00000.png.png") > 127
    assert not m[120, 120] and m[160, 160] and not m[150, 230]  # person out; radius 75 px from the middle
    assert (read(out / "00001.png.png") > 127)[120, 120]  # no people mask there: the lens edge alone
    inv = tmp_path / "inv"
    assert cli.main(["lens", str(rig / "cam0"), "--out", str(inv), "--invert", "--radius", "50", "--margin", "0"]) == 0
    assert (read(inv / "00000.png.png") > 127)[5, 5]


def test_lens_without_a_circle_fails_those_images(tmp_path):
    flat = tmp_path / "flat"
    flat.mkdir()
    cv2.imencode(".png", np.full((100, 120, 3), 128, np.uint8))[1].tofile(str(flat / "a.png"))
    out = tmp_path / "m"
    assert cli.main(["lens", str(flat), "--out", str(out)]) == 1
    assert not out.exists() or not any(out.iterdir())
