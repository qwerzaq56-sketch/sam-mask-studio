"""Projection conversion of a COLMAP scene (docs/specs/08-erp-to-pinhole.md).

The converter walks the *target* pixels: each one becomes a ray, and the
*source* camera model's projection (ray -> pixel) says where to sample the
source image. Adding a source model therefore means adding one projection
function (``SOURCE_PROJECTIONS``). P1: EQUIRECTANGULAR -> pinhole views.

Camera frame (COLMAP): X right, Y down, Z forward. Pixel coordinates put the
upper-left corner at (0, 0), so pixel centers are at i + 0.5.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.core.colmap import MODEL_IDS, Camera, read_cameras_full
from src.core.colmap_model import POINT2D, TRACK, _read_images_bin, _write_images_bin, dataset_blocker

DEFAULT_YAWS = (0.0, 90.0, 180.0, 270.0)
DEFAULT_PITCHES = (-35.0, 0.0, 35.0)
DEFAULT_FOV = 90.0


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


# --- source projections: rays (N, 3) in the source camera frame -> pixels -------------------------


def project_equirect(cam: Camera, rays: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    w, h = cam.params[0], cam.params[1]
    x, y, z = rays[..., 0], rays[..., 1], rays[..., 2]
    theta = np.arctan2(x, z)
    phi = np.arctan2(-y, np.hypot(x, z))
    return (theta / (2 * np.pi) + 0.5) * w, (0.5 - phi / np.pi) * h, np.ones(theta.shape, bool)


SOURCE_PROJECTIONS: Dict[str, Callable] = {"EQUIRECTANGULAR": project_equirect}


# --- pinhole views ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Views:
    yaws: Tuple[float, ...] = DEFAULT_YAWS
    pitches: Tuple[float, ...] = DEFAULT_PITCHES
    fov: float = DEFAULT_FOV
    size: int = 0  # square views; 0 = the source width / 4 (the equator's resolution at 90°)

    def pairs(self) -> List[Tuple[float, float]]:
        return [(y, p) for p in self.pitches for y in self.yaws]

    def side(self, source_width: int) -> int:
        s = self.size or max(64, source_width // 4)
        return int(s) // 2 * 2

    def focal(self, side: int) -> float:
        return side / 2.0 / np.tan(np.radians(self.fov) / 2.0)


def view_name(stem: str, yaw: float, pitch: float) -> str:
    """``frame_010_y090_pm35`` (m = minus)."""
    p = int(round(pitch))
    return f"{stem}_y{int(round(yaw)) % 360:03d}_p{'m' if p < 0 else ''}{abs(p):02d}"


def remap_tables(src: Camera, rot: np.ndarray, side: int, focal: float) -> Tuple[np.ndarray, np.ndarray]:
    """cv2.remap maps (pixel-index coordinates) sampling *src* for a pinhole view turned by *rot*."""
    c = side / 2.0
    j, i = np.meshgrid(np.arange(side) + 0.5, np.arange(side) + 0.5)
    rays = np.stack([(j - c) / focal, (i - c) / focal, np.ones_like(j)], axis=-1) @ rot  # view -> source
    x, y, _ok = SOURCE_PROJECTIONS[src.model](src, rays)
    return (x - 0.5).astype(np.float32), (y - 0.5).astype(np.float32)


@dataclass
class MaskJob:
    """Masks written beside the converted images, remapped like them."""

    out_dir: Path
    name_pattern: str  # "{name}.png" / "{stem}.png"
    invert: bool  # write the object black
    include_empty: bool
    get: Callable[[str], Optional[np.ndarray]]  # image key -> the full-resolution mask (bool), None = none


@dataclass
class ConvertReport:
    images_in: int = 0
    views_out: int = 0
    points_kept: int = 0
    points_dropped: int = 0
    side: int = 0
    skipped: List[str] = field(default_factory=list)  # images whose camera cannot be converted


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


def convert_to_pinhole(images_dir: Path, model_dir: Path, root: Path, keep: Sequence[str], views: Views,
                       masks: Sequence[MaskJob] = (), progress: Optional[Callable[[int, int], None]] = None
                       ) -> ConvertReport:
    """``root/images`` + ``root/sparse/0`` (binary) with pinhole views of the kept images, and the masks.

    Only images whose camera model has a source projection are converted; the source is only read.
    """
    why = dataset_blocker(root)
    if why:
        raise FileExistsError(why)
    if not (model_dir / "images.bin").is_file():
        raise ValueError("Pinhole conversion reads a binary model (images.bin); convert the text model with COLMAP first")
    cams = read_cameras_full(model_dir)
    keep_set = set(keep)
    images = [im for im in _read_images_bin(model_dir / "images.bin") if im[3] in keep_set]
    report = ConvertReport(images_in=len(images))
    convertible = [im for im in images if cams.get(im[2]) is not None and cams[im[2]].model in SOURCE_PROJECTIONS]
    report.skipped = [im[3] for im in images if im not in convertible]
    if not convertible:
        raise ValueError("No image here uses a camera this can convert (EQUIRECTANGULAR)")
    side = views.side(max(cams[im[2]].width for im in convertible))
    focal = views.focal(side)
    report.side = side
    pairs = views.pairs()
    rots = [view_rotation(y, p) for y, p in pairs]
    if (model_dir / "points3D.bin").is_file():
        pids, xyz, rgb, err = _read_points(model_dir / "points3D.bin")
    else:
        pids, xyz, rgb, err = np.zeros(0, np.uint64), np.zeros((0, 3)), np.zeros((0, 3), np.uint8), np.zeros(0)
    row_of = {int(p): i for i, p in enumerate(pids)}
    out_img = root / "images"
    out_img.mkdir(parents=True)
    for job in masks:
        job.out_dir.mkdir(parents=True, exist_ok=True)
    tables: Dict[Tuple[int, int], tuple] = {}  # (camera id, view) -> remap tables, reused across images
    new_images: List[tuple] = []
    tracks: Dict[int, List[Tuple[int, int]]] = {}
    next_id = 1
    for n, (iid, pose, cid, name, pts) in enumerate(convertible):
        cam = cams[cid]
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
        stem = Path(name).stem
        for v, ((yaw, pitch), rot) in enumerate(zip(pairs, rots)):
            key = (cid, v)
            if key not in tables:
                tables[key] = remap_tables(cam, rot, side, focal)
            mx, my = tables[key]
            vname = view_name(stem, yaw, pitch) + ".jpg"
            _write_image(out_img / vname, cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP))
            for job, m in zip(masks, full_masks):
                if m is None and not job.include_empty:
                    continue
                src = (m.astype(np.uint8) * 255) if m is not None else np.zeros(img.shape[:2], np.uint8)
                if src.shape != img.shape[:2]:
                    src = cv2.resize(src, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
                out = cv2.remap(src, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_WRAP)
                if job.invert:
                    out = 255 - out
                mname = job.name_pattern.format(stem=Path(vname).stem, name=vname)
                ok, buf = cv2.imencode(".png", out)
                buf.tofile(str(job.out_dir / mname))
            # the view's pose and the 3D points it sees
            r_view = rot @ r_src
            t_view = rot @ t
            vp = cam_pts @ rot.T
            ok = vp[:, 2] > 1e-9
            x = focal * vp[:, 0] / np.where(ok, vp[:, 2], 1) + side / 2.0
            y = focal * vp[:, 1] / np.where(ok, vp[:, 2], 1) + side / 2.0
            inside = ok & (x >= 0) & (x < side) & (y >= 0) & (y < side)
            vid = next_id
            next_id += 1
            obs = np.zeros(int(inside.sum()), dtype=POINT2D)
            obs["x"], obs["y"] = x[inside], y[inside]
            obs["id"] = pids[rows[inside]].astype(np.int64) if rows.size else []
            for idx, pid in enumerate(obs["id"]):
                tracks.setdefault(int(pid), []).append((vid, idx))
            new_pose = struct.pack("<4d", *rotmat_to_qvec(r_view)) + struct.pack("<3d", *t_view)
            new_images.append((vid, new_pose, 1, vname, obs))
            report.views_out += 1
        if progress:
            progress(n + 1, len(convertible))
    # points: keep those seen twice or more; the views forget the rest
    kept = {pid for pid, tr in tracks.items() if len(tr) >= 2}
    for im in new_images:
        gone = ~np.isin(im[4]["id"], np.array(sorted(kept), dtype=np.int64))
        im[4]["id"][gone] = -1
    sparse = root / "sparse" / "0"
    sparse.mkdir(parents=True)
    with open(sparse / "cameras.bin", "wb") as f:
        f.write(struct.pack("<QiiQQ", 1, 1, MODEL_IDS["PINHOLE"], side, side))
        f.write(struct.pack("<4d", focal, focal, side / 2.0, side / 2.0))
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
