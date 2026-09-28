import math

import numpy as np
import pytest

from src.core.erp import (
    View,
    dir_to_erp,
    erp_point_to_view,
    erp_to_dir,
    is_erp_shape,
    merge_view_detections,
    paste_view_mask,
    preset_views,
    render_view,
    view_coverage,
    view_for_mask,
    view_for_points,
    view_mask_to_erp,
    view_point_to_erp,
)

HW = (256, 512)


def test_dir_roundtrip_and_conventions():
    uu, vv = np.meshgrid(np.arange(0, 512, 37.0), np.arange(0, 256, 23.0))
    u, v = dir_to_erp(erp_to_dir(uu, vv, HW), HW)
    assert np.allclose(u, uu, atol=1e-6) and np.allclose(v, vv, atol=1e-6)
    c = erp_to_dir(255.5, 127.5, HW)  # ERP centre looks forward (+z)
    assert np.allclose(c, [0, 0, 1], atol=1e-6)
    assert erp_to_dir(383.5, 127.5, HW)[0] > 0.99  # 90° right is +x
    assert erp_to_dir(10, 0, HW)[1] > 0.99  # top row is up


def test_view_basis_orthonormal_including_poles():
    for yaw, pitch in [(0, 0), (37, 20), (-120, -60), (0, 90), (45, -90)]:
        r, d, f = View(yaw, pitch).basis()
        m = np.stack([r, d, f])
        assert np.allclose(m @ m.T, np.eye(3), atol=1e-9)
        # x right / y up / z forward is left-handed: right × down = -forward for every view,
        # i.e. no view (poles included) is mirrored.
        assert np.allclose(np.cross(r, d), -f, atol=1e-9)


def test_point_roundtrip_view_erp():
    view = View(30, -20, 90, 400, 300)
    for x, y in [(0, 0), (200, 150), (399, 299), (57.3, 211.8)]:
        u, v = view_point_to_erp(x, y, HW, view)
        back = erp_point_to_view(u, v, HW, view)
        assert back is not None and abs(back[0] - x) < 1e-6 and abs(back[1] - y) < 1e-6
    assert erp_point_to_view(*view_point_to_erp(200, 150, HW, View(210, 20)), HW, view) is None  # behind


def test_render_view_center_matches_erp_and_wraps_seam():
    erp = np.zeros((*HW, 3), np.uint8)
    erp[:, :, 0] = (np.arange(512) % 256)[None, :]
    erp[:, :256, 1] = 200  # left half green
    front = render_view(erp, View(0, 0, 60, 64, 64))
    assert abs(int(front[32, 32, 0]) - 256 % 256) <= 2 or abs(int(front[32, 32, 0]) - 255) <= 2
    back = render_view(erp, View(180, 0, 60, 64, 64))  # straddles the 0/360 seam
    assert back[32, 5, 1] == 0 and back[32, 58, 1] == 200  # right side of the seam is the left half


def test_mask_backprojection_roundtrip_and_paste():
    view = View(-40, 10, 90, 256, 256)
    vm = np.zeros((256, 256), bool)
    vm[100:160, 90:170] = True
    erp_m = view_mask_to_erp(vm, view, HW)
    assert erp_m.any() and not erp_m[:, :100].all()
    again = render_view(erp_m, view)
    inner = vm.copy()
    inner[:105, :] = inner[155:, :] = False
    inner[:, :95] = inner[:, 165:] = False
    assert again[inner].mean() > 0.95
    cover = view_coverage(view, HW)
    base = np.ones(HW, bool)
    pasted = paste_view_mask(base, np.zeros((256, 256), bool), view, HW)
    assert not pasted[cover].any() and pasted[~cover].all()


def test_pole_view_sees_the_bottom_rows():
    down = View(0, -90, 90, 128, 128)
    cover = view_coverage(down, HW)
    assert cover[-1].all() and not cover[0].any()


def test_view_for_points_covers_points_across_seam():
    pts = [(505.0, 128.0), (8.0, 120.0)]  # both near the seam (behind the camera)
    v = view_for_points(pts, HW)
    assert abs(abs(v.yaw) - 180) < 5 and v.fov >= 80
    for p in pts:
        q = erp_point_to_view(*p, HW, v)
        assert q is not None and 0 < q[0] < v.width and 0 < q[1] < v.height


def test_view_for_mask_nadir():
    m = np.zeros(HW, bool)
    m[230:, :] = True  # a band at the bottom = something under the camera
    v = view_for_mask(m)
    assert v.pitch < -80
    assert view_for_mask(np.zeros(HW, bool)) is None


def test_presets():
    assert len(preset_views("cube6", 64)) == 6
    assert len(preset_views("ring8", 64)) == 10
    assert len(preset_views("fast4", 64)) == 4
    union = np.zeros(HW, bool)
    for v in preset_views("cube6", 64):
        union |= view_coverage(v, HW)
    assert union.all()  # the cube covers the whole sphere


def test_merge_split_and_duplicate_detections():
    a = np.zeros(HW, bool)
    a[100:140, 200:256] = True
    b = np.zeros(HW, bool)
    b[100:140, 256:300] = True  # other half of the same object, from the next view
    c = np.zeros(HW, bool)
    c[10:20, 10:20] = True
    dup = a.copy()
    out = merge_view_detections([("person", 0.9, a, 0), ("person", 0.8, b, 1), ("person", 0.7, dup, 1), ("person", 0.6, c, 2)])
    assert len(out) == 2
    big = max(out, key=lambda t: t[2].sum())
    assert big[1] == 0.9 and big[2][120, 220] and big[2][120, 280]
    seam_l = np.zeros(HW, bool)
    seam_l[50:60, 0:10] = True
    seam_r = np.zeros(HW, bool)
    seam_r[50:60, 500:512] = True
    assert len(merge_view_detections([("car", 0.9, seam_l, 0), ("car", 0.9, seam_r, 1)])) == 1
    assert len(merge_view_detections([("car", 0.9, seam_l, 0), ("person", 0.9, seam_r, 1)])) == 2


def test_block_coverage_matches_brute_force():
    """The ERP block shortcut must see exactly what a full-image projection sees."""
    from src.core.erp import project_dirs

    uu, vv = np.meshgrid(np.arange(HW[1], dtype=np.float64), np.arange(HW[0], dtype=np.float64))
    dirs = erp_to_dir(uu, vv, HW)
    rng = np.random.default_rng(0)
    views = [View(180, 0, 90, 200, 150), View(0, 90, 100, 128, 128), View(33, -80, 120, 160, 90), View(-170, 40, 60, 300, 300)]
    views += [View(float(rng.uniform(-180, 180)), float(rng.uniform(-89, 89)), float(rng.uniform(40, 140)), 256, 192) for _ in range(12)]
    for v in views:
        x, y, front = project_dirs(dirs, v)
        truth = front & (x >= -0.5) & (x <= v.width - 0.5) & (y >= -0.5) & (y <= v.height - 0.5)
        got = view_coverage(v, HW)
        assert (got != truth).sum() == 0, v


def test_is_erp_shape():
    assert is_erp_shape(2880, 5760) and not is_erp_shape(1080, 1920)


@pytest.mark.parametrize("fov", [60, 90, 120])
def test_focal(fov):
    v = View(0, 0, fov, 1000, 1000)
    assert math.isclose(math.degrees(2 * math.atan(500 / v.focal)), fov)
