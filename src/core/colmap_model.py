"""Writing a COLMAP sparse model without some images (docs/specs/07-export-presets.md 6).

The source model is only read. ``filter_model`` writes a copy to another folder
with the excluded images taken out: their observations leave every 3D point's
track, points left with fewer than two observations are removed (COLMAP's own
rule), and the remaining images forget those points (``point3D_id = -1``).
Binary and text models are both handled, each written in its own format.
"""

from __future__ import annotations

import os
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Set, Tuple

import numpy as np

POINT2D = np.dtype([("x", "<f8"), ("y", "<f8"), ("id", "<i8")])
TRACK = np.dtype([("image", "<i4"), ("point2d", "<i4")])
MODEL_FILES = ("cameras", "images", "points3D")


@dataclass
class FilterReport:
    images_kept: int = 0
    images_dropped: int = 0
    points_kept: int = 0
    points_dropped: int = 0
    skipped_files: Tuple[str, ...] = ()  # model files not carried over (rigs / frames of newer COLMAP)


def filter_model(src: Path, dst: Path, keep_names: Iterable[str]) -> FilterReport:
    """Write *src*'s model to *dst* keeping only the images named in *keep_names*."""
    dst.mkdir(parents=True, exist_ok=True)
    keep = set(keep_names)
    if (src / "images.bin").is_file():
        report = _filter_bin(src, dst, keep)
        cameras = "cameras.bin"
    elif (src / "images.txt").is_file():
        report = _filter_txt(src, dst, keep)
        cameras = "cameras.txt"
    else:
        raise FileNotFoundError(f"No images.bin / images.txt in {src}")
    if (src / cameras).is_file():
        shutil.copy2(src / cameras, dst / cameras)
    known = {f"{n}.{ext}" for n in MODEL_FILES for ext in ("bin", "txt")}
    report.skipped_files = tuple(sorted(p.name for p in src.iterdir() if p.is_file() and p.name not in known))
    return report


# --- binary --------------------------------------------------------------------------------


def _read_images_bin(path: Path) -> List[tuple]:
    """[(image_id, qvec+tvec bytes, camera_id, name, points2D array)]"""
    out = []
    with open(path, "rb") as f:
        (n,) = struct.unpack("<Q", f.read(8))
        for _ in range(n):
            (iid,) = struct.unpack("<i", f.read(4))
            pose = f.read(8 * 7)
            (cid,) = struct.unpack("<i", f.read(4))
            name = bytearray()
            while (c := f.read(1)) not in (b"\0", b""):
                name += c
            (npts,) = struct.unpack("<Q", f.read(8))
            pts = np.frombuffer(f.read(POINT2D.itemsize * npts), dtype=POINT2D).copy()
            out.append((iid, pose, cid, name.decode("utf-8"), pts))
    return out


def _write_images_bin(path: Path, images: List[tuple]) -> None:
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(images)))
        for iid, pose, cid, name, pts in images:
            f.write(struct.pack("<i", iid) + pose + struct.pack("<i", cid))
            f.write(name.encode("utf-8") + b"\0")
            f.write(struct.pack("<Q", len(pts)))
            f.write(pts.astype(POINT2D, copy=False).tobytes())


HEAD3D = struct.Struct("<Q3d3BdQ")  # point3D_id, xyz, rgb, error, track length


def _filter_points_bin(src: Path, dst: Path, dropped_images: Set[int]) -> Tuple[int, Set[int]]:
    """Copy points3D.bin without the dropped images' observations; returns (kept, removed point ids)."""
    removed: Set[int] = set()
    kept = 0
    body = bytearray()
    drop = np.array(sorted(dropped_images), dtype="<i4")
    with open(src, "rb") as f:
        (n,) = struct.unpack("<Q", f.read(8))
        for _ in range(n):
            head = HEAD3D.unpack(f.read(HEAD3D.size))
            track = np.frombuffer(f.read(TRACK.itemsize * head[-1]), dtype=TRACK)
            if drop.size:
                track = track[~np.isin(track["image"], drop)]
            if len(track) < 2:
                removed.add(head[0])
                continue
            body += HEAD3D.pack(*head[:-1], len(track)) + track.tobytes()
            kept += 1
    with open(dst, "wb") as f:
        f.write(struct.pack("<Q", kept))
        f.write(body)
    return kept, removed


def _filter_bin(src: Path, dst: Path, keep: Set[str]) -> FilterReport:
    images = _read_images_bin(src / "images.bin")
    kept = [im for im in images if im[3] in keep]
    dropped = {im[0] for im in images if im[3] not in keep}
    r = FilterReport(images_kept=len(kept), images_dropped=len(dropped))
    removed: Set[int] = set()
    if (src / "points3D.bin").is_file():
        with open(src / "points3D.bin", "rb") as f:
            (total,) = struct.unpack("<Q", f.read(8))
        r.points_kept, removed = _filter_points_bin(src / "points3D.bin", dst / "points3D.bin", dropped)
        r.points_dropped = total - r.points_kept
    if removed:
        gone = np.array(sorted(removed), dtype="<i8")
        for im in kept:
            pts = im[4]
            pts["id"][np.isin(pts["id"], gone)] = -1
    _write_images_bin(dst / "images.bin", kept)
    return r


# --- text ----------------------------------------------------------------------------------


def _filter_txt(src: Path, dst: Path, keep: Set[str]) -> FilterReport:
    lines = (src / "images.txt").read_text(encoding="utf-8").splitlines()
    header = [ln for ln in lines if ln.startswith("#")]
    rows = [ln for ln in lines if not ln.startswith("#")]
    pairs = [(rows[i], rows[i + 1] if i + 1 < len(rows) else "") for i in range(0, len(rows), 2)]
    pairs = [(a, b) for a, b in pairs if len(a.split(maxsplit=9)) == 10]
    kept = [(a, b) for a, b in pairs if a.split(maxsplit=9)[9] in keep]
    dropped = {int(a.split()[0]) for a, b in pairs if a.split(maxsplit=9)[9] not in keep}
    r = FilterReport(images_kept=len(kept), images_dropped=len(dropped))
    removed: Set[int] = set()
    p3 = src / "points3D.txt"
    if p3.is_file():
        out, total = [], 0
        for ln in p3.read_text(encoding="utf-8").splitlines():
            if ln.startswith("#") or not ln.strip():
                out.append(ln)
                continue
            total += 1
            v = ln.split()
            track = [(int(v[i]), v[i + 1]) for i in range(8, len(v) - 1, 2)]
            track = [(im, idx) for im, idx in track if im not in dropped]
            if len(track) < 2:
                removed.add(int(v[0]))
                continue
            out.append(" ".join(v[:8] + [f"{im} {idx}" for im, idx in track]))
        (dst / "points3D.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
        r.points_dropped = len(removed)
        r.points_kept = total - len(removed)
    body = []
    for a, b in kept:
        v = b.split()
        if removed and v:
            for i in range(2, len(v), 3):
                if int(v[i]) in removed:
                    v[i] = "-1"
        body += [a, " ".join(v)]
    (dst / "images.txt").write_text("\n".join(header + body) + "\n", encoding="utf-8")
    return r


# --- a new dataset: images (hard-linked), the filtered model -----------------------------------


@dataclass
class DatasetReport:
    model: FilterReport
    linked: int = 0
    copied: int = 0


def dataset_blocker(root: Path) -> str:
    """Why *root* cannot take a new dataset ("" when it can): it must be new or hold no images/ / sparse/."""
    for name in ("images", "sparse"):
        if (root / name).exists():
            return f"{root} already has {name}/: pick a new folder"
    return ""


def build_dataset(images_dir: Path, model_dir: Path, root: Path, keep: List[str]) -> DatasetReport:
    """``root/images/`` (the kept images, hard-linked where the drive allows, else copied) and
    ``root/sparse/0/`` (the model without the other images). The source is only read."""
    why = dataset_blocker(root)
    if why:
        raise FileExistsError(why)
    out = root / "images"
    out.mkdir(parents=True)
    report = DatasetReport(model=filter_model(model_dir, root / "sparse" / "0", keep))
    for name in keep:
        src, dst = images_dir / name, out / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(src, dst)
            report.linked += 1
        except OSError:
            shutil.copy2(src, dst)
            report.copied += 1
    return report
