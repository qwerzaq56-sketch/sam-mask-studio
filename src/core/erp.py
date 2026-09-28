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


@lru_cache(maxsize=4)
def _erp_dirs(hw: HW) -> np.ndarray:
    h, w = hw
    uu, vv = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return erp_to_dir(uu, vv, hw).astype(np.float32)


@lru_cache(maxsize=16)
def _erp_from_view_maps(view_key: tuple, hw: HW) -> Tuple[np.ndarray, np.ndarray]:
    view = View(*view_key)
    x, y, front = project_dirs(_erp_dirs(hw), view)
    inside = front & (x >= -0.5) & (x <= view.width - 0.5) & (y >= -0.5) & (y <= view.height - 0.5)
    x = np.where(inside, x, -10).astype(np.float32)
    y = np.where(inside, y, -10).astype(np.float32)
    return x, y


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
    x, _ = _erp_from_view_maps(view.key(), hw)
    return x > -5


def view_mask_to_erp(mask: np.ndarray, view: View, hw: HW) -> np.ndarray:
    """Project a view-space mask back onto the ERP (pixels outside the view are False)."""
    mx, my = _erp_from_view_maps(view.key(), hw)
    out = cv2.remap(mask.astype(np.uint8), mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return out > 0


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


def _touching(a: np.ndarray, b: np.ndarray) -> bool:
    """True when masks overlap or touch (also across the 360° seam)."""
    ka = cv2.dilate(a.astype(np.uint8), np.ones((5, 5), np.uint8))
    if (ka.astype(bool) & b).any():
        return True
    return bool((a[:, :2].any(axis=1) & b[:, -2:].any(axis=1)).any() or (a[:, -2:].any(axis=1) & b[:, :2].any(axis=1)).any())


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
        area = int(mask.sum())
        if area == 0:
            continue
        target = None
        for c in clusters:
            if c["label"] != label:
                continue
            inter = int((c["mask"] & mask).sum())
            if inter / max(1, min(area, c["area"])) >= overlap:
                target = c
                break
            if vi not in c["views"] and _touching(c["mask"], mask):
                target = c
                break
        if target is None:
            clusters.append({"label": label, "score": score, "mask": mask.copy(), "area": area, "views": {vi}})
        else:
            target["mask"] |= mask
            target["area"] = int(target["mask"].sum())
            target["score"] = max(target["score"], score)
            target["views"].add(vi)
    return [(c["label"], c["score"], c["mask"]) for c in clusters]


def is_erp_shape(h: int, w: int, tol: float = 0.02) -> bool:
    """Width is (about) twice the height."""
    return h > 0 and abs(w / h - 2.0) <= 2.0 * tol
