"""A camera rig's dataset without a COLMAP model (docs/specs/06-colmap.md 2.1)."""

import cv2
import numpy as np

from src.core.rig import camera_dirs, check, rig_images, rig_images_dir, rig_root
from src.core.storage import sidecar_dir
from tests.fakes import make_images


def make_rig(root, n=2, masks=True):
    for cam in ("cam0", "cam1"):
        make_images(root / "images" / cam, n=n)
        if masks:
            (root / "masks" / cam).mkdir(parents=True)
            for i in range(n):
                cv2.imwrite(str(root / "masks" / cam / f"frame_{i:03d}.png.png"), np.zeros((4, 4), np.uint8))
    return root


def test_the_rig_is_found_from_its_root_images_or_one_camera(tmp_path):
    root = make_rig(tmp_path / "rig")
    images = root / "images"
    for picked in (root, images, images / "cam0", images / "cam1"):
        assert rig_images_dir(picked) == images
    assert rig_root(images) == root
    assert sidecar_dir(images) == tmp_path / "rig.sms"  # beside the dataset, as a scene's


def test_only_camera_named_folders_one_level_down(tmp_path):
    images = tmp_path / "rig" / "images"
    for name in ("cam0", "Camera_1", "front", "masks_old"):
        make_images(images / name, n=1)
    make_images(images / "cam0" / "deeper", n=1)
    (images / "cam9").mkdir()  # no images: not a camera
    assert [d.name for d in camera_dirs(images)] == ["cam0", "Camera_1"]
    assert [p.relative_to(images).as_posix() for p in rig_images(images)] == [
        "cam0/frame_000.png", "Camera_1/frame_000.png"]


def test_one_camera_or_a_big_folder_is_no_rig(tmp_path):
    make_images(tmp_path / "solo" / "images" / "cam0", n=1)
    assert rig_images_dir(tmp_path / "solo") is None
    make_rig(tmp_path / "big" / "scene_a")  # the rig two levels down: not looked for
    assert rig_images_dir(tmp_path / "big") is None


def test_check_finds_what_is_missing(tmp_path):
    root = make_rig(tmp_path / "rig", n=3)
    images = root / "images"
    keys = [p.relative_to(images).as_posix() for p in rig_images(images)]
    assert check(images, keys) == []
    (images / "cam1" / "frame_002.png").unlink()
    (root / "masks" / "cam0" / "frame_001.png.png").unlink()
    cv2.imwrite(str(root / "masks" / "cam0" / "frame_009.png.png"), np.zeros((4, 4), np.uint8))
    keys = [p.relative_to(images).as_posix() for p in rig_images(images)]
    lines = check(images, keys)
    assert any("cam1/ lacks 1 image(s)" in s and "frame_002.png" in s for s in lines)
    assert any("masks/cam0/: 1 of 3 image(s) have no mask: frame_001.png" in s for s in lines)
    assert any("masks/cam0/: 1 mask(s) without an image: frame_009.png.png" in s for s in lines)
    assert any("masks/cam1/: 1 mask(s) without an image: frame_002.png.png" in s for s in lines)  # its image gone
    assert len(lines) == 4


def test_same_name_masks_count_too(tmp_path):
    root = make_rig(tmp_path / "rig", n=1, masks=False)
    for cam in ("cam0", "cam1"):
        (root / "mask" / cam).mkdir(parents=True)
        cv2.imwrite(str(root / "mask" / cam / "frame_000.png"), np.zeros((4, 4), np.uint8))
    images = root / "images"
    assert check(images, ["cam0/frame_000.png", "cam1/frame_000.png"]) == []
