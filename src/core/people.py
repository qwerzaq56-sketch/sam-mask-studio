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
PERSON = "person"  # the label whose finds are told apart: the photographer or someone else (split_people)
HANDS = ("hand",)  # with split_people: a hand on the pole or reaching the lens rim is the photographer's
RIM = 0.9  # of the inscribed circle's radius: a hand past it lies on the lens (the other lens's photographer)
LOW = 0.85  # of the height: with no pole found, a person reaching below it is the one holding the camera


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
    return grow_mask(main | touching(main, extra, touch), grow)


def grow_mask(mask: np.ndarray, px: int = GROW) -> np.ndarray:
    """*mask* grown by *px* (a disc)."""
    if px <= 0 or not mask.any():
        return mask
    return cv2.dilate(mask.astype(np.uint8), _disc(px)) > 0


def split_people(detections: Iterable, shape, labels: Sequence[str] = LABELS, attach: Sequence[str] = ATTACH,
                 threshold: float = THRESHOLD, touch: int = TOUCH, hands: Sequence[str] = HANDS,
                 rim: float = RIM, low: float = LOW):
    """(the photographer, everyone else), neither grown: :func:`people_mask` told apart by who holds the camera.

    The photographer: every *labels* find but :data:`PERSON` (the pole), each person touching it (within
    *touch* px) or, when no pole is found, each person reaching below *low* of the height; the *hands* finds
    touching those or reaching past *rim* of the inscribed circle (fingers on the lens, mostly the other
    lens's view) unless mostly inside someone else; the *attach* ones (a bag) touching them. Everyone else:
    the other people, the bags they carry, and a hand no person covers."""
    h, w = shape
    pole = np.zeros(shape, bool)
    extra = np.zeros(shape, bool)
    people, hand_finds = [], []
    for d in detections:
        if d.score < threshold or d.mask.shape != tuple(shape) or not d.mask.any():
            continue
        if d.label == PERSON:
            people.append(d.mask)
        elif d.label in labels:
            pole |= d.mask
        elif d.label in hands:
            hand_finds.append(d.mask)
        elif d.label in attach:
            extra |= d.mask
    if pole.any():
        near = cv2.dilate(pole.astype(np.uint8), _disc(touch)) > 0
        mine = [bool((m & near).any()) for m in people]
    else:
        mine = [bool(m[int(h * low):].any()) for m in people]
    me = pole.copy()
    others = np.zeros(shape, bool)
    for m, is_mine in zip(people, mine):
        if is_mine:
            me |= m
        else:
            others |= m
    yy, xx = np.ogrid[:h, :w]
    edge = np.hypot(yy - (h - 1) / 2, xx - (w - 1) / 2) > rim * min(h, w) / 2
    near_me = cv2.dilate(me.astype(np.uint8), _disc(touch)) > 0 if me.any() else me
    for m in hand_finds:
        if (m & others).sum() >= 0.5 * m.sum():
            continue  # someone else's own hand, already theirs
        if (m & (near_me | edge)).any():
            me |= m
        else:
            others |= m  # a hand no person covers
    me |= touching(me, extra, touch)
    others |= touching(others, extra & ~me, touch)
    return me, others & ~me
