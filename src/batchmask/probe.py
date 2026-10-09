"""Trying SAM3 prompts on a few frames before a whole run.

For each prompt: in how many frames it finds something, how sure SAM3 is, how much of the image it takes.
With reference masks (the scene's ``masks/``, checked by hand; black = ignored, people only — not the lens
edge, or leave it out with *inside*), also how much of the reference each prompt covers and how much of it spills outside, and how well the
preset's people mask matches (IoU, missed, extra) — the numbers prompts were chosen by on 0022. Contact
sheets show it all: the people mask tinted red, each prompt's outline in its colour, the reference in green.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import cv2
import numpy as np

from src.batchmask.presets import PersonStep

TILE = 384
COLUMNS = 4
PER_SHEET = 16
COLORS = [(255, 200, 0), (0, 170, 255), (255, 0, 255), (0, 255, 255), (255, 128, 0), (160, 100, 255),
          (255, 255, 255), (0, 120, 255)]  # RGB, one per prompt
TINT = (255, 40, 40)
REFERENCE = (40, 255, 40)


def pick_frames(keys: Sequence[str], per_folder: int) -> List[str]:
    """Up to *per_folder* frames spread evenly over each camera folder."""
    groups: Dict[str, List[str]] = {}
    for k in keys:
        groups.setdefault(k.rsplit("/", 1)[0] if "/" in k else "", []).append(k)
    out = []
    for ks in groups.values():
        out += [ks[i] for i in np.unique(np.linspace(0, len(ks) - 1, min(per_folder, len(ks))).astype(int))]
    return out


def reference_mask(folder: Path, key: str) -> Optional[np.ndarray]:
    """True where the reference ignores (black in ``masks/``), from ``<key>.png`` or ``<stem>.png``."""
    from src.engine.imageio import key_stem

    for name in (f"{key}.png", f"{key_stem(key)}.png"):
        p = folder / name
        if p.is_file():
            data = np.fromfile(str(p), np.uint8)
            m = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if data.size else None
            if m is not None:
                return m <= 127
    return None


def circle(shape, radius: float) -> np.ndarray:
    """True inside a centred circle of *radius* % of the inscribed circle."""
    h, w = shape
    yy, xx = np.ogrid[:h, :w]
    return np.hypot(xx - (w - 1) / 2, yy - (h - 1) / 2) <= radius / 100.0 * min(h, w) / 2


def _fit(mask: np.ndarray, shape) -> np.ndarray:
    if mask.shape == tuple(shape):
        return mask
    return cv2.resize(mask.astype(np.uint8), (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST) > 0


def _tile(work: np.ndarray, combined: np.ndarray, per_label: Dict[str, np.ndarray], colors: Dict[str, tuple],
          ref: Optional[np.ndarray], caption: str) -> np.ndarray:
    h, w = work.shape[:2]
    s = TILE / max(h, w)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    img = cv2.resize(work, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    c = cv2.resize(combined.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    img[c] = img[c] * 0.55 + np.array(TINT, np.float32) * 0.45
    img = img.astype(np.uint8)
    for label, m in per_label.items():
        small = cv2.resize(m.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST)
        contours, _ = cv2.findContours(small, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, contours, -1, colors[label], 1)
    if ref is not None:
        small = cv2.resize(ref.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST)
        contours, _ = cv2.findContours(small, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, contours, -1, REFERENCE, 1)
    out = np.zeros((TILE + 22, TILE, 3), np.uint8)
    out[:size[1], :size[0]] = img
    cv2.putText(out, caption[:60], (4, TILE + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (230, 230, 230), 1, cv2.LINE_AA)
    return out


def _legend(colors: Dict[str, tuple], reference: bool) -> np.ndarray:
    items = [("people mask (filled)", TINT)] + list(colors.items()) + ([("reference", REFERENCE)] if reference else [])
    out = np.zeros((24, TILE * COLUMNS, 3), np.uint8)
    x = 6
    for text, color in items:
        cv2.rectangle(out, (x, 7), (x + 12, 17), color, -1)
        cv2.putText(out, text, (x + 16, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (230, 230, 230), 1, cv2.LINE_AA)
        x += 16 + 8 * len(text) + 18
    return out


def _sheet(tiles: List[np.ndarray], legend: np.ndarray) -> np.ndarray:
    rows = [tiles[i:i + COLUMNS] for i in range(0, len(tiles), COLUMNS)]
    blank = np.zeros_like(tiles[0])
    grid = np.vstack([np.hstack(r + [blank] * (COLUMNS - len(r))) for r in rows])
    return np.vstack([legend, grid])


def probe(images: Path, keys: Sequence[str], detect: Callable, person: PersonStep, also: Sequence[str] = (),
          reference: Optional[Path] = None, out: Optional[Path] = None, inside: Optional[float] = None,
          log: Callable[[str], None] = print) -> dict:
    """Run *person*'s prompts and the extra ones in *also* on the frames *keys*; *detect*(image, labels)
    is SAM3 (:meth:`InferenceEngine.detect_many`). Writes ``sheet_NN.jpg`` to *out*. *inside*: compare with
    the reference only inside a centred circle of this radius (% of the inscribed circle), so a lens edge in
    the reference does not count. Returns the report."""
    from src.core.people import people_mask
    from src.engine.imageio import read_rgb, to_working

    steady = list(getattr(person, "steady", []))  # one frame at a time here: treated as attach (p145)
    prompts = list(dict.fromkeys([*person.labels, *person.attach, *steady, *also]))
    colors = {p: COLORS[i % len(COLORS)] for i, p in enumerate(prompts)}
    stats = {p: {"found_in": 0, "scores": [], "area": [], "covers": [], "spill": []} for p in prompts}
    frames: Dict[str, dict] = {}
    tiles: List[np.ndarray] = []
    sheets: List[str] = []
    legend = _legend(colors, reference is not None)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)

    def flush():
        if out is not None and tiles:
            path = out / f"sheet_{len(sheets) + 1:02d}.jpg"
            ok, buf = cv2.imencode(".jpg", cv2.cvtColor(_sheet(tiles, legend), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
            if ok:
                buf.tofile(str(path))
                sheets.append(path.name)
        tiles.clear()

    for n, key in enumerate(keys, 1):
        work = to_working(read_rgb(images / key), person.max_side)
        shape = work.shape[:2]
        dets = detect(work, prompts)
        per_label: Dict[str, np.ndarray] = {}
        for d in dets:
            if d.score >= person.threshold and d.mask.shape == shape:
                per_label[d.label] = per_label.get(d.label, np.zeros(shape, bool)) | d.mask
                stats[d.label]["scores"].append(float(d.score))
        combined = people_mask(dets, shape, person.labels, [*person.attach, *steady], person.threshold, person.touch,
                               person.grow)
        ref = reference_mask(reference, key) if reference is not None else None
        ref = None if ref is None else _fit(ref, shape)
        area = circle(shape, inside) if inside else None
        if ref is not None and area is not None:
            ref = ref & area
        note: Dict[str, object] = {"found": {p: round(float(m.mean()), 4) for p, m in per_label.items()},
                                   "masked": round(float(combined.mean()), 4)}
        for p, m in per_label.items():
            stats[p]["found_in"] += 1
            stats[p]["area"].append(float(m.mean()))
            if area is not None:
                m = m & area
            if ref is not None and ref.any():
                stats[p]["covers"].append(float((m & ref).sum() / ref.sum()))
                if m.any():
                    stats[p]["spill"].append(float((m & ~ref).sum() / m.sum()))
        if ref is not None and ref.any():
            c = combined if area is None else combined & area
            inter, union = (c & ref).sum(), (c | ref).sum()
            note.update(iou=round(float(inter / union), 4), missed=round(float((ref & ~c).sum() / ref.sum()), 4),
                        extra=round(float((c & ~ref).sum() / ref.sum()), 4))
        elif reference is not None:
            note["reference"] = "missing" if ref is None else "empty"
        frames[key] = note
        caption = key + (f"  IoU {note['iou']:.3f}" if "iou" in note else "")
        tiles.append(_tile(work, combined, per_label, colors, ref, caption))
        if len(tiles) == PER_SHEET:
            flush()
        log(f"[{n}/{len(keys)}] {key}  " + (", ".join(per_label) or "nothing found")
            + (f"  IoU {note['iou']:.3f}" if "iou" in note else ""))
    flush()

    def mean(v):
        return round(float(np.mean(v)), 4) if v else None

    labels = {}
    for p, s in stats.items():
        labels[p] = {"role": "label" if p in person.labels else "attach" if p in person.attach
                     else "steady" if p in steady else "also",
                     "found_in": s["found_in"], "score_mean": mean(s["scores"]),
                     "score_max": round(max(s["scores"]), 3) if s["scores"] else None,
                     "area_mean": mean(s["area"]), "covers": mean(s["covers"]), "spill": mean(s["spill"])}
    report = {"frames_tried": len(keys), "person": person.__dict__, "inside": inside, "prompts": labels, "frames": frames, "sheets": sheets}
    ious = [f["iou"] for f in frames.values() if "iou" in f]
    if ious:
        worst = sorted(((f["iou"], k) for k, f in frames.items() if "iou" in f))[:5]
        report["against_reference"] = {
            "frames": len(ious), "iou_mean": mean(ious), "iou_min": round(min(ious), 4),
            "missed_mean": mean([f["missed"] for f in frames.values() if "missed" in f]),
            "extra_mean": mean([f["extra"] for f in frames.values() if "extra" in f]),
            "worst": [{"image": k, "iou": i} for i, k in worst]}
    return report


def table(report: dict) -> str:
    """The report as lines to print."""
    n = report["frames_tried"]
    lines = [f"{'prompt':<22} {'role':<7} {'found in':>9} {'score':>6} {'area %':>7} {'covers':>7} {'spill':>6}"]
    for p, s in report["prompts"].items():
        def pct(v):
            return "-" if v is None else f"{100 * v:.1f}"
        lines.append(f"{p[:22]:<22} {s['role']:<7} {s['found_in']:>4}/{n:<4} "
                     f"{'-' if s['score_mean'] is None else format(s['score_mean'], '.2f'):>6} {pct(s['area_mean']):>7} "
                     f"{pct(s['covers']):>7} {pct(s['spill']):>6}")
    r = report.get("against_reference")
    if r:
        lines.append(f"people mask vs reference ({r['frames']} frames): IoU {r['iou_mean']:.3f} (lowest {r['iou_min']:.3f}), "
                     f"missed {100 * r['missed_mean']:.1f} %, extra {100 * r['extra_mean']:.1f} %")
        lines.append("  lowest: " + ", ".join(f"{w['image']} {w['iou']:.3f}" for w in r["worst"]))
    return "\n".join(lines)
