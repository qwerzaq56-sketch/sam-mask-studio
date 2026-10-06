"""SAM Mask Studio without the window: ``python -m src.cli <command> ...`` (for batch pipelines).

``sky``: a sky mask for every image of a folder, at the image's full resolution — the Sky special
Object's model and settings (src/core/special.py), its edge decided again on the full-size image
(src/core/sky_edges.py), as the Export window does with "Sky edges at full resolution".

    python -m src.cli sky H:/scene/images --out H:/scene/sky_masks --recursive

- White = sky (``--invert``: black = sky). One PNG per image, named ``<image name>.png``
  (``00011.jpg.png``; ``--names stem``: ``00011.png``), sub-folders kept (``cam0/``, ``cam1/``).
- Files already in ``--out`` are never replaced unless asked: ``--skip-existing`` (carry on after a
  stop) or ``--overwrite``.
- No GPU: the sky model runs on the CPU. About 2-3 s per 3840² image.
- Exit code 0 when every image got a mask, 1 when some failed (listed), 2 for a wrong call.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

import cv2
import numpy as np

from src.version import app_version

ROOT = Path(__file__).resolve().parents[1]
SKY_MODEL = ROOT / "checkpoints" / "sky" / "skyseg.onnx"


def _write_png(path: Path, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", mask.astype(np.uint8) * 255)
    if not ok:
        raise IOError(f"PNG encode failed for {path}")
    buf.tofile(str(path))  # non-ASCII Windows paths


def sky_folder(images: Path, out: Path, recursive: bool = False, names: str = "name", invert: bool = False,
               threshold: float = 50.0, grow: int = 0, top_only: bool = False, refine: bool = True,
               edges: bool = True, max_side: int = 1024, model_path: Path = SKY_MODEL,
               existing: str = "stop", log=print) -> dict:
    """The ``sky`` command; returns its report (also what ``--report`` writes)."""
    from src.core.sky_edges import sky_edges
    from src.core.special import SKY, SkyModel, Special, sky_maps, sky_mask
    from src.engine.imageio import find_images, image_key, key_stem, read_rgb, resize_mask, to_working

    paths = find_images(images, recursive=recursive)
    if not paths:
        raise SystemExit(f"No images in {images}" + ("" if recursive else " (sub-folders: --recursive)"))
    keys = [image_key(images, p) for p in paths]

    def target(key: str) -> Path:
        return out / (f"{key}.png" if names == "name" else f"{key_stem(key)}.png")

    there = [k for k in keys if target(k).exists()]
    if there and existing == "stop":
        raise SystemExit(f"{len(there)} of {len(keys)} mask(s) already in {out} (e.g. {target(there[0]).name}). "
                         "Nothing written. --skip-existing to carry on, --overwrite to replace them.")
    todo = [k for k in keys if not (existing == "skip" and k in there)]
    sp = Special.new(SKY).with_params(threshold=threshold, grow=grow, top_only=float(top_only),
                                      refine=float(refine))
    model = SkyModel(model_path)
    report = {
        "command": "sky", "version": app_version(), "images": str(images), "out": str(out),
        "settings": {"threshold": threshold, "grow": grow, "top_only": top_only, "refine": refine,
                     "full_resolution_edges": edges, "max_side": max_side, "invert": invert, "names": names,
                     "model": str(model_path)},
        "total": len(keys), "skipped_existing": len(keys) - len(todo), "written": 0, "failed": [], "frames": {},
    }
    t0 = time.time()
    for n, key in enumerate(todo, 1):
        t = time.time()
        try:
            rgb = read_rgb(images / key)
            prob, refined = sky_maps(model, to_working(rgb, max_side))
            m = sky_mask(refined if refine else prob, sp)
            full = sky_edges(m, rgb) if edges else resize_mask(m, rgb.shape[:2])
            _write_png(target(key), ~full if invert else full)
        except Exception as e:  # one bad image must not end the batch
            report["failed"].append({"image": key, "error": f"{type(e).__name__}: {e}"})
            log(f"[{n}/{len(todo)}] {key}  FAILED: {e}")
            continue
        report["written"] += 1
        report["frames"][key] = {"sky": round(float(full.mean()), 4), "seconds": round(time.time() - t, 2)}
        log(f"[{n}/{len(todo)}] {key}  sky {100 * full.mean():.1f}%  {time.time() - t:.1f}s")
    report["seconds"] = round(time.time() - t0, 1)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description=f"SAM Mask Studio {app_version()}, "
                                     "no window (for batch pipelines)")
    sub = parser.add_subparsers(dest="command", required=True)
    sky = sub.add_parser("sky", help="Sky masks for a folder, at full resolution",
                         description="A sky mask per image (white = sky), its edge decided on the full-size image.")
    sky.add_argument("images", type=Path, help="Image folder")
    sky.add_argument("--out", type=Path, required=True, help="Mask folder (made if missing)")
    sky.add_argument("--recursive", action="store_true", help="Also the sub-folders (cam0/, cam1/), kept in --out")
    sky.add_argument("--names", choices=("name", "stem"), default="name",
                     help="name: 00011.jpg.png (COLMAP, default); stem: 00011.png")
    sky.add_argument("--invert", action="store_true", help="Black = sky, white = the rest")
    sky.add_argument("--threshold", type=float, default=50.0, help="Sky above this %% of the model's map (50)")
    sky.add_argument("--grow", type=int, default=0, help="Grow (+) / shrink (-) the sky by px at 1024 px (0)")
    sky.add_argument("--top-only", action="store_true", help="Only sky touching the image's top edge")
    sky.add_argument("--no-refine", action="store_true", help="The model's map without its edge refinement")
    sky.add_argument("--no-edges", action="store_true",
                     help="Scale the working mask up (nearest) instead of deciding the edge at full resolution")
    sky.add_argument("--max-side", type=int, default=1024, help="Working resolution's longer side (1024)")
    sky.add_argument("--model", type=Path, default=SKY_MODEL, help=f"skyseg.onnx (default {SKY_MODEL})")
    how = sky.add_mutually_exclusive_group()
    how.add_argument("--skip-existing", action="store_true", help="Leave masks already in --out, make the rest")
    how.add_argument("--overwrite", action="store_true", help="Replace masks already in --out")
    sky.add_argument("--report", type=Path, help="Write the run's report (JSON) here")
    args = parser.parse_args(argv)

    if args.command == "sky":
        if not args.images.is_dir():
            parser.error(f"not a folder: {args.images}")
        if not args.model.is_file():
            parser.error(f"sky model not found: {args.model} (download skyseg.onnx from "
                         "https://huggingface.co/JianyuanWang/skyseg into checkpoints/sky/)")
        report = sky_folder(
            args.images, args.out, recursive=args.recursive, names=args.names, invert=args.invert,
            threshold=args.threshold, grow=args.grow, top_only=args.top_only, refine=not args.no_refine,
            edges=not args.no_edges, max_side=args.max_side, model_path=args.model,
            existing="skip" if args.skip_existing else "overwrite" if args.overwrite else "stop",
        )
        print(f"{report['written']} mask(s) written to {args.out}, {report['skipped_existing']} left as they were, "
              f"{len(report['failed'])} failed, {report['seconds']} s")
        for f in report["failed"]:
            print(f"  failed: {f['image']}: {f['error']}")
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        return 1 if report["failed"] else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
