"""SAM2 video propagation over a range of an image sequence."""

from __future__ import annotations

import contextlib
import gc
import tempfile
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import cv2
import numpy as np
import torch

from src.core.propagation import PropagationPlan
from src.engine.imageio import read_rgb, resize_mask, to_working
from src.logging_config import get_logger

logger = get_logger(__name__)

ProgressFn = Callable[[str, int, int], None]  # (phase, done, total)


def propagate(
    sam2_ckpt: str,
    image_paths: List[Path],
    plan: PropagationPlan,
    seeds: Dict[int, np.ndarray],
    max_side: int,
    device: str = "cuda",
    cancel: Optional[Callable[[], bool]] = None,
    progress: Optional[ProgressFn] = None,
) -> Iterator[Tuple[int, Dict[int, np.ndarray]]]:
    """Propagate each seed mask (obj_id -> bool mask on ``plan.current``) through the plan.

    Yields ``(sequence_index, {obj_id: bool mask at that image's working size})``
    for every target frame, backward pass first, then forward. The current
    frame is never yielded.

    SAM2's video loader only reads a folder of numbered JPEGs, so the frames in
    the plan's window are written there at working resolution. Copies are used
    instead of symlinks, which need admin/Developer Mode on Windows.
    """
    from sam2.build_sam import build_sam2_video_predictor

    from src.sam2.config import cfg_for_ckpt

    if not seeds:
        raise ValueError("No objects to propagate.")
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    lo, hi = plan.window
    total = len(plan.targets)
    cancelled = lambda: bool(cancel and cancel())  # noqa: E731

    with tempfile.TemporaryDirectory(prefix="sms_video_") as tmp:
        sizes: Dict[int, Tuple[int, int]] = {}
        for n, idx in enumerate(range(lo, hi + 1)):
            if cancelled():
                return
            img = to_working(read_rgb(image_paths[idx]), max_side)
            sizes[idx] = img.shape[:2]
            ok, buf = cv2.imencode(".jpg", cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise IOError(f"JPEG encode failed: {image_paths[idx]}")
            buf.tofile(str(Path(tmp) / f"{n:05d}.jpg"))
            if progress:
                progress("Preparing frames", n + 1, hi - lo + 1)

        if progress:
            progress("Loading SAM2 video model", 0, 0)
        predictor = build_sam2_video_predictor(cfg_for_ckpt(sam2_ckpt), sam2_ckpt, device=device)
        state = None
        try:
            state = predictor.init_state(video_path=tmp, offload_video_to_cpu=True)
            rel_cur = plan.current - lo
            for oid, m in seeds.items():
                predictor.add_new_mask(state, frame_idx=rel_cur, obj_id=int(oid), mask=torch.from_numpy(np.asarray(m, dtype=bool)))

            done = 0
            for phase, targets, reverse in (("Backward", plan.backward, True), ("Forward", plan.forward, False)):
                if not targets or cancelled():
                    continue
                if progress:
                    progress(phase, done, total)
                stream = predictor.propagate_in_video(
                    state, start_frame_idx=rel_cur, max_frame_num_to_track=len(targets), reverse=reverse
                )
                for rel_idx, obj_ids, video_masks in stream:
                    if cancelled():
                        return
                    idx = lo + rel_idx
                    if idx == plan.current:
                        continue
                    out = {}
                    for j, oid in enumerate(obj_ids):
                        m = (video_masks[j, 0] > 0.0).cpu().numpy()
                        out[int(oid)] = resize_mask(m, sizes[idx])
                    done += 1
                    if progress:
                        progress(phase, done, total)
                    yield idx, out
        finally:
            del predictor
            with contextlib.suppress(Exception):
                del state
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
