"""ERP (360°) mode with the fake engine: prompts and detections go through perspective views."""

import numpy as np
import pytest

from src.app.session import Session
from src.core.erp import erp_point_to_view
from src.engine.batch import batch_detect
from src.engine.panorama import prompt_view
from tests.fakes import FakeEngine, make_images


@pytest.fixture
def erp_session(tmp_path):
    make_images(tmp_path / "pano", n=3, hw=(300, 600))  # 2:1 = ERP, larger than the working width
    s = Session(FakeEngine(), max_side=1024)
    assert s.folder_info(tmp_path / "pano") == {"count": 3, "saved": None, "looks_erp": True}
    s.open_folder(tmp_path / "pano", "erp", erp_max_side=512)
    return s


def test_open_as_erp_and_projection_is_kept(erp_session, tmp_path):
    s = erp_session
    assert s.erp and s.image.shape[:2] == (256, 512)
    s.click(256, 128)
    s.save(force=True)
    s2 = Session(FakeEngine())
    assert s2.folder_info(tmp_path / "pano")["saved"] == "erp"
    s2.open_folder(tmp_path / "pano", "perspective")  # an existing project keeps its projection
    assert s2.erp and s2.max_side == 512 and s2.image.shape[:2] == (256, 512)


def test_normal_folder_is_not_erp(tmp_path):
    make_images(tmp_path / "flat", n=1, hw=(60, 80))
    assert Session.folder_info(tmp_path / "flat")["looks_erp"] is False


def test_click_runs_on_a_view_and_lands_in_erp(erp_session):
    s = erp_session
    oid = s.click(256, 128)  # centre of the panorama
    fs = s.editing_frame()
    assert oid is not None and len(fs.variants) == 3
    m = fs.mask
    assert m.shape == (256, 512) and m[128, 256]
    assert s.engine.image.shape[:2] == (1024, 1024)  # SAM2 saw a perspective view


def test_click_across_the_seam(erp_session):
    s = erp_session
    s.click(511, 128)  # the last column, right at the 0/360 seam
    s.select_variant(1)  # the r=20 view-px disc ≈ 2 ERP px here
    m = s.editing_frame().mask
    assert m[128, 511] and m[128, 510] and m[128, 0]  # it continues past the seam on the left edge


def test_click_near_the_bottom_pole(erp_session):
    s = erp_session
    s.click(100, 250)  # nadir region (tripod / operator)
    v = prompt_view(s.editing_frame().points, None, (256, 512))
    assert v.pitch < -60
    m = s.editing_frame().mask
    assert m[250, 100] and m[250:, :].sum() > 0


def test_refine_keeps_seed_outside_the_view(erp_session):
    s = erp_session
    oid = s.click(256, 128)
    s.finish_editing()
    far = np.zeros((256, 512), bool)
    far[120:130, 0:10] = True  # something behind the camera, part of the Object's base mask
    fs = s.project.get(oid).frame(s.key)
    import dataclasses

    from src.core.project import freeze

    base = freeze(fs.mask | far)
    s.project.set_frame(oid, s.key, dataclasses.replace(fs, base_mask=base, points=(), variants=()))
    s.edit(oid)
    s.click(270, 128)  # a new point in front: re-run in a front view
    m = s.editing_frame().mask
    assert m[125, 5]  # the part behind the camera (outside that view) is kept


def test_erp_detection_merges_views(erp_session):
    s = erp_session
    dets = s.detect_current(s.engine, ["person"])
    assert dets and all(d.label == "person" and d.mask.shape == (256, 512) and d.mask.any() for d in dets)
    # each cube view yields 2 candidates; overlapping/touching ones across views may merge, never grow in count
    assert len(dets) <= 12


def test_erp_batch_uses_the_multi_view_detector(erp_session):
    s = erp_session
    res = dict(batch_detect(s.engine, s.paths, [0, 1], ["car"], s.max_side, 0.5, detect=s.detector()))
    assert res[0]["car"].mask.shape == (256, 512) and res[0]["car"].count >= 1


def test_prompt_view_contains_box_and_points():
    hw = (256, 512)
    from src.core.project import Point

    pts = [Point(300, 100), Point(330, 140, False)]
    v = prompt_view(pts, (280, 90, 360, 160), hw)
    for p in pts:
        q = erp_point_to_view(p.x, p.y, hw, v)
        assert q is not None and 0 <= q[0] < v.width and 0 <= q[1] < v.height
