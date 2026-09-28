"""Model-free stand-ins for the SAM2/SAM3 engine, used by session and GUI tests."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.core.project import Box, Detection, Point, Variant, freeze, mask_box


def disc(hw: Tuple[int, int], x: float, y: float, r: int) -> np.ndarray:
    m = np.zeros(hw, np.uint8)
    cv2.circle(m, (int(x), int(y)), r, 1, -1)
    return m > 0


class FakeEngine:
    """Deterministic "SAM": positive points grow discs, negative points cut them, a box fills."""

    RADII = (10, 20, 5)

    def __init__(self, sam2: bool = True, sam3: bool = True):
        self.sam2_ready = sam2
        self.sam3_ready = sam3
        self.image: Optional[np.ndarray] = None
        self.calls: List[tuple] = []

    def set_image(self, image: np.ndarray) -> None:
        self.image = image

    def predict(self, points: Sequence[Point], box: Optional[Box] = None, seed_mask=None) -> Tuple[Variant, ...]:
        assert self.image is not None
        self.calls.append((tuple(points), box, seed_mask is not None))
        hw = self.image.shape[:2]
        out = []
        for i, r in enumerate(self.RADII):
            m = np.zeros(hw, bool) if seed_mask is None else seed_mask.copy()
            if box is not None:
                x0, y0, x1, y1 = (int(v) for v in box)
                m[y0 : y1 + 1, x0 : x1 + 1] = True
            for p in points:
                if p.positive:
                    m |= disc(hw, p.x, p.y, r)
            for p in points:
                if not p.positive:
                    m &= ~disc(hw, p.x, p.y, r)
            out.append(Variant(freeze(m), 0.9 - 0.1 * i))
        return tuple(out)

    def detect(self, text: str) -> List[Detection]:
        assert self.image is not None
        return self.detect_many(self.image, [text])

    def detect_many(self, image: np.ndarray, labels: Sequence[str]) -> List[Detection]:
        """Two candidates per label (scores 0.95 and 0.6), placed in a column per label.

        A label containing "none" finds nothing, to exercise empty results.
        """
        h, w = image.shape[:2]
        dets = []
        for j, text in enumerate(labels):
            if "none" in text:
                continue
            for i, score in enumerate((0.95, 0.6)):
                m = np.zeros((h, w), bool)
                m[5 + 20 * i : 15 + 20 * i, 5 + 25 * j : 25 + 25 * j] = True
                dets.append(Detection(text, score, freeze(m), mask_box(m)))
        return dets


def fake_propagate(
    sam2_ckpt, image_paths, plan, seeds, max_side, device="cuda", cancel=None, progress=None
) -> Iterator:
    """Stand-in for ``src.engine.video.propagate``: copies each seed to every target frame."""
    total = len(plan.targets)
    done = 0
    for phase, targets in (("Backward", plan.backward), ("Forward", plan.forward)):
        for idx in targets:
            if cancel and cancel():
                return
            done += 1
            if progress:
                progress(phase, done, total)
            yield idx, dict(seeds)


def make_images(folder: Path, n: int = 5, hw: Tuple[int, int] = (60, 80)) -> List[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        img = np.full((*hw, 3), 40 * i % 255, np.uint8)
        p = folder / f"frame_{i:03d}.png"
        cv2.imwrite(str(p), img)
        paths.append(p)
    return paths


__all__ = ["FakeEngine", "fake_propagate", "make_images", "disc"]
