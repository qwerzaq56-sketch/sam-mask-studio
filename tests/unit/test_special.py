"""Special Objects' mask makers (src/core/special.py): lens edge, image circle detection, sky."""

import cv2
import numpy as np

from src.core.special import (
    LENS_EDGE,
    SKY,
    Special,
    detect_lens_circle,
    lens_circle,
    lens_edge_mask,
    refine_sky,
    sky_mask,
    stretch_to_uint8,
)


def test_settings_round_trip_and_defaults():
    sp = Special.new(SKY).with_params(threshold=70, nonsense=3)
    assert sp.get("threshold") == 70 and sp.get("refine") == 1 and "nonsense" not in dict(sp.params)
    sp = sp.with_keys(["b", "a"], order=["a", "b", "c"])
    assert sp.keys == ("a", "b")
    assert Special.from_json(sp.to_json()) == sp
    assert Special.from_json({"kind": "nope"}) is None and Special.from_json(None) is None


def test_lens_edge_is_outside_the_circle():
    sp = Special.new(LENS_EDGE)
    m = lens_edge_mask(100, 200, sp)
    assert m[0, 0] and m[50, 10] and not m[50, 100] and not m[5, 100]  # the circle touches top and bottom
    smaller = lens_edge_mask(100, 200, sp.with_params(radius=50))
    assert smaller[5, 100] and not smaller[50, 100]
    moved = lens_edge_mask(100, 200, sp.with_params(cx=50))  # right by half the radius
    assert moved[50, 60] and not moved[50, 140]


def test_the_image_circle_is_detected():
    h, w = 300, 400
    truth = Special.new(LENS_EDGE).with_params(radius=90, cx=10, cy=-5)
    rng = np.random.default_rng(1)
    imgs = []
    for _ in range(3):
        img = rng.integers(40, 255, (h, w, 3), dtype=np.uint8)
        img[lens_edge_mask(h, w, truth)] = rng.integers(0, 8)  # the black corners
        imgs.append(img)
    found = detect_lens_circle(imgs)
    assert found is not None
    assert abs(found["radius"] - 90) < 1.5 and abs(found["cx"] - 10) < 1.5 and abs(found["cy"] + 5) < 1.5
    assert detect_lens_circle([np.full((h, w, 3), 128, np.uint8)]) is None  # no black edge: nothing to find


def _scene(h=240, w=320):
    yy, xx = np.mgrid[0:h, 0:w]
    sky = yy < 100 + 30 * np.sin(xx / 19.0) + (xx % 40 < 10) * 25
    img = np.zeros((h, w, 3), np.uint8)
    img[sky] = (120, 170, 235)
    img[~sky] = (90, 80, 70)
    img = np.clip(img + np.random.default_rng(0).normal(0, 8, img.shape), 0, 255).astype(np.uint8)
    coarse = cv2.resize(cv2.resize(sky.astype(np.float32), (10, 8), interpolation=cv2.INTER_AREA), (w, h))
    return sky, img, (coarse * 255).astype(np.uint8)


def test_refinement_snaps_the_sky_to_the_image():
    sky, img, prob = _scene()
    sp = Special.new(SKY)

    def iou(m):
        return (m & sky).sum() / (m | sky).sum()

    raw, refined = iou(sky_mask(prob, sp)), iou(sky_mask(refine_sky(prob, img), sp))
    assert refined > 0.98 and refined > raw + 0.02


def test_sky_settings():
    prob = np.zeros((60, 80), np.uint8)
    prob[:20] = 200  # sky at the top
    prob[40:50, 30:40] = 200  # a sky-like window below
    sp = Special.new(SKY)
    m = sky_mask(prob, sp)
    assert m[5, 5] and m[45, 35]
    assert not sky_mask(prob, sp.with_params(top_only=1))[45, 35]
    assert not sky_mask(prob, sp.with_params(threshold=90)).any()
    assert sky_mask(prob, sp.with_params(grow=3))[21, 5] and not sky_mask(prob, sp.with_params(grow=-3))[18, 5]


def test_network_output_is_stretched_and_sized():
    out = np.linspace(-2, 3, 320 * 320, dtype=np.float32).reshape(1, 1, 320, 320)
    m = stretch_to_uint8(out.squeeze(), 90, 160)
    assert m.shape == (90, 160) and m.min() <= 1 and m.max() >= 254


def test_close_gaps_fills_narrow_gaps_and_notches_only():
    from src.core.refine import close_gaps

    m = np.zeros((60, 120), bool)
    m[20:40, 10:50] = True
    m[20:40, 56:100] = True  # a 6 px gap between two parts
    m[20:32, 70:74] = False  # a 4 px wide notch cut in from the top
    m[20:40, 100:120] = False
    out = close_gaps(m, 8)
    assert out[30, 52] and out[25, 72]  # the gap and the notch are filled
    assert (out | ~m).all()  # nothing taken away
    assert not out[10, 30] and not out[50, 30]  # not grown outward
    assert not close_gaps(m, 4)[30, 52]  # a 6 px gap is wider than 4
    edge = np.zeros((40, 40), bool)
    edge[:, :10] = True
    assert (close_gaps(edge, 10) == edge).all()  # the image border is no reason to fill


def test_black_is_never_sky():
    from src.core.special import sky_maps

    class Everything:  # a network that calls every pixel sky
        def probability(self, rgb):
            p = np.full(rgb.shape[:2], 255, np.uint8)
            p[0, 0] = 0
            return p

    rgb = np.full((80, 80, 3), 180, np.uint8)
    rgb[:, :15] = 3  # a fisheye's black edge
    prob, refined = sky_maps(Everything(), rgb)
    assert prob[40, 5] == 0 and refined[40, 5] == 0 and prob[40, 50] == 255

