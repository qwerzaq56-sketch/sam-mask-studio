"""Special Objects (docs/specs/09-special-objects.md): masks made from settings, not from points.

A special Object keeps its kind, its settings and the images it covers; its masks are made again
whenever the settings change. **Apply** turns it into an ordinary Object (the masks stay, the
settings go), which can then be edited by hand like any other.

- ``sky``: the sky, from the Sky-Segmentation-and-Post-processing model (U2Net, ONNX,
  https://github.com/xiongzhu666/Sky-Segmentation-and-Post-processing), with its edge refinement.
  The model's output is cached per image, so moving a setting needs no model run.
- ``lens_edge``: what lies outside a fisheye's image circle (the black corners).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.core.refine import grow_mask, shrink_mask

SKY = "sky"
LENS_EDGE = "lens_edge"
KINDS = (SKY, LENS_EDGE)
LABELS = {SKY: "Sky", LENS_EDGE: "Lens edge"}
# % of the found circle's radius left out with the black: a fisheye's last few % is soft and dark. 0022
# (OSMO 360, 3840²): detail and SIFT points hold to 0.95 of the circle, then fall (points 20 -> 5 -> 1.5
# per 10⁴ px at 0.95 / 0.96 / 0.97), and the SfM split in 2-4 models until that band was masked (p127).
LENS_MARGIN = 5.0

# settings (all numbers, so they save and compare simply); see sky_mask / lens_edge_mask
DEFAULTS: Dict[str, Tuple[Tuple[str, float], ...]] = {
    SKY: (("threshold", 50.0), ("refine", 1.0), ("grow", 0.0), ("top_only", 0.0)),
    LENS_EDGE: (("radius", 100.0), ("cx", 0.0), ("cy", 0.0)),
}

SKY_INPUT = 320  # the model's input side
SKY_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
SKY_STD = np.array([0.229, 0.224, 0.225], np.float32)


@dataclass(frozen=True)
class Special:
    """What makes an Object special: *kind*, its settings, the image keys it covers."""

    kind: str
    params: Tuple[Tuple[str, float], ...] = ()
    keys: Tuple[str, ...] = ()
    # sky: the finish after the model (By Color + tree tips + SAM2, src/core/sky_sam2.py) as JSON
    # {"name", "color": a By Color preset's values, "tree_tips"}; "" = none. Values, not a preset's name: a preset
    # changed or deleted later does not change the masks made with it
    finish: str = ""

    @classmethod
    def new(cls, kind: str) -> "Special":
        if kind not in KINDS:
            raise ValueError(f"Unknown special Object: {kind}")
        return cls(kind, DEFAULTS[kind])

    def get(self, name: str) -> float:
        return dict(self.params).get(name, dict(DEFAULTS[self.kind]).get(name, 0.0))

    def with_params(self, **values: float) -> "Special":
        d = dict(DEFAULTS[self.kind])
        d.update(self.params)
        d.update({k: float(v) for k, v in values.items() if k in d})
        return dataclasses.replace(self, params=tuple(d.items()))

    def with_keys(self, keys: Iterable[str], order: Sequence[str]) -> "Special":
        wanted = set(keys)
        return dataclasses.replace(self, keys=tuple(k for k in order if k in wanted))

    def with_finish(self, finish: Optional[dict]) -> "Special":
        return dataclasses.replace(self, finish=json.dumps(finish, sort_keys=True) if finish else "")

    @property
    def finish_values(self) -> Optional[dict]:
        """The finish (name, color, tree_tips), None = none."""
        return json.loads(self.finish) if self.finish else None

    def to_json(self) -> dict:
        d = {"kind": self.kind, "params": dict(self.params), "keys": list(self.keys)}
        if self.finish:
            d["finish"] = self.finish_values
        return d

    @classmethod
    def from_json(cls, d: Optional[dict]) -> Optional["Special"]:
        if not d or d.get("kind") not in KINDS:
            return None
        base = cls.new(d["kind"]).with_params(**{k: v for k, v in (d.get("params") or {}).items()})
        return dataclasses.replace(base, keys=tuple(d.get("keys") or ())).with_finish(d.get("finish"))


# ----------------------------------------------------------------------
# Lens edge
# ----------------------------------------------------------------------


def lens_circle(h: int, w: int, sp: Special) -> Tuple[float, float, float]:
    """(cx, cy, r) in pixels: *radius* % of the inscribed circle, the center moved by *cx*, *cy* % of it."""
    r0 = min(h, w) / 2.0
    return w / 2.0 + sp.get("cx") / 100.0 * r0, h / 2.0 + sp.get("cy") / 100.0 * r0, r0 * sp.get("radius") / 100.0


def lens_edge_mask(h: int, w: int, sp: Special) -> np.ndarray:
    """True outside the image circle (what training should ignore)."""
    cx, cy, r = lens_circle(h, w, sp)
    yy, xx = np.ogrid[0:h, 0:w]
    return (xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2 >= r * r


def detect_lens_circle(images: Sequence[np.ndarray], dark: int = 16) -> Optional[Dict[str, float]]:
    """Settings (radius, cx, cy) of the image circle seen in *images* (RGB): the lit area of their mean,
    a circle fitted to its rim where the rim is not the frame's edge. None when nothing looks like one."""
    if not len(images):
        return None
    h, w = images[0].shape[:2]
    lit = np.zeros((h, w), np.float32)
    n = 0
    for img in images:
        if img.shape[:2] != (h, w):
            continue
        lit += (cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) > dark).astype(np.float32)
        n += 1
    region = (lit / max(n, 1) > 0.5).astype(np.uint8)
    region = cv2.morphologyEx(region, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    pts = max(contours, key=cv2.contourArea)[:, 0, :].astype(np.float64)
    inner = pts[(pts[:, 0] > 1) & (pts[:, 0] < w - 2) & (pts[:, 1] > 1) & (pts[:, 1] < h - 2)]
    if len(inner) < 20:
        return None  # the lit area fills the frame: no circle to see
    # Kasa fit: x^2 + y^2 + D x + E y + F = 0
    x, y = inner[:, 0] + 0.5, inner[:, 1] + 0.5
    a = np.column_stack([x, y, np.ones_like(x)])
    d, e, f = np.linalg.lstsq(a, -(x * x + y * y), rcond=None)[0]
    cx, cy = -d / 2, -e / 2
    r = float(np.sqrt(max(cx * cx + cy * cy - f, 0.0)))
    r0 = min(h, w) / 2.0
    if not (0.2 * r0 < r < 3 * r0):
        return None
    return {"radius": round(100.0 * r / r0, 1), "cx": round(100.0 * (cx - w / 2) / r0, 1) + 0.0,
            "cy": round(100.0 * (cy - h / 2) / r0, 1) + 0.0}  # + 0.0: no "-0.0"


# ----------------------------------------------------------------------
# Sky
# ----------------------------------------------------------------------


class SkyModel:
    """The sky segmentation network (``skyseg.onnx``): onnxruntime when installed, else OpenCV's DNN."""

    def __init__(self, path: Path):
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Sky model not found: {path}")
        try:
            import onnxruntime as ort  # optional

            self._ort = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            self._net = None
        except ImportError:
            self._ort = None
            self._net = cv2.dnn.readNetFromONNX(str(path))

    def probability(self, rgb: np.ndarray) -> np.ndarray:
        """uint8 H x W: how much each pixel looks like sky (0..255, stretched to the full range)."""
        h, w = rgb.shape[:2]
        x = cv2.resize(rgb, (SKY_INPUT, SKY_INPUT), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        x = ((x - SKY_MEAN) / SKY_STD).transpose(2, 0, 1)[None].astype(np.float32)
        if self._ort is not None:
            inp = self._ort.get_inputs()[0].name
            out = self._ort.run([self._ort.get_outputs()[0].name], {inp: x})[0]
        else:
            self._net.setInput(x)
            out = self._net.forward()
        return stretch_to_uint8(np.asarray(out).squeeze(), h, w)


def stretch_to_uint8(out: np.ndarray, h: int, w: int) -> np.ndarray:
    """The network's map, stretched to 0..255 (as the reference code does) and sized to the image."""
    out = out.astype(np.float32)
    lo, hi = float(out.min()), float(out.max())
    out = (out - lo) / (hi - lo) if hi > lo else np.zeros_like(out)
    return cv2.resize((out * 255).astype(np.uint8), (w, h), interpolation=cv2.INTER_LINEAR)


def _confidence(p: np.ndarray, low: float = 0.3, high: float = 0.5, bias: float = 0.8,
                eps: float = 0.01) -> np.ndarray:
    """How sure the network is at each pixel: 0 between *low* and *high*, rising to 1 at 0 and 1."""
    c = np.zeros_like(p)
    lo, hi = p < low, p > high
    c[lo] = (low - p[lo]) / low
    c[hi] = (p[hi] - high) / (1 - high)
    c = c / (((1 / bias) - 2) * (1 - c) + 1)
    return np.maximum(c, eps)


def refine_sky(prob: np.ndarray, rgb: np.ndarray, cell: int = 0, reg: float = 1e-4) -> np.ndarray:
    """The sky map snapped to the image's edges (the repository's mask_refine, as a confidence-weighted
    guided filter): per area, the map as a linear function of the colors, fitted where the network is
    sure, then applied everywhere. *cell*: the area's side in px (0 = 1/4 of the longer side: the
    reference works on 256 px areas of the full image; large areas hold up where the map is badly wrong)."""
    h, w = prob.shape
    p = prob.astype(np.float32) / 255.0
    img = rgb.astype(np.float32) / 255.0
    c = _confidence(p)
    cell = cell or max(32, max(h, w) // 4)
    size = (max(1, round(w / cell)), max(1, round(h / cell)))

    def down(x):
        return cv2.resize(x, size, interpolation=cv2.INTER_AREA)

    wsum = down(c)
    if wsum.ndim == 2:
        wsum = wsum[..., None]

    def mean(x):
        return down(x * (c[..., None] if x.ndim == 3 else c)).reshape(size[1], size[0], -1) / wsum

    m_i = mean(img)  # (sh, sw, 3)
    m_p = mean(p)  # (sh, sw, 1)
    cov = np.empty((size[1], size[0], 3, 3), np.float32)
    for a in range(3):
        for b in range(a, 3):
            v = mean(img[..., a] * img[..., b])[..., 0] - m_i[..., a] * m_i[..., b]
            cov[..., a, b] = cov[..., b, a] = v
    cov[..., [0, 1, 2], [0, 1, 2]] += reg
    cross = mean(img * p[..., None]) - m_i * m_p
    coef = np.linalg.solve(cov, cross[..., None])[..., 0]  # (sh, sw, 3)
    offset = m_p[..., 0] - (coef * m_i).sum(-1)
    coef_up = cv2.resize(coef, (w, h), interpolation=cv2.INTER_LINEAR)
    off_up = cv2.resize(offset, (w, h), interpolation=cv2.INTER_LINEAR)
    q = np.clip((coef_up * img).sum(-1) + off_up, 0, 1)
    q8 = (q * 255).astype(np.uint8)
    return cv2.bilateralFilter(q8, 9, 20, 10)


def sky_maps(model, rgb: np.ndarray, dark: int = 32) -> Tuple[np.ndarray, np.ndarray]:
    """(the network's sky map, the refined one) of an RGB image. Near-black pixels (every channel below
    *dark*) are never sky: a fisheye's black corners and its dark rim came out as sky (10 left the rim,
    32 cleared it on OSMO 360 footage), and left in they would also teach the refinement that black is sky."""
    prob = model.probability(rgb)
    black = rgb.max(axis=2) < dark
    prob[black] = 0
    refined = refine_sky(prob, rgb)
    refined[black] = 0
    return prob, refined


def sky_mask(prob: np.ndarray, sp: Special) -> np.ndarray:
    """The sky from its map (already refined, when *refine* is on): above *threshold* %, only the
    pieces touching the top edge (*top_only*), then grown (+) or shrunk (-) by *grow* px."""
    m = prob >= sp.get("threshold") * 2.55
    if sp.get("top_only") and m.any():
        n, labels = cv2.connectedComponents(m.astype(np.uint8), connectivity=8)
        top = np.unique(labels[0][labels[0] > 0])
        m = np.isin(labels, top)
    g = int(round(sp.get("grow")))
    if g > 0:
        m = grow_mask(m, g)
    elif g < 0:
        m = shrink_mask(m, -g)
    return m
