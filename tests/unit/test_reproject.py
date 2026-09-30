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


# --- p30: fisheye sources, a 360 target -------------------------------------------------------


def test_fisheye_projection_follows_colmap():
    from src.core.reproject import source_projection

    f, c = 100.0, 200.0
    plain = Camera(1, "OPENCV_FISHEYE", 400, 400, (f, f, c, c, 0, 0, 0, 0))
    a = 0.6  # 0.6 rad off the axis, to the right
    x, y, ok = source_projection(plain)(plain, np.array([[np.tan(a), 0, 1.0]]))
    assert np.isclose(x[0], f * a + c) and np.isclose(y[0], c) and ok[0]  # equidistant: r = f * theta
    k1 = 0.1
    dist = Camera(1, "OPENCV_FISHEYE", 400, 400, (f, f, c, c, k1, 0, 0, 0))
    x, _, _ = source_projection(dist)(dist, np.array([[np.tan(a), 0, 1.0]]))
    assert np.isclose(x[0], f * a * (1 + k1 * a * a) + c)
    side = Camera(1, "SIMPLE_RADIAL_FISHEYE", 400, 400, (f, c, c, k1))
    assert np.isclose(source_projection(side)(side, np.array([[np.tan(a), 0, 1.0]]))[0][0], x[0])
    x, _, ok = source_projection(plain)(plain, np.array([[1.0, 0, -0.2]]))  # past 90°: a fisheye still sees it
    assert ok[0] and x[0] > f * np.pi / 2 + c - 1e-9


def make_fisheye_scene(root: Path, f: float = 40.0, size: int = 160):
    """Two OPENCV_FISHEYE images (one lens, looking along +Z) 1 m apart; points ahead."""
    (root / "images").mkdir(parents=True)
    names = ["f0.jpg", "f1.jpg"]
    yy, xx = np.mgrid[0:size, 0:size]
    for n in names:
        img = np.zeros((size, size, 3), np.uint8)
        img[(xx - size / 2) ** 2 + (yy - size / 2) ** 2 < (size / 2 - 2) ** 2] = (0, 200, 0)  # the image circle
        ok, buf = cv2.imencode(".jpg", img)
        buf.tofile(str(root / "images" / n))
    model = root / "sparse" / "0"
    model.mkdir(parents=True)
    with open(model / "cameras.bin", "wb") as fh:
        fh.write(struct.pack("<QiiQQ8d", 1, 1, 5, size, size, f, f, size / 2, size / 2, 0, 0, 0, 0))
    world = np.array([[0, 0, 5], [2, 0, 4], [-2, 1, 4]], float)
    with open(model / "images.bin", "wb") as fh:
        fh.write(struct.pack("<Q", 2))
        for iid, n in enumerate(names, 1):
            obs = np.zeros(len(world), POINT2D)
            obs["id"] = np.arange(1, len(world) + 1)
            fh.write(struct.pack("<i4d3di", iid, 1, 0, 0, 0, -(iid - 1.0), 0, 0, 1) + n.encode() + b"\0")
            fh.write(struct.pack("<Q", len(obs)) + obs.tobytes())
    with open(model / "points3D.bin", "wb") as fh:
        fh.write(struct.pack("<Q", len(world)))
        for pid, p in enumerate(world, 1):
            fh.write(struct.pack("<Q3d3BdQ", pid, *p, 1, 2, 3, 0.1, 2) + np.array([(1, pid - 1), (2, pid - 1)], TRACK).tobytes())
    return names


def test_fisheye_to_360_marks_what_the_lens_never_saw(tmp_path):
    from src.core.reproject import Erp, convert

    src = tmp_path / "fish"
    names = make_fisheye_scene(src)
    out = tmp_path / "erp"
    job = MaskJob(out / "masks", "{name}.png", invert=True, include_empty=True, get=lambda k: None)
    r = convert(src / "images", src / "sparse" / "0", out, names, Erp(), [job])
    w = int(round(2 * np.pi * 40)) // 2 * 2
    assert r.views_out == 2 and r.side == w and r.points_kept == 3
    [cam] = read_cameras_full(out / "sparse" / "0").values()
    assert cam.model == "EQUIRECTANGULAR" and (cam.width, cam.height) == (w, w // 2)
    img = cv2.imread(str(out / "images" / "f0.jpg"))
    m = cv2.imread(str(out / "masks" / "f0.jpg.png"), cv2.IMREAD_GRAYSCALE)
    h = w // 2
    assert img[h // 2, w // 2][1] > 150  # straight ahead: the lens's green circle
    assert m[h // 2, w // 2] == 255 and m[h // 2, 2] == 0  # ahead: trained · behind: ignored (black)
    imgs = {name: pts for _, _, _, name, pts in _read_images_bin(out / "sparse" / "0" / "images.bin")}
    p1 = imgs["f0.jpg"][imgs["f0.jpg"]["id"] == 1]
    assert np.allclose([p1["x"][0], p1["y"][0]], [w / 2, h / 2])  # the point ahead: the 360 image's center


def test_fisheye_to_pinhole_views(tmp_path):
    from src.core.reproject import convert

    src = tmp_path / "fish"
    names = make_fisheye_scene(src)
    out = tmp_path / "pin"
    job = MaskJob(out / "masks", "{name}.png", invert=True, include_empty=True, get=lambda k: None)
    r = convert(src / "images", src / "sparse" / "0", out, names, Views(yaws=(-45, 0, 45), pitches=(0,)), [job])
    assert r.views_out == 6
    front = cv2.imread(str(out / "images" / "f0_y000_p00.jpg"))
    s = front.shape[0]
    assert front[s // 2, s // 2][1] > 150
    assert cv2.imread(str(out / "masks" / "f0_y000_p00.jpg.png"), cv2.IMREAD_GRAYSCALE).min() == 255  # all seen


# --- p32: a dual fisheye rig stitched into 360 images ---------------------------------------------


def make_dual_fisheye_scene(root: Path, frames: int = 2, size: int = 160, with_frames_bin: bool = False):
    """cam0 looks along +Z (a red picture circle), cam1 back along -Z (blue); circles reach ~95°."""
    f = (size / 2) / np.radians(95)
    yy, xx = np.mgrid[0:size, 0:size]
    circle = (xx + 0.5 - size / 2) ** 2 + (yy + 0.5 - size / 2) ** 2 < (size / 2) ** 2
    names = []
    for cam, color in (("cam0", (0, 0, 220)), ("cam1", (220, 0, 0))):
        (root / "images" / cam).mkdir(parents=True)
        for k in range(frames):
            img = np.zeros((size, size, 3), np.uint8)
            img[circle] = color
            ok, buf = cv2.imencode(".png", img)
            buf.tofile(str(root / "images" / cam / f"{k:03d}.png"))
            names.append(f"{cam}/{k:03d}.png")
    model = root / "sparse" / "0"
    model.mkdir(parents=True)
    with open(model / "cameras.bin", "wb") as fh:
        fh.write(struct.pack("<Q", 2))
        for cid in (1, 2):
            fh.write(struct.pack("<iiQQ8d", cid, 5, size, size, f, f, size / 2, size / 2, 0, 0, 0, 0))
    world = np.array([[0, 0, 5], [0, 0, -5], [3, 0.5, 0]], float)
    back = np.diag([-1.0, 1, -1])  # cam1: turned 180° about Y
    q_back = rotmat_to_qvec(back)
    images = []  # (id, camera, name, R, t)
    iid = 1
    for k in range(frames):
        c = np.array([0.5 * k, 0, 0])
        images.append((iid, 1, f"cam0/{k:03d}.png", np.eye(3), -c))
        images.append((iid + 1, 2, f"cam1/{k:03d}.png", back, -back @ c))
        iid += 2
    with open(model / "images.bin", "wb") as fh:
        fh.write(struct.pack("<Q", len(images)))
        for iid, cid, name, r, t in images:
            obs = np.zeros(len(world), POINT2D)
            obs["id"] = np.arange(1, len(world) + 1)
            q = rotmat_to_qvec(r)
            fh.write(struct.pack("<i4d3di", iid, *q, *t, cid) + name.encode() + b"\0")
            fh.write(struct.pack("<Q", len(obs)) + obs.tobytes())
    with open(model / "points3D.bin", "wb") as fh:
        fh.write(struct.pack("<Q", len(world)))
        for pid, p in enumerate(world, 1):
            tr = np.array([(im[0], pid - 1) for im in images], TRACK)
            fh.write(struct.pack("<Q3d3BdQ", pid, *p, 1, 2, 3, 0.1, len(tr)) + tr.tobytes())
    if with_frames_bin:
        with open(model / "frames.bin", "wb") as fh:
            fh.write(struct.pack("<Q", frames))
            for k in range(frames):
                fh.write(struct.pack("<II7d", k + 1, 1, 1, 0, 0, 0, 0, 0, 0))
                fh.write(struct.pack("<I", 2))
                for cid, iid in ((1, 2 * k + 1), (2, 2 * k + 2)):
                    fh.write(struct.pack("<iIQ", 0, cid, iid))
    return names


def _group_input(model):
    return [(im[0], im[2], im[3]) for im in _read_images_bin(model / "images.bin")]


def test_rig_frames_are_found_by_folder_or_frames_bin(tmp_path):
    from src.core.colmap import frame_groups

    a = tmp_path / "a"
    make_dual_fisheye_scene(a)
    assert frame_groups(a / "sparse" / "0", _group_input(a / "sparse" / "0")) == [
        ["cam0/000.png", "cam1/000.png"], ["cam0/001.png", "cam1/001.png"]]
    b = tmp_path / "b"
    make_dual_fisheye_scene(b, with_frames_bin=True)
    (b / "images" / "cam1" / "000.png").rename(b / "images" / "cam1" / "zzz.png")  # names no longer pair up
    model = b / "sparse" / "0"
    renamed = [(i, c, n.replace("cam1/000", "cam1/zzz")) for i, c, n in _group_input(model)]
    assert frame_groups(model, renamed)[0] == ["cam0/000.png", "cam1/zzz.png"]  # frames.bin decides


def test_dual_fisheye_stitched_into_360(tmp_path):
    from src.core.colmap import frame_groups
    from src.core.reproject import stitch_to_erp

    src = tmp_path / "rig"
    make_dual_fisheye_scene(src)
    model = src / "sparse" / "0"
    groups = frame_groups(model, _group_input(model))
    out = tmp_path / "pano"
    person = np.zeros((160, 160), bool)
    person[60:100, 60:100] = True  # in the middle of cam1's picture: straight behind
    job = MaskJob(out / "masks", "{name}.png", invert=True, include_empty=True,
                  get=lambda k: person if k.startswith("cam1/") else None)
    r = stitch_to_erp(src / "images", model, out, groups, width=256, masks=[job])
    assert (r.images_in, r.views_out, r.side) == (4, 2, 256) and r.points_kept == 3
    [cam] = read_cameras_full(out / "sparse" / "0").values()
    assert cam.model == "EQUIRECTANGULAR" and (cam.width, cam.height) == (256, 128)
    pano = cv2.imread(str(out / "images" / "000.jpg"))
    assert pano[64, 128][2] > 150 and pano[64, 128][0] < 60  # ahead: cam0's red
    assert pano[64, 2][0] > 150 and pano[64, 2][2] < 60  # behind: cam1's blue
    m = cv2.imread(str(out / "masks" / "000.jpg.png"), cv2.IMREAD_GRAYSCALE)
    assert m[64, 128] == 255 and m[64, 2] == 0  # the person behind is ignored (black), ahead is trained
    imgs = {n: pts for _, _, _, n, pts in _read_images_bin(out / "sparse" / "0" / "images.bin")}
    ahead = imgs["000.jpg"][imgs["000.jpg"]["id"] == 1]
    assert np.allclose([ahead["x"][0], ahead["y"][0]], [128, 64])  # the point ahead: the 360 image's center
    behind = imgs["000.jpg"][imgs["000.jpg"]["id"] == 2]
    assert np.isclose(behind["x"][0] % 256, 0) or np.isclose(behind["x"][0], 256)  # straight behind: the seam


def test_stitching_gives_the_panorama_back(tmp_path):
    """A panorama (hue by azimuth, brightness by elevation) cut into a back-to-back fisheye pair and stitched."""
    from src.core.colmap import frame_groups
    from src.core.reproject import stitch_to_erp

    w, h, s = 256, 128, 200
    jj, ii = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    hsv = np.dstack([(jj / w * 180).astype(np.uint8), np.full((h, w), 230, np.uint8),
                     (60 + 195 * (1 - ii / h)).astype(np.uint8)])
    pano = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    root = tmp_path / "rig"
    make_dual_fisheye_scene(root, frames=2, size=s)
    f = (s / 2) / np.radians(95)
    yy, xx = np.mgrid[0:s, 0:s]
    u, v = (xx + 0.5 - s / 2) / f, (yy + 0.5 - s / 2) / f
    th = np.hypot(u, v)
    ray = np.stack([np.sin(th) * u / np.maximum(th, 1e-9), np.sin(th) * v / np.maximum(th, 1e-9), np.cos(th)], -1)
    for cam, r in (("cam0", np.eye(3)), ("cam1", np.diag([-1.0, 1, -1]))):
        d = ray @ r  # this camera's rays in the reference (cam0) frame
        az, el = np.arctan2(d[..., 0], d[..., 2]), np.arctan2(-d[..., 1], np.hypot(d[..., 0], d[..., 2]))
        mx = ((az / (2 * np.pi) + 0.5) * w - 0.5).astype(np.float32)
        my = ((0.5 - el / np.pi) * h - 0.5).astype(np.float32)
        img = cv2.remap(pano, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        img[th > np.radians(95)] = 0
        for k in range(2):
            cv2.imwrite(str(root / "images" / cam / f"{k:03d}.png"), img)
    model = root / "sparse" / "0"
    stitch_to_erp(root / "images", model, tmp_path / "pano", frame_groups(model, _group_input(model)), width=w)
    back = cv2.imread(str(tmp_path / "pano" / "images" / "000.jpg"))
    diff = np.abs(back.astype(int) - pano.astype(int)).mean(axis=2)[10:-10]  # away from the poles
    assert diff.mean() < 3 and np.percentile(diff, 99) < 12


def test_thin_prism_fisheye_matches_colmap():
    """THIN_PRISM_FISHEYE (OSMO 360 scenes): zero distortion = FISHEYE; with distortion, COLMAP's formula
    written out point by point (sensor/models/thin_prism.h)."""
    import math

    from src.core.colmap import Camera
    from src.core.reproject import CONVERTIBLE, source_projection

    assert "THIN_PRISM_FISHEYE" in CONVERTIBLE
    rays = np.array([[0.1, -0.2, 1.0], [0.8, 0.3, 0.5], [-0.4, 0.9, 0.2], [0.0, 0.0, 1.0]])
    plain = Camera(1, "THIN_PRISM_FISHEYE", 1000, 900, (400.0, 410.0, 500.0, 450.0) + (0.0,) * 8)
    fish = Camera(1, "FISHEYE", 1000, 900, (400.0, 410.0, 500.0, 450.0))
    a, b = source_projection(plain)(plain, rays), source_projection(fish)(fish, rays)
    assert np.allclose(a[0], b[0]) and np.allclose(a[1], b[1])
    params = (400.0, 410.0, 500.0, 450.0, 0.05, -0.01, 0.002, -0.003, 0.004, -0.001, 0.0015, -0.002)
    cam = Camera(1, "THIN_PRISM_FISHEYE", 1000, 900, params)
    xs, ys, ok = source_projection(cam)(cam, rays)
    fx, fy, cx, cy, k1, k2, p1, p2, k3, k4, sx1, sy1 = params
    for (x, y, z), gx, gy in zip(rays, xs, ys):
        u, v = x / z, y / z
        r = math.hypot(u, v)
        if r > 1e-12:
            th = math.atan(r)
            u, v = u * th / r, v * th / r
        r2 = u * u + v * v
        rad = k1 * r2 + k2 * r2 ** 2 + k3 * r2 ** 3 + k4 * r2 ** 4
        du = u * rad + 2 * p1 * u * v + p2 * (r2 + 2 * u * u) + sx1 * r2
        dv = v * rad + 2 * p2 * u * v + p1 * (r2 + 2 * v * v) + sy1 * r2
        assert math.isclose(gx, fx * (u + du) + cx, abs_tol=1e-6) and math.isclose(gy, fy * (v + dv) + cy, abs_tol=1e-6)
    assert ok.all()

