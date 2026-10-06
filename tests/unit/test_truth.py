"""Sky ground truth crops and scores (src/batchmask/truth.py, the 'truth' command)."""

import json

import cv2
import numpy as np
import pytest

from src import cli
from src.batchmask import truth as T


def skyline(h=1200, w=1200, top=500):
    m = np.zeros((h, w), bool)
    m[:top] = True
    for x in range(300, 900, 40):  # tree tops: a jagged edge in the middle
        m[top - 120:top, x:x + 20] = False
    return m


def test_pick_crops_follow_the_skyline_inside_the_circle():
    got = T.pick_crops(skyline(), n=2, size=256, inside=95)
    assert len(got) == 2
    for c in got:
        assert 300 - 256 <= c["x"] <= 900 and 0.2 <= c["sky"] <= 0.8
        assert c["y"] < 500 < c["y"] + 256
    assert abs(got[0]["x"] - got[1]["x"]) >= 256 or abs(got[0]["y"] - got[1]["y"]) >= 256
    assert T.pick_crops(np.zeros((1200, 1200), bool), size=256) == []


def test_compare_and_boundary_f():
    t = skyline()
    r = T.compare(t, t)
    assert r["iou"] == 1 and r["spill"] == 0 and r["edge_f2"] == 1
    worse = t.copy()
    worse[500:506] = True  # 6 px of sky over the scene
    r = T.compare(worse, t)
    assert r["spill"] > 0 and r["missed"] == 0 and r["edge_f2"] < 0.8 and r["edge_f8"] > 0.9


def test_truth_make_and_score(tmp_path, monkeypatch):
    images = tmp_path / "images"
    images.mkdir()
    sky = skyline()
    img = np.where(sky[..., None], np.uint8([230, 180, 120]), np.uint8([40, 90, 40])).astype(np.uint8)
    for n in ("a.jpg", "b.jpg"):
        cv2.imencode(".jpg", img)[1].tofile(str(images / n))
    out = tmp_path / "truth"
    m = T.make_set(images, ["a.jpg", "b.jpg"], out, lambda rgb: sky, per_frame=1, size=256, inside=95, log=lambda s: None)
    assert len(m["crops"]) == 2 and (out / "images" / f"{m['crops'][0]['name']}.jpg").is_file()
    with pytest.raises(FileExistsError):
        T.make_set(images, ["a.jpg"], out, lambda rgb: sky, log=lambda s: None)

    fixed = out / "images_masks"  # what the app's export writes: <stem>.png, white = sky
    fixed.mkdir()
    for c in m["crops"]:
        d = (out / "drafts" / f"{c['name']}.jpg.png").read_bytes()
        (fixed / f"{c['name']}.png").write_bytes(d)
    masks = tmp_path / "pred"
    masks.mkdir()
    worse = sky.copy()
    worse[500:506] = True
    cv2.imencode(".png", sky.astype(np.uint8) * 255)[1].tofile(str(masks / "a.jpg.png"))
    cv2.imencode(".png", worse.astype(np.uint8) * 255)[1].tofile(str(masks / "b.png"))
    rep = tmp_path / "s.json"
    assert cli.main(["truth", "score", str(out), str(masks), "--report", str(rep)]) == 0
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["scored"] == 2 and r["summary"]["iou_min"] < 1 and r["rows"][m["crops"][0]["name"]]["iou"] == 1


def leafy(n=256):
    """Blue sky over dark green leaves with a few sky gaps, gray twigs against a white cloud; the true sky."""
    rng = np.random.default_rng(2)
    img = np.empty((n, n, 3), np.uint8)
    img[:] = (235, 190, 150)  # BGR: blue sky
    img[:60, 140:] = (245, 245, 245)  # a white cloud
    sky = np.ones((n, n), bool)
    sky[128:] = False
    img[128:] = (40, 80, 50)  # leaves
    for y, x in ((170, 40), (200, 120), (180, 200)):  # sky between the leaves
        img[y:y + 8, x:x + 8] = (235, 190, 150)
        sky[y:y + 8, x:x + 8] = True
    img[20:24, 160:220] = (150, 150, 145)  # a gray twig in front of the cloud
    sky[20:24, 160:220] = False
    img = np.clip(img.astype(int) + rng.integers(-6, 7, img.shape), 0, 255).astype(np.uint8)
    return img, sky


def test_matte_sky_follows_colors_not_the_draft():
    img, sky = leafy()
    draft = np.zeros_like(sky)
    draft[:136] = True  # spills 8 px over the trees, misses the gaps, takes the twig
    m = T.matte_sky(img, draft)
    assert (m != sky).mean() < 0.002
    assert not m[22, 190]  # the twig is no sky
    assert m[174, 44]  # a gap is


def test_truth_auto_writes_candidates_once(tmp_path):
    img, sky = leafy()
    d = tmp_path / "set"
    T._write(d / "images" / "a_x0_y0.jpg", img, ".jpg", (cv2.IMWRITE_JPEG_QUALITY, 98))
    draft = np.zeros_like(sky)
    draft[:136] = True
    T._write(d / "drafts" / "a_x0_y0.jpg.png", draft.astype(np.uint8) * 255, ".png")
    (d / "manifest.json").write_text(json.dumps({"kind": "sky", "crops": [{"name": "a_x0_y0"}]}), encoding="utf-8")
    assert cli.main(["truth", "auto", str(d)]) == 0
    got = T._read(d / "candidates" / "a_x0_y0.png")
    assert (got != sky).mean() < 0.01 and (d / "review" / "a_x0_y0.jpg").is_file()
    assert json.loads((d / "manifest.json").read_text(encoding="utf-8"))["candidates"]["candidates"]["crops"]
    with pytest.raises(SystemExit):
        cli.main(["truth", "auto", str(d)])  # never over masks already there
