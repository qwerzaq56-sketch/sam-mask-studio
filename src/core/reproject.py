"""Projection conversion of a COLMAP scene (docs/specs/08-erp-to-pinhole.md).

The converter walks the *target* pixels: each becomes a ray, and the *source*
camera model's projection (ray -> pixel) says where to sample the source image.
Sources: EQUIRECTANGULAR, the pinhole family (with its distortion) and the
fisheye family; targets: pinhole views (``Views``) or one 360 image (``Erp``).
Parts of a target the source lens never saw are marked ignored in every mask
written, so trainers do not learn the black fill.

Camera frame (COLMAP): X right, Y down, Z forward. Pixel coordinates put the
upper-left corner at (0, 0), so pixel centers are at i + 0.5.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

import cv2
import numpy as np

from src.core.colmap import MODEL_IDS, Camera, read_cameras_full
from src.core.colmap_model import POINT2D, TRACK, _read_images_bin, _write_images_bin, dataset_blocker
from src.engine.imageio import key_stem

DEFAULT_YAWS = (0.0, 90.0, 180.0, 270.0)
DEFAULT_PITCHES = (-35.0, 0.0, 35.0)
DEFAULT_FOV = 90.0
FISHEYE_YAWS = (-45.0, 0.0, 45.0)  # a fisheye looks one way: views around its axis
MAX_FISHEYE_ANGLE = np.radians(110)  # beyond this the distortion polynomial is not trusted


# --- rotations -------------------------------------------------------------------------------


def qvec_to_rotmat(q) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * w * z, 2 * x * z + 2 * w * y],
        [2 * x * y + 2 * w * z, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * w * x],
        [2 * x * z - 2 * w * y, 2 * y * z + 2 * w * x, 1 - 2 * x * x - 2 * y * y],
    ])


def rotmat_to_qvec(r: np.ndarray) -> np.ndarray:
    """The unit quaternion (w, x, y, z) of *r*, w >= 0 (COLMAP's read_write_model method)."""
    rxx, ryx, rzx, rxy, ryy, rzy, rxz, ryz, rzz = r.flat
    k = np.array([
        [rxx - ryy - rzz, 0, 0, 0],
        [ryx + rxy, ryy - rxx - rzz, 0, 0],
        [rzx + rxz, rzy + ryz, rzz - rxx - ryy, 0],
        [ryz - rzy, rzx - rxz, rxy - ryx, rxx + ryy + rzz],
    ]) / 3.0
    vals, vecs = np.linalg.eigh(k)
    q = vecs[[3, 0, 1, 2], np.argmax(vals)]
    return -q if q[0] < 0 else q


def view_rotation(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    """Source camera -> view: rows are the view's right, down and forward axes in source coordinates.

    Yaw turns right (0 = the source's forward), pitch looks up (positive).
    """
    yaw, pitch = np.radians(yaw_deg), np.radians(pitch_deg)
    fwd = np.array([np.cos(pitch) * np.sin(yaw), -np.sin(pitch), np.cos(pitch) * np.cos(yaw)])
    right = np.array([np.cos(yaw), 0.0, -np.sin(yaw)])
    down = np.cross(fwd, right)
    return np.stack([right, down, fwd])


# --- source projections: rays (..., 3) in the source camera frame -> (x, y, valid) ----------------


def project_equirect(cam: Camera, rays: np.ndarray):
    w, h = cam.params[0], cam.params[1]
    x, y, z = rays[..., 0], rays[..., 1], rays[..., 2]
    theta = np.arctan2(x, z)
    phi = np.arctan2(-y, np.hypot(x, z))
    return (theta / (2 * np.pi) + 0.5) * w, (0.5 - phi / np.pi) * h, np.ones(theta.shape, bool)


def _pinhole(fx, fy, cx, cy, k1=0.0, k2=0.0, p1=0.0, p2=0.0):
    """COLMAP's OPENCV projection (PINHOLE / SIMPLE_* / RADIAL are special cases)."""
    def project(_cam, rays):
        z = rays[..., 2]
        ok = z > 1e-9
        zz = np.where(ok, z, 1.0)
        u, v = rays[..., 0] / zz, rays[..., 1] / zz
        r2 = u * u + v * v
        radial = k1 * r2 + k2 * r2 * r2
        du = u * radial + 2 * p1 * u * v + p2 * (r2 + 2 * u * u)
        dv = v * radial + 2 * p2 * u * v + p1 * (r2 + 2 * v * v)
        return fx * (u + du) + cx, fy * (v + dv) + cy, ok
    return project


def _fisheye(fx, fy, cx, cy, ks=()):
    """COLMAP's fisheye family: equidistant angle theta, then theta * (1 + k1 theta^2 + k2 theta^4 + ...)."""
    def project(_cam, rays):
        x, y, z = rays[..., 0], rays[..., 1], rays[..., 2]
        r = np.hypot(x, y)
        theta = np.arctan2(r, z)
        scale = np.where(r > 1e-12, theta / np.where(r > 1e-12, r, 1.0), 1.0 / np.where(z > 1e-12, z, 1.0))
        uu, vv = x * scale, y * scale
        t2 = theta * theta
        radial = sum(k * t2 ** (i + 1) for i, k in enumerate(ks))
        return fx * uu * (1 + radial) + cx, fy * vv * (1 + radial) + cy, theta < MAX_FISHEYE_ANGLE
    return project


def _thin_prism_fisheye(fx, fy, cx, cy, k1, k2, p1, p2, k3, k4, sx1, sy1):
    """COLMAP's THIN_PRISM_FISHEYE (sensor/models/thin_prism.h): the equidistant fisheye point (uu, vv),
    then radial (k1..k4 on r^2..r^8), tangential (p1, p2) and thin-prism (sx1, sy1) distortion of it."""
    def project(_cam, rays):
        x, y, z = rays[..., 0], rays[..., 1], rays[..., 2]
        r = np.hypot(x, y)
        theta = np.arctan2(r, z)
        scale = np.where(r > 1e-12, theta / np.where(r > 1e-12, r, 1.0), 1.0 / np.where(z > 1e-12, z, 1.0))
        u, v = x * scale, y * scale
        u2, v2, uv = u * u, v * v, u * v
        r2 = u2 + v2
        radial = k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3 + k4 * r2 ** 4
        du = u * radial + 2 * p1 * uv + p2 * (r2 + 2 * u2) + sx1 * r2
        dv = v * radial + 2 * p2 * uv + p1 * (r2 + 2 * v2) + sy1 * r2
        return fx * (u + du) + cx, fy * (v + dv) + cy, theta < MAX_FISHEYE_ANGLE
    return project


def source_projection(cam: Camera) -> Optional[Callable]:
    """The projection of *cam*'s model, or None when it cannot be converted."""
    p, m = cam.params, cam.model
    if m == "EQUIRECTANGULAR":
        return project_equirect
    if m == "SIMPLE_PINHOLE":
        return _pinhole(p[0], p[0], p[1], p[2])
    if m == "PINHOLE":
        return _pinhole(*p[:4])
    if m == "SIMPLE_RADIAL":
        return _pinhole(p[0], p[0], p[1], p[2], p[3])
    if m == "RADIAL":
        return _pinhole(p[0], p[0], p[1], p[2], p[3], p[4])
    if m == "OPENCV":
        return _pinhole(*p[:8])
    if m == "SIMPLE_FISHEYE":
        return _fisheye(p[0], p[0], p[1], p[2])
    if m == "FISHEYE":
        return _fisheye(*p[:4])
    if m == "SIMPLE_RADIAL_FISHEYE":
        return _fisheye(p[0], p[0], p[1], p[2], (p[3],))
    if m == "RADIAL_FISHEYE":
        return _fisheye(p[0], p[0], p[1], p[2], (p[3], p[4]))
    if m == "OPENCV_FISHEYE":
        return _fisheye(p[0], p[1], p[2], p[3], tuple(p[4:8]))
    if m == "THIN_PRISM_FISHEYE":
        return _thin_prism_fisheye(*p[:12])
    return None


CONVERTIBLE = ("EQUIRECTANGULAR", "SIMPLE_PINHOLE", "PINHOLE", "SIMPLE_RADIAL", "RADIAL", "OPENCV",
               "SIMPLE_FISHEYE", "FISHEYE", "SIMPLE_RADIAL_FISHEYE", "RADIAL_FISHEYE", "OPENCV_FISHEYE",
               "THIN_PRISM_FISHEYE")
FISHEYES = ("SIMPLE_FISHEYE", "FISHEYE", "SIMPLE_RADIAL_FISHEYE", "RADIAL_FISHEYE", "OPENCV_FISHEYE",
            "THIN_PRISM_FISHEYE")


def _focal(cam: Camera) -> float:
    return float(cam.params[0]) if cam.model != "EQUIRECTANGULAR" else cam.width / (2 * np.pi)


# --- targets --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ring:
    """*count* views evenly around at *pitch*, the first at yaw *offset* (degrees)."""

    pitch: float
    count: int
    offset: float = 0.0

    def yaws(self) -> List[float]:
        return [(self.offset + i * 360.0 / self.count) % 360 for i in range(self.count)]


@dataclass(frozen=True)
class ViewLayout:
    """A rule for where a 360 image's pinhole views look (docs/specs/08 P4): rings of views, plus single
    views straight up / down (*poles*: +90 / -90). The field of view and the resolution are separate
    settings (``Views.fov`` / ``Views.size``), so one layout works at 90°, 110°, 120° ..."""

    key: str
    label: str
    purpose: str
    rings: Tuple[Ring, ...]
    poles: Tuple[float, ...] = ()

    def pairs(self, yaw_offset: float = 0.0) -> List[Tuple[float, float]]:
        out = [((y + yaw_offset) % 360, float(ring.pitch)) for ring in self.rings for y in ring.yaws()]
        return out + [(yaw_offset % 360, float(p)) for p in self.poles]

    @property
    def count(self) -> int:
        return sum(r.count for r in self.rings) + len(self.poles)

    def overlap(self, fov: float) -> Tuple[float, Optional[float]]:
        """(sideways, between rings) overlap in degrees at *fov*: how far neighbouring views cover the same
        directions (<= 0: they only touch or leave a gap). Measured at the horizon, a simple guide."""
        side = min(fov - 360.0 / r.count for r in self.rings)
        pitches = sorted({r.pitch for r in self.rings} | set(self.poles))
        gaps = [b - a for a, b in zip(pitches, pitches[1:])]
        return side, (fov - min(gaps)) if gaps else None


# the layouts 360 tools use (docs/specs/08 §8, sources there); no more: these cover the usual needs
VIEW_LAYOUTS = {lay.key: lay for lay in (
    ViewLayout("colmap12", "COLMAP Overlap · 12 Views",
               "Overlapping perspective views as in COLMAP's panorama SfM (4 × pitch −35 / 0 / 35, the upper row "
               "turned 45°). The usual default for 360 → COLMAP: the overlap helps feature matching and SfM",
               (Ring(-35, 4), Ring(0, 4), Ring(35, 4, 45.0))),
    ViewLayout("cube6", "Cubemap · 6 Views",
               "Six directions 90° apart (front · right · back · left · up · down): simple, covers the whole "
               "sphere evenly",
               (Ring(0, 4),), (90.0, -90.0)),
    ViewLayout("horizon4", "Horizon · 4 Views",
               "Four level directions, no up / down (COLMAP's non-overlapping). For level spaces (indoors, "
               "buildings), fast. Leaves out the sky and the operator below",
               (Ring(0, 4),)),
    ViewLayout("rings16", "Two Rings · 16 Views",
               "Two rows of 8 at ±35° (the upper row turned 22.5°, LichtFeld's 360 plugin Medium). More coverage "
               "and overlap up and down: for dense coverage / SfM stability experiments",
               (Ring(-35, 8), Ring(35, 8, 22.5))),
)}
MIN_VIEW_SHARE = 0.5  # a fisheye's view with less of it seen by the lens is not made (docs/specs/08 P4)


def view_share(cam: Camera, yaw: float, pitch: float, fov: float, n: int = 24) -> float:
    """How much of a view the source camera sees (0..1), from an n x n grid of its rays.
    A 360 image sees everything; a fisheye only its side (and inside its frame)."""
    proj = source_projection(cam)
    if proj is None:
        return 0.0
    if cam.model == "EQUIRECTANGULAR":
        return 1.0
    t = np.tan(np.radians(fov) / 2)
    s = (np.arange(n) + 0.5) / n * 2 * t - t
    uu, vv = np.meshgrid(s, s)
    rays = np.stack([uu, vv, np.ones_like(uu)], -1) @ view_rotation(yaw, pitch)
    x, y, ok = proj(cam, rays)
    inside = ok & (x >= 0) & (x < cam.width) & (y >= 0) & (y < cam.height)
    return float(inside.mean())


@dataclass(frozen=True)
class Views:
    """Pinhole views: every yaw at every pitch (or the (yaw, pitch) list of a layout), square, *fov* wide."""

    yaws: Tuple[float, ...] = DEFAULT_YAWS
    pitches: Tuple[float, ...] = DEFAULT_PITCHES
    fov: float = DEFAULT_FOV
    size: int = 0  # 0 = auto: the source's resolution at that field of view
    layout: Optional["ViewLayout"] = None  # a layout rule (VIEW_LAYOUTS) instead of the yaw x pitch grid
    yaw_offset: float = 0.0  # the whole layout turned right by this much

    def pairs(self) -> List[Tuple[float, float]]:
        if self.layout is not None:
            return self.layout.pairs(self.yaw_offset)
        return [((y + self.yaw_offset) % 360 if self.yaw_offset else y, p) for p in self.pitches for y in self.yaws]

    def side(self, source_width: int) -> int:  # kept for callers of v0.4-p29
        s = self.size or max(64, source_width // 4)
        return int(s) // 2 * 2

    def focal(self, side: int) -> float:
        return side / 2.0 / np.tan(np.radians(self.fov) / 2.0)


@dataclass(frozen=True)
class Erp:
    """One 360 image per source image (same pose), *width* x width / 2."""

    width: int = 0  # 0 = auto: 2 pi x the source focal length (its angular resolution)


@dataclass(frozen=True)
class Stitch:
    """One 360 image per moment from a rig's cameras (dual fisheye), *width* x width / 2."""

    width: int = 0  # 0 = auto: 2 pi x the first camera's focal length


Target = Union[Views, Erp]


class _Plan:
    """What one target makes of one source camera: the views (name suffix, rotation) and the output camera."""

    def __init__(self, target: Target, src: Camera):
        self.erp = isinstance(target, Erp)
        f = _focal(src)
        if self.erp:
            w = target.width or int(round(2 * np.pi * f))
            self.w = max(64, min(16384, int(w) // 2 * 2))
            self.h = self.w // 2
            self.views = [("", np.eye(3))]
            self.camera = (MODEL_IDS["EQUIRECTANGULAR"], self.w, self.h, (float(self.w), float(self.h)))
        else:
            side = target.size or int(round(2 * f * np.tan(np.radians(target.fov) / 2)))
            if src.model == "EQUIRECTANGULAR" and not target.size:
                side = src.width // 4 if target.fov == 90 else side
            self.w = self.h = max(64, min(8192, int(side) // 2 * 2))
            self.focal = target.focal(self.w)
            self.views = [(view_name("", y, p), view_rotation(y, p)) for y, p in target.pairs()]
            c = self.w / 2.0
            self.camera = (MODEL_IDS["PINHOLE"], self.w, self.h, (self.focal, self.focal, c, c))

    def rays(self) -> np.ndarray:
        """The target pixels' rays in the target camera frame, (h, w, 3)."""
        j, i = np.meshgrid(np.arange(self.w) + 0.5, np.arange(self.h) + 0.5)
        if self.erp:
            theta = 2 * np.pi * (j / self.w - 0.5)
            phi = np.pi * (0.5 - i / self.h)
            return np.stack([np.cos(phi) * np.sin(theta), -np.sin(phi), np.cos(phi) * np.cos(theta)], axis=-1)
        c = self.w / 2.0
        return np.stack([(j - c) / self.focal, (i - c) / self.focal, np.ones_like(j)], axis=-1)

    def project(self, pts: np.ndarray):
        """Points in the target camera frame -> (x, y, inside)."""
        if self.erp:
            x, y, _ = project_equirect(Camera(0, "EQUIRECTANGULAR", self.w, self.h, (self.w, self.h)), pts)
            return x, y, np.ones(len(pts), bool)
        z = pts[:, 2]
        ok = z > 1e-9
        zz = np.where(ok, z, 1.0)
        c = self.w / 2.0
        x, y = self.focal * pts[:, 0] / zz + c, self.focal * pts[:, 1] / zz + c
        return x, y, ok & (x >= 0) & (x < self.w) & (y >= 0) & (y < self.h)


def view_name(stem: str, yaw: float, pitch: float) -> str:
    """``frame_010_y090_pm35`` (m = minus)."""
    p = int(round(pitch))
    y = int(round(yaw)) % 360
    return f"{stem}_y{y:03d}_p{'m' if p < 0 else ''}{abs(p):02d}"


def remap_tables(src: Camera, rot: np.ndarray, side: int, focal: float) -> Tuple[np.ndarray, np.ndarray]:
    """cv2.remap maps sampling *src* for a pinhole view turned by *rot* (kept from v0.4-p29)."""
    c = side / 2.0
    j, i = np.meshgrid(np.arange(side) + 0.5, np.arange(side) + 0.5)
    rays = np.stack([(j - c) / focal, (i - c) / focal, np.ones_like(j)], axis=-1) @ rot
    x, y, _ok = source_projection(src)(src, rays)
    return (x - 0.5).astype(np.float32), (y - 0.5).astype(np.float32)


def _tables(src: Camera, plan: _Plan, rot: np.ndarray):
    """(map x, map y, valid) for one view: valid = the source lens saw that direction and it is in its frame."""
    x, y, ok = source_projection(src)(src, plan.rays() @ rot)
    if src.model != "EQUIRECTANGULAR":
        ok = ok & (x >= 0) & (x < src.width) & (y >= 0) & (y < src.height)
    return (x - 0.5).astype(np.float32), (y - 0.5).astype(np.float32), ok


@dataclass
class MaskJob:
    """Masks written beside the converted images, remapped like them."""

    out_dir: Path
    name_pattern: str  # "{name}.png" / "{stem}.png"
    invert: bool  # write the object (what training ignores) black
    include_empty: bool
    get: Callable[[str], Optional[np.ndarray]]  # image key -> the full-resolution mask (bool), None = none


@dataclass
class ConvertReport:
    images_in: int = 0
    views_out: int = 0
    points_kept: int = 0
    points_dropped: int = 0
    side: int = 0  # the output width
    skipped: List[str] = field(default_factory=list)  # images whose camera cannot be converted
    views_dropped: int = 0  # views a fisheye could not fill (less than MIN_VIEW_SHARE seen): not made


def _read_points(path: Path):
    """(ids, xyz, rgb, error) of points3D.bin; tracks are rebuilt, so skipped."""
    ids, xyz, rgb, err = [], [], [], []
    head = struct.Struct("<Q3d3BdQ")
    with open(path, "rb") as f:
        (n,) = struct.unpack("<Q", f.read(8))
        for _ in range(n):
            v = head.unpack(f.read(head.size))
            ids.append(v[0])
            xyz.append(v[1:4])
            rgb.append(v[4:7])
            err.append(v[7])
            f.seek(TRACK.itemsize * v[8], 1)
    return (np.array(ids, np.uint64), np.array(xyz, float).reshape(-1, 3), np.array(rgb, np.uint8).reshape(-1, 3),
            np.array(err, float))


def _write_image(path: Path, img: np.ndarray) -> None:
    ok, buf = cv2.imencode(path.suffix, img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        raise IOError(f"Could not encode {path}")
    buf.tofile(str(path))


def convert(images_dir: Path, model_dir: Path, root: Path, keep: Sequence[str], target: Target,
            masks: Sequence[MaskJob] = (), progress: Optional[Callable[[int, int], None]] = None) -> ConvertReport:
    """``root/images`` + ``root/sparse/0`` (binary) with the kept images converted to *target*, and the masks.

    Images whose camera model has no projection here are left out (listed in the report); the source is only read.
    """
    why = dataset_blocker(root)
    if why:
        raise FileExistsError(why)
    if not (model_dir / "images.bin").is_file():
        raise ValueError("The conversion reads a binary model (images.bin); convert a text model with COLMAP first")
    cams = read_cameras_full(model_dir)
    keep_set = set(keep)
    images = [im for im in _read_images_bin(model_dir / "images.bin") if im[3] in keep_set]
    report = ConvertReport(images_in=len(images))
    convertible = [im for im in images if cams.get(im[2]) is not None and source_projection(cams[im[2]]) is not None]
    report.skipped = [im[3] for im in images if im not in convertible]
    if not convertible:
        raise ValueError("No image here uses a camera this can convert")
    plans = {cid: _Plan(target, cams[cid]) for cid in {im[2] for im in convertible}}
    first = plans[convertible[0][2]]
    report.side = first.w
    if (model_dir / "points3D.bin").is_file():
        pids, xyz, rgb, err = _read_points(model_dir / "points3D.bin")
    else:
        pids, xyz, rgb, err = np.zeros(0, np.uint64), np.zeros((0, 3)), np.zeros((0, 3), np.uint8), np.zeros(0)
    row_of = {int(p): i for i, p in enumerate(pids)}
    out_img = root / "images"
    out_img.mkdir(parents=True)
    for job in masks:
        job.out_dir.mkdir(parents=True, exist_ok=True)
    out_cams: Dict[tuple, int] = {}  # one output camera per distinct (model, size, params)
    tables: Dict[Tuple[int, int], tuple] = {}
    new_images: List[tuple] = []
    tracks: Dict[int, List[Tuple[int, int]]] = {}
    next_id = 1
    for n, (iid, pose, cid, name, pts) in enumerate(convertible):
        cam, plan = cams[cid], plans[cid]
        ocid = out_cams.setdefault(plan.camera, len(out_cams) + 1)
        border = cv2.BORDER_WRAP if cam.model == "EQUIRECTANGULAR" else cv2.BORDER_CONSTANT
        q, t = np.array(struct.unpack("<4d", pose[:32])), np.array(struct.unpack("<3d", pose[32:]))
        r_src = qvec_to_rotmat(q)
        data = np.fromfile(str(images_dir / name), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
        if img is None:
            report.skipped.append(name)
            continue
        full_masks = [job.get(name) for job in masks]
        seen = np.unique(pts["id"][pts["id"] >= 0])
        rows = np.array([row_of[int(p)] for p in seen if int(p) in row_of], dtype=int)
        cam_pts = (xyz[rows] @ r_src.T + t) if rows.size else np.zeros((0, 3))
        stem = key_stem(name)  # folders kept: cam0/0001
        for v, (suffix, rot) in enumerate(plan.views):
            if (cid, v) not in tables:
                tables[(cid, v)] = _tables(cam, plan, rot)
            mx, my, valid = tables[(cid, v)]
            if valid.mean() < MIN_VIEW_SHARE:  # a direction the lens barely saw (a fisheye's back): no view
                report.views_dropped += 1
                continue
            vname = f"{stem}{suffix}.jpg"
            (out_img / vname).parent.mkdir(parents=True, exist_ok=True)
            _write_image(out_img / vname, cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=border))
            for job, m in zip(masks, full_masks):
                if m is None and not job.include_empty and valid.all():
                    continue
                src = (m.astype(np.uint8) * 255) if m is not None else np.zeros(img.shape[:2], np.uint8)
                if src.shape != img.shape[:2]:
                    src = cv2.resize(src, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
                ignore = cv2.remap(src, mx, my, cv2.INTER_NEAREST, borderMode=border) > 0
                ignore |= ~valid  # never seen by the source lens: not to be learned
                out = ignore.astype(np.uint8) * 255
                if job.invert:
                    out = 255 - out
                ok, buf = cv2.imencode(".png", out)
                mpath = job.out_dir / job.name_pattern.format(stem=key_stem(vname), name=vname)
                mpath.parent.mkdir(parents=True, exist_ok=True)
                buf.tofile(str(mpath))
            vid = next_id
            next_id += 1
            x, y, inside = plan.project(cam_pts @ rot.T)
            obs = np.zeros(int(inside.sum()), dtype=POINT2D)
            obs["x"], obs["y"] = x[inside], y[inside]
            obs["id"] = pids[rows[inside]].astype(np.int64) if rows.size else []
            for idx, pid in enumerate(obs["id"]):
                tracks.setdefault(int(pid), []).append((vid, idx))
            new_pose = struct.pack("<4d", *rotmat_to_qvec(rot @ r_src)) + struct.pack("<3d", *(rot @ t))
            new_images.append((vid, new_pose, ocid, vname, obs))
            report.views_out += 1
        if progress:
            progress(n + 1, len(convertible))
    kept = {pid for pid, tr in tracks.items() if len(tr) >= 2}
    keep_arr = np.array(sorted(kept), dtype=np.int64)
    for im in new_images:
        im[4]["id"][~np.isin(im[4]["id"], keep_arr)] = -1
    sparse = root / "sparse" / "0"
    sparse.mkdir(parents=True)
    with open(sparse / "cameras.bin", "wb") as f:
        f.write(struct.pack("<Q", len(out_cams)))
        for (mid, w, h, params), ocid in sorted(out_cams.items(), key=lambda kv: kv[1]):
            f.write(struct.pack("<iiQQ", ocid, mid, w, h) + struct.pack(f"<{len(params)}d", *params))
    _write_images_bin(sparse / "images.bin", new_images)
    head = struct.Struct("<Q3d3BdQ")
    with open(sparse / "points3D.bin", "wb") as f:
        f.write(struct.pack("<Q", len(kept)))
        for pid in sorted(kept):
            i = row_of[pid]
            tr = np.array(tracks[pid], dtype=TRACK)
            f.write(head.pack(pid, *xyz[i], *(int(c) for c in rgb[i]), err[i], len(tr)) + tr.tobytes())
    report.points_kept = len(kept)
    report.points_dropped = len(row_of) - len(kept)
    return report


def convert_to_pinhole(images_dir: Path, model_dir: Path, root: Path, keep: Sequence[str], views: Views,
                       masks: Sequence[MaskJob] = (), progress: Optional[Callable[[int, int], None]] = None
                       ) -> ConvertReport:
    """Pinhole views of every kept image (the v0.4-p29 entry point)."""
    return convert(images_dir, model_dir, root, keep, views, masks, progress)


# --- a rig's cameras stitched into one 360 image per moment (dual fisheye, docs/specs/08 P3) --------------

CENTER_FIRST = ("SIMPLE_FISHEYE", "SIMPLE_RADIAL_FISHEYE", "RADIAL_FISHEYE", "SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL")


def _circle_weight(cam: Camera, x: np.ndarray, y: np.ndarray, ok: np.ndarray, feather: float = 0.05) -> np.ndarray:
    """How much a camera's pixel counts: 1 inside its image circle (the largest circle around the principal
    point inside the frame, where a circular fisheye's picture is), fading to 0 over its outer *feather*."""
    p = cam.params
    cx, cy = (p[1], p[2]) if cam.model in CENTER_FIRST else (p[2], p[3])
    radius = min(cx, cy, cam.width - cx, cam.height - cy)
    d = np.hypot(x - cx, y - cy)
    return np.where(ok, np.clip((radius - d) / (feather * radius), 0.0, 1.0), 0.0)


def _group_name(names: Sequence[str]) -> str:
    """The stitched image's name: the first image's path without its camera folder (cam0/0001.jpg -> 0001)."""
    first = names[0]
    return key_stem(first.split("/", 1)[1] if "/" in first else first)


def stitch_to_erp(images_dir: Path, model_dir: Path, root: Path, groups: Sequence[Sequence[str]], width: int = 0,
                  masks: Sequence[MaskJob] = (), progress: Optional[Callable[[int, int], None]] = None) -> ConvertReport:
    """root/images + root/sparse/0: one 360 image per group of images (a rig's cameras at one moment),
    facing the group's first camera. Where lenses overlap they blend by how far each pixel is inside its image
    circle; masks take the stronger lens's value; what no lens saw is marked ignored."""
    why = dataset_blocker(root)
    if why:
        raise FileExistsError(why)
    if not (model_dir / "images.bin").is_file():
        raise ValueError("Stitching reads a binary model (images.bin)")
    cams = read_cameras_full(model_dir)
    by_name = {im[3]: im for im in _read_images_bin(model_dir / "images.bin")}
    groups = [[n for n in g if n in by_name and source_projection(cams[by_name[n][2]]) is not None] for g in groups]
    groups = [g for g in groups if len(g) >= 2]
    report = ConvertReport(images_in=sum(len(g) for g in groups))
    if not groups:
        raise ValueError("No group of two or more convertible images to stitch")
    ref_cam = cams[by_name[groups[0][0]][2]]
    w = width or int(round(2 * np.pi * _focal(ref_cam)))
    w = max(64, min(16384, int(w) // 2 * 2))
    h = w // 2
    report.side = w
    j, i = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    theta, phi = 2 * np.pi * (j / w - 0.5), np.pi * (0.5 - i / h)
    rays = np.stack([np.cos(phi) * np.sin(theta), -np.sin(phi), np.cos(phi) * np.cos(theta)], axis=-1)
    erp = _Plan(Erp(w), Camera(0, "EQUIRECTANGULAR", w, h, (w, h)))
    if (model_dir / "points3D.bin").is_file():
        pids, xyz, rgb, err = _read_points(model_dir / "points3D.bin")
    else:
        pids, xyz, rgb, err = np.zeros(0, np.uint64), np.zeros((0, 3)), np.zeros((0, 3), np.uint8), np.zeros(0)
    row_of = {int(p): k for k, p in enumerate(pids)}
    (root / "images").mkdir(parents=True)
    for job in masks:
        job.out_dir.mkdir(parents=True, exist_ok=True)
    tables: Dict[tuple, tuple] = {}
    new_images: List[tuple] = []
    tracks: Dict[int, List[Tuple[int, int]]] = {}

    def pose(im):
        return qvec_to_rotmat(np.array(struct.unpack("<4d", im[1][:32]))), np.array(struct.unpack("<3d", im[1][32:]))

    for n, names in enumerate(groups):
        r_ref, t_ref = pose(by_name[names[0]])
        acc = np.zeros((h, w, 3), np.float64)
        total = np.zeros((h, w), np.float64)
        weights, samples = [], []
        seen = set()
        for name in names:
            im = by_name[name]
            cam = cams[im[2]]
            r_j, _t = pose(im)
            rel = r_j @ r_ref.T  # reference camera -> this camera
            key = (im[2], np.round(rel, 6).tobytes())
            if key not in tables:
                x, y, ok = source_projection(cam)(cam, rays @ rel.T)
                ok = ok & (x >= 0) & (x < cam.width) & (y >= 0) & (y < cam.height)
                tables[key] = ((x - 0.5).astype(np.float32), (y - 0.5).astype(np.float32),
                               _circle_weight(cam, x, y, ok))
            mx, my, wt = tables[key]
            data = np.fromfile(str(images_dir / name), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
            if img is None:
                report.skipped.append(name)
                continue
            acc += cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT) * wt[..., None]
            total += wt
            weights.append(wt)
            samples.append((name, mx, my, img.shape[:2]))
            seen.update(int(p) for p in im[4]["id"][im[4]["id"] >= 0])
        out_name = f"{_group_name(names)}.jpg"
        (root / "images" / out_name).parent.mkdir(parents=True, exist_ok=True)
        pano = np.where(total[..., None] > 0, acc / np.maximum(total, 1e-9)[..., None], 0).astype(np.uint8)
        _write_image(root / "images" / out_name, pano)
        strongest = np.argmax(np.stack(weights), axis=0) if weights else None
        for job in masks:
            ignore = total <= 0  # no lens saw it
            for k, (name, mx, my, shape) in enumerate(samples):
                m = job.get(name)
                if m is None:
                    continue
                src = m.astype(np.uint8) * 255
                if src.shape != shape:
                    src = cv2.resize(src, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
                ignore |= (strongest == k) & (cv2.remap(src, mx, my, cv2.INTER_NEAREST) > 0)
            out = ignore.astype(np.uint8) * 255
            if job.invert:
                out = 255 - out
            mpath = job.out_dir / job.name_pattern.format(stem=key_stem(out_name), name=out_name)
            mpath.parent.mkdir(parents=True, exist_ok=True)
            ok, buf = cv2.imencode(".png", out)
            buf.tofile(str(mpath))
        rows = np.array([row_of[p] for p in sorted(seen) if p in row_of], dtype=int)
        cam_pts = (xyz[rows] @ r_ref.T + t_ref) if rows.size else np.zeros((0, 3))
        x, y, inside = erp.project(cam_pts)
        vid = len(new_images) + 1
        obs = np.zeros(int(inside.sum()), dtype=POINT2D)
        obs["x"], obs["y"] = x[inside], y[inside]
        obs["id"] = pids[rows[inside]].astype(np.int64) if rows.size else []
        for idx, pid in enumerate(obs["id"]):
            tracks.setdefault(int(pid), []).append((vid, idx))
        new_images.append((vid, struct.pack("<4d", *rotmat_to_qvec(r_ref)) + struct.pack("<3d", *t_ref), 1,
                           out_name, obs))
        report.views_out += 1
        if progress:
            progress(n + 1, len(groups))
    kept = {pid for pid, tr in tracks.items() if len(tr) >= 2}
    keep_arr = np.array(sorted(kept), dtype=np.int64)
    for im in new_images:
        im[4]["id"][~np.isin(im[4]["id"], keep_arr)] = -1
    sparse = root / "sparse" / "0"
    sparse.mkdir(parents=True)
    with open(sparse / "cameras.bin", "wb") as f:
        f.write(struct.pack("<QiiQQ2d", 1, 1, MODEL_IDS["EQUIRECTANGULAR"], w, h, float(w), float(h)))
    _write_images_bin(sparse / "images.bin", new_images)
    head = struct.Struct("<Q3d3BdQ")
    with open(sparse / "points3D.bin", "wb") as f:
        f.write(struct.pack("<Q", len(kept)))
        for pid in sorted(kept):
            k = row_of[pid]
            tr = np.array(tracks[pid], dtype=TRACK)
            f.write(head.pack(pid, *xyz[k], *(int(c) for c in rgb[k]), err[k], len(tr)) + tr.tobytes())
    report.points_kept = len(kept)
    report.points_dropped = len(row_of) - len(kept)
    return report
