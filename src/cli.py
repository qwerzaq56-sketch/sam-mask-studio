"""SAM Mask Studio without the window: ``python -m src.cli <command> ...`` (for batch pipelines).

``sky``: a sky mask for every image of a folder, at the image's full resolution — the Sky special
Object's model and settings (src/core/special.py), its edge decided again on the full-size image
(src/core/sky_edges.py), as the Export window does with "Sky edges at full resolution".

    python -m src.cli sky H:/scene/images --out H:/scene/sky_masks --recursive

``--color-preset NAME`` then puts By Color on each full-size mask, as the app's auto tool does: a preset saved
in the app's By Color panel (config.local.json) or a .json file of those settings (p109). With it, tree tips the
sky model painted over beyond By Color's band (rough, not sky-colored, near the tree) are taken out too
(p110; ``--no-tree-tips`` leaves them), and SAM2 brings back the sky pieces whose colors the preset does not
have (p111, src/core/sky_sam2.py): on the GPU (keep it free: no training, no viewer), or ``--cpu`` (about 10x
slower). By Color alone misses those pieces (missed 1.13 % against 0.34 % on the 0022 truth), so there is no
way to leave SAM2 out.

``lens``: a fisheye's image circle for every image — the Lens edge special Object's circle, found in
each camera folder's frames (cam0/ and cam1/ may differ), pulled in by a margin over the lens rim's glow.

    python -m src.cli lens H:/scene/images --out H:/scene/masks --recursive [--and-with H:/scene/person_masks]

``person``: people and what they carry (the selfie stick, a bag) for every image, from SAM3's text
prompts (src/core/people.py) — on the GPU, so never while a training runs.

    python -m src.cli person H:/scene/images --out H:/scene/people_masks --recursive

A scene's ``masks/`` (people and the lens edge, black = ignored): ``person`` to a folder, then ``lens``
``--and-with`` it into ``masks/``.

Presets (src/batchmask/): which steps a scene gets and with what settings — above all the SAM3 prompts,
which fit the rig and scenes a preset was checked on and maybe nothing else.

    python -m src.cli run H:/scene/images --preset osmo360-selfie-stick --out H:/scene --recursive
    python -m src.cli probe H:/scene/images --out H:/tmp/probe --recursive --preset people-only --also "black pole;bag"
    python -m src.cli preset list | show NAME | save NAME --from NAME --labels "person;silver pole"

``run`` writes ``masks/`` and ``sky_masks/`` into the scene folder, all of a preset's steps; ``probe`` tries
prompts on a few frames (a table, contact sheets, scores against hand-checked masks) before a whole run;
``sky``, ``lens`` and ``person`` take ``--preset`` too, their own options changing it.

Common to all:

- One PNG per image, named ``<image name>.png`` (``00011.jpg.png``; ``--names stem``: ``00011.png``),
  sub-folders kept (``cam0/``, ``cam1/``).
- Files already in ``--out`` are never replaced unless asked: ``--skip-existing`` (carry on after a
  stop) or ``--overwrite``.
- sky and lens use no GPU (sky: about 2-3 s per 3840² image on the CPU; lens: about 0.1 s). person needs
  about 4.5 GB of it (about 2 s per image) and refuses to start when less is free.
- Exit code 0 when every image got a mask, 1 when some failed (listed), 2 for a wrong call.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.core.sky_sam2 import SKY_GPU_NEEDED, SKY_SAM2
from src.core.special import LENS_MARGIN  # % of the radius: the soft, dark rim (p127: 2 -> 5)
from src.version import app_version

ROOT = Path(__file__).resolve().parents[1]
SKY_MODEL = ROOT / "checkpoints" / "sky" / "skyseg.onnx"
LENS_SAMPLES = 16  # frames per camera folder the circle is found in
SAM3_MODEL = ROOT / "checkpoints" / "sam3" / "sam3.pt"
SAM2_MODEL = SKY_SAM2  # SAM2 tiny: the engine wants a path; sky after By Color loads it
GPU_NEEDED = 5.0  # GB free before person starts (SAM3 at 1024 px peaked at 4.2 GB on 0022)
KEYFRAME_MIN_PIECE = 0.0005  # of the frame: smaller pieces of a keyframe's people are not propagated


def _write_png(path: Path, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", mask.astype(np.uint8) * 255)
    if not ok:
        raise IOError(f"PNG encode failed for {path}")
    buf.tofile(str(path))  # non-ASCII Windows paths


def _read_mask(path: Path) -> Optional[np.ndarray]:
    data = np.fromfile(str(path), dtype=np.uint8)
    m = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if data.size else None
    return None if m is None else m > 127


class Batch:
    """A folder's images, where their masks go, which to make, and the run's report."""

    def __init__(self, command: str, images: Path, out: Path, recursive: bool, names: str, existing: str,
                 settings: dict, log: Callable[[str], None] = print):
        from src.engine.imageio import find_images, image_key, key_stem

        paths = find_images(images, recursive=recursive)
        if not paths:
            raise SystemExit(f"No images in {images}" + ("" if recursive else " (sub-folders: --recursive)"))
        self.images, self.out, self.names, self.log = images, out, names, log
        self._stem = key_stem
        self.keys = [image_key(images, p) for p in paths]
        there = [k for k in self.keys if self.target(k).exists()]
        if there and existing == "stop":
            raise SystemExit(f"{len(there)} of {len(self.keys)} mask(s) already in {out} "
                             f"(e.g. {self.target(there[0]).name}). Nothing written. "
                             "--skip-existing to carry on, --overwrite to replace them.")
        skip = set(there) if existing == "skip" else set()
        self.todo = [k for k in self.keys if k not in skip]
        self.report = {
            "command": command, "version": app_version(), "images": str(images), "out": str(out),
            "settings": dict(settings, names=names), "total": len(self.keys),
            "skipped_existing": len(self.keys) - len(self.todo), "written": 0, "failed": [], "frames": {},
        }
        self._t0 = time.time()

    def name(self, key: str) -> str:
        return f"{key}.png" if self.names == "name" else f"{self._stem(key)}.png"

    def target(self, key: str) -> Path:
        return self.out / self.name(key)

    def run(self, make: Callable[[str], Tuple[np.ndarray, dict]], what: Callable[[dict], str]) -> dict:
        """*make*(key) -> (the mask to write, what to note for that frame); one bad image never ends it."""
        for n, key in enumerate(self.todo, 1):
            t = time.time()
            try:
                mask, note = make(key)
                _write_png(self.target(key), mask)
            except Exception as e:
                self.fail(key, f"{type(e).__name__}: {e}", f"[{n}/{len(self.todo)}]")
                continue
            self.report["written"] += 1
            self.report["frames"][key] = dict(note, seconds=round(time.time() - t, 2))
            self.log(f"[{n}/{len(self.todo)}] {key}  {what(note)}  {time.time() - t:.1f}s")
        self.report["seconds"] = round(time.time() - self._t0, 1)
        return self.report

    def fail(self, key: str, error: str, where: str = "") -> None:
        self.report["failed"].append({"image": key, "error": error})
        self.log(f"{where} {key}  FAILED: {error}".strip())


def sky_folder(images: Path, out: Path, recursive: bool = False, names: str = "name", invert: bool = False,
               threshold: float = 50.0, grow: int = 0, top_only: bool = False, refine: bool = True,
               edges: bool = True, max_side: int = 1024, model_path: Path = SKY_MODEL,
               existing: str = "stop", log=print, color: Optional[dict] = None, tree_tips: bool = True,
               device: str = "cuda") -> dict:
    """The ``sky`` command; returns its report (also what ``--report`` writes). *color*: By Color settings (a
    preset as the app saves it, see :func:`color_preset`) put on each full-size mask before ``invert``;
    *tree_tips*: with them, also take out the tree tips beyond By Color's band (:func:`src.core.refine.tree_tips`).
    With *color*, SAM2 on *device* then brings back the sky pieces By Color left out
    (:func:`src.core.sky_sam2.sam2_tiles`)."""
    from src.core.refine import TREE_TIPS
    from src.core.sky_edges import sky_edges
    from src.core.sky_sam2 import SAM2_TILES, finish_sky, tips_apply
    from src.core.special import SKY, SkyModel, Special, sky_maps, sky_mask
    from src.engine.imageio import read_rgb, resize_mask, to_working

    tips_on = tips_apply(color, tree_tips)
    b = Batch("sky", images, out, recursive, names, existing, log=log, settings={
        "threshold": threshold, "grow": grow, "top_only": top_only, "refine": refine,
        "full_resolution_edges": edges, "max_side": max_side, "invert": invert, "model": str(model_path),
        "by_color": color, "tree_tips": dict(TREE_TIPS) if tips_on else None,
        "sam2": {**SAM2_TILES, "model": SAM2_MODEL.name, "device": device} if color is not None else None})
    sp = Special.new(SKY).with_params(threshold=threshold, grow=grow, top_only=float(top_only),
                                      refine=float(refine))
    model = SkyModel(model_path)
    sam2 = _sam2_engine(device) if color is not None else None

    def make(key):
        rgb = read_rgb(images / key)
        prob, refined = sky_maps(model, to_working(rgb, max_side))
        m = sky_mask(refined if refine else prob, sp)
        full = sky_edges(m, rgb) if edges else resize_mask(m, rgb.shape[:2])
        note = {}
        if color is not None:
            full, note["sam2_clicks"] = finish_sky(full, rgb, color, tree_tips, sam2)
        return (~full if invert else full), {"sky": round(float(full.mean()), 4), **note}

    return b.run(make, lambda note: f"sky {100 * note['sky']:.1f}%")


def _folder(key: str) -> str:
    return key.rsplit("/", 1)[0] if "/" in key else ""


def find_circles(images: Path, keys: Sequence[str], samples: int = LENS_SAMPLES,
                 max_side: int = 1024) -> Dict[str, Optional[dict]]:
    """The image circle (radius, cx, cy in % of the inscribed circle, as the Lens edge Object keeps them) of
    each camera folder among *keys*, from up to *samples* frames spread over it; with how much single
    frames disagree (``spread``: their standard deviation). None for a folder with no circle to see."""
    from src.core.special import detect_lens_circle
    from src.engine.imageio import read_rgb, to_working

    groups: Dict[str, List[str]] = {}
    for k in keys:
        groups.setdefault(_folder(k), []).append(k)
    found: Dict[str, Optional[dict]] = {}
    for folder, ks in groups.items():
        pick = [ks[i] for i in np.unique(np.linspace(0, len(ks) - 1, min(samples, len(ks))).astype(int))]
        frames = [to_working(read_rgb(images / k), max_side) for k in pick]
        circle = detect_lens_circle(frames)
        if circle is not None:
            singles = [c for c in (detect_lens_circle([f]) for f in frames) if c is not None]
            if len(singles) > 1:
                circle["spread"] = {p: round(float(np.std([c[p] for c in singles])), 2) for p in ("radius", "cx", "cy")}
            circle["frames"] = len(pick)
        found[folder] = circle
    return found


def lens_folder(images: Path, out: Path, recursive: bool = False, names: str = "name", invert: bool = False,
                margin: float = LENS_MARGIN, circle: Optional[dict] = None, samples: int = LENS_SAMPLES,
                and_with: Optional[Path] = None, existing: str = "stop", log=print) -> dict:
    """The ``lens`` command: white = inside the image circle (what training uses), black = outside it and
    the rim's *margin* (% of the radius). *circle*: radius / cx / cy (%) for every folder instead of
    finding it. *and_with*: a mask folder (white = keep, same names) multiplied in, e.g. people already
    masked: the result is one ``masks/`` folder. Returns the report."""
    from src.core.special import LENS_EDGE, Special, lens_circle, lens_edge_mask
    from src.engine.imageio import original_size

    b = Batch("lens", images, out, recursive, names, existing, log=log, settings={
        "margin": margin, "given_circle": circle, "samples": samples, "invert": invert,
        "and_with": str(and_with) if and_with else None})
    if circle is not None:
        circles = {f: dict(circle) for f in {_folder(k) for k in b.todo}}
    else:
        circles = find_circles(images, b.todo, samples)
    b.report["circles"] = {}
    for folder, c in circles.items():
        name = folder or "."
        if c is None:
            log(f"{name}: no image circle found (no black edge around the images: not a fisheye?)")
        else:
            b.report["circles"][name] = c
            log(f"{name}: circle radius {c['radius']} %, center {c['cx']:+} / {c['cy']:+} %"
                + (f" (from {c['frames']} frame(s); single frames differ by ±{c['spread']['radius']} / "
                   f"±{c['spread']['cx']} / ±{c['spread']['cy']})" if "spread" in c else ""))
    masks: Dict[Tuple[str, int, int], Tuple[np.ndarray, list]] = {}  # one per camera folder and image size
    missing = []

    def make(key):
        c = circles.get(_folder(key))
        if c is None:
            raise ValueError("no image circle in this folder (pass --radius to set one)")
        h, w = original_size(images / key)
        cache = (_folder(key), h, w)
        if cache not in masks:
            sp = Special.new(LENS_EDGE).with_params(radius=c["radius"] * (1 - margin / 100.0), cx=c["cx"], cy=c["cy"])
            masks[cache] = ~lens_edge_mask(h, w, sp), [round(v, 1) for v in lens_circle(h, w, sp)]
        keep, circle_px = masks[cache]
        if and_with is not None:
            keep = _multiply(keep, and_with, b.name(key), missing, key)
        return (~keep if invert else keep), {"kept": round(float(keep.mean()), 4), "circle_px": circle_px}

    report = b.run(make, lambda note: f"kept {100 * note['kept']:.1f}%")
    if and_with is not None:
        report["and_with_missing"] = missing
        if missing:
            log(f"{len(missing)} image(s) had no mask in {and_with}: the lens edge alone was written for them")
    return report


def _multiply(keep: np.ndarray, folder: Path, name: str, missing: List[str], key: str) -> np.ndarray:
    """*keep* times the mask *name* in *folder* (white = keep); noted in *missing* when there is none."""
    other = _read_mask(folder / name) if (folder / name).exists() else None
    if other is None:
        missing.append(key)
        return keep
    if other.shape != keep.shape:
        other = cv2.resize(other.astype(np.uint8), (keep.shape[1], keep.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    return keep & other


def gpu_free_gb() -> Optional[float]:
    """Free GPU memory in GB, None without CUDA."""
    import torch

    if not torch.cuda.is_available():
        return None
    free, _total = torch.cuda.mem_get_info()
    return free / 2**30


def _sam2_engine(device: str):
    """SAM2 alone (sky after By Color)."""
    from src.engine.inference import InferenceEngine

    eng = InferenceEngine(str(SAM2_MODEL), None, device=device)
    eng.load_sam2()
    return eng


def _engine(model: Path, device: str):
    from src.engine.inference import InferenceEngine

    eng = InferenceEngine(str(SAM2_MODEL), str(model), device=device)
    eng.load_sam3()
    return eng


def keyframe_indices(n: int, every: int) -> List[int]:
    """The frames SAM3 looks at among *n* in a row: every *every*-th from the first, and the last."""
    picks = list(range(0, n, max(1, every)))
    if picks[-1] != n - 1:
        picks.append(n - 1)
    return picks


def mask_pieces(mask: np.ndarray, min_share: float = KEYFRAME_MIN_PIECE) -> Dict[int, np.ndarray]:
    """A mask's separate pieces as SAM2 objects 1, 2, ..., specks under *min_share* of the frame left out."""
    n, lab = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    out: Dict[int, np.ndarray] = {}
    for i in range(1, n):
        piece = lab == i
        if piece.sum() >= min_share * mask.size:
            out[len(out) + 1] = piece
    return out


def propagated(images: Path, keys: Sequence[str], marks: Dict[int, np.ndarray], wanted: Callable[[int], bool],
               max_side: int, device: str, propagate) -> Iterator[Tuple[int, np.ndarray, int]]:
    """The people of each frame of one camera folder (*keys*, in order) at the working size, in order: the
    keyframes' own masks (*marks*: index -> mask), a frame between two keyframes the union of what SAM2
    carries forward from the one before and back from the one after. Yields (index, mask, how many keyframes
    it came from; 0 for a keyframe). A keyframe's SAM2 run is left out when no frame it reaches is *wanted*."""
    from src.core.propagation import Direction, PropagationPlan

    paths = [images / k for k in keys]
    picks = sorted(marks)
    got: Dict[int, np.ndarray] = {}
    hits: Dict[int, int] = {}
    nxt = 0  # the next index to hand out
    for j, k in enumerate(picks):
        lo = picks[j - 1] if j else k
        hi = picks[j + 1] if j + 1 < len(picks) else k
        seeds = mask_pieces(marks[k])
        if seeds and any(wanted(i) for i in range(lo + 1, hi) if i not in marks):
            plan = PropagationPlan(lo, hi, k, Direction.BOTH)
            for idx, objs in propagate(str(SAM2_MODEL), paths, plan, seeds, max_side, device=device):
                if idx in marks:
                    continue
                m = got.get(idx, np.zeros_like(marks[k]))
                for o in objs.values():
                    if o.shape == m.shape:
                        m = m | o
                got[idx] = m
                hits[idx] = hits.get(idx, 0) + 1
        while nxt <= k:  # every frame up to this keyframe has had both its keyframes now
            if nxt in marks:
                yield nxt, marks[nxt], 0
            else:
                yield nxt, got.pop(nxt, np.zeros_like(marks[k])), hits.pop(nxt, 0)
            nxt += 1


def person_folder(images: Path, out: Path, recursive: bool = False, names: str = "name", invert: bool = False,
                  labels: Sequence[str] = (), attach: Sequence[str] = (), threshold: float = 0.4,
                  grow: int = 2, max_side: int = 1024, touch: int = 16, model: Path = SAM3_MODEL, device: str = "cuda",
                  and_with: Optional[Path] = None, existing: str = "stop", keyframes: int = 0, propagate=None,
                  log=print) -> dict:
    """The ``person`` command: black = people and what they carry (ignored in training), white = the rest
    (``--invert``: white = people). Returns the report.

    *keyframes* N > 1: SAM3 only on every N-th frame of each camera folder (and its last), then SAM2
    propagation as the app's (:func:`src.engine.video.propagate`, or *propagate*) from each keyframe to its
    neighbours; a frame in between gets the union of both sides. SAM3 is released before SAM2 loads."""
    from src.core.people import grow_mask, people_mask
    from src.engine.imageio import read_rgb, resize_mask, to_working

    every = keyframes if keyframes > 1 else 0
    b = Batch("person", images, out, recursive, names, existing, log=log, settings={
        "labels": list(labels), "attach": list(attach), "threshold": threshold, "touch": touch, "grow": grow,
        "max_side": max_side, "invert": invert, "model": str(model), "device": device,
        "and_with": str(and_with) if and_with else None,
        **({"keyframes": every, "propagation_model": SAM2_MODEL.name} if every else {})})
    missing: List[str] = []
    if b.todo:
        t = time.time()
        eng = _engine(model, device)
        log(f"SAM3 loaded on {eng.device} in {time.time() - t:.0f} s")
    else:
        eng = None

    def detect(key):
        """(full size, the people at the working size before growing, what was found)."""
        rgb = read_rgb(images / key)
        work = to_working(rgb, max_side)
        dets = eng.detect_many(work, list(labels) + list(attach))
        counts: Dict[str, int] = {}
        for d in dets:
            if d.score >= threshold:
                counts[d.label] = counts.get(d.label, 0) + 1
        return rgb.shape[:2], people_mask(dets, work.shape[:2], labels, attach, threshold, touch, 0), counts

    def finish(key, people, size, note):
        found = resize_mask(grow_mask(people, grow), size)
        keep = ~found
        if and_with is not None:
            keep = _multiply(keep, and_with, b.name(key), missing, key)
        return (~keep if invert else keep), dict(note, people=round(float(found.mean()), 4))

    def make(key):
        size, people, counts = detect(key)
        return finish(key, people, size, {"found": counts})

    def what(note):
        if "from_keyframes" in note:
            how = f"propagated from {note['from_keyframes']} keyframe(s)"
        else:
            how = ", ".join(f"{k} {v}" for k, v in note["found"].items()) or "nothing found"
        return f"masked {100 * note['people']:.1f}%  {how}"

    if every and b.todo:
        make = _keyframe_maker(b, images, every, detect, finish, max_side, device,
                               propagate or _default_propagate(), eng, log)
        eng = None  # released once the keyframes are done
    report = b.run(make, what)
    if every:
        report["keyframe_count"] = sum(1 for n in report["frames"].values() if "found" in n)
    if and_with is not None:
        report["and_with_missing"] = missing
        if missing:
            log(f"{len(missing)} image(s) had no mask in {and_with}: the people alone were written for them")
    if eng is not None and hasattr(eng, "release"):
        eng.release()
    return report


def _default_propagate():
    from src.engine.video import propagate

    return propagate


def _keyframe_maker(b: "Batch", images: Path, every: int, detect, finish, max_side: int, device: str, propagate,
                    eng, log):
    """``make`` for :func:`person_folder` with keyframes: SAM3 on every keyframe first (then released), then
    each camera folder's frames in order from :func:`propagated`."""
    from src.engine.imageio import read_rgb

    todo = set(b.todo)
    folders: Dict[str, List[str]] = {}
    for k in b.keys:
        folders.setdefault(_folder(k), []).append(k)
    marks: Dict[str, Dict[int, np.ndarray]] = {}
    sizes: Dict[str, tuple] = {}
    found: Dict[str, dict] = {}
    t = time.time()
    for folder, keys in folders.items():
        marks[folder] = {}
        for i in keyframe_indices(len(keys), every):
            sizes[keys[i]], marks[folder][i], found[keys[i]] = detect(keys[i])
    log(f"SAM3 on {sum(len(m) for m in marks.values())} keyframe(s) (every {every}) in {time.time() - t:.0f} s; "
        "SAM2 propagation between them")
    if hasattr(eng, "release"):
        eng.release()
    streams = {f: propagated(images, keys, marks[f], lambda i, ks=keys: ks[i] in todo, max_side, device, propagate)
               for f, keys in folders.items()}
    where = {k: (f, i) for f, keys in folders.items() for i, k in enumerate(keys)}

    def make(key):
        folder, i = where[key]
        for j, people, hits in streams[folder]:
            if j == i:
                break
        else:
            raise RuntimeError("propagation ended before this frame")
        if key in found:
            return finish(key, people, sizes[key], {"found": found[key]})
        return finish(key, people, read_rgb(images / key).shape[:2], {"from_keyframes": hits})

    return make


def probe_folder(images: Path, out: Path, person, recursive: bool = False, also: Sequence[str] = (),
                 frames: int = 8, reference: Optional[Path] = None, inside: Optional[float] = None,
                 model: Path = SAM3_MODEL, device: str = "cuda", log=print) -> dict:
    """The ``probe`` command: *person*'s prompts (a :class:`PersonStep`) and *also* tried on *frames* frames
    per camera folder; contact sheets and ``probe.json`` go to *out*. Returns the report."""
    from src.batchmask.probe import pick_frames, probe
    from src.engine.imageio import find_images, image_key

    paths = find_images(images, recursive=recursive)
    if not paths:
        raise SystemExit(f"No images in {images}" + ("" if recursive else " (sub-folders: --recursive)"))
    keys = pick_frames([image_key(images, p) for p in paths], frames)
    t = time.time()
    eng = _engine(model, device)
    log(f"SAM3 loaded on {eng.device} in {time.time() - t:.0f} s; trying {len(keys)} frame(s)")
    try:
        report = probe(images, keys, eng.detect_many, person, also, reference, out, inside, log)
    finally:
        if hasattr(eng, "release"):
            eng.release()
    report.update(command="probe", version=app_version(), images=str(images),
                  reference=str(reference) if reference else None, seconds=round(time.time() - t, 1))
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


RUN_FOLDERS = {"people": "people_masks", "masks": "masks", "sky": "sky_masks"}


def run_folders(preset, out: Path) -> Dict[str, Path]:
    """Where ``run`` writes: ``masks/`` (people and the lens edge, black = ignored; with both, the people
    first go to ``people_masks/``) and ``sky_masks/`` (white = sky)."""
    f: Dict[str, Path] = {}
    if preset.person is not None:
        f["person"] = out / RUN_FOLDERS["people" if preset.lens is not None else "masks"]
    if preset.lens is not None:
        f["lens"] = out / RUN_FOLDERS["masks"]
    if preset.sky is not None:
        f["sky"] = out / RUN_FOLDERS["sky"]
    return f


def run_folder(images: Path, out: Path, preset, recursive: bool = False, names: str = "name",
               existing: str = "stop", sam3_model: Path = SAM3_MODEL, sky_model: Path = SKY_MODEL,
               device: str = "cuda", log=print) -> dict:
    """The ``run`` command: every step of *preset* (a :class:`MaskPreset`) into the scene folder *out*.
    Masks already in any of its folders stop it before anything runs (unless *existing* says otherwise)."""
    folders = run_folders(preset, out)
    if not folders:
        raise SystemExit(f"Preset {preset.name} has no steps (person, lens, sky): nothing to do.")
    if existing == "stop":
        full = [f"{p} ({sum(1 for _ in p.rglob('*.png'))} PNG)" for p in dict.fromkeys(folders.values())
                if p.is_dir() and any(p.rglob("*.png"))]
        if full:
            raise SystemExit("Masks already there: " + ", ".join(full) + ". Nothing done. "
                             "--skip-existing to carry on, --overwrite to replace them, or another --out.")
    log(f"Preset {preset.name}" + (f" ({preset.title})" if preset.title else ""))
    for line in preset.summary().splitlines():
        log("  " + line)
    if preset.checked_on:
        log("  checked on: " + " | ".join(preset.checked_on))
    else:
        log("  not checked on any data yet: look at the results (or probe first)")
    t = time.time()
    steps: Dict[str, dict] = {}
    common = dict(recursive=recursive, names=names, existing=existing, log=log)
    if preset.person is not None:
        p = preset.person
        log(f"--- person -> {folders['person']}")
        steps["person"] = person_folder(images, folders["person"], labels=p.labels, attach=p.attach,
                                        threshold=p.threshold, grow=p.grow, max_side=p.max_side, touch=p.touch,
                                        model=sam3_model, device=device, **common)
    if preset.lens is not None:
        c = preset.lens
        log(f"--- lens -> {folders['lens']}" + (f" (with {folders['person'].name}/)" if "person" in folders else ""))
        steps["lens"] = lens_folder(images, folders["lens"], margin=c.margin, samples=c.samples,
                                    circle=None if c.radius is None else {"radius": c.radius, "cx": c.cx, "cy": c.cy},
                                    and_with=folders.get("person"), **common)
    if preset.sky is not None:
        s = preset.sky
        log(f"--- sky -> {folders['sky']}")
        steps["sky"] = sky_folder(images, folders["sky"], threshold=s.threshold, grow=s.grow, top_only=s.top_only,
                                  refine=s.refine, edges=s.edges, max_side=s.max_side, model_path=sky_model,
                                  color=s.color, tree_tips=s.tree_tips, device=device, **common)
    return {
        "command": "run", "version": app_version(), "images": str(images), "out": str(out),
        "preset": preset.to_dict(), "folders": {k: str(v) for k, v in folders.items()}, "steps": steps,
        "written": sum(r["written"] for r in steps.values()),
        "skipped_existing": sum(r["skipped_existing"] for r in steps.values()),
        "failed": [dict(f, step=s) for s, r in steps.items() for f in r["failed"]],
        "seconds": round(time.time() - t, 1),
    }


def _common(p: argparse.ArgumentParser, what: str) -> None:
    p.add_argument("images", type=Path, help="Image folder")
    p.add_argument("--out", type=Path, required=True, help="Mask folder (made if missing)")
    p.add_argument("--recursive", action="store_true", help="Also the sub-folders (cam0/, cam1/), kept in --out")
    p.add_argument("--names", choices=("name", "stem"), default="name",
                   help="name: 00011.jpg.png (COLMAP, default); stem: 00011.png")
    p.add_argument("--invert", action="store_true", help=what)
    how = p.add_mutually_exclusive_group()
    how.add_argument("--skip-existing", action="store_true", help="Leave masks already in --out, make the rest")
    how.add_argument("--overwrite", action="store_true", help="Replace masks already in --out")
    p.add_argument("--report", type=Path, help="Write the run's report (JSON) here")


def _preset_option(p: argparse.ArgumentParser) -> None:
    p.add_argument("--preset", help="A masking preset by name ('preset list') or a .json file: its settings for this "
                                    "step, the options given here changing them")


def _person_options(p: argparse.ArgumentParser) -> None:
    from src.core.people import ATTACH, GROW, LABELS, THRESHOLD, TOUCH

    p.add_argument("--labels", help=f"SAM3 text prompts always masked, ';'-separated (default {';'.join(LABELS)})")
    p.add_argument("--attach", help=f"Prompts masked only where they touch the above (default {';'.join(ATTACH)}; "
                                    "\"\" = none)")
    p.add_argument("--threshold", type=float, help=f"Detection score to keep (default {THRESHOLD})")
    p.add_argument("--touch", type=int, help=f"How near (px at 1024) an --attach find must be (default {TOUCH})")
    p.add_argument("--grow", type=int, help=f"Grow the mask by px at 1024 px (default {GROW})")
    p.add_argument("--max-side", type=int, help="Working resolution's longer side (default 1024)")


def _gpu_options(p: argparse.ArgumentParser, model: str = "--model") -> None:
    p.add_argument(model, dest="sam3_model", type=Path, default=SAM3_MODEL, help=f"sam3.pt (default {SAM3_MODEL})")
    p.add_argument("--cpu", action="store_true", help="Run SAM3 on the CPU (very slow)")
    p.add_argument("--gpu-anyway", action="store_true",
                   help=f"Start even with less than {GPU_NEEDED:.0f} GB of GPU memory free")


# what the default steps are when no preset is given: the measured defaults of src/core/people.py
def _default_person():
    from src.batchmask.presets import PersonStep
    from src.core.people import ATTACH, GROW, LABELS, THRESHOLD, TOUCH

    return PersonStep(labels=list(LABELS), attach=list(ATTACH), threshold=THRESHOLD, touch=TOUCH, grow=GROW)


COLOR_KEYS = {"color_samples", "color_tol", "color_use", "color_not", "color_samples_out", "color_tol_out",
              "bright_range", "bright_use", "bright_not", "range_join", "color_invert", "color_band",
              "color_band_on", "color_action"}


def color_preset(value: str) -> dict:
    """By Color settings for ``sky --color-preset``: a .json file of them, else the name of a preset saved in the
    app's By Color panel (config.local.json ``color_presets``)."""
    p = Path(value)
    if p.suffix.lower() == ".json":
        if not p.is_file():
            raise ValueError(f"no such file: {p}")
        d = json.loads(p.read_text(encoding="utf-8"))
    else:
        from src.app.settings import Settings

        presets = Settings.load().color_presets
        if value not in presets:
            raise ValueError(f"no By Color preset '{value}' (saved in the app: {', '.join(presets) or 'none'})")
        d = presets[value]
    if not isinstance(d, dict):
        raise ValueError(f"By Color settings are a JSON object: {value}")
    bad = sorted(set(d) - COLOR_KEYS)
    if bad:
        raise ValueError(f"unknown By Color setting(s) in {value}: {', '.join(bad)}")
    return dict(d)


def _settings(parser: argparse.ArgumentParser, args, step: str):
    """(*step*'s settings: the preset's, else the defaults, changed by the options given; the preset or None)."""
    from dataclasses import asdict

    from src.batchmask.presets import STEPS, find_preset, split

    preset = None
    if getattr(args, "preset", None):
        try:
            preset = find_preset(args.preset)
        except ValueError as e:
            parser.error(str(e))
    base = getattr(preset, step, None) if preset is not None else None
    if base is None:
        base = _default_person() if step == "person" else STEPS[step]()
        if preset is not None:
            print(f"Preset {preset.name} has no {step} step: the defaults, changed by the options given")
    values = asdict(base)
    for k in values:
        v = getattr(args, k, None)
        if v is not None:
            values[k] = split(v) if k in ("labels", "attach") else v
    if getattr(args, "no_color", False):
        values["color"] = None
    elif getattr(args, "color_preset", None):
        try:
            values["color"] = color_preset(args.color_preset)
        except ValueError as e:
            parser.error(str(e))
    return STEPS[step](**values), preset


def _device(parser: argparse.ArgumentParser, args, sam3: bool = True, need: float = GPU_NEEDED) -> str:
    """cuda, or cpu with --cpu; refuses when another job (a training) holds the GPU. *sam3*: SAM3 runs (person),
    else SAM2 alone (sky after By Color); *need*: GB of GPU memory free to start."""
    if sam3 and not args.sam3_model.is_file():
        parser.error(f"SAM3 model not found: {args.sam3_model}")
    if not sam3 and not SAM2_MODEL.is_file():
        parser.error(f"SAM2 model not found: {SAM2_MODEL}")
    if args.cpu:
        return "cpu"
    free = gpu_free_gb()
    if free is None:
        parser.error("no CUDA GPU (--cpu to run on the CPU, very slowly)")
    if free < need and not args.gpu_anyway:
        raise SystemExit(f"Only {free:.1f} GB of GPU memory is free ({need:.0f} needed): another GPU "
                         "job (a training? a viewer?) is running. Nothing done. Free the GPU or wait for it; "
                         "--cpu (slow) or --gpu-anyway.")
    return "cuda"


def _preset_command(parser: argparse.ArgumentParser, args) -> int:
    from dataclasses import asdict

    from src.batchmask.presets import (MaskPreset, PersonStep, broken_presets, find_preset, list_presets, save_preset,
                                       split, user_dir, with_changes)

    try:
        if args.action == "list":
            for pr in list_presets():
                where = "built-in" if pr.builtin else str(pr.path)
                print(f"{pr.name:<28} {', '.join(pr.steps) or '-':<18} {'checked' if pr.checked_on else 'NOT CHECKED':<12} "
                      f"{pr.title}  [{where}]")
            for bad in broken_presets():
                print(f"(unreadable) {bad}")
            print(f"Your presets: {user_dir()}")
            return 0
        if args.action == "show":
            pr = find_preset(args.name)
            if args.json:
                print(json.dumps(pr.to_dict(), indent=2, ensure_ascii=False))
                return 0
            print(f"{pr.name}: {pr.title}" + (f"\n{pr.description}" if pr.description else ""))
            print(pr.summary())
            print("Checked on: " + ("\n  " + "\n  ".join(pr.checked_on) if pr.checked_on else
                                    "nothing yet: probe it on your frames"))
            print(f"File: {pr.path}" + (" (built-in)" if pr.builtin else ""))
            return 0
        # save
        base = find_preset(args.base) if args.base else MaskPreset(name=args.name, person=PersonStep())
        person = {k: (split(v) if k in ("labels", "attach") else v)
                  for k in asdict(PersonStep()) if (v := getattr(args, k, None)) is not None}
        changes = {"person": person if person else (asdict(base.person) if base.person else None)}
        if args.margin is not None or args.radius is not None:
            changes["lens"] = {k: v for k, v in (("margin", args.margin), ("radius", args.radius)) if v is not None}
        if args.sky_threshold is not None:
            changes["sky"] = {"threshold": args.sky_threshold}
        for step in ("person", "lens", "sky"):
            if getattr(args, f"no_{step}"):
                changes[step] = None
        pr = with_changes(base, name=args.name, **changes)
        pr.title = args.title if args.title is not None else (f"{base.title} (changed)" if args.base else "")
        if args.description is not None:
            pr.description = args.description
        elif args.base:
            pr.description = f"From {base.name}. " + base.description
        pr.checked_on = list(args.checked_on or [])  # what the base was checked on is not this one's
        path = save_preset(pr, args.to, overwrite=args.overwrite)
    except (ValueError, FileExistsError) as e:
        parser.error(str(e))
    print(f"Saved {path}\n{pr.summary()}")
    if not pr.checked_on:
        print("Not checked on any data: probe it (--reference with hand-checked masks), then --checked-on to note it.")
    return 0


def _truth_command(parser: argparse.ArgumentParser, args) -> int:
    from src.batchmask import truth as T
    from src.batchmask.presets import split

    if args.action == "make":
        if not args.images.is_dir():
            parser.error(f"not a folder: {args.images}")
        if not args.model.is_file():
            parser.error(f"sky model not found: {args.model}")
        keys = split(args.frames)
        missing = [k for k in keys if not (args.images / k).is_file()]
        if missing:
            parser.error(f"not in {args.images}: {', '.join(missing)}")
        from src.core.sky_edges import sky_edges
        from src.core.special import SKY, SkyModel, Special, sky_maps, sky_mask
        from src.engine.imageio import to_working

        model, sp = SkyModel(args.model), Special.new(SKY)

        def draft(rgb):
            _prob, refined = sky_maps(model, to_working(rgb, 1024))
            return sky_edges(sky_mask(refined, sp), rgb)

        try:
            m = T.make_set(args.images, keys, args.out, draft, args.per_frame, args.size, args.inside,
                           settings={"method": "cli sky defaults (skyseg, refine, full-resolution edges)",
                                     "version": app_version()})
        except FileExistsError as e:
            raise SystemExit(str(e))
        print(f"{len(m['crops'])} crop(s) in {args.out}: fix images/ in the app (drafts/ imports as an Object), "
              "export white = sky to images_masks/, then 'truth score'.")
        return 0
    if args.action == "auto":
        if not (args.truth / "manifest.json").is_file():
            parser.error(f"not a truth set (no manifest.json): {args.truth}")
        try:
            T.auto_set(args.truth, args.out, args.cut, args.max_de, app_version())
        except FileExistsError as e:
            raise SystemExit(str(e))
        print(f"Masks in {args.truth / args.out}, side by side in {args.truth / 'review'}: check them; fix the "
              "wrong ones in the app (import the folder as an Object) and export white = sky to images_masks/.")
        return 0
    for p in (args.truth, args.masks):
        if not p.is_dir():
            parser.error(f"not a folder: {p}")
    try:
        r = T.score(args.truth, args.masks, args.truth_masks, args.invert, args.invert_truth)
    except (FileNotFoundError, ValueError) as e:
        raise SystemExit(str(e))
    print(T.table(r))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description=f"SAM Mask Studio {app_version()}, "
                                     "no window (for batch pipelines)")
    sub = parser.add_subparsers(dest="command", required=True)
    sky = sub.add_parser("sky", help="Sky masks for a folder, at full resolution",
                         description="A sky mask per image (white = sky), its edge decided on the full-size image.")
    _common(sky, "Black = sky, white = the rest")
    _preset_option(sky)
    sky.add_argument("--threshold", type=float, help="Sky above this %% of the model's map (default 50)")
    sky.add_argument("--grow", type=int, help="Grow (+) / shrink (-) the sky by px at 1024 px (default 0)")
    sky.add_argument("--top-only", dest="top_only", action="store_const", const=True,
                     help="Only sky touching the image's top edge")
    sky.add_argument("--no-refine", dest="refine", action="store_const", const=False,
                     help="The model's map without its edge refinement")
    sky.add_argument("--no-edges", dest="edges", action="store_const", const=False,
                     help="Scale the working mask up (nearest) instead of deciding the edge at full resolution")
    sky.add_argument("--max-side", type=int, help="Working resolution's longer side (default 1024)")
    sky.add_argument("--color-preset", help="Put By Color on each full-size mask, as the app does: a preset saved in "
                                            "the app's By Color panel, by name, or a .json file of those settings")
    sky.add_argument("--no-color", action="store_true", help="No By Color, even if --preset has it")
    sky.add_argument("--no-tree-tips", dest="tree_tips", action="store_const", const=False,
                     help="With By Color, leave the tree tips beyond its band (by default they are taken out)")
    sky.add_argument("--model", type=Path, default=SKY_MODEL, help=f"skyseg.onnx (default {SKY_MODEL})")
    sky.add_argument("--cpu", action="store_true",
                     help="With --color-preset: run its SAM2 step on the CPU (about 10x slower than the GPU)")
    sky.add_argument("--gpu-anyway", action="store_true",
                     help=f"Start the SAM2 step even with less than {SKY_GPU_NEEDED:.0f} GB of GPU memory free")

    lens = sub.add_parser("lens", help="Fisheye lens edge masks for a folder",
                          description="White = inside the image circle (trained on), black = outside it and its "
                                      "rim. The circle is found per camera folder.")
    _common(lens, "White = outside the circle (the edge to ignore), black = inside")
    _preset_option(lens)
    lens.add_argument("--margin", type=float,
                      help=f"Pull the circle in by this %% of its radius, over the soft, dark rim (default {LENS_MARGIN:g})")
    lens.add_argument("--samples", type=int,
                      help=f"Frames per camera folder the circle is found in (default {LENS_SAMPLES})")
    lens.add_argument("--radius", type=float, help="Set the circle instead of finding it: radius in %% of the "
                                                    "inscribed circle (100 = touches the shorter sides)")
    lens.add_argument("--cx", type=float, help="With --radius: center right of the middle, %% (default 0)")
    lens.add_argument("--cy", type=float, help="With --radius: center below the middle, %% (default 0)")
    lens.add_argument("--and-with", type=Path, help="Mask folder (white = keep, same names) to multiply in, "
                                                    "e.g. people masks: one masks/ folder comes out")

    person = sub.add_parser("person", help="People and what they carry (selfie stick, bag), SAM3 on the GPU",
                            description="Black = people, the selfie stick and their bags (what training ignores), "
                                        "white = the rest: the masks/ convention. The prompts that fit one rig may "
                                        "not fit another: see 'probe'.")
    _common(person, "White = people, black = the rest")
    _preset_option(person)
    _person_options(person)
    _gpu_options(person)
    person.add_argument("--and-with", type=Path, help="Mask folder (white = keep, same names) to multiply in, "
                                                      "e.g. the lens edge: one masks/ folder comes out")
    person.add_argument("--keyframes", type=int, default=0, metavar="N",
                        help="SAM3 only on every N-th frame of each camera folder (and its last), SAM2 propagation "
                             "in between (as the app's Propagate). Default 0: SAM3 on every frame")

    probe = sub.add_parser("probe", help="Try SAM3 prompts on a few frames before a run (contact sheets, a table)",
                           description="What each prompt finds on a few frames per camera folder: in how many "
                                       "frames, how sure, how much; with --reference (hand-checked masks/, people "
                                       "only) how well it matches. Look at the sheets, change the prompts, try "
                                       "again; --save-preset keeps them.")
    probe.add_argument("images", type=Path, help="Image folder")
    probe.add_argument("--out", type=Path, required=True, help="Folder for the contact sheets and probe.json")
    probe.add_argument("--recursive", action="store_true", help="Also the sub-folders (cam0/, cam1/)")
    _preset_option(probe)
    _person_options(probe)
    probe.add_argument("--also", default="", help="More prompts to measure, not put in the mask: candidates, "
                                                  "';'-separated (e.g. \"selfie stick;tripod;backpack\")")
    probe.add_argument("--frames", type=int, default=8, help="Frames per camera folder (default 8)")
    probe.add_argument("--reference", type=Path, help="Masks checked by hand (masks/ convention: black = people), "
                                                      "same names as the images")
    probe.add_argument("--inside", type=float, help="Compare with --reference only inside a centred circle of this "
                                                    "radius (%% of the inscribed circle), e.g. 90 when the reference "
                                                    "also blacks out the lens edge")
    probe.add_argument("--save-preset", metavar="NAME", help="Save the tried settings as your preset NAME (on top "
                                                              "of --preset), noting the --reference score")
    probe.add_argument("--overwrite-preset", action="store_true", help="With --save-preset: replace NAME")
    _gpu_options(probe)

    pre = sub.add_parser("preset", help="List, show or save masking presets",
                         description="Presets keep the prompts and settings a rig needs. Built-in ones ship with "
                                     "the app; yours go to mask_presets/ (or $SMS_MASK_PRESETS).")
    pre_sub = pre.add_subparsers(dest="action", required=True)
    pre_sub.add_parser("list", help="Every preset, yours first")
    show = pre_sub.add_parser("show", help="One preset's settings and what it was checked on")
    show.add_argument("name", help="Name or .json file")
    show.add_argument("--json", action="store_true", help="As JSON")
    save = pre_sub.add_parser("save", help="Save a preset of your own (from another one, changed)")
    save.add_argument("name", help="New preset's name (a file name)")
    save.add_argument("--from", dest="base", help="Start from this preset (name or .json)")
    _person_options(save)
    save.add_argument("--margin", type=float, help="Lens: rim margin, %% of the radius (adds a lens step)")
    save.add_argument("--radius", type=float, help="Lens: a fixed circle radius, %% (adds a lens step)")
    save.add_argument("--sky-threshold", type=float, help="Sky: threshold, %% (adds a sky step)")
    for step in ("person", "lens", "sky"):
        save.add_argument(f"--no-{step}", action="store_true", help=f"No {step} step")
    save.add_argument("--title", help="One line saying what it is for")
    save.add_argument("--description", help="Longer notes")
    save.add_argument("--checked-on", action="append", help="What it was checked on, with the result (repeatable)")
    save.add_argument("--to", type=Path, help="Folder to save in (default: your preset folder)")
    save.add_argument("--overwrite", action="store_true", help="Replace a preset of yours with this name")

    run = sub.add_parser("run", help="Every step of a preset into a scene folder (masks/, sky_masks/)",
                         description="People, lens edge and sky as a preset says, into --out: masks/ (black = "
                                     "ignored; people then the lens edge, the people kept in people_masks/) and "
                                     "sky_masks/ (white = sky). Masks already there stop it before anything runs.")
    run.add_argument("images", type=Path, help="Image folder")
    run.add_argument("--preset", required=True, help="Preset name ('preset list') or .json file")
    run.add_argument("--out", type=Path, required=True, help="Scene folder: masks/, sky_masks/ go in it")
    run.add_argument("--recursive", action="store_true", help="Also the sub-folders (cam0/, cam1/), kept")
    run.add_argument("--names", choices=("name", "stem"), default="name",
                     help="name: 00011.jpg.png (COLMAP, default); stem: 00011.png")
    how = run.add_mutually_exclusive_group()
    how.add_argument("--skip-existing", action="store_true", help="Leave masks already there, make the rest")
    how.add_argument("--overwrite", action="store_true", help="Replace masks already there")
    run.add_argument("--report", type=Path, help="Write the run's report (JSON) here")
    run.add_argument("--sky-model", type=Path, default=SKY_MODEL, help=f"skyseg.onnx (default {SKY_MODEL})")
    _gpu_options(run, "--sam3-model")
    truth = sub.add_parser("truth", help="Sky ground truth: crops to fix by hand, and scores against them",
                           description="'make' cuts full-resolution crops where the sky's edge is hardest (with "
                                       "drafts to fix in this app); 'auto' makes careful masks of them from "
                                       "their colors to check by hand; 'score' compares any method's full-frame sky "
                                       "masks with the fixed crops (IoU, spill over tree tops, missed, edge F).")
    t_sub = truth.add_subparsers(dest="action", required=True)
    tm = t_sub.add_parser("make", help="Cut a truth set")
    tm.add_argument("images", type=Path, help="Image folder")
    tm.add_argument("--out", type=Path, required=True, help="New folder for the set (refused if it holds one)")
    tm.add_argument("--frames", required=True, help="Images, ';'-separated keys as in the folder (00429.jpg; "
                                                    "cam0/00429.jpg with sub-folders)")
    tm.add_argument("--per-frame", type=int, default=2, help="Crops per frame (default 2)")
    tm.add_argument("--size", type=int, default=768, help="Crop side in px (default 768: edited at full resolution)")
    tm.add_argument("--inside", type=float, default=90.0, help="Crops stay inside this %% of the inscribed circle "
                                                               "(default 90; 100+ for a non-fisheye)")
    tm.add_argument("--model", type=Path, default=SKY_MODEL, help=f"skyseg.onnx for the drafts (default {SKY_MODEL})")
    ta = t_sub.add_parser("auto", help="Careful sky masks of the crops from their colors, to check by hand")
    ta.add_argument("truth", type=Path, help="The truth set folder (manifest.json)")
    ta.add_argument("--out", default="candidates", help="Sub-folder for the masks (default candidates; "
                                                         "refused if it holds masks)")
    ta.add_argument("--cut", type=float, default=0.6, help="How much of a pixel must be sky (0-1, default 0.6: "
                                                           "mixed edge pixels go to the trees)")
    ta.add_argument("--max-de", type=float, default=22.0, help="Lab distance a sky pixel may have from the sky "
                                                               "around it (default 22; lower keeps more twigs)")
    ts = t_sub.add_parser("score", help="Score full-frame sky masks against a fixed truth set")
    ts.add_argument("truth", type=Path, help="The truth set folder (manifest.json)")
    ts.add_argument("masks", type=Path, help="Full-frame sky masks to score (white = sky; sub-folders as the images)")
    ts.add_argument("--truth-masks", type=Path, help="The fixed crops (default: images_masks/ or masks/ in the set)")
    ts.add_argument("--invert", action="store_true", help="The masks to score are black = sky")
    ts.add_argument("--invert-truth", action="store_true", help="The fixed crops are black = sky")
    ts.add_argument("--report", type=Path, help="Write the scores (JSON) here")
    args = parser.parse_args(argv)

    if args.command == "truth":
        return _truth_command(parser, args)
    if args.command == "preset":
        return _preset_command(parser, args)
    if not args.images.is_dir():
        parser.error(f"not a folder: {args.images}")
    if args.command == "probe":
        step, preset = _settings(parser, args, "person")
        if args.reference is not None and not args.reference.is_dir():
            parser.error(f"not a folder: {args.reference}")
        if args.save_preset:
            from src.batchmask.presets import check_name

            try:
                check_name(args.save_preset)
            except ValueError as e:
                parser.error(str(e))
        device = _device(parser, args)
        from src.batchmask.presets import split
        from src.batchmask.probe import table

        report = probe_folder(args.images, args.out, step, recursive=args.recursive, also=split(args.also),
                              frames=args.frames, reference=args.reference, inside=args.inside,
                              model=args.sam3_model, device=device)
        print(table(report))
        print(f"Contact sheets: {args.out} ({', '.join(report['sheets'])})")
        if args.save_preset:
            from dataclasses import asdict

            from src.batchmask.presets import MaskPreset, save_preset, with_changes

            base = preset or MaskPreset(name=args.save_preset)
            pr = with_changes(base, name=args.save_preset, person=asdict(step))
            pr.title = (f"{base.title} (changed)" if preset else "") or f"From probe on {args.images.name}"
            r = report.get("against_reference")
            pr.checked_on = [f"{args.images} ({r['frames']} frames, probe): IoU {r['iou_mean']:.3f}, lowest "
                             f"{r['iou_min']:.3f}, missed {100 * r['missed_mean']:.1f} %"] if r else []
            try:
                path = save_preset(pr, overwrite=args.overwrite_preset)
            except (ValueError, FileExistsError) as e:
                print(f"Preset not saved: {e}")
                return 1
            print(f"Saved preset {pr.name}: {path}")
        return 0
    existing = "skip" if args.skip_existing else "overwrite" if args.overwrite else "stop"
    if getattr(args, "and_with", None) is not None:
        if not args.and_with.is_dir():
            parser.error(f"not a folder: {args.and_with}")
        if args.and_with.resolve() == args.out.resolve():
            parser.error("--and-with and --out must be different folders")
    if args.command == "sky":
        s, _ = _settings(parser, args, "sky")
        device = _device(parser, args, sam3=False, need=SKY_GPU_NEEDED) if s.color is not None else "cpu"
        if s.color is not None and device == "cpu":
            print("SAM2 on the CPU: about 10x slower than the GPU (some 15 s a 3840² frame)")
        if not args.model.is_file():
            parser.error(f"sky model not found: {args.model} (download skyseg.onnx from "
                         "https://huggingface.co/JianyuanWang/skyseg into checkpoints/sky/)")
        report = sky_folder(
            args.images, args.out, recursive=args.recursive, names=args.names, invert=args.invert,
            threshold=s.threshold, grow=s.grow, top_only=s.top_only, refine=s.refine,
            edges=s.edges, max_side=s.max_side, model_path=args.model, existing=existing, color=s.color,
            tree_tips=s.tree_tips, device=device,
        )
    elif args.command == "lens":
        c, _ = _settings(parser, args, "lens")
        circle = None if c.radius is None else {"radius": c.radius, "cx": c.cx, "cy": c.cy}
        report = lens_folder(
            args.images, args.out, recursive=args.recursive, names=args.names, invert=args.invert,
            margin=c.margin, circle=circle, samples=c.samples, and_with=args.and_with, existing=existing,
        )
    elif args.command == "person":
        p, _ = _settings(parser, args, "person")
        device = _device(parser, args)
        report = person_folder(
            args.images, args.out, recursive=args.recursive, names=args.names, invert=args.invert,
            labels=p.labels, attach=p.attach, threshold=p.threshold, grow=p.grow, max_side=p.max_side,
            touch=p.touch, model=args.sam3_model, device=device, and_with=args.and_with, existing=existing,
            keyframes=args.keyframes,
        )
    elif args.command == "run":
        from src.batchmask.presets import find_preset

        try:
            preset = find_preset(args.preset)
        except ValueError as e:
            parser.error(str(e))
        device = "cpu"
        if preset.person is not None:
            device = _device(parser, args)
        elif preset.sky is not None and preset.sky.color is not None:  # SAM2 after By Color (p111)
            device = _device(parser, args, sam3=False, need=SKY_GPU_NEEDED)
        if args.cpu and (preset.person is not None or (preset.sky is not None and preset.sky.color is not None)):
            print("On the CPU: much slower than the GPU (the sky's SAM2 about 10x, SAM3 more)")
        if preset.sky is not None and not args.sky_model.is_file():
            parser.error(f"sky model not found: {args.sky_model}")
        report = run_folder(args.images, args.out, preset, recursive=args.recursive, names=args.names,
                            existing=existing, sam3_model=args.sam3_model, sky_model=args.sky_model, device=device)
    else:
        return 2
    print(f"{report['written']} mask(s) written to {args.out}, {report['skipped_existing']} left as they were, "
          f"{len(report['failed'])} failed, {report['seconds']} s")
    for f in report["failed"]:
        print(f"  failed: {f['image']}: {f['error']}")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
