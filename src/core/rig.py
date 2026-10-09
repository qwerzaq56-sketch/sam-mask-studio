"""A camera rig's dataset, with or without a COLMAP model (docs/specs/06-colmap.md 2.1).

A dual fisheye's images sit in one folder per camera, and its masks the same way::

    <root>/images/cam0/  images/cam1/      (``image/`` too)
    <root>/masks/cam0/   masks/cam1/       (``mask/`` too; none yet before the first masking)

Picking ``<root>``, its ``images/`` or one camera's folder opens the whole rig: every camera
folder, by name (``cam0``, ``cam_1``, ``Camera2`` ...), one level down and no deeper, so a big
folder picked by mistake still finds nothing. Opening checks that nothing is missing: an image
one camera has and another lacks, an image without its mask, a mask without its image.
Its mask folders (``masks/``, ``masks_*/``, ``masks/<set>/``) are offered as Objects, model or not.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from src.engine.imageio import IMG_EXTS, find_images, key_stem

CAMERA_DIR = re.compile(r"^cam(era)?[_-]?\d+$", re.IGNORECASE)
IMAGES_NAMES = ("images", "image")
MASKS_NAMES = ("masks", "mask")
SHOWN = 5  # names listed in a warning before "…"


def camera_dirs(folder: Path) -> List[Path]:
    """The camera folders right under *folder* that hold images, by name."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted((d for d in folder.iterdir() if d.is_dir() and CAMERA_DIR.match(d.name) and find_images(d)),
                  key=lambda d: d.name.lower())


def is_rig(folder: Path) -> bool:
    return len(camera_dirs(folder)) >= 2


def rig_images_dir(folder: Path) -> Optional[Path]:
    """The folder holding the rig's camera folders that *folder* is, is the root of, or is one camera of."""
    folder = Path(folder)
    for cand in [folder] + [folder / n for n in IMAGES_NAMES] + [folder.parent]:
        if is_rig(cand):
            return cand
    return None


def rig_root(images_dir: Path) -> Optional[Path]:
    """The dataset folder of a rig's ``images/``; None when the camera folders sit in a folder of another name."""
    images_dir = Path(images_dir)
    return images_dir.parent if images_dir.name.lower() in IMAGES_NAMES and is_rig(images_dir) else None


def rig_images(images_dir: Path) -> List[Path]:
    """Every camera's images (each camera folder's own, not deeper), sorted by ``cam/name``."""
    images_dir = Path(images_dir)
    found = [p for d in camera_dirs(images_dir) for p in find_images(d)]
    return sorted(found, key=lambda p: p.relative_to(images_dir).as_posix().lower())


def masks_dir(root: Path) -> Optional[Path]:
    """``<root>/masks/`` (or ``mask/``) when it has camera folders."""
    for n in MASKS_NAMES:
        d = Path(root) / n
        if d.is_dir() and any(c.is_dir() and CAMERA_DIR.match(c.name) for c in d.iterdir()):
            return d
    return None


def _has_cameras(folder: Path) -> bool:
    return any(c.is_dir() and CAMERA_DIR.match(c.name) for c in folder.iterdir())


def mask_sets(root: Path) -> List[Path]:
    """The rig's mask folders, each one Object: ``masks/`` (``mask/``) and ``masks_*/`` that hold camera
    folders, and the sets inside ``masks/`` (``masks/<set>/cam0`` ...); by name."""
    root = Path(root)
    if not root.is_dir():
        return []
    out = []
    for d in sorted((d for d in root.iterdir() if d.is_dir()), key=lambda p: p.name.lower()):
        low = d.name.lower()
        if low not in MASKS_NAMES and not low.startswith("masks_"):
            continue
        if _has_cameras(d):
            out.append(d)
        if low in MASKS_NAMES:
            out += sorted((s for s in d.iterdir() if s.is_dir() and not CAMERA_DIR.match(s.name) and _has_cameras(s)),
                          key=lambda p: p.name.lower())
    return out


def _listed(names) -> str:
    names = sorted(names)
    return ", ".join(names[:SHOWN]) + (" …" if len(names) > SHOWN else "")


def check(images_dir: Path, keys: List[str]) -> List[str]:
    """What the rig is missing, one log line each (``⚠ …``); [] when nothing is."""
    from src.core.colmap import mask_file  # late: colmap imports imageio only

    cams = {}
    for k in keys:
        cam, _, name = k.partition("/")
        if name:
            cams.setdefault(cam, set()).add(name)
    out = []
    every = set().union(*cams.values()) if cams else set()
    for cam, names in sorted(cams.items()):
        lacking = every - names
        if lacking:
            out.append(f"⚠ {cam}/ lacks {len(lacking)} image(s) another camera has: {_listed(lacking)}")
    root = rig_root(images_dir)
    md = masks_dir(root) if root is not None else None
    if md is None:
        return out
    for cam, names in sorted(cams.items()):
        no_mask = [n for n in names if mask_file(md, f"{cam}/{n}") is None]
        if no_mask:
            out.append(f"⚠ {md.name}/{cam}/: {len(no_mask)} of {len(names)} image(s) have no mask: {_listed(no_mask)}")
        stems = names | {key_stem(n) for n in names}
        cam_dir = md / cam
        orphans = [] if not cam_dir.is_dir() else [
            f.name for f in cam_dir.iterdir()
            if f.is_file() and f.suffix.lower() in IMG_EXTS and f.stem not in stems]  # a.jpg.png -> a.jpg, a.png -> a
        if orphans:
            out.append(f"⚠ {md.name}/{cam}/: {len(orphans)} mask(s) without an image: {_listed(orphans)}")
    return out

