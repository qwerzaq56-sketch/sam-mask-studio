"""Sky edges at the image's full resolution.

A sky mask is made and edited at the working resolution (1024 px), where a tree's crown is a few
pixels of stairs: written as is, the sky reaches over the outer leaves and its holes between them
are blobs. Here the edge is decided again pixel by pixel on the full-resolution image:

- a colour model of *this* image: sky colours from just inside the working mask's edge, the rest from
  just outside it (a 32³ RGB histogram each), so clouds, blue sky, foliage and trunks all count;
- deep inside the working mask stays sky, and pixels further than *reach* from it are never sky (white
  flowers, a white shirt below the trees are not looked at);
- in between, a pixel is sky when its colour is sky's with at least *threshold* odds. That also finds
  the sky seen through the leaves near the edge, which the working mask could not hold.

Pure numpy / OpenCV, no model: it works on the mask as edited, of any Object (meant for the sky). Both
sides are treated alike, so an inverted sky (everything but the sky) comes out the same, inverted.
"""

from __future__ import annotations

import cv2
import numpy as np

BINS = 32  # per channel


def _dist(mask: np.ndarray) -> np.ndarray:
    """Distance (px) from each pixel of *mask* to the nearest pixel outside it; 0 outside."""
    return cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 5)


def sky_edges(coarse: np.ndarray, rgb: np.ndarray, band: int = 0, reach: int = 0,
              threshold: float = 0.6, dark: int = 32) -> np.ndarray:
    """The sky mask *coarse* (bool, any size) with its edge decided again on *rgb* (uint8 H x W x 3, the
    full-resolution image): bool H x W.

    *band*: how far (px) from the working edge the colours are re-decided inside the sky, 0 = 1/96 of the
    longer side (40 px on 3840). *reach*: how far outside it sky may be found, 0 = 1/19 (200 px).
    *threshold*: the odds a pixel's colour needs to join the mask's side (0.5 = even; higher keeps leaves
    out of a sky). Near-black pixels (every channel below *dark*: a fisheye's corners and rim) keep the
    working mask's answer: their colour says nothing."""
    h, w = rgb.shape[:2]
    side = max(h, w)
    band = band or max(2, side // 96)
    reach = reach or max(band, side // 19)
    m = coarse.astype(np.uint8)
    if m.shape != (h, w):
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
    sky = m > 0
    if not sky.any() or sky.all():
        return sky
    inside = _dist(sky)  # depth into the sky
    outside = _dist(~sky)  # distance to the sky
    lit = rgb.max(axis=2) >= dark
    # the colour model, from the pixels near the edge (3 bands deep) the working mask is sure about
    sure_sky = (inside > band) & (inside <= 3 * band) & lit
    sure_not = (outside > band) & (outside <= 3 * band) & lit
    if not sure_sky.any() or not sure_not.any():
        return sky
    q = (rgb // (256 // BINS)).astype(np.int32)
    idx = (q[..., 0] * BINS + q[..., 1]) * BINS + q[..., 2]
    hist = []
    for sample in (sure_sky, sure_not):
        hc = np.bincount(idx[sample], minlength=BINS ** 3).astype(np.float32).reshape(BINS, BINS * BINS)
        hc = cv2.GaussianBlur(hc, (0, 0), 0.8).ravel()  # neighbouring colours, crudely
        hist.append(hc / max(float(hc.sum()), 1.0))
    odds = (hist[0] / (hist[0] + hist[1] + 1e-9))[idx]
    luma = rgb.mean(axis=2)
    if luma[sure_sky].mean() < luma[sure_not].mean():  # an inverted sky: the bright side is outside
        threshold = 1.0 - threshold + 1e-6  # still the sky that must earn its pixels
    out = inside > band
    look = ~out & (outside <= reach) & lit
    out[look] = odds[look] >= threshold
    out[~lit] = sky[~lit]
    return out

