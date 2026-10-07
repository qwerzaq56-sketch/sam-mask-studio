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
    # color and brightness, And: the sky's color, but only its darker half
    dark_sky = select_range(img, [sky_color], 25, brightness=(0, 178), use_brightness=True, join="and")
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


def test_left_out_colors_the_nearer_wins():
    """BC-P4 b (p98): a pixel near a picked and a left-out color goes to the nearer one (a tie: left out)."""
    from src.core.refine import select_range

    img = np.zeros((1, 5, 3), np.uint8)
    img[0, 0] = (230, 200, 60)  # the leaf color itself
    img[0, 1] = (245, 240, 200)  # whitish: near both (Lab 51 / 21), nearer the cloud
    img[0, 2] = (250, 250, 250)  # cloud
    img[0, 3] = (20, 40, 20)  # dark leaves: near neither
    img[0, 4] = (240, 225, 140)  # pale leaf: near both (Lab 27 / 44), nearer the leaf
    leaf, cloud = (230, 200, 60), (250, 250, 250)
    sel, overlap, _ = select_range(img, [leaf], 60, samples_out=[cloud], tolerance_out=60, with_parts=True)
    assert sel[0].tolist() == [True, False, False, False, True]
    assert overlap[0, 1] and overlap[0, 4] and not overlap[0, 3]
    # a left-out color only claims pixels within its own tolerance
    assert select_range(img, [leaf], 60, samples_out=[cloud], tolerance_out=1)[0].tolist() == [True, True, False, False, True]
    # left-out colors alone: everything they do not claim (the same as Not on them)
    alone = select_range(img, (), 30, samples_out=[cloud], tolerance_out=30)
    assert alone[0].tolist() == (~select_range(img, [cloud], 30))[0].tolist()


def test_not_turns_only_the_picked_colors_around():
    """p99: Not used to turn "not the sky" (left-out sky only) back into "the sky", so Brightness ∧ that was
    the bright sky. Not touches picked colors only; left-out colors leave out either way."""
    from src.core.refine import select_range

    img = np.zeros((1, 3, 3), np.uint8)
    img[0, 0] = (95, 165, 220)  # sky
    img[0, 1] = (225, 195, 95)  # leaf
    img[0, 2] = (20, 40, 20)  # dark leaf
    sky, leaf = (95, 165, 220), (225, 195, 95)
    only_out = select_range(img, (), 30, samples_out=[sky], tolerance_out=30)[0].tolist()
    assert only_out == [False, True, True]
    assert select_range(img, (), 30, samples_out=[sky], tolerance_out=30, not_color=True)[0].tolist() == only_out
    # picked leaf, Not: far from the leaf, and the left-out sky still out
    both = select_range(img, [leaf], 30, samples_out=[sky], tolerance_out=30, not_color=True)[0].tolist()
    assert both == [False, False, True]
    # the color condition alone comes back with the parts; a huge tolerance takes everything
    _, _, color = select_range(img, [leaf], 100, with_parts=True)
    assert color.all()


def test_or_joins_two_ways_of_catching_the_sky():
    """p101: color and brightness catch the same sky two ways and add up (Or, the default); And keeps only what
    both catch; left-out colors come off the result either way."""
    from src.core.refine import select_range

    img = np.zeros((1, 4, 3), np.uint8)
    img[0, 0] = (126, 169, 220)  # blue sky (gray 162): the color catches it, the brightness does not
    img[0, 1] = (245, 245, 245)  # white cloud: the brightness catches it, the color does not
    img[0, 2] = (110, 120, 60)  # leaf: neither
    img[0, 3] = (215, 225, 230)  # pale haze: both
    sky = (126, 169, 220)
    kw = dict(brightness=(205, 255), use_brightness=True)
    assert select_range(img, [sky], 40, **kw)[0].tolist() == [True, True, False, True]
    assert select_range(img, [sky], 40, join="and", **kw)[0].tolist() == [False, False, False, True]
    # the haze left out (it is nearer to its own color than to the sky): off the Or result too
    out = select_range(img, [sky], 40, samples_out=[(215, 225, 230)], tolerance_out=5, **kw)
    assert out[0].tolist() == [True, True, False, False]
    # Not per condition and Swap still apply on top: the inverse mask
    assert (~select_range(img, [sky], 40, **kw))[0].tolist() == [False, False, True, False]



def test_tree_tips_beyond_the_band():
    """p110: rough, not-sky-colored pixels the sky mask painted over beyond the band, near the tree, come out."""
    from src.core.refine import tree_tips

    blue = (170, 195, 235)
    img = np.zeros((200, 120, 3), np.uint8)
    img[:] = blue
    img[140:] = (40, 80, 40)  # the tree
    yy, xx = np.mgrid[:200, :120]
    checker = ((yy + xx) % 2 == 0)[..., None]
    rough = np.where(checker, np.uint8(40), np.uint8(200)).repeat(3, -1)  # dark leaf / pale gray, not A
    img[60:80, 20:40] = rough[60:80, 20:40]  # a tip 60-80 px above the tree: beyond the band, within reach
    img[2:12, 20:40] = rough[2:12, 20:40]  # 128+ px from the tree: out of reach
    img[60:80, 70:90] = (120, 120, 120)  # not sky-colored but smooth: not a tip
    base = np.zeros((200, 120), bool)
    base[:140] = True  # the sky model painted everything above the tree
    st = {"color_samples": (blue,), "color_tol": 7, "color_use": True, "bright_range": (205, 255),
          "bright_use": True, "range_join": "or", "color_band": 30, "color_band_on": True}
    tips = tree_tips(base, img, st, grow=0)
    assert tips[60:80, 20:40].mean() > 0.9
    assert not tips[:30].any() and not tips[110:].any()  # out of reach; the band is By Color's job
    assert not tips[64:76, 74:86].any()  # inside the smooth patch (its rim against the sky is rough)
    grown = tree_tips(base, img, st, grow=1)
    assert (grown >= tips).all() and not (grown & ~base).any()
    assert not tree_tips(base, img, {**st, "color_band_on": False}).any()  # no band: nothing beyond it
