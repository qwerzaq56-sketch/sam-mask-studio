"""By Color's filter: picked colors and / or a brightness range (src/core/refine.select_range).
The Auto ways (split_by_color) went in v0.4-p97 (BC-P5)."""

import numpy as np


def skyline(h=200, w=200):
    """Bright blue sky above a wavy dark-green tree line, with sky gaps in the leaves; the true sky mask."""
    img = np.zeros((h, w, 3), np.uint8)
    ys = (100 + 15 * np.sin(np.arange(w) / 9)).astype(int)
    sky = np.arange(h)[:, None] < ys[None, :]
    sky[130:136, 40:46] = True  # a gap in the leaves, near the line
    img[sky] = (150, 190, 240)
    img[~sky] = (30, 70, 25)
    rng = np.random.default_rng(1)
    img = np.clip(img.astype(int) + rng.integers(-12, 13, img.shape), 0, 255).astype(np.uint8)
    return img, sky


def test_select_range_by_picked_colors_and_brightness():
    from src.core.refine import select_range

    img, sky = skyline()  # RGB-ish: (150, 190, 240) sky, (30, 70, 25) trees, noise ±12
    sky_color, tree_color = (150, 190, 240), (30, 70, 25)
    assert (select_range(img, [sky_color], 25) == sky).mean() > 0.99
    assert (select_range(img, [tree_color], 25) == ~sky).mean() > 0.99
    both = select_range(img, [sky_color, tree_color], 25)
    assert both.mean() > 0.99
    bright = select_range(img, (), use_color=False, brightness=(120, 255), use_brightness=True)
    assert (bright == sky).mean() > 0.99
    # color and brightness together: the sky's color, but only its darker half
    dark_sky = select_range(img, [sky_color], 25, brightness=(0, 178), use_brightness=True)
    assert dark_sky.sum() < sky.sum() * 0.8 and not (dark_sky & ~sky).any()
    assert not select_range(img).any()  # nothing picked, no range: nothing
    # p78: lightness counts: a white sky does not take a dark gray leaf
    gray = np.zeros((2, 2, 3), np.uint8)
    gray[0] = 235
    gray[1] = (60, 66, 58)
    assert (select_range(gray, [(235, 235, 235)], 30) == [[True, True], [False, False]]).all()


def test_near_edge_band():
    from src.core.refine import near_edge

    m = np.zeros((40, 40), bool)
    m[:20] = True
    band = near_edge(m, 5)
    assert band[15:25].all() and not band[:13].any() and not band[27:].any()
    assert near_edge(m, 0).all()  # 0: everywhere
