"""SAM3 text-prompt masking over many images (one merged mask per label per image)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from src.core.project import freeze
from src.engine.imageio import read_rgb, to_working


@dataclass(frozen=True)
class LabelHit:
    """All detections of one label on one image that passed the threshold, merged."""

    mask: Optional[np.ndarray]  # union of the kept detections, None when there were none
    count: int
    best_score: float


def batch_detect(
    engine,
    image_paths: Sequence[Path],
    indices: Sequence[int],
    labels: Sequence[str],
    max_side: int,
    threshold: float,
    cancel: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[str, int, int], None]] = None,
) -> Iterator[Tuple[int, Dict[str, LabelHit]]]:
    """Yield ``(index, {label: LabelHit})`` for each image in *indices*.

    Uses ``engine.detect_many`` so the image being edited in the UI is not
    disturbed. Detections scoring below *threshold* are ignored. *cancel* is
    checked before every label, so a stop takes effect within one prompt; an
    image interrupted half-way is not yielded.
    """
    total = len(indices)
    for n, idx in enumerate(indices):
        if cancel and cancel():
            return
        image = to_working(read_rgb(image_paths[idx]), max_side)
        dets = []
        for label in labels:
            if cancel and cancel():
                return
            dets.extend(engine.detect_many(image, [label]))
        hits: Dict[str, LabelHit] = {}
        for label in labels:
            kept = [d for d in dets if d.label == label and d.score >= threshold]
            if kept:
                m = kept[0].mask.copy()
                for d in kept[1:]:
                    if d.mask.shape == m.shape:
                        m |= d.mask
                hits[label] = LabelHit(freeze(m), len(kept), max(d.score for d in kept))
            else:
                hits[label] = LabelHit(None, 0, 0.0)
        if progress:
            progress("Detecting", n + 1, total)
        yield idx, hits


def summarize(hits: Dict[str, LabelHit]) -> str:
    """``"person 2 · car 0"``."""
    return " · ".join(f"{label} {h.count}" for label, h in hits.items())


__all__: List[str] = ["LabelHit", "batch_detect", "summarize"]
