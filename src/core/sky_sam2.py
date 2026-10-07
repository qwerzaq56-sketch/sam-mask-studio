"""SAM2 on a sky mask after By Color (p111): the sky pieces By Color left out because their colors are not in the
preset (deep blue, darker clouds) come back as SAM2 sees them.

The way the app's Ctrl+click works (a point on its own, the best-scored piece), placed without a person: the frame
in full-resolution tiles; in each tile with both sky and not-sky, every sky piece deep enough to be sure of gets one
click at its innermost point. SAM2 there takes the whole sky it belongs to; what it adds is kept only where the
caller allows (inside the sky model's mask, not where the tree tips were taken out).

Measured on the 0022 sky truth (12 crops, after p110): missed 1.13 -> 0.34 %, spill 0.85 -> 0.92 %; about 14 clicks
and 1.6 s a 3840² frame on an RTX 2060 SUPER (sam2.1 hiera tiny, 0.6 GB), about 10x that on the CPU. The same click
on the whole frame at the app's 1024 px working size: spill 0.61 % at the edge alone (a coarse edge), not used.
"""

from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np

from src.core.project import Point

SAM2_TILES = {"tile": 1024, "step": 768, "min_depth": 15, "max_per": 4}


def _starts(size: int, tile: int, step: int) -> List[int]:
    """Tile origins along one side: every *step*, the last one flush with the end."""
    if size <= tile:
        return [0]
    out = list(range(0, size - tile + 1, step))
    if out[-1] != size - tile:
        out.append(size - tile)
    return out


def sam2_tiles(engine, image: np.ndarray, sky: np.ndarray, allowed: np.ndarray, tile: int = 1024, step: int = 768,
               min_depth: float = 15, max_per: int = 4) -> Tuple[np.ndarray, int]:
    """(*sky* with what SAM2 adds inside *allowed*, clicks). *engine*: ``set_image(rgb)`` and
    ``predict(points, box, seed)`` -> Variants, best first (src/engine/inference.py). In each *tile* (every *step*
    px) whose sky is 1-99 %, the *max_per* largest sky pieces with a point at least *min_depth* px from their edge
    each get a positive click there."""
    sky = sky.astype(bool)
    h, w = sky.shape
    add = np.zeros_like(sky)
    clicks = 0
    for y0 in _starts(h, tile, step):
        for x0 in _starts(w, tile, step):
            sl = (slice(y0, y0 + tile), slice(x0, x0 + tile))
            part = sky[sl]
            if not 0.01 <= part.mean() <= 0.99:
                continue
            n, lbl, stats, _ = cv2.connectedComponentsWithStats(part.astype(np.uint8), connectivity=8)
            points = []
            for i in (np.argsort(-stats[1:, cv2.CC_STAT_AREA])[:max_per] + 1):
                inner = cv2.distanceTransform(np.pad(lbl == i, 1).astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
                if inner.max() >= min_depth:
                    y, x = np.unravel_index(inner.argmax(), inner.shape)
                    points.append(Point(float(x), float(y), True))
            if not points:
                continue
            engine.set_image(np.ascontiguousarray(image[sl][..., :3]))
            for p in points:
                variants = engine.predict((p,), None, None)
                if variants:
                    add[sl] |= np.asarray(variants[0].mask, bool)
                clicks += 1
    return sky | (add & allowed.astype(bool)), clicks
