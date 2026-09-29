"""COLMAP scenes: recognising one, reading the model, matching mask files (docs/specs/06-colmap.md)."""

import struct
from pathlib import Path

import cv2
import numpy as np

from src.core.colmap import find_scene, mask_file, matched, read_mask, scene_root, white_share
from src.core.storage import sidecar_dir
from tests.fakes import make_images


def write_model_bin(model: Path, names, points: int = 3) -> None:
    """A tiny sparse model: one PINHOLE camera, *names* as images (two 2D points each), *points* 3D points."""
    model.mkdir(parents=True, exist_ok=True)
    with open(model / "cameras.bin", "wb") as f:
        f.write(struct.pack("<Q", 1))
        f.write(struct.pack("<iiQQ", 1, 1, 64, 48))
        f.write(struct.pack("<4d", 50, 50, 32, 24))
    with open(model / "images.bin", "wb") as f:
        f.write(struct.pack("<Q", len(names)))
        for i, name in enumerate(names, 1):
            f.write(struct.pack("<i7di", i, 1, 0, 0, 0, 0, 0, 0, 1))
            f.write(name.encode() + b"\0")
            f.write(struct.pack("<Q", 2))
            f.write(struct.pack("<ddq", 1.0, 2.0, -1) * 2)
    with open(model / "points3D.bin", "wb") as f:
        f.write(struct.pack("<Q", points))


def make_scene(root: Path, n: int = 4, model_names=None) -> Path:
    make_images(root / "images", n=n)
    names = sorted(p.name for p in (root / "images").iterdir())
    write_model_bin(root / "sparse" / "0", model_names if model_names is not None else names)
    return root


def test_scene_is_recognised_from_the_root_or_its_images(tmp_path):
    root = make_scene(tmp_path / "scene")
    assert scene_root(root) == root and scene_root(root / "images") == root
    assert scene_root(tmp_path) is None
    s = find_scene(root / "images")
    assert s.images_dir == root / "images" and s.model_dir == root / "sparse" / "0"
    assert len(s.image_names) == 4 and s.image_names[0] == "frame_000.png"
    assert s.cameras == 1 and s.camera_models == ["PINHOLE"] and s.points == 3


def test_images_txt_with_an_empty_points_line(tmp_path):
    root = tmp_path / "scene"
    make_images(root / "images", n=2)
    model = root / "sparse" / "0"
    model.mkdir(parents=True)
    (model / "images.txt").write_text(
        "# Image list\n"
        "1 1 0 0 0 0 0 0 1 frame_000.png\n"
        "\n"  # no 2D points
        "2 1 0 0 0 0 0 0 1 my frame 1.png\n"
        "1.0 2.0 -1\n",
        encoding="utf-8",
    )
    (model / "cameras.txt").write_text("1 OPENCV 64 48 1 1 1 1 0 0 0 0\n", encoding="utf-8")
    s = find_scene(root)
    assert s.image_names == ["frame_000.png", "my frame 1.png"] and s.camera_models == ["OPENCV"]


def test_sidecar_goes_beside_the_scene_but_an_old_one_is_kept(tmp_path):
    root = make_scene(tmp_path / "scene")
    assert sidecar_dir(root / "images") == tmp_path / "scene.sms"
    other = tmp_path / "plain"
    make_images(other, n=1)
    assert sidecar_dir(other) == tmp_path / "plain.sms"  # not a scene: as before
    (root / "images.sms").mkdir()  # a project saved inside the scene before v0.4-c1
    assert sidecar_dir(root / "images") == root / "images.sms"


def test_mask_files_match_by_colmap_or_same_name(tmp_path):
    d = tmp_path / "masks"
    d.mkdir()
    m = np.zeros((48, 64), np.uint8)
    m[10:20, 10:20] = 255
    cv2.imwrite(str(d / "a.jpg.png"), m)
    cv2.imwrite(str(d / "b.png"), 255 - m)
    assert mask_file(d, "a.jpg") == d / "a.jpg.png"
    assert mask_file(d, "b.jpg") == d / "b.png"
    assert mask_file(d, "c.jpg") is None
    assert set(matched(d, ["a.jpg", "b.jpg", "c.jpg"])) == {"a.jpg", "b.jpg"}
    assert read_mask(d / "a.jpg.png").sum() == 100
    assert white_share(d, ["b.jpg"]) > 0.9
