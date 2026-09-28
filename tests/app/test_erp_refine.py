"""Objects spanning several cube faces / bigger than the prompt view are re-segmented whole."""

import math

import cv2
import numpy as np

from src.core.erp import erp_to_dir, preset_views
from src.core.project import Detection, Point, Variant, freeze, mask_box
from src.engine.panorama import erp_detect, erp_predict

HW = (512, 1024)
MIN_CUT_AREA = 60_000  # a part cut by the view edge is only "recognised" when this big


def blob_erp(yaw0: float, yaw1: float, lat: float = 9.0) -> np.ndarray:
    """ERP with a bright band between two longitudes (degrees) around the horizon."""
    img = np.zeros((*HW, 3), np.uint8)
    d = erp_to_dir(*np.meshgrid(np.arange(HW[1]), np.arange(HW[0])), HW)
    lon = np.degrees(np.arctan2(d[..., 0], d[..., 2]))
    la = np.degrees(np.arcsin(d[..., 1]))
    img[(lon >= yaw0) & (lon <= yaw1) & (np.abs(la) <= lat)] = 255
    return img


def col(yaw: float) -> int:
    return int((yaw + 180) / 360 * HW[1])


class BlobEngine:
    """SAM stand-in on the bright region: SAM2 = connected part under a point; SAM3 = parts,
    but a part touching the view border is only recognised when it is large (like a real
    detector missing a half-visible person)."""

    sam2_ready = sam3_ready = True

    def __init__(self):
        self.image = None

    def set_image(self, image):
        self.image = image

    def _parts(self, image):
        bright = (image[..., 0] > 200).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
        return [(labels == i, stats[i]) for i in range(1, n)]

    def predict(self, points, box=None, seed_mask=None):
        m = np.zeros(self.image.shape[:2], bool)
        for part, _ in self._parts(self.image):
            if any(p.positive and part[int(p.y), int(p.x)] for p in points if 0 <= p.y < part.shape[0] and 0 <= p.x < part.shape[1]):
                m |= part
        return tuple(Variant(freeze(m), 0.9 - 0.1 * i) for i in range(3))

    def detect_many(self, image, labels):
        h, w = image.shape[:2]
        out = []
        for part, (x, y, bw, bh, area) in self._parts(image):
            cut = x == 0 or y == 0 or x + bw == w or y + bh == h
            if cut and area < MIN_CUT_AREA:
                continue
            for label in labels:
                out.append(Detection(label, 0.9, freeze(part), mask_box(part)))
        return out


def test_object_across_cube_faces_is_detected_whole():
    erp = blob_erp(28, 72)  # crosses the front/right cube face border at 45°
    views = preset_views("cube6", 1024)
    eng = BlobEngine()
    plain = erp_detect(eng, erp, ["thing"], views, refine=False)
    refined = erp_detect(eng, erp, ["thing"], views, refine=True)
    row = HW[0] // 2
    assert len(plain) == 1 and not plain[0].mask[row, col(35)]  # the smaller half was missed
    assert len(refined) == 1
    m = refined[0].mask
    assert m[row, col(35)] and m[row, col(65)]  # whole object now
    truth = erp[..., 0] > 200
    assert (m & truth).sum() / truth.sum() > 0.97


def test_object_inside_one_face_is_not_redone():
    erp = blob_erp(-15, 15)
    eng = BlobEngine()
    calls = []
    orig = eng.detect_many
    eng.detect_many = lambda img, lb: calls.append(1) or orig(img, lb)
    dets = erp_detect(eng, erp, ["thing"], preset_views("cube6", 1024))
    assert len(dets) == 1 and len(calls) == 6  # only the 6 faces, no extra pass


def test_click_on_object_wider_than_the_prompt_view():
    erp = blob_erp(0, 100)
    eng = BlobEngine()
    (best, *_) = erp_predict(eng, erp, [Point(col(90), HW[0] // 2)])
    row = HW[0] // 2
    assert best.mask[row, col(90)] and best.mask[row, col(8)]  # re-centred until it fits
    truth = erp[..., 0] > 200
    assert (best.mask & truth).sum() / truth.sum() > 0.95


def test_object_bigger_than_120_degrees_stays_partial_but_contains_click():
    erp = blob_erp(-100, 100)
    (best, *_) = erp_predict(BlobEngine(), erp, [Point(col(0), HW[0] // 2)])
    assert best.mask[HW[0] // 2, col(0)] and not math.isnan(best.score)
