"""Filtering a COLMAP model: dropped images leave every track; thin points go (docs/specs/07 6)."""

import struct
from pathlib import Path

import numpy as np

from src.core.colmap import read_image_names_bin, read_image_names_txt
from src.core.colmap_model import POINT2D, TRACK, _read_images_bin, filter_model

# three images; point 1 seen by all three, point 2 by images 1 and 2, point 3 by images 2 and 3
TRACKS = {1: [(1, 0), (2, 0), (3, 0)], 2: [(1, 1), (2, 1)], 3: [(2, 2), (3, 1)]}
NAMES = {1: "a.jpg", 2: "b.jpg", 3: "c.jpg"}


def points_of(iid):
    """The image's 2D points, in point2D index order, each with its 3D point id."""
    obs = sorted((idx, pid) for pid, tr in TRACKS.items() for im, idx in tr if im == iid)
    return np.array([(float(i), float(i), pid) for i, pid in obs], dtype=POINT2D)


def write_bin(model: Path, names=None) -> None:
    """The three-image model; *names* renames the images (in id order)."""
    names = dict(zip(NAMES, names)) if names is not None else NAMES
    model.mkdir(parents=True)
    with open(model / "cameras.bin", "wb") as f:
        f.write(struct.pack("<QiiQQ4d", 1, 1, 1, 64, 48, 50, 50, 32, 24))
    with open(model / "images.bin", "wb") as f:
        f.write(struct.pack("<Q", 3))
        for iid, name in names.items():
            pts = points_of(iid)
            f.write(struct.pack("<i7di", iid, 1, 0, 0, 0, iid, 0, 0, 1) + name.encode() + b"\0")
            f.write(struct.pack("<Q", len(pts)) + pts.tobytes())
    with open(model / "points3D.bin", "wb") as f:
        f.write(struct.pack("<Q", len(TRACKS)))
        for pid, tr in TRACKS.items():
            f.write(struct.pack("<Q3d3BdQ", pid, pid, 0, 0, 200, 100, 50, 0.5, len(tr)))
            f.write(np.array(tr, dtype=TRACK).tobytes())
    (model / "rigs.bin").write_bytes(b"x")


def read_points_bin(path: Path) -> dict:
    out = {}
    with open(path, "rb") as f:
        (n,) = struct.unpack("<Q", f.read(8))
        for _ in range(n):
            head = struct.unpack("<Q3d3BdQ", f.read(51))
            track = np.frombuffer(f.read(8 * head[-1]), dtype=TRACK)
            out[head[0]] = sorted(int(i) for i in track["image"])
    return out


def test_filter_bin_drops_the_image_its_observations_and_thin_points(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    write_bin(src)
    r = filter_model(src, dst, ["a.jpg", "c.jpg"])  # b.jpg out
    assert (r.images_kept, r.images_dropped, r.points_kept, r.points_dropped) == (2, 1, 1, 2)
    assert r.skipped_files == ("rigs.bin",)
    assert read_image_names_bin(dst / "images.bin") == ["a.jpg", "c.jpg"]
    assert read_points_bin(dst / "points3D.bin") == {1: [1, 3]}  # 2 and 3 fell under two observations
    imgs = {name: pts for _, _, _, name, pts in _read_images_bin(dst / "images.bin")}
    assert list(imgs["a.jpg"]["id"]) == [1, -1] and list(imgs["c.jpg"]["id"]) == [1, -1]
    assert (dst / "cameras.bin").read_bytes() == (src / "cameras.bin").read_bytes()
    assert read_image_names_bin(src / "images.bin") == ["a.jpg", "b.jpg", "c.jpg"]  # the source is untouched


def test_filter_keeping_everything_is_the_same_model(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    write_bin(src)
    filter_model(src, dst, NAMES.values())
    for f in ("images.bin", "points3D.bin"):
        assert (dst / f).read_bytes() == (src / f).read_bytes()


def test_filter_txt(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    (src / "cameras.txt").write_text("1 PINHOLE 64 48 50 50 32 24\n", encoding="utf-8")
    img = ["# Image list"]
    for iid, name in NAMES.items():
        pts = points_of(iid)
        img += [f"{iid} 1 0 0 0 {iid} 0 0 1 {name}", " ".join(f"{p['x']} {p['y']} {p['id']}" for p in pts)]
    (src / "images.txt").write_text("\n".join(img) + "\n", encoding="utf-8")
    (src / "points3D.txt").write_text("# 3D points\n" + "\n".join(
        f"{pid} 0 0 0 200 100 50 0.5 " + " ".join(f"{im} {idx}" for im, idx in tr) for pid, tr in TRACKS.items()
    ) + "\n", encoding="utf-8")
    r = filter_model(src, dst, ["a.jpg", "c.jpg"])
    assert (r.images_kept, r.points_kept, r.points_dropped) == (2, 1, 2)
    assert read_image_names_txt(dst / "images.txt") == ["a.jpg", "c.jpg"]
    rows = [ln for ln in (dst / "points3D.txt").read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    assert rows == ["1 0 0 0 200 100 50 0.5 1 0 3 0"]
    second = (dst / "images.txt").read_text(encoding="utf-8").splitlines()[2]
    assert second.split()[2::3] == ["1", "-1"]
