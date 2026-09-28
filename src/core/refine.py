"""Mask clean-up for the edit layer: fill holes, remove specks, grow to the object's edges."""

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


def fill_holes(mask: np.ndarray, max_area: int) -> np.ndarray:
    """Fill background regions of at most *max_area* px fully enclosed by the mask."""
    m = mask.astype(bool)
    if max_area <= 0 or not m.any():
        return m.copy()
    return m | _small_components(~m, max_area, skip_border=True)


def remove_specks(mask: np.ndarray, max_area: int) -> np.ndarray:
    """Drop separate pieces of at most *max_area* px (the largest piece always stays)."""
    m = mask.astype(bool)
    if max_area <= 0 or not m.any():
        return m.copy()
    return m & ~_small_components(m, max_area, skip_border=False, keep_largest=True)


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


def grow_to_edges(image: np.ndarray, mask: np.ndarray, max_grow: int, iterations: int = 4) -> np.ndarray:
    """Grow *mask* outward, by at most *max_grow* px, to where the object's colors end.

    GrabCut on a crop around the mask: the mask is sure foreground, a band of
    *max_grow* px around it is "probably background" (GrabCut moves the band
    pixels that look like the object to the foreground) and everything beyond
    is sure background. Only growth connected to the mask is kept, and the
    mask never shrinks.
    """
    m = mask.astype(bool)
    if max_grow <= 0 or not m.any():
        return m.copy()
    h, w = m.shape
    x, y, bw, bh = cv2.boundingRect(m.astype(np.uint8))
    pad = max_grow + 8
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)
    crop = m[y0:y1, x0:x1]
    img = np.ascontiguousarray(image[y0:y1, x0:x1, :3])
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * max_grow + 1, 2 * max_grow + 1))
    band = cv2.dilate(crop.astype(np.uint8), k) > 0
    gc = np.full(crop.shape, cv2.GC_BGD, np.uint8)
    gc[band] = cv2.GC_PR_BGD
    gc[crop] = cv2.GC_FGD
    if not (gc == cv2.GC_BGD).any():
        return m.copy()  # the band covers the whole crop: nothing to learn the background from
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img, gc, None, bgd, fgd, iterations, cv2.GC_INIT_WITH_MASK)
    fg = (gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD) | crop
    # keep only the pieces that touch the original mask
    n, labels = cv2.connectedComponents(fg.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[np.unique(labels[crop])] = True
    keep[0] = False
    out = m.copy()
    out[y0:y1, x0:x1] |= keep[labels]
    return out


def within(region: np.ndarray | None, before: np.ndarray, after: np.ndarray) -> np.ndarray:
    """*after* inside *region*, *before* outside it (the whole of *after* without a region)."""
    if region is None or region.shape != before.shape:
        return after
    return np.where(region, after, before)
