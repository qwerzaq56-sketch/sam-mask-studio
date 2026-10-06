"""People and what they carry, from SAM3 text detections: one mask per image of what training ignores.

Measured on 0022 (OSMO 360 dual fisheye on a selfie stick, cam0 94 frames, against the scene's
hand-checked masks): "person" alone misses the stick and the bag (IoU 0.66); "selfie stick" is found
in 18 of 94 frames, "black pole" in 93 (0.91); the crossbody bag is not part of "person" (+ "bag": 0.95).
A bag counts only when it touches the person or the pole, so a bag left on a bench stays scene.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import cv2
import numpy as np

LABELS = ("person", "black pole")  # what is always masked
ATTACH = ("bag",)  # masked where it touches what LABELS found
THRESHOLD = 0.4
TOUCH = 16  # px at the working resolution
GROW = 2  # px at the working resolution: a person mask too big costs little, too small leaves a ghost


def _disc(r: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def touching(base: np.ndarray, add: np.ndarray, px: int = TOUCH) -> np.ndarray:
    """The pieces of *add* within *px* of *base*."""
    if not add.any() or not base.any():
        return np.zeros_like(add)
    near = cv2.dilate(base.astype(np.uint8), _disc(px)) > 0
    n, labels = cv2.connectedComponents(add.astype(np.uint8), connectivity=8)
    keep = np.unique(labels[near & add])
    return np.isin(labels, keep[keep > 0])


def people_mask(detections: Iterable, shape, labels: Sequence[str] = LABELS, attach: Sequence[str] = ATTACH,
                threshold: float = THRESHOLD, touch: int = TOUCH, grow: int = GROW) -> np.ndarray:
    """True where training should ignore: every detection of *labels* scoring at least *threshold*, the
    *attach* ones touching them, grown by *grow* px. *detections*: objects with ``label``, ``score`` and
    ``mask`` (bool, *shape*), as :meth:`InferenceEngine.detect_many` returns them."""
    main = np.zeros(shape, bool)
    extra = np.zeros(shape, bool)
    for d in detections:
        if d.score < threshold or d.mask.shape != tuple(shape):
            continue
        if d.label in labels:
            main |= d.mask
        elif d.label in attach:
            extra |= d.mask
    out = main | touching(main, extra, touch)
    if grow > 0 and out.any():
        out = cv2.dilate(out.astype(np.uint8), _disc(grow)) > 0
    return out
