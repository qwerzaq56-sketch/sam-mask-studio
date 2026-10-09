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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from src.engine.imageio import IMG_EXTS, find_images, key_stem

CAMERA_DIR = re.compile(r"^cam(era)?[_-]?\d+$", re.IGNORECASE)
IMAGES_NAMES = ("images", "image")
MASKS_NAMES = ("masks", "mask")
SHOWN = 5  # names listed in a warning before "…"
CIRCLE_SAMPLES = 16  # frames per camera the image circle is looked for in (as the cli's lens command)


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


@dataclass
class RigDataset:
    """A rig without a model, where Export writes as into a scene (06 2.1 R3): the fields Export reads of a
    ``Scene``, with no model (``model_dir`` None, no camera models, no moments to stitch)."""

    root: Path
    images_dir: Path
    model_dir: Optional[Path] = None
    image_names: List[str] = field(default_factory=list)
    camera_models: List[str] = field(default_factory=list)

    @property
    def mask_dirs(self) -> List[Path]:
        return mask_sets(self.root)

    def rig_groups(self) -> List[List[str]]:
        return []


def rig_dataset(images_dir: Path) -> Optional[RigDataset]:
    """The dataset of a rig's ``images/``; None when its folder is named otherwise (no ``<root>/masks`` to write)."""
    root = rig_root(images_dir)
    return RigDataset(root=root, images_dir=Path(images_dir)) if root is not None else None


def _small(path: Path) -> Optional[np.ndarray]:
    """*path* as RGB, decoded at a quarter size (a 4K frame in ~20 ms): enough to see a circle."""
    import cv2

    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_REDUCED_COLOR_4) if data.size else None
    return None if img is None else cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def find_circles(images_dir: Path, keys: List[str], samples: int = CIRCLE_SAMPLES) -> Dict[str, Optional[dict]]:
    """Each camera's image circle (radius, cx, cy in % of the inscribed circle, as Lens edge keeps them) from
    up to *samples* frames spread over it; None for a camera with no circle to see (not a fisheye).
    How a rig without a model is told to be a fisheye (06 2.1 R4)."""
    from src.core.special import detect_lens_circle

    cams: Dict[str, List[str]] = {}
    for k in keys:
        cams.setdefault(k.rpartition("/")[0], []).append(k)
    out = {}
    for cam, ks in sorted(cams.items()):
        pick = [ks[i] for i in np.unique(np.linspace(0, len(ks) - 1, min(samples, len(ks))).astype(int))]
        frames = [f for f in (_small(Path(images_dir) / k) for k in pick) if f is not None]
        out[cam] = detect_lens_circle(frames) if frames else None
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

