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
