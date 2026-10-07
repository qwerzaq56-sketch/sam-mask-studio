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
    with_parts: bool = False,
    join: str = "or",
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
    the range. Not touches the picked colors only: left-out colors leave out either way, and with no picked
    colors Not does nothing.
    *join* (p101): ``"or"`` = A is what **either** condition catches (two ways of catching the same thing, e.g.
    the sky by its blue and the clouds by their brightness, add up); ``"and"`` = both must hold (bright leaves
    = "brightness, Not the sky's colors"). The left-out colors are taken out of that at the end, so "brightness
    less the sky's colors" works either way. Nothing in use (and nothing left out): nothing is selected.
    *with_parts*: return ``(selection, overlap, color)``: also where both kinds of colors claim a pixel (decided
    by the nearer one) and what the color condition alone takes (None when it is not in use), so a condition that
    takes everything or nothing can be pointed out (p99).
    """
    img = np.ascontiguousarray(image[..., :3])
    shape = img.shape[:2]
    color_on = use_color and (len(samples) > 0 or len(samples_out) > 0)
    overlap = np.zeros(shape, bool)
    near = None  # what the color condition alone takes (reported, p99)
    conds = []  # the conditions in use, joined by *join*
    out = None  # what the left-out colors take out at the end
    if color_on:
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
        lab[..., 0] *= 100 / 255  # L* in 0-100 like a*, b* (OpenCV scales it to 0-255)
        d_in, d_out = _lab_distance2(lab, samples), _lab_distance2(lab, samples_out)
        tol_out = tolerance if tolerance_out is None else tolerance_out
        claimed = d_out <= float(tol_out) ** 2 if d_out is not None else None
        if d_in is not None:
            near_in = d_in <= float(tolerance) ** 2
            if not_color:  # Not turns the picked colors around only; left-out colors still leave out (p99)
                near, out = ~near_in, claimed
            else:
                near = near_in
                if claimed is not None:  # near both kinds: the nearer one wins; a tie: left out
                    overlap = near_in & claimed
                    out = claimed & ~(near_in & (d_in < d_out))
            conds.append(near)
        elif claimed is not None:  # left-out colors only: everything they do not claim
            near, out = ~claimed, claimed
    if use_brightness:
        lo, hi = sorted(brightness)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        inside = (gray >= lo) & (gray <= hi)
        conds.append(~inside if not_brightness else inside)
    if conds:
        sel = conds[0].copy()
        for c in conds[1:]:
            sel = (sel & c) if join == "and" else (sel | c)
    else:  # left-out colors alone: everything else; nothing in use: nothing
        sel = np.full(shape, out is not None)
    if out is not None:
        sel &= ~out
    return (sel, overlap, near) if with_parts else sel


# --- By Color as a whole (the app's auto tool and the ``sky --color-preset`` command, p109) ------------------

RANGE_KEYS = ("color_samples", "color_tol", "color_use", "color_not", "color_samples_out", "color_tol_out",
              "bright_range", "bright_use", "bright_not", "range_join", "color_invert")


def range_selection(image: np.ndarray, settings: dict, with_parts: bool = False):
    """By Color's A: the picked colors (less the left-out ones, the nearer wins) and / or the brightness range,
    each maybe turned around (Not), joined by Or (default) / And (p101), less the left-out colors, then Swap.
    *with_parts*: ``(A, overlap, color)``, see :func:`select_range`."""
    sel, overlap, color = select_range(image, settings.get("color_samples", ()), settings.get("color_tol", 20),
                                settings.get("color_use", True), settings.get("bright_range", (0, 255)),
                                settings.get("bright_use", False), settings.get("color_not", False),
                                settings.get("bright_not", False), settings.get("color_samples_out", ()),
                                settings.get("color_tol_out"), with_parts=True,
                                join=settings.get("range_join", "or"))
    if settings.get("color_invert", False):  # Swap A / B
        sel = ~sel
    return (sel, overlap, color) if with_parts else sel


def apply_by_color(base: np.ndarray, image: np.ndarray, settings: dict, sel: Optional[np.ndarray] = None) -> np.ndarray:
    """By Color on *base* (*image* RGB, same size): A = the selection, B = the rest, both only inside the Near edge
    area (``color_band`` px around *base*'s edge, or anywhere); Changes: Add puts A in, Remove takes B out, both
    does both. *sel*: A when it is already worked out (:func:`range_selection`)."""
    band = settings.get("color_band", 30) if settings.get("color_band_on", True) else 0  # 0: anywhere
    if sel is None:
        sel = range_selection(image, settings)
    area = near_edge(base, band)
    a, b = sel & area, ~sel & area
    action = settings.get("color_action", "both")
    if action == "add":
        return base | a
    if action == "remove":
        return base & ~b
    return (base | a) & ~b


# Tree tips beyond the band (p110), measured on the 0022 sky truth (12 crops, user's "sky 8 colors + bright 205"):
# spill 0.95 -> 0.85 %, missed 1.06 -> 1.13 %. Beyond the band B is never taken out, yet not-A there is still
# mostly sky (100 : 1); brightness does not tell the tips (mixed with the sky behind them) from it, roughness does.
TREE_TIPS = {"reach": 120, "rough": 12.0, "far": 10.0, "grow": 1}


def tree_tips(base: np.ndarray, image: np.ndarray, settings: dict, sel: Optional[np.ndarray] = None,
              reach: float = 120, rough: float = 12.0, far: float = 10.0, grow: int = 1) -> np.ndarray:
    """Tree tips *base* (a sky mask) painted over beyond By Color's Near edge band, to take out after By Color:
    inside *base*, not A, outside the band, within *reach* px of what is not *base*, rough (gray's 7x7 standard
    deviation above *rough*) and at least *far* (Lab) from every picked color; then grown *grow* px through not-A
    pixels of *base* (the tips' mixed rims). Nothing without a band (By Color works anywhere then)."""
    m = base.astype(bool)
    band = settings.get("color_band", 30) if settings.get("color_band_on", True) else 0
    if band <= 0 or not m.any():
        return np.zeros(m.shape, bool)
    if sel is None:
        sel = range_selection(image, settings)
    img = np.ascontiguousarray(image[..., :3])
    # distance to the tree inside the sky; the image's border is not tree (the same padding as near_edge)
    dist = cv2.distanceTransform(np.pad(m, 1, mode="edge").astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    cand = m & ~sel & ~near_edge(m, band) & (dist <= reach)
    if not cand.any():
        return cand
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    mean = cv2.blur(gray, (7, 7))
    sd = np.sqrt(np.maximum(cv2.blur(gray * gray, (7, 7)) - mean * mean, 0))
    cand &= sd > rough
    samples = settings.get("color_samples", ())
    if cand.any() and len(samples):
        ys, xs = np.nonzero(cand)
        lab = cv2.cvtColor(img[ys, xs][:, None], cv2.COLOR_RGB2LAB).astype(np.float32)
        lab[..., 0] *= 100 / 255
        near = _lab_distance2(lab, samples)[:, 0] < float(far) ** 2
        cand[ys[near], xs[near]] = False
    path = (m & ~sel).astype(np.uint8)
    k = np.ones((3, 3), np.uint8)
    for _ in range(max(int(grow), 0)):
        cand |= (cv2.dilate(cand.astype(np.uint8), k) & path).astype(bool)
    return cand


def color_settings(values: dict) -> dict:
    """A By Color preset as saved (lists, from JSON) in the form the functions above take (tuples)."""
    v = dict(values)
    for k in ("color_samples", "color_samples_out"):
        if k in v:
            v[k] = tuple(tuple(int(x) for x in c) for c in v[k])
    if "bright_range" in v:
        v["bright_range"] = tuple(int(x) for x in v["bright_range"])
    return v

