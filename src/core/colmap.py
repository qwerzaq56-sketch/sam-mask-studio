"""COLMAP scenes: recognise one, read what the model holds, find mask folders (docs/specs/06-colmap.md).

A scene is a folder with ``images/`` and a sparse model (``sparse/0/`` or
``sparse/``) holding ``images.bin`` or ``images.txt``. Only reading here:
the source scene is never changed (docs/specs/07-export-presets.md).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np

from src.engine.imageio import IMG_EXTS

MODEL_FILES = ("images.bin", "images.txt")


@dataclass
class Scene:
    root: Path
    images_dir: Path
    model_dir: Path
    image_names: List[str] = field(default_factory=list)  # the images the model registered
    cameras: int = 0
    points: int = 0
    camera_models: List[str] = field(default_factory=list)

    @property
    def mask_dirs(self) -> List[Path]:
        """``masks/`` and ``masks_*/`` in the scene, by name."""
        return sorted(p for p in self.root.iterdir() if p.is_dir() and (p.name == "masks" or p.name.startswith("masks_")))

    def summary(self) -> str:
        return f"COLMAP scene {self.root.name}: {len(self.image_names)} images in the model, " \
               f"{self.cameras} camera(s), {self.points} 3D points"


def _model_dir(root: Path) -> Optional[Path]:
    sparse = root / "sparse"
    if not sparse.is_dir():
        return None
    for d in [sparse / "0", sparse] + sorted(p for p in sparse.iterdir() if p.is_dir()):
        if any((d / f).is_file() for f in MODEL_FILES):
            return d
    return None


def scene_root(folder: Path) -> Optional[Path]:
    """The scene *folder* is, or is the ``images*`` folder of; None when it is not a COLMAP scene."""
    folder = Path(folder)
    if (folder / "images").is_dir() and _model_dir(folder) is not None:
        return folder
    if folder.name.startswith("images") and _model_dir(folder.parent) is not None:
        return folder.parent
    return None


def find_scene(folder: Path) -> Optional[Scene]:
    root = scene_root(folder)
    if root is None:
        return None
    folder = Path(folder)
    images_dir = folder if folder != root else root / "images"
    model = _model_dir(root)
    scene = Scene(root=root, images_dir=images_dir, model_dir=model)
    try:
        if (model / "images.bin").is_file():
            scene.image_names = read_image_names_bin(model / "images.bin")
        else:
            scene.image_names = read_image_names_txt(model / "images.txt")
        scene.cameras, scene.camera_models = read_cameras(model)
        scene.points = count_points(model)
    except (OSError, ValueError, struct.error):
        pass  # a damaged model: the images still open; the summary shows what could be read
    return scene


# --- the model files (COLMAP's documented binary / text layout) --------------------------

CAMERA_MODELS = {  # id: (name, number of params)
    0: ("SIMPLE_PINHOLE", 3), 1: ("PINHOLE", 4), 2: ("SIMPLE_RADIAL", 4), 3: ("RADIAL", 5),
    4: ("OPENCV", 8), 5: ("OPENCV_FISHEYE", 8), 6: ("FULL_OPENCV", 12), 7: ("FOV", 5),
    8: ("SIMPLE_RADIAL_FISHEYE", 4), 9: ("RADIAL_FISHEYE", 5), 10: ("THIN_PRISM_FISHEYE", 12),
    11: ("RAD_TAN_THIN_PRISM_FISHEYE", 16), 12: ("SIMPLE_DIVISION", 4), 13: ("DIVISION", 5),
    14: ("SIMPLE_FISHEYE", 3), 15: ("FISHEYE", 4), 16: ("EUCM", 6),
    17: ("EQUIRECTANGULAR", 2),  # 360: params w, h (colmap/sensor/models/spherical.h)
}
MODEL_IDS = {name: mid for mid, (name, _n) in CAMERA_MODELS.items()}


@dataclass(frozen=True)
class Camera:
    id: int
    model: str
    width: int
    height: int
    params: tuple


def read_image_names_bin(path: Path) -> List[str]:
    names = []
    with open(path, "rb") as f:
        (n,) = struct.unpack("<Q", f.read(8))
        for _ in range(n):
            f.read(4 + 8 * 7 + 4)  # image_id, qvec, tvec, camera_id
            name = bytearray()
            while (c := f.read(1)) not in (b"\0", b""):
                name += c
            names.append(name.decode("utf-8"))
            (npts,) = struct.unpack("<Q", f.read(8))
            f.seek(24 * npts, 1)  # x, y (double), point3D_id (int64)
    return names


def read_image_names_txt(path: Path) -> List[str]:
    """images.txt: two lines per image, the first ending in the name (lines with # are comments).

    The second line (the 2D points) is empty for an image without points, so blank lines count.
    """
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    return [ln.split(maxsplit=9)[9] for ln in lines[0::2] if len(ln.split(maxsplit=9)) == 10]


def read_cameras_full(model: Path) -> Dict[int, Camera]:
    """Every camera of cameras.bin / cameras.txt (empty when missing or unreadable)."""
    b, t = model / "cameras.bin", model / "cameras.txt"
    cams: Dict[int, Camera] = {}
    if b.is_file():
        with open(b, "rb") as f:
            (n,) = struct.unpack("<Q", f.read(8))
            for _ in range(n):
                cid, mid = struct.unpack("<ii", f.read(8))
                w, h = struct.unpack("<QQ", f.read(16))
                if mid not in CAMERA_MODELS:
                    cams[cid] = Camera(cid, f"model {mid}", w, h, ())
                    break  # unknown parameter count: cannot read further
                name, nparams = CAMERA_MODELS[mid]
                cams[cid] = Camera(cid, name, w, h, struct.unpack(f"<{nparams}d", f.read(8 * nparams)))
    elif t.is_file():
        for ln in t.read_text(encoding="utf-8").splitlines():
            v = ln.split()
            if ln.startswith("#") or len(v) < 4:
                continue
            cams[int(v[0])] = Camera(int(v[0]), v[1], int(v[2]), int(v[3]), tuple(float(x) for x in v[4:]))
    return cams


def read_cameras(model: Path) -> tuple:
    """(count, model names) from cameras.bin / cameras.txt; (0, []) when missing."""
    cams = read_cameras_full(model)
    return len(cams), sorted({c.model for c in cams.values()})


def count_points(model: Path) -> int:
    b, t = model / "points3D.bin", model / "points3D.txt"
    if b.is_file():
        with open(b, "rb") as f:
            return struct.unpack("<Q", f.read(8))[0]
    if t.is_file():
        return sum(1 for ln in t.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#"))
    return 0


# --- mask folders ----------------------------------------------------------------------------


def mask_file(mask_dir: Path, image_name: str) -> Optional[Path]:
    """The mask of *image_name*: ``a.jpg.png`` (COLMAP) or ``a.png`` / ``a.<image ext>`` (same name)."""
    stem = Path(image_name).stem
    for cand in [mask_dir / f"{image_name}.png", mask_dir / f"{stem}.png"] + [
        mask_dir / f"{stem}{ext}" for ext in sorted(IMG_EXTS) if ext != ".png"
    ]:
        if cand.is_file():
            return cand
    return None


def read_mask(path: Path) -> Optional[np.ndarray]:
    """A mask file as bool (white = True); None if unreadable. An alpha channel wins over gray."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data.size else None
    if img is None:
        return None
    if img.ndim == 3:
        img = img[:, :, 3] if img.shape[2] == 4 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img > 127


def white_share(mask_dir: Path, image_names: List[str], sample: int = 12) -> Optional[float]:
    """The share of white pixels over a few masks (to suggest which color is the object)."""
    picked = image_names[:: max(1, len(image_names) // sample)][:sample]
    shares = []
    for name in picked:
        p = mask_file(mask_dir, name)
        m = read_mask(p) if p is not None else None
        if m is not None:
            shares.append(float(m.mean()))
    return sum(shares) / len(shares) if shares else None


def matched(mask_dir: Path, image_names: List[str]) -> Dict[str, Path]:
    """image name -> its mask file, for the images that have one."""
    out = {}
    for name in image_names:
        p = mask_file(mask_dir, name)
        if p is not None:
            out[name] = p
    return out
