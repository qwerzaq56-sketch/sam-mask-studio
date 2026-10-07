"""Mask clean-up for the edit layer: fill holes, remove specks, grow to the object's edges, select by color range."""

from __future__ import annotations

from typing import Optional

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


def _gmm_log_density(model: np.ndarray, pixels: np.ndarray) -> np.ndarray:
    """Log density of *pixels* (N, 3) under an OpenCV GrabCut color model (1, 65).

    Layout (opencv grabcut.cpp): 5 weights, 5 means (3), 5 covariances (3x3).
    """
    model = model.reshape(-1)
    weights, means, covs = model[:5], model[5:20].reshape(5, 3), model[20:65].reshape(5, 3, 3)
    total = np.zeros(len(pixels))
    for w, mu, cov in zip(weights, means, covs, strict=True):
        if w <= 0:
            continue
        cov = cov + np.eye(3) * 1e-3
        det = np.linalg.det(cov)
        if det <= 0:
            continue
        d = pixels - mu
        maha = np.einsum("ni,ij,nj->n", d, np.linalg.inv(cov), d)
        total += w * np.exp(-0.5 * maha) / np.sqrt((2 * np.pi) ** 3 * det)
    return np.log(total + 1e-300)


def grow_to_edges(
    image: np.ndarray, mask: np.ndarray, max_grow: int, sensitivity: int = 50, iterations: int = 4
) -> np.ndarray:
    """Grow *mask* outward, by at most *max_grow* px, to where the object's colors end.

    GrabCut on a crop around the mask learns the object's and the surrounding
    background's colors: the mask is sure foreground, a band of *max_grow* px
    around it is "probably background" and everything beyond is sure
    background. A band pixel joins the mask when its color is more likely
    object than background; *sensitivity* (0-100, default 50) shifts that
    decision — higher grows further into similar colors, lower stops sooner.
    Only growth connected to the mask is kept, and the mask never shrinks.
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
    band = (cv2.dilate(crop.astype(np.uint8), k) > 0) & ~crop
    gc = np.full(crop.shape, cv2.GC_BGD, np.uint8)
    gc[band] = cv2.GC_PR_BGD
    gc[crop] = cv2.GC_FGD
    if not (gc == cv2.GC_BGD).any():
        return m.copy()  # the band covers the whole crop: nothing to learn the background from
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img, gc, None, bgd, fgd, iterations, cv2.GC_INIT_WITH_MASK)
    # per band pixel: log p(object color) - log p(background color), smoothed so that
    # the decision follows regions rather than single noisy pixels
    px = img[band].astype(np.float64)
    ratio = np.zeros(crop.shape, np.float32)
    ratio[band] = np.clip(_gmm_log_density(fgd, px) - _gmm_log_density(bgd, px), -50, 50)
    ratio = cv2.GaussianBlur(ratio, (0, 0), 1.5)
    threshold = (50 - int(sensitivity)) / 8.0  # 50 -> 0 (equal odds); 100 -> -6.25; 0 -> +6.25
    grown = crop | (band & (ratio > threshold))
    grown = cv2.morphologyEx(grown.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    grown |= crop
    # keep only the pieces that touch the original mask
    n, labels = cv2.connectedComponents(grown.astype(np.uint8), connectivity=8)
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


def grow_mask(mask: np.ndarray, px: int) -> np.ndarray:
    """Every pixel within *px* of the mask (a round dilation)."""
    m = mask.astype(bool)
    if px <= 0 or not m.any():
        return m.copy()
    dist = cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, 5)
    return dist <= px


def shrink_mask(mask: np.ndarray, px: int) -> np.ndarray:
    """The mask without a *px*-wide rim (a round erosion)."""
    m = mask.astype(bool)
    if px <= 0 or not m.any():
        return m.copy()
    # edge padding: where the mask runs off the image, the image border is not an edge of it
    dist = cv2.distanceTransform(np.pad(m, 1, mode="edge").astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    return dist > px


def close_gaps(mask: np.ndarray, gap: int) -> np.ndarray:
    """Fill gaps up to *gap* px wide between parts of the mask, and narrow U-shaped notches cut into it
    (a round morphological closing: grow by half the gap, then shrink back). Only adds: what the mask
    covers stays, and wide bays or anything farther than the gap are left alone."""
    m = mask.astype(bool)
    r = max(1, int(round(gap / 2)))
    if gap <= 0 or not m.any():
        return m.copy()
    # padded so the image border does not count as mask when growing, nor as an edge when shrinking
    pad = r + 2
    grown = grow_mask(np.pad(m, pad), r)
    closed = shrink_mask(grown, r)[pad:-pad, pad:-pad]
    return m | closed



def near_edge(mask: np.ndarray, band: int) -> np.ndarray:
    """Pixels within *band* px of the mask's edge, on either side (everything when *band* <= 0)."""
    m = mask.astype(bool)
    if band <= 0:
        return np.ones(m.shape, bool)
    outside = cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, 5)
    inside = cv2.distanceTransform(np.pad(m, 1, mode="edge").astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    return np.where(m, inside, outside) <= band


def _lab_distance2(lab: np.ndarray, samples) -> Optional[np.ndarray]:
    """Squared Lab distance from every pixel to the nearest of *samples* (RGB); None without samples."""
    if not len(samples):
        return None
    refs = cv2.cvtColor(np.array([samples], np.uint8), cv2.COLOR_RGB2LAB)[0].astype(np.float32)
    refs[:, 0] *= 100 / 255
    d = None
    for ref in refs:
        r = ((lab - ref) ** 2).sum(-1)
        d = r if d is None else np.minimum(d, r)
    return d


def select_range(
    image: np.ndarray,
    samples=(),
    tolerance: float = 20,
    use_color: bool = True,
    brightness: tuple = (0, 255),
    use_brightness: bool = False,
    not_color: bool = False,
    not_brightness: bool = False,
    samples_out=(),
    tolerance_out: Optional[float] = None,
    with_overlap: bool = False,
):
    """Pixels like the picked colors (Photoshop's Color Range, roughly), on either or both of:

    - color: Lab distance (lightness, hue and saturation) within *tolerance* of any of the *samples* (RGB).
      Lightness counts (p78): with it left out, white sky and dark gray-green leaves were both "colorless"
      and 40-50 % of the tree matched a whitish sky at 20.
      *samples_out* (BC-P4 b, p98) are colors to leave out: a pixel within *tolerance_out* of one of them is
      claimed by it. Where a pixel is near both kinds, the **nearer** one wins (a tie: left out), so a leaf pixel
      close to the leaf color is kept even inside a cloud color's tolerance. Left-out colors alone: every pixel
      they do not claim (the same as Not on those colors).
    - brightness: gray level within *brightness* (lo, hi), 0-255.

    *not_color* / *not_brightness* turn that condition around (BC-P4 a): far from every picked color / outside
    the range. All conditions in use must hold, so bright leaves under a bright sky are "brightness, not the sky's
    colors". Neither in use (or color with no samples): nothing is selected.
    *with_overlap*: also return where both kinds of colors claim a pixel (decided by the nearer one).
    """
    img = np.ascontiguousarray(image[..., :3])
    color_on = use_color and (len(samples) > 0 or len(samples_out) > 0)
    overlap = np.zeros(img.shape[:2], bool)
    if not color_on and not use_brightness:
        sel = np.zeros(img.shape[:2], bool)
        return (sel, overlap) if with_overlap else sel
    sel = np.ones(img.shape[:2], bool)
    if color_on:
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
        lab[..., 0] *= 100 / 255  # L* in 0-100 like a*, b* (OpenCV scales it to 0-255)
        d_in, d_out = _lab_distance2(lab, samples), _lab_distance2(lab, samples_out)
        tol_out = tolerance if tolerance_out is None else tolerance_out
        claimed = d_out <= float(tol_out) ** 2 if d_out is not None else np.zeros(sel.shape, bool)
        if d_in is None:
            near = ~claimed
        else:
            near_in = d_in <= float(tolerance) ** 2
            overlap = near_in & claimed
            near = near_in if d_out is None else near_in & ~(claimed & (d_out <= d_in))  # nearer wins; tie: out
        sel &= ~near if not_color else near
    if use_brightness:
        lo, hi = sorted(brightness)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        inside = (gray >= lo) & (gray <= hi)
        sel &= ~inside if not_brightness else inside
    return (sel, overlap) if with_overlap else sel
