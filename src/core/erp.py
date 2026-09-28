"""Equirectangular (ERP / 360°) ↔ perspective view geometry.

Masks in ERP mode are always stored in ERP pixels; SAM runs on undistorted
perspective views rendered from the ERP and its results are projected back.

Conventions: world +y is up, +z is the direction at the ERP's centre column
(yaw 0), +x is to its right. An ERP pixel column maps to longitude
``lon ∈ [-π, π)`` left to right, a row to latitude ``lat ∈ (π/2, -π/2)`` top
to bottom. A view looks at (``yaw``, ``pitch``) in degrees (pitch +90 = up)
with a horizontal field of view ``fov`` and an image of ``width × height``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

HW = Tuple[int, int]


@dataclass(frozen=True)
class View:
    yaw: float  # degrees, 0 = ERP centre, + to the right
    pitch: float  # degrees, + up
    fov: float = 90.0  # horizontal field of view, degrees
    width: int = 1024
    height: int = 1024

    @property
    def focal(self) -> float:
        return (self.width / 2.0) / math.tan(math.radians(self.fov) / 2.0)

    def basis(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(right, down, forward) unit vectors of the view camera in world space."""
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        f = np.array([math.cos(p) * math.sin(y), math.sin(p), math.cos(p) * math.cos(y)])
        r = np.array([math.cos(y), 0.0, -math.sin(y)])
        up = np.cross(f, r)
        return r, -up, f

    def key(self) -> tuple:
        return (round(self.yaw, 4), round(self.pitch, 4), round(self.fov, 4), self.width, self.height)


# ----------------------------------------------------------------------
# Pixel ↔ direction
# ----------------------------------------------------------------------


def erp_to_dir(u, v, hw: HW) -> np.ndarray:
    """ERP pixel coords (arrays or scalars, pixel centres at +0.5) -> unit vectors (..., 3)."""
    h, w = hw
    lon = (np.asarray(u, np.float64) + 0.5) / w * 2 * math.pi - math.pi
    lat = math.pi / 2 - (np.asarray(v, np.float64) + 0.5) / h * math.pi
    cl = np.cos(lat)
    return np.stack([cl * np.sin(lon), np.sin(lat), cl * np.cos(lon)], axis=-1)


def dir_to_erp(d: np.ndarray, hw: HW) -> Tuple[np.ndarray, np.ndarray]:
    """Unit vectors (..., 3) -> ERP pixel coords (u, v) as float arrays."""
    h, w = hw
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    lon = np.arctan2(x, z)
    lat = np.arcsin(np.clip(y, -1.0, 1.0))
    u = (lon + math.pi) / (2 * math.pi) * w - 0.5
    v = (math.pi / 2 - lat) / math.pi * h - 0.5
    return u, v


def view_pixel_dirs(view: View) -> np.ndarray:
    """World direction of every view pixel, shape (height, width, 3)."""
    r, d, f = view.basis()
    xs = (np.arange(view.width) + 0.5 - view.width / 2.0) / view.focal
    ys = (np.arange(view.height) + 0.5 - view.height / 2.0) / view.focal
    gx, gy = np.meshgrid(xs, ys)
    rays = gx[..., None] * r + gy[..., None] * d + f
    return rays / np.linalg.norm(rays, axis=-1, keepdims=True)


def project_dirs(dirs: np.ndarray, view: View) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """World directions -> view pixel coords (x, y) and a 'in front of the camera' flag."""
    r, d, f = view.basis()
    xc, yc, zc = dirs @ r, dirs @ d, dirs @ f
    front = zc > 1e-6
    safe = np.where(front, zc, 1.0)
    x = xc / safe * view.focal + view.width / 2.0 - 0.5
    y = yc / safe * view.focal + view.height / 2.0 - 0.5
    return x, y, front


def erp_point_to_view(u: float, v: float, hw: HW, view: View) -> Optional[Tuple[float, float]]:
    x, y, front = project_dirs(erp_to_dir(u, v, hw), view)
    return (float(x), float(y)) if bool(front) else None


def view_point_to_erp(x: float, y: float, hw: HW, view: View) -> Tuple[float, float]:
    r, d, f = view.basis()
    ray = r * (x + 0.5 - view.width / 2.0) / view.focal + d * (y + 0.5 - view.height / 2.0) / view.focal + f
    u, v = dir_to_erp(ray / np.linalg.norm(ray), hw)
    return float(u) % hw[1], float(np.clip(v, 0, hw[0] - 1))


# ----------------------------------------------------------------------
# Resampling
# ----------------------------------------------------------------------


@lru_cache(maxsize=16)
def _view_from_erp_maps(view_key: tuple, hw: HW) -> Tuple[np.ndarray, np.ndarray]:
    view = View(*view_key)
    u, v = dir_to_erp(view_pixel_dirs(view), hw)
    return (u % hw[1]).astype(np.float32), np.clip(v, 0, hw[0] - 1).astype(np.float32)


def _erp_block(view: View, hw: HW) -> Tuple[int, int, np.ndarray]:
    """ERP rows [r0, r1) and column indices (may wrap the seam) that can see *view*.

    A view is a convex patch of the sphere, so its extreme longitudes and
    latitudes lie on its outline — unless it contains a pole, which then takes
    every column and the rows up to that pole.
    """
    h, w = hw
    n = 64
    t = np.linspace(-0.5, 1.0 * max(view.width, view.height), n)
    xs = np.concatenate([np.clip(t, -0.5, view.width - 0.5)] * 2 + [np.full(n, -0.5), np.full(n, view.width - 0.5)])
    ys = np.concatenate([np.full(n, -0.5), np.full(n, view.height - 0.5)] + [np.clip(t, -0.5, view.height - 0.5)] * 2)
    r, d, f = view.basis()
    rays = (
        r[None, :] * ((xs + 0.5 - view.width / 2.0) / view.focal)[:, None]
        + d[None, :] * ((ys + 0.5 - view.height / 2.0) / view.focal)[:, None]
        + f[None, :]
    )
    u, v = dir_to_erp(rays / np.linalg.norm(rays, axis=1, keepdims=True), hw)
    r0, r1 = int(max(0, np.floor(v.min()) - 2)), int(min(h, np.ceil(v.max()) + 3))
    north = project_dirs(np.array([0.0, 1.0, 0.0]), view)
    south = project_dirs(np.array([0.0, -1.0, 0.0]), view)
    pole = False
    for (px, py, front), row in ((north, "top"), (south, "bottom")):
        if bool(front) and -0.5 <= float(px) <= view.width - 0.5 and -0.5 <= float(py) <= view.height - 0.5:
            pole = True
            r0, r1 = (0, r1) if row == "top" else (r0, h)
    if pole:
        return r0, r1, np.arange(w)
    uu = np.sort(np.mod(u, w))
    gaps = np.diff(np.concatenate([uu, [uu[0] + w]]))
    k = int(np.argmax(gaps))  # the empty arc; the block is its complement
    start = uu[(k + 1) % len(uu)]
    span = w - gaps[k]
    c0 = int(np.floor(start)) - 2
    cols = np.mod(np.arange(c0, c0 + int(np.ceil(span)) + 5), w)
    return r0, r1, cols


@lru_cache(maxsize=24)
def _erp_from_view_maps(view_key: tuple, hw: HW) -> Tuple[int, int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Maps from the ERP block that sees the view to view pixels: (r0, r1, cols, map_x, map_y, inside)."""
    view = View(*view_key)
    r0, r1, cols = _erp_block(view, hw)
    uu, vv = np.meshgrid(cols.astype(np.float32), np.arange(r0, r1, dtype=np.float32))
    x, y, front = project_dirs(erp_to_dir(uu, vv, hw).astype(np.float32), view)
    inside = front & (x >= -0.5) & (x <= view.width - 0.5) & (y >= -0.5) & (y <= view.height - 0.5)
    x = np.where(inside, x, -10).astype(np.float32)
    y = np.where(inside, y, -10).astype(np.float32)
    return r0, r1, cols, x, y, inside


def render_view(erp: np.ndarray, view: View, nearest: bool = False) -> np.ndarray:
    """Render a perspective view from an ERP image or mask (wraps across the 360° seam)."""
    mx, my = _view_from_erp_maps(view.key(), erp.shape[:2])
    src = erp.astype(np.uint8) if erp.dtype == np.bool_ else erp
    out = cv2.remap(
        src, mx, my, cv2.INTER_NEAREST if nearest or erp.dtype == np.bool_ else cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_WRAP,
    )
    return out > 0 if erp.dtype == np.bool_ else out


def view_coverage(view: View, hw: HW) -> np.ndarray:
    """ERP pixels that the view can see (bool, ERP shape)."""
    r0, r1, cols, _, _, inside = _erp_from_view_maps(view.key(), hw)
    out = np.zeros(hw, bool)
    out[r0:r1, cols] = inside
    return out


@lru_cache(maxsize=32)
def _border_band(view_key: tuple, hw: HW, width: int) -> np.ndarray:
    cover = view_coverage(View(*view_key), hw).astype(np.uint8)
    # Default border: erosion never eats in from the ERP's left/right edge, which is the
    # 360° seam — a view that wraps across it has no edge there.
    inner = cv2.erode(cover, np.ones((2 * width + 1, 2 * width + 1), np.uint8))
    band = (cover > 0) & (inner == 0)
    band[0, :] = band[-1, :] = False  # the ERP's top/bottom rows are poles, not view edges
    return band


def touches_view_edge(erp_mask: np.ndarray, views: Sequence[View], width: int = 3) -> bool:
    """True when the mask reaches the edge of any of *views* (so it may have been cut there)."""
    hw = erp_mask.shape[:2]
    box = _bbox(erp_mask)
    if box is None:
        return False
    y0, y1, x0, x1 = box
    crop = erp_mask[y0:y1, x0:x1]
    return any((crop & _border_band(v.key(), hw, width)[y0:y1, x0:x1]).any() for v in views)


def view_mask_touches_border(mask: np.ndarray, margin: int = 2) -> bool:
    """True when a view-space mask reaches the view image's border."""
    return bool(mask[:margin].any() or mask[-margin:].any() or mask[:, :margin].any() or mask[:, -margin:].any())


def view_mask_to_erp(mask: np.ndarray, view: View, hw: HW) -> np.ndarray:
    """Project a view-space mask back onto the ERP (pixels outside the view are False)."""
    r0, r1, cols, mx, my, _ = _erp_from_view_maps(view.key(), hw)
    block = cv2.remap(mask.astype(np.uint8), mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    out = np.zeros(hw, bool)
    out[r0:r1, cols] = block > 0
    return out


def paste_view_mask(erp_mask: Optional[np.ndarray], view_mask: np.ndarray, view: View, hw: HW) -> np.ndarray:
    """ERP mask where the view's area is replaced by *view_mask* (the rest kept)."""
    base = erp_mask if erp_mask is not None else np.zeros(hw, bool)
    cover = view_coverage(view, hw)
    return np.where(cover, view_mask_to_erp(view_mask, view, hw), base)


# ----------------------------------------------------------------------
# Choosing views
# ----------------------------------------------------------------------


def _angles(dirs: np.ndarray, center: np.ndarray) -> np.ndarray:
    return np.degrees(np.arccos(np.clip(dirs @ center, -1.0, 1.0)))


def _view_towards(center: np.ndarray, spread: float, min_fov: float, max_fov: float, size: int) -> View:
    center = center / (np.linalg.norm(center) or 1.0)
    yaw = math.degrees(math.atan2(center[0], center[2]))
    pitch = math.degrees(math.asin(float(np.clip(center[1], -1, 1))))
    fov = float(np.clip(2 * spread, min_fov, max_fov))
    return View(yaw, pitch, fov, size, size)


def view_for_points(
    points_uv: Sequence[Tuple[float, float]],
    hw: HW,
    min_fov: float = 80.0,
    max_fov: float = 120.0,
    margin: float = 20.0,
    size: int = 1024,
) -> View:
    """A view centred on the points (ERP px) that keeps them all well inside."""
    d = erp_to_dir(np.array([p[0] for p in points_uv]), np.array([p[1] for p in points_uv]), hw).reshape(-1, 3)
    center = d.sum(axis=0)
    if np.linalg.norm(center) < 1e-6:
        center = d[0]
    center = center / np.linalg.norm(center)
    spread = float(_angles(d, center).max()) * 1.2 + margin
    return _view_towards(center, spread, min_fov, max_fov, size)


def view_for_mask(
    mask: np.ndarray, min_fov: float = 70.0, max_fov: float = 120.0, margin: float = 10.0, size: int = 1024
) -> Optional[View]:
    """A view centred on an ERP mask's area-weighted direction that covers most of it."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    step = max(1, len(xs) // 20000)
    d = erp_to_dir(xs[::step], ys[::step], mask.shape)
    wgt = np.sqrt(np.clip(1 - d[:, 1] ** 2, 0, 1))  # ERP rows near the poles cover less area
    center = (d * wgt[:, None]).sum(axis=0)
    if np.linalg.norm(center) < 1e-6:
        center = d[0]
    center = center / np.linalg.norm(center)
    spread = float(np.percentile(_angles(d, center), 98)) + margin
    return _view_towards(center, spread, min_fov, max_fov, size)


VIEW_PRESETS = {
    "cube6": "Cube map — 6 × 90° (front, right, back, left, up, down)",
    "ring8": "Overlapping — 8 × 90° around at 45° + up + down",
    "fast4": "Fast — 3 × 120° around + down",
}


def preset_views(name: str, size: int = 1024) -> List[View]:
    if name == "ring8":
        return [View(y, 0, 90, size, size) for y in range(0, 360, 45)] + [
            View(0, 90, 90, size, size),
            View(0, -90, 90, size, size),
        ]
    if name == "fast4":
        return [View(y, 0, 120, size, size) for y in (0, 120, 240)] + [View(0, -90, 120, size, size)]
    return [View(y, 0, 90, size, size) for y in (0, 90, 180, 270)] + [
        View(0, 90, 90, size, size),
        View(0, -90, 90, size, size),
    ]


# ----------------------------------------------------------------------
# Merging per-view detections
# ----------------------------------------------------------------------


def _bbox(mask: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """(y0, y1, x0, x1) half-open bounds of a mask, or None if empty."""
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if len(rows) == 0:
        return None
    return int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1


def _touching(a: np.ndarray, b: np.ndarray, ba=None, bb=None, pad: int = 2) -> bool:
    """True when masks overlap or touch (also across the 360° seam). Works on bounding-box crops."""
    ba = ba or _bbox(a)
    bb = bb or _bbox(b)
    if ba is None or bb is None:
        return False
    w = a.shape[1]
    if ba[3] >= w - pad and bb[2] <= pad or bb[3] >= w - pad and ba[2] <= pad:  # both reach the seam
        rows = slice(max(ba[0], bb[0]) - pad, min(ba[1], bb[1]) + pad)
        if (a[rows, -pad:].any(axis=1) & b[rows, :pad].any(axis=1)).any() or (
            a[rows, :pad].any(axis=1) & b[rows, -pad:].any(axis=1)
        ).any():
            return True
    y0, y1 = max(ba[0], bb[0]) - pad, min(ba[1], bb[1]) + pad
    x0, x1 = max(ba[2], bb[2]) - pad, min(ba[3], bb[3]) + pad
    if y0 >= y1 or x0 >= x1:
        return False
    y0, x0 = max(0, y0), max(0, x0)
    ca = a[max(0, y0 - pad) : y1 + pad, max(0, x0 - pad) : x1 + pad]
    cb = b[max(0, y0 - pad) : y1 + pad, max(0, x0 - pad) : x1 + pad]
    ka = cv2.dilate(ca.astype(np.uint8), np.ones((2 * pad + 1, 2 * pad + 1), np.uint8))
    return bool((ka.astype(bool) & cb).any())


def _overlap(a: np.ndarray, b: np.ndarray, ba, bb) -> int:
    y0, y1, x0, x1 = max(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), min(ba[3], bb[3])
    if y0 >= y1 or x0 >= x1:
        return 0
    return int((a[y0:y1, x0:x1] & b[y0:y1, x0:x1]).sum())


def merge_view_detections(
    items: Iterable[Tuple[str, float, np.ndarray, int]], overlap: float = 0.3
) -> List[Tuple[str, float, np.ndarray]]:
    """Merge back-projected detections ``(label, score, erp_mask, view_index)`` of the same object.

    Two detections of one label are the same object when they overlap enough
    (intersection over the smaller mask ≥ *overlap*), or when they come from
    different views and touch — an object cut by a view border shows up as
    two halves that meet at the border.
    """
    clusters: List[dict] = []
    for label, score, mask, vi in sorted(items, key=lambda t: -t[1]):
        box = _bbox(mask)
        if box is None:
            continue
        area = int(mask.sum())
        target = None
        for c in clusters:
            if c["label"] != label:
                continue
            inter = _overlap(c["mask"], mask, c["box"], box)
            if inter / max(1, min(area, c["area"])) >= overlap:
                target = c
                break
            if vi not in c["views"] and _touching(c["mask"], mask, c["box"], box):
                target = c
                break
        if target is None:
            clusters.append(
                {"label": label, "score": score, "mask": mask.copy(), "area": area, "views": {vi}, "box": box}
            )
        else:
            target["mask"] |= mask
            target["area"] = int(target["mask"].sum())
            target["score"] = max(target["score"], score)
            target["views"].add(vi)
            b = target["box"]
            target["box"] = (min(b[0], box[0]), max(b[1], box[1]), min(b[2], box[2]), max(b[3], box[3]))
    return [(c["label"], c["score"], c["mask"]) for c in clusters]


def is_erp_shape(h: int, w: int, tol: float = 0.02) -> bool:
    """Width is (about) twice the height."""
    return h > 0 and abs(w / h - 2.0) <= 2.0 * tol
