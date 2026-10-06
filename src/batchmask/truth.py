"""Sky ground truth: full-resolution crops where the sky's edge is hard, masks fixed by hand, and scores.

Whole 3840² fisheye frames cannot be traced by hand to the pixel, and most of their sky is easy; the
errors that matter (sky spilling over tree tops, missed sky between leaves, railings) sit along the edge.
So the truth is a set of crops (768² by default: the app edits them at full resolution) cut where a draft
sky mask's edge is densest, each fixed by hand in this app. :func:`score` crops any method's full-frame
masks at the same places and compares.

A crop's draft comes from this app's own sky step, so a hand check that only looks for its mistakes leans
towards it: trace the edge itself, or start the crop over with SAM2 points.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

SIZE = 768
PER_FRAME = 2
INSIDE = 90.0  # % of the inscribed circle every crop corner stays in (a fisheye's dark rim is no sky edge)
TOLERANCES = (2, 8)  # px, boundary F-score


def edge(mask: np.ndarray) -> np.ndarray:
    """The mask's own boundary pixels (inside ones)."""
    m = mask.astype(np.uint8)
    return (m - cv2.erode(m, np.ones((3, 3), np.uint8))) > 0


SKY_SHARE = (0.2, 0.8)  # a crop's sky share: a skyline to trace, not a tree's inside (leaf gaps everywhere)


def pick_crops(mask: np.ndarray, n: int = PER_FRAME, size: int = SIZE, inside: float = INSIDE,
               share: Tuple[float, float] = SKY_SHARE) -> List[dict]:
    """Up to *n* non-overlapping *size* squares where *mask*'s edge is longest, with a sky share in *share*
    (where tree tops meet the sky: what can be traced by hand and where sky spills), all four corners inside
    a centred circle of *inside* % of the inscribed circle."""
    h, w = mask.shape
    if size > min(h, w):
        return []
    step = 8
    e = cv2.resize(edge(mask).astype(np.float32), (w // step, h // step), interpolation=cv2.INTER_AREA)
    k = size // step
    density = cv2.boxFilter(e, -1, (k, k), normalize=False, anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
    sky = cv2.resize(mask.astype(np.float32), (w // step, h // step), interpolation=cv2.INTER_AREA)
    frac = cv2.boxFilter(sky, -1, (k, k), normalize=True, anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
    r = inside / 100.0 * min(h, w) / 2
    cx, cy = (w - 1) / 2, (h - 1) / 2
    stride = max(1, k // 4)
    cands = []
    for gy in range(0, h // step - k + 1, stride):
        for gx in range(0, w // step - k + 1, stride):
            x, y = gx * step, gy * step
            corners = ((x, y), (x + size, y), (x, y + size), (x + size, y + size))
            if share[0] <= frac[gy, gx] <= share[1] and all(np.hypot(px - cx, py - cy) <= r for px, py in corners):
                cands.append((float(density[gy, gx]), x, y))
    cands.sort(reverse=True)
    picked: List[dict] = []
    for d, x, y in cands:
        if d <= 0 or len(picked) == n:
            break
        if all(abs(x - p["x"]) >= size or abs(y - p["y"]) >= size for p in picked):
            gy, gx = y // step, x // step
            picked.append({"x": int(x), "y": int(y), "w": size, "h": size, "edge_px": int(d * step),
                           "sky": round(float(frac[gy, gx]), 3)})
    return picked


def crop_name(key: str, x: int, y: int) -> str:
    from src.engine.imageio import key_stem

    return f"{key_stem(key).replace('/', '_')}_x{x}_y{y}"


def _write(path: Path, img: np.ndarray, ext: str, params=()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(ext, img, list(params))
    if not ok:
        raise IOError(f"could not encode {path}")
    buf.tofile(str(path))


def make_set(images: Path, keys: Sequence[str], out: Path, draft: Callable[[np.ndarray], np.ndarray],
             per_frame: int = PER_FRAME, size: int = SIZE, inside: float = INSIDE, settings: Optional[dict] = None,
             log: Callable[[str], None] = print) -> dict:
    """Cut the crops of *keys* into *out*: ``images/`` (to fix in the app), ``drafts/`` (white = sky, to
    import as an Object), ``overview/`` (where the crops are) and ``manifest.json``. *draft*(rgb) is the
    full-frame sky mask the edges are found on."""
    from src.engine.imageio import read_rgb

    if (out / "manifest.json").exists():
        raise FileExistsError(f"{out} already holds a truth set (manifest.json): nothing written")
    crops: List[dict] = []
    for n, key in enumerate(keys, 1):
        rgb = read_rgb(images / key)
        sky = draft(rgb)
        picked = pick_crops(sky, per_frame, size, inside)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        over = bgr.copy()
        tint = over[sky]
        over[sky] = (0.6 * tint + np.array([90, 40, 0]) * 0.4 + 0.4 * 100).clip(0, 255).astype(np.uint8)
        for c in picked:
            name = crop_name(key, c["x"], c["y"])
            sl = (slice(c["y"], c["y"] + size), slice(c["x"], c["x"] + size))
            _write(out / "images" / f"{name}.jpg", bgr[sl], ".jpg", (cv2.IMWRITE_JPEG_QUALITY, 98))
            _write(out / "drafts" / f"{name}.jpg.png", sky[sl].astype(np.uint8) * 255, ".png")
            cv2.rectangle(over, (c["x"], c["y"]), (c["x"] + size, c["y"] + size), (0, 255, 255), 12)
            cv2.putText(over, name.rsplit("_x", 1)[0][-5:] + f" x{c['x']} y{c['y']}", (c["x"] + 16, c["y"] + 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 255, 255), 5, cv2.LINE_AA)
            crops.append(dict(c, name=name, image=key))
        s = 1280 / max(over.shape[:2])
        _write(out / "overview" / f"{key.replace('/', '_')}.jpg",
               cv2.resize(over, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), ".jpg", (cv2.IMWRITE_JPEG_QUALITY, 85))
        log(f"[{n}/{len(keys)}] {key}: {len(picked)} crop(s) " + ", ".join(f"x{c['x']} y{c['y']}" for c in picked))
    manifest = {"kind": "sky", "images": str(images), "size": size, "inside": inside, "draft": settings or {},
                "polarity": "white = sky", "crops": crops}
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return manifest


def _read(path: Path) -> Optional[np.ndarray]:
    data = np.fromfile(str(path), np.uint8)
    m = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if data.size else None
    return None if m is None else m > 127


def truth_mask(folder: Path, name: str) -> Optional[np.ndarray]:
    for f in (f"{name}.png", f"{name}.jpg.png"):
        if (folder / f).is_file():
            return _read(folder / f)
    return None


def boundary_f(pred: np.ndarray, truth: np.ndarray, tol: int) -> Optional[float]:
    """Boundary F-score: the share of each mask's edge within *tol* px of the other's, combined."""
    ep, et = edge(pred), edge(truth)
    if not ep.any() and not et.any():
        return None
    if not ep.any() or not et.any():
        return 0.0
    dt_t = cv2.distanceTransform((~et).astype(np.uint8), cv2.DIST_L2, 3)
    dt_p = cv2.distanceTransform((~ep).astype(np.uint8), cv2.DIST_L2, 3)
    precision = float((dt_t[ep] <= tol).mean())
    recall = float((dt_p[et] <= tol).mean())
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def compare(pred: np.ndarray, truth: np.ndarray) -> dict:
    """Sky against the truth: IoU; ``spill`` (sky where the truth has none: over tree tops) and ``missed``,
    both in % of the truth's sky; ``spill_of_scene``: spill in % of the crop's non-sky; boundary F-scores."""
    t, p = truth.sum(), pred.sum()
    union = (pred | truth).sum()
    out = {
        "iou": round(float((pred & truth).sum() / union), 4) if union else None,
        "spill": round(float((pred & ~truth).sum() / t), 4) if t else None,
        "missed": round(float((truth & ~pred).sum() / t), 4) if t else None,
        "spill_of_scene": round(float((pred & ~truth).sum() / (~truth).sum()), 4) if (~truth).any() else None,
        "sky_truth": round(float(truth.mean()), 4), "sky_pred": round(float(pred.mean()), 4),
    }
    for tol in TOLERANCES:
        f = boundary_f(pred, truth, tol)
        out[f"edge_f{tol}"] = None if f is None else round(f, 4)
    return out


def score(truth_dir: Path, masks: Path, truth_masks: Optional[Path] = None, invert: bool = False,
          invert_truth: bool = False, log: Callable[[str], None] = print) -> dict:
    """Compare full-frame sky masks in *masks* (white = sky, ``<image>.png`` or ``<stem>.png``; *invert*:
    black = sky) with the hand-fixed crops in *truth_masks* (default: the app's export folder
    ``images_masks/`` beside ``images/``, else ``masks/``)."""
    from src.engine.imageio import key_stem

    manifest = json.loads((truth_dir / "manifest.json").read_text(encoding="utf-8"))
    if truth_masks is None:
        truth_masks = next((truth_dir / d for d in ("images_masks", "masks") if (truth_dir / d).is_dir()), None)
        if truth_masks is None:
            raise FileNotFoundError(f"no fixed masks yet in {truth_dir} (images_masks/ or masks/): export them "
                                    "from the app, or give the folder")
    rows: Dict[str, dict] = {}
    not_fixed, no_pred = [], []
    full: Dict[str, Optional[np.ndarray]] = {}
    for c in manifest["crops"]:
        t = truth_mask(truth_masks, c["name"])
        if t is None:
            not_fixed.append(c["name"])
            continue
        if invert_truth:
            t = ~t
        key = c["image"]
        if key not in full:
            path = next((masks / f for f in (f"{key}.png", f"{key_stem(key)}.png") if (masks / f).is_file()), None)
            full[key] = None if path is None else _read(path)
        m = full[key]
        if m is None:
            no_pred.append(key)
            continue
        m = ~m if invert else m
        p = m[c["y"]:c["y"] + c["h"], c["x"]:c["x"] + c["w"]]
        if p.shape != t.shape:
            raise ValueError(f"{c['name']}: mask {m.shape} is not the frame's full resolution")
        rows[c["name"]] = dict(compare(p, t), image=key)
        r = rows[c["name"]]
        log(f"{c['name']}: IoU {r['iou']}  spill {_pct(r['spill'])}  missed {_pct(r['missed'])}  "
            f"edge F@2 {r['edge_f2']}  F@8 {r['edge_f8']}")

    def mean(k):
        v = [r[k] for r in rows.values() if r.get(k) is not None]
        return round(float(np.mean(v)), 4) if v else None

    summary = {k: mean(k) for k in ("iou", "spill", "missed", "spill_of_scene", "edge_f2", "edge_f8")}
    summary["iou_min"] = round(min(r["iou"] for r in rows.values() if r["iou"] is not None), 4) if rows else None
    summary["spill_max"] = round(max((r["spill"] or 0) for r in rows.values()), 4) if rows else None
    return {"truth": str(truth_dir), "truth_masks": str(truth_masks), "masks": str(masks), "crops": len(manifest["crops"]),
            "scored": len(rows), "not_fixed": not_fixed, "no_mask": sorted(set(no_pred)), "summary": summary,
            "rows": rows}


def _pct(v) -> str:
    return "-" if v is None else f"{100 * v:.2f} %"


def table(report: dict) -> str:
    s = report["summary"]
    lines = [f"{report['scored']} of {report['crops']} crop(s) scored"
             + (f"; not fixed yet: {len(report['not_fixed'])}" if report["not_fixed"] else "")
             + (f"; no mask for: {', '.join(report['no_mask'])}" if report["no_mask"] else "")]
    if report["scored"]:
        lines.append(f"IoU {s['iou']} (lowest {s['iou_min']})  spill {_pct(s['spill'])} (most {_pct(s['spill_max'])})  "
                     f"missed {_pct(s['missed'])}  edge F@2 px {s['edge_f2']}  F@8 px {s['edge_f8']}")
    return "\n".join(lines)
