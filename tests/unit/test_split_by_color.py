"""By Color auto tool: the mask's edge redrawn by brightness or color (src/core/refine.split_by_color)."""

import numpy as np
import pytest

from src.core.refine import near_edge, split_by_color


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


def rough(sky):
    """A rough draft: a straight line through the waves."""
    m = np.zeros_like(sky)
    m[:100] = True
    return m


@pytest.mark.parametrize("basis", ["color", "brightness"])
def test_edge_follows_the_image(basis):
    img, sky = skyline()
    out = split_by_color(img, rough(sky), basis, 50, 40)
    assert (out != sky).mean() < 0.002
    assert out[132, 42]  # the gap in the leaves is sky


def test_only_near_the_edge_changes():
    img, sky = skyline()
    draft = rough(sky)
    draft[150:190, 150:190] = True  # a wrong piece: its rim is redone, its middle is too far
    out = split_by_color(img, draft, "color", 50, 10)
    changed = out != draft
    assert not (changed & ~near_edge(draft, 10)).any()
    assert out[170, 170] and not out[152, 170]


def test_balance_moves_the_line():
    img, sky = skyline()
    img[sky] = img[sky] // 2 + 60  # a hazy sky, closer to the trees
    for basis in ("brightness", "color"):
        a = split_by_color(img, rough(sky), basis, 20, 40).sum()
        b = split_by_color(img, rough(sky), basis, 80, 40).sum()
        assert a <= b


def test_dark_mask_takes_the_dark_side():
    img, sky = skyline()
    out = split_by_color(img, ~rough(sky), "brightness", 50, 40)  # the trees as the mask
    assert (out != ~sky).mean() < 0.002


def test_nothing_to_learn_from():
    img, _ = skyline()
    m = np.zeros(img.shape[:2], bool)
    assert not split_by_color(img, m).any()
    with pytest.raises(ValueError):
        split_by_color(img, np.eye(200, dtype=bool), "hue")


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


def test_take_add_or_remove_only():
    from src.core.refine import take

    base = np.array([True, True, False, False])
    result = np.array([True, False, True, False])
    assert take(base, result, "both").tolist() == result.tolist()
    assert take(base, result, "add").tolist() == [True, True, True, False]
    assert take(base, result, "remove").tolist() == [True, False, False, False]
    with pytest.raises(ValueError):
        take(base, result, "flip")
