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
