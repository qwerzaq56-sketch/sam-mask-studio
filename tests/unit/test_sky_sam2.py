"""SAM2 after By Color on the sky (src/core/sky_sam2.py, p111), with the fake SAM (discs at the clicks)."""

import numpy as np

from src.core.sky_sam2 import sam2_tiles
from tests.fakes import FakeEngine


def test_clicks_sure_sky_per_mixed_tile_and_adds_only_where_allowed(monkeypatch):
    monkeypatch.setattr(FakeEngine, "RADII", (60,))  # the piece reaches past the sky's edge
    eng = FakeEngine()
    img = np.zeros((200, 200, 3), np.uint8)
    sky = np.zeros((200, 200), bool)
    sky[:50] = True  # sky over the top two tiles, none in the bottom two
    allowed = np.zeros_like(sky)
    allowed[:70] = True  # e.g. the sky model's mask
    out, clicks = sam2_tiles(eng, img, sky, allowed, tile=100, step=100)
    assert clicks == 2  # one sky piece in each top tile; all-ground tiles are skipped
    pts, box, seed = eng.calls[0]
    assert pts[0].positive and 20 <= pts[0].y <= 30 and box is None and not seed  # innermost point, alone
    assert out[:50].all() and out[60, 50] and not out[80, 50]  # added below the sky, only where allowed
    assert not (out & ~(sky | allowed)).any()


def test_no_click_on_sky_too_thin_to_be_sure_of():
    eng = FakeEngine()
    sky = np.zeros((200, 200), bool)
    sky[:20] = True  # 10 px from its edge at most
    out, clicks = sam2_tiles(eng, np.zeros((200, 200, 3), np.uint8), sky, np.ones_like(sky), tile=100, step=100)
    assert clicks == 0 and (out == sky).all() and not eng.calls


def test_tiles_cover_the_frame_with_the_last_one_flush():
    from src.core.sky_sam2 import _starts

    assert _starts(3840, 1024, 768) == [0, 768, 1536, 2304, 2816]
    assert _starts(500, 1024, 768) == [0]
