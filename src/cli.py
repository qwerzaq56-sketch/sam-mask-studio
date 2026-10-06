"""SAM Mask Studio without the window: ``python -m src.cli <command> ...`` (for batch pipelines).

``sky``: a sky mask for every image of a folder, at the image's full resolution — the Sky special
Object's model and settings (src/core/special.py), its edge decided again on the full-size image
(src/core/sky_edges.py), as the Export window does with "Sky edges at full resolution".

    python -m src.cli sky H:/scene/images --out H:/scene/sky_masks --recursive

``lens``: a fisheye's image circle for every image — the Lens edge special Object's circle, found in
each camera folder's frames (cam0/ and cam1/ may differ), pulled in by a margin over the lens rim's glow.

    python -m src.cli lens H:/scene/images --out H:/scene/masks --recursive [--and-with H:/scene/person_masks]

Common to both:

- One PNG per image, named ``<image name>.png`` (``00011.jpg.png``; ``--names stem``: ``00011.png``),
  sub-folders kept (``cam0/``, ``cam1/``).
- Files already in ``--out`` are never replaced unless asked: ``--skip-existing`` (carry on after a
  stop) or ``--overwrite``.
- No GPU (sky: about 2-3 s per 3840² image on the CPU; lens: about 0.1 s).
- Exit code 0 when every image got a mask, 1 when some failed (listed), 2 for a wrong call.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.version import app_version

ROOT = Path(__file__).resolve().parents[1]
SKY_MODEL = ROOT / "checkpoints" / "sky" / "skyseg.onnx"
LENS_MARGIN = 2.0  # % of the radius: the lens rim's glow, about 40 px on a 3840² OSMO 360 fisheye
LENS_SAMPLES = 16  # frames per camera folder the circle is found in


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
               existing: str = "stop", log=print) -> dict:
    """The ``sky`` command; returns its report (also what ``--report`` writes)."""
    from src.core.sky_edges import sky_edges
    from src.core.special import SKY, SkyModel, Special, sky_maps, sky_mask
    from src.engine.imageio import read_rgb, resize_mask, to_working

    b = Batch("sky", images, out, recursive, names, existing, log=log, settings={
        "threshold": threshold, "grow": grow, "top_only": top_only, "refine": refine,
        "full_resolution_edges": edges, "max_side": max_side, "invert": invert, "model": str(model_path)})
    sp = Special.new(SKY).with_params(threshold=threshold, grow=grow, top_only=float(top_only),
                                      refine=float(refine))
    model = SkyModel(model_path)

    def make(key):
        rgb = read_rgb(images / key)
        prob, refined = sky_maps(model, to_working(rgb, max_side))
        m = sky_mask(refined if refine else prob, sp)
        full = sky_edges(m, rgb) if edges else resize_mask(m, rgb.shape[:2])
        return (~full if invert else full), {"sky": round(float(full.mean()), 4)}

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
            other = _read_mask(and_with / b.name(key)) if (and_with / b.name(key)).exists() else None
            if other is None:
                missing.append(key)
            else:
                if other.shape != keep.shape:
                    other = cv2.resize(other.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
                keep = keep & other
        return (~keep if invert else keep), {"kept": round(float(keep.mean()), 4), "circle_px": circle_px}

    report = b.run(make, lambda note: f"kept {100 * note['kept']:.1f}%")
    if and_with is not None:
        report["and_with_missing"] = missing
        if missing:
            log(f"{len(missing)} image(s) had no mask in {and_with}: the lens edge alone was written for them")
    return report


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description=f"SAM Mask Studio {app_version()}, "
                                     "no window (for batch pipelines)")
    sub = parser.add_subparsers(dest="command", required=True)
    sky = sub.add_parser("sky", help="Sky masks for a folder, at full resolution",
                         description="A sky mask per image (white = sky), its edge decided on the full-size image.")
    _common(sky, "Black = sky, white = the rest")
    sky.add_argument("--threshold", type=float, default=50.0, help="Sky above this %% of the model's map (50)")
    sky.add_argument("--grow", type=int, default=0, help="Grow (+) / shrink (-) the sky by px at 1024 px (0)")
    sky.add_argument("--top-only", action="store_true", help="Only sky touching the image's top edge")
    sky.add_argument("--no-refine", action="store_true", help="The model's map without its edge refinement")
    sky.add_argument("--no-edges", action="store_true",
                     help="Scale the working mask up (nearest) instead of deciding the edge at full resolution")
    sky.add_argument("--max-side", type=int, default=1024, help="Working resolution's longer side (1024)")
    sky.add_argument("--model", type=Path, default=SKY_MODEL, help=f"skyseg.onnx (default {SKY_MODEL})")

    lens = sub.add_parser("lens", help="Fisheye lens edge masks for a folder",
                          description="White = inside the image circle (trained on), black = outside it and its "
                                      "rim. The circle is found per camera folder.")
    _common(lens, "White = outside the circle (the edge to ignore), black = inside")
    lens.add_argument("--margin", type=float, default=LENS_MARGIN,
                      help=f"Pull the circle in by this %% of its radius, over the rim's glow ({LENS_MARGIN})")
    lens.add_argument("--samples", type=int, default=LENS_SAMPLES,
                      help=f"Frames per camera folder the circle is found in ({LENS_SAMPLES})")
    lens.add_argument("--radius", type=float, help="Set the circle instead of finding it: radius in %% of the "
                                                    "inscribed circle (100 = touches the shorter sides)")
    lens.add_argument("--cx", type=float, default=0.0, help="With --radius: center right of the middle, %% (0)")
    lens.add_argument("--cy", type=float, default=0.0, help="With --radius: center below the middle, %% (0)")
    lens.add_argument("--and-with", type=Path, help="Mask folder (white = keep, same names) to multiply in, "
                                                    "e.g. people masks: one masks/ folder comes out")
    args = parser.parse_args(argv)

    if not args.images.is_dir():
        parser.error(f"not a folder: {args.images}")
    existing = "skip" if args.skip_existing else "overwrite" if args.overwrite else "stop"
    if args.command == "sky":
        if not args.model.is_file():
            parser.error(f"sky model not found: {args.model} (download skyseg.onnx from "
                         "https://huggingface.co/JianyuanWang/skyseg into checkpoints/sky/)")
        report = sky_folder(
            args.images, args.out, recursive=args.recursive, names=args.names, invert=args.invert,
            threshold=args.threshold, grow=args.grow, top_only=args.top_only, refine=not args.no_refine,
            edges=not args.no_edges, max_side=args.max_side, model_path=args.model, existing=existing,
        )
    elif args.command == "lens":
        if args.and_with is not None and not args.and_with.is_dir():
            parser.error(f"not a folder: {args.and_with}")
        if args.and_with is not None and args.and_with.resolve() == args.out.resolve():
            parser.error("--and-with and --out must be different folders")
        circle = None if args.radius is None else {"radius": args.radius, "cx": args.cx, "cy": args.cy}
        report = lens_folder(
            args.images, args.out, recursive=args.recursive, names=args.names, invert=args.invert,
            margin=args.margin, circle=circle, samples=args.samples, and_with=args.and_with, existing=existing,
        )
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
