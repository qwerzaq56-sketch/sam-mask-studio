"""Sky edges at full resolution (src/core/sky_edges.py) and the export that uses them."""

import cv2
import numpy as np

from src.core.project import FrameState, Project, Source, freeze
from src.core.sky_edges import sky_edges
from src.core.storage import ExportOptions, export_final_masks, full_mask, has_sky, is_sky

SIDE = 400
SKY_RGB = (170, 195, 235)
TREE_RGB = (45, 85, 40)


def scene():
    """A sky over a jagged tree line, sky seen through two leaf gaps near the edge, and a white patch far
    below it. Returns (rgb, true sky)."""
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[:SIDE, :SIDE]
    line = 200 + (18 * np.sin(xx / 6.0)).astype(int)
    sky = yy < line
    sky[line[0, 100] + 8:line[0, 100] + 12, 98:102] = True  # leaf gaps, 8 px below the edge
    sky[line[0, 250] + 8:line[0, 250] + 12, 248:252] = True
    rgb = np.where(sky[..., None], np.array(SKY_RGB), np.array(TREE_RGB)).astype(np.int16)
    rgb[370:380, 300:320] = 245  # white, but far from the sky
    rgb += rng.integers(-6, 7, rgb.shape, dtype=np.int16)
    return np.clip(rgb, 0, 255).astype(np.uint8), sky


def coarse(sky, side=50):
    return cv2.resize(sky.astype(np.uint8), (side, side), interpolation=cv2.INTER_AREA) > 0


def test_edges_follow_the_image_not_the_blocks():
    rgb, truth = scene()
    work = coarse(truth)
    blocky = cv2.resize(work.astype(np.uint8), (SIDE, SIDE), interpolation=cv2.INTER_NEAREST) > 0
    out = sky_edges(work, rgb)
    assert out.shape == truth.shape and out.dtype == bool
    wrong_blocky = (blocky != truth).sum()
    wrong = (out != truth).sum()
    assert wrong < wrong_blocky / 10, (wrong, wrong_blocky)
    assert (out & ~truth).sum() < (blocky & ~truth).sum() / 10  # hardly over the leaves
    assert not out[370:380, 300:320].any()  # white far from the sky stays out


def test_leaf_gaps_near_the_edge_are_found():
    rgb, truth = scene()
    work = cv2.resize(truth.astype(np.uint8), (50, 50), interpolation=cv2.INTER_NEAREST) > 0
    work[25:, :] = False  # the working mask cannot hold 4 px gaps
    yy, xx = np.nonzero(truth & (np.mgrid[:SIDE, :SIDE][0] > 200 + 18 * np.sin(np.mgrid[:SIDE, :SIDE][1] / 6.0)))
    assert len(yy) == 32
    out = sky_edges(work, rgb)
    assert out[yy, xx].mean() > 0.9


def test_degenerate_masks_pass_through():
    rgb, _ = scene()
    assert not sky_edges(np.zeros((50, 50), bool), rgb).any()
    assert sky_edges(np.ones((50, 50), bool), rgb).all()


def test_full_mask_refines_sky_objects_only(tmp_path):
    rgb, truth = scene()
    keys = ["a.jpg"]
    p = Project(keys)
    sky_id = p.add_object("a.jpg", FrameState.from_mask(freeze(coarse(truth))), Source.SPECIAL, "Sky")
    person = np.zeros((50, 50), bool)
    person[40:45, 10:15] = True
    p.add_object("a.jpg", FrameState.from_mask(freeze(person)), Source.SAM2_POINT, "person")
    assert is_sky(p.get(sky_id)) and has_sky(p) and not has_sky(p, [sky_id + 1])
    size = lambda k: (SIDE, SIDE)
    plain = full_mask(p, "a.jpg", size)
    edged = full_mask(p, "a.jpg", size, image=lambda k: rgb)
    assert plain.shape == edged.shape == (SIDE, SIDE)
    assert edged[320:360, 80:120].all() and plain[320:360, 80:120].all()  # the person, scaled up as before
    assert (edged != plain).sum() > 0
    assert (edged[:300] != truth[:300]).sum() < (plain[:300] != truth[:300]).sum() / 5

    img_dir = tmp_path / "images"
    img_dir.mkdir()
    cv2.imencode(".jpg", rgb[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 98])[1].tofile(str(img_dir / "a.jpg"))
    out = tmp_path / "out"
    written = export_final_masks(p, img_dir, size, ExportOptions(out, "{name}.png", sky_edges=True))
    got = cv2.imdecode(np.fromfile(str(written[0]), np.uint8), 0) > 127
    assert (got[:300] != truth[:300]).sum() < (plain[:300] != truth[:300]).sum() / 3  # read back from a JPEG


def test_an_inverted_sky_comes_out_inverted():
    """Applied and inverted (everything but the sky, as 0022's Sky #4): the same edge, the other way round."""
    rgb, truth = scene()
    work = coarse(truth)
    out = sky_edges(work, rgb)
    inv = sky_edges(~work, rgb)
    assert (inv == out).mean() < 0.005
