"""ERP -> pinhole views (docs/specs/08-erp-to-pinhole.md): the math, then a whole small scene."""

import struct
from pathlib import Path

import cv2
import numpy as np

from src.core.colmap import Camera, read_cameras_full, read_image_names_bin
from src.core.colmap_model import POINT2D, TRACK, _read_images_bin
from src.core.reproject import (
    MaskJob,
    Views,
    convert_to_pinhole,
    project_equirect,
    qvec_to_rotmat,
    remap_tables,
    rotmat_to_qvec,
    view_name,
    view_rotation,
)

W, H = 256, 128
ERP = Camera(1, "EQUIRECTANGULAR", W, H, (W, H))


def test_quaternion_round_trip():
    rng = np.random.default_rng(1)
    for _ in range(20):
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        q = q if q[0] >= 0 else -q
        assert np.allclose(rotmat_to_qvec(qvec_to_rotmat(q)), q, atol=1e-9)


def test_view_axes():
    assert np.allclose(view_rotation(0, 0), np.eye(3))
    assert np.allclose(view_rotation(90, 0)[2], [1, 0, 0])  # yaw 90: looks right (+X)
    assert np.allclose(view_rotation(0, 90)[2], [0, -1, 0], atol=1e-12)  # pitch up: looks at -Y (up)
    r = view_rotation(123, -20)
    assert np.allclose(r @ r.T, np.eye(3)) and np.isclose(np.linalg.det(r), 1)


def test_equirect_projection_matches_colmap():
    x, y, _ = project_equirect(ERP, np.array([[0, 0, 1.0], [1, 0, 0], [0, -1, 0]]))
    assert np.allclose(x[:2], [W / 2, W * 0.75]) and np.allclose(y[:2], [H / 2, H / 2])  # forward, right
    assert np.isclose(y[2], 0)  # straight up: the top edge


def test_a_view_shows_the_right_part_of_the_panorama():
    erp = np.zeros((H, W, 3), np.uint8)
    erp[:, int(W * 0.75) - 4: int(W * 0.75) + 4] = (0, 0, 255)  # a red stripe at azimuth +90°
    side = 64
    f = side / 2 / np.tan(np.radians(45))
    mx, my = remap_tables(ERP, view_rotation(90, 0), side, f)
    view = cv2.remap(erp, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    assert tuple(view[side // 2, side // 2]) == (0, 0, 255)
    mx, my = remap_tables(ERP, view_rotation(0, 0), side, f)
    front = cv2.remap(erp, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    assert tuple(front[side // 2, side // 2]) == (0, 0, 0)


def test_view_names():
    assert view_name("frame_010", 90, -35) == "frame_010_y090_pm35"
    assert view_name("a", 0, 0) == "a_y000_p00" and view_name("a", 270, 35) == "a_y270_p35"


# --- a whole ERP scene ------------------------------------------------------------------------


def make_erp_scene(root: Path):
    """Two ERP images 1 m apart along X; five 3D points ahead / right / behind, seen by both."""
    (root / "images").mkdir(parents=True)
    names = ["a.jpg", "b.jpg"]
    for i, n in enumerate(names):
        img = np.full((H, W, 3), 60 + 60 * i, np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        buf.tofile(str(root / "images" / n))
    model = root / "sparse" / "0"
    model.mkdir(parents=True)
    with open(model / "cameras.bin", "wb") as f:
        f.write(struct.pack("<QiiQQ2d", 1, 1, 17, W, H, W, H))
    world = np.array([[0, 0, 5], [5, 0, 0], [0, 0, -5], [-5, 0, 0.5], [0.5, -3, 3]], float)
    centers = [np.zeros(3), np.array([1.0, 0, 0])]
    with open(model / "images.bin", "wb") as f:
        f.write(struct.pack("<Q", 2))
        for iid, (n, c) in enumerate(zip(names, centers), 1):
            t = -c  # identity rotation: t = -R c
            obs = np.zeros(len(world), POINT2D)
            obs["id"] = np.arange(1, len(world) + 1)
            f.write(struct.pack("<i4d3di", iid, 1, 0, 0, 0, *t, 1) + n.encode() + b"\0")
            f.write(struct.pack("<Q", len(obs)) + obs.tobytes())
    with open(model / "points3D.bin", "wb") as f:
        f.write(struct.pack("<Q", len(world)))
        for pid, p in enumerate(world, 1):
            tr = np.array([(1, pid - 1), (2, pid - 1)], TRACK)
            f.write(struct.pack("<Q3d3BdQ", pid, *p, 10, 20, 30, 0.1, 2) + tr.tobytes())
    return names


def test_convert_a_scene_to_pinhole_views(tmp_path):
    src = tmp_path / "scene"
    names = make_erp_scene(src)
    out = tmp_path / "pinhole"
    mask = np.zeros((H, W), bool)
    mask[:, int(W * 0.75) - 10: int(W * 0.75) + 10] = True  # an object to the right
    job = MaskJob(out / "masks", "{name}.png", invert=True, include_empty=True, get=lambda k: mask if k == "a.jpg" else None)
    r = convert_to_pinhole(src / "images", src / "sparse" / "0", out, names, Views(size=64), [job])
    assert (r.images_in, r.views_out, r.side) == (2, 24, 64) and not r.skipped
    assert len(list((out / "images").iterdir())) == 24 and len(list((out / "masks").iterdir())) == 24
    [cam] = read_cameras_full(out / "sparse" / "0").values()
    assert cam.model == "PINHOLE" and (cam.width, cam.height) == (64, 64) and np.isclose(cam.params[0], 32)
    assert read_image_names_bin(out / "sparse" / "0" / "images.bin")[0] == "a_y000_pm35.jpg"
    right = cv2.imread(str(out / "masks" / "a_y090_p00.jpg.png"), cv2.IMREAD_GRAYSCALE)
    front = cv2.imread(str(out / "masks" / "a_y000_p00.jpg.png"), cv2.IMREAD_GRAYSCALE)
    assert right[32, 32] == 0 and front.min() == 255  # the object (black) is in the right view only
    # the point straight ahead of image a (0, 0, 5) sits at the center of a's front view
    imgs = {name: (pose, pts) for _, pose, _, name, pts in _read_images_bin(out / "sparse" / "0" / "images.bin")}
    pose, pts = imgs["a_y000_p00.jpg"]
    p1 = pts[pts["id"] == 1]
    assert len(p1) == 1 and np.allclose([p1["x"][0], p1["y"][0]], [32, 32])
    q, t = np.array(struct.unpack("<4d", pose[:32])), np.array(struct.unpack("<3d", pose[32:]))
    assert np.allclose(qvec_to_rotmat(q), np.eye(3)) and np.allclose(t, 0)
    # the point to the right (5, 0, 0) is in a's yaw-90 view, near the center
    pose, pts = imgs["a_y090_p00.jpg"]
    p2 = pts[pts["id"] == 2]
    assert len(p2) == 1 and abs(p2["x"][0] - 32) < 1e-6
    assert r.points_kept == 5  # every point is seen by both images' views
