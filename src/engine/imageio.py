"""Image reading and working-resolution helpers (Unicode-path safe on Windows)."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def find_images(directory: Path, recursive: bool = False) -> list[Path]:
    """Supported image files in *directory*, sorted by (relative) name.

    *recursive*: also in sub-folders (a multi-camera COLMAP scene: images/cam0/, images/cam1/),
    never inside a mask folder (``masks*``) that may sit among them.
    """
    if not directory.is_dir():
        return []
    if not recursive:
        return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTS)
    found = [
        p for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in IMG_EXTS
        and not any(part.lower().startswith("masks") for part in p.relative_to(directory).parts[:-1])
    ]
    return sorted(found, key=lambda p: p.relative_to(directory).as_posix())


def image_key(directory: Path, path: Path) -> str:
    """The name an image goes by: its path under *directory*, with ``/`` (``cam0/0001.jpg``)."""
    return path.relative_to(directory).as_posix()


def key_stem(key: str) -> str:
    """*key* without its extension, folders kept: ``cam0/0001.jpg`` -> ``cam0/0001``."""
    return key[: -len(Path(key).suffix)] if Path(key).suffix else key


def read_rgb(path: Path) -> np.ndarray:
    """Read an image as RGB uint8. Works with non-ASCII paths (cv2.imread does not)."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def original_size(path: Path) -> Tuple[int, int]:
    """(height, width) of an image file, reading only its header when possible."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
        return h, w
    except Exception:
        h, w = read_rgb(path).shape[:2]
        return h, w


def image_size(path: Path) -> Tuple[int, int]:
    """(height, width) of an image file."""
    h, w = read_rgb(path).shape[:2]
    return h, w


def working_size(h: int, w: int, max_side: int) -> Tuple[int, int]:
    """(height, width) after limiting the longer side to *max_side* (0 = no limit)."""
    if max_side <= 0 or max(h, w) <= max_side:
        return h, w
    s = max_side / float(max(h, w))
    return max(1, int(round(h * s))), max(1, int(round(w * s)))


def to_working(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    th, tw = working_size(h, w, max_side)
    if (th, tw) == (h, w):
        return img
    return cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)


def resize_mask(mask: np.ndarray, hw: Tuple[int, int]) -> np.ndarray:
    """Nearest-neighbour resize of a bool mask to (height, width)."""
    if mask.shape[:2] == tuple(hw):
        return mask
    out = cv2.resize(mask.astype(np.uint8), (hw[1], hw[0]), interpolation=cv2.INTER_NEAREST)
    return out > 0
