"""Mask clean-up used by the edit layer's Refine button."""

from __future__ import annotations

import cv2
import numpy as np


def _small_components(mask: np.ndarray, max_area: int, skip_border: bool, keep_largest: bool = False) -> np.ndarray:
    """Pixels of 8-connected components of *mask* with area <= *max_area*."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n <= 1:
        return np.zeros(mask.shape, bool)
    h, w = mask.shape
    small = np.zeros(n, bool)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    for i in range(1, n):
        if keep_largest and i == largest:
            continue  # never erase the object itself, however small
        x, y, bw, bh, area = stats[i]
        if area > max_area:
            continue
        if skip_border and (x == 0 or y == 0 or x + bw == w or y + bh == h):
            continue  # background touching the image edge is not a hole
        small[i] = True
    return small[labels]


def fill_holes_and_specks(mask: np.ndarray, max_area: int) -> np.ndarray:
    """Fill enclosed holes and drop isolated specks of at most *max_area* pixels.

    Holes are background regions fully surrounded by the mask (not touching
    the image border); specks are small separate pieces of the mask. Larger
    holes (e.g. the inside of a ring) and larger pieces are kept.
    """
    m = mask.astype(bool)
    if max_area <= 0 or not m.any():
        return m.copy()
    out = m | _small_components(~m, max_area, skip_border=True)
    out &= ~_small_components(out, max_area, skip_border=False, keep_largest=True)
    return out
