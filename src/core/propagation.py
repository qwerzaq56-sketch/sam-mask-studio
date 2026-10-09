"""Pure propagation planning and result grading (no model code)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from src.core.project import FrameStatus, Origin


class Direction(str, Enum):
    BOTH = "both"
    FORWARD = "forward"
    BACKWARD = "backward"


@dataclass(frozen=True)
class PropagationPlan:
    """Sequence indices to fill, walking outward from ``current`` (the reference frame).

    ``start``/``end`` bound the range; ``current`` is never re-processed. With
    ``frames`` only those images are used (e.g. picked in the Images list):
    they are treated as one sequence, skipping the images in between.
    """

    start: int
    end: int
    current: int
    direction: Direction
    frames: Optional[Tuple[int, ...]] = None

    def __post_init__(self):
        if not (self.start <= self.current <= self.end):
            raise ValueError(f"Current image ({self.current}) must lie within Start..End ({self.start}..{self.end}).")

    @staticmethod
    def of_frames(frames: Sequence[int], reference: int, direction: Direction) -> "PropagationPlan":
        """A plan over just *frames* (plus the reference), in sequence order."""
        fs = tuple(sorted(set(frames) | {reference}))
        return PropagationPlan(fs[0], fs[-1], reference, direction, fs)

    @property
    def sequence(self) -> List[int]:
        """The frames the model loads, in order (the reference included)."""
        lo, hi = self.window
        base = self.frames if self.frames is not None else range(self.start, self.end + 1)
        return [i for i in sorted(set(base) | {self.current}) if lo <= i <= hi]

    @property
    def forward(self) -> List[int]:
        if self.direction == Direction.BACKWARD:
            return []
        return [i for i in self.sequence if i > self.current]

    @property
    def backward(self) -> List[int]:
        if self.direction == Direction.FORWARD:
            return []
        return [i for i in self.sequence if i < self.current][::-1]

    @property
    def targets(self) -> List[int]:
        return self.backward[::-1] + self.forward

    @property
    def window(self) -> Tuple[int, int]:
        """The index range whose frames the model actually needs to load."""
        lo = self.current if self.direction == Direction.FORWARD else self.start
        hi = self.current if self.direction == Direction.BACKWARD else self.end
        return lo, hi


def origins(plan: PropagationPlan, run: int, keys: Sequence[str]) -> Dict[int, Origin]:
    """Each target frame's origin in *run*: the plan's reference, its direction, how many frames out (p152)."""
    ref = keys[plan.current]
    out = {i: Origin(run, ref, True, n) for n, i in enumerate(plan.forward, 1)}
    out.update({i: Origin(run, ref, False, n) for n, i in enumerate(plan.backward, 1)})
    return out


@dataclass(frozen=True)
class RunSummary:
    """One propagation run as the given Objects still hold it: its reference, and how many of their frames
    (and how far out) it filled backward / forward."""

    run: int
    ref: str
    backward: int
    forward: int
    far_backward: int
    far_forward: int

    def describe(self) -> str:
        parts = [f"◀ {self.backward}" if self.backward else "", f"▶ {self.forward}" if self.forward else ""]
        return f"Run {self.run} — from {self.ref.rsplit('.', 1)[0]}: " + " · ".join(p for p in parts if p)


def run_summaries(objects: Iterable, ids: Iterable[int]) -> List[RunSummary]:
    """The runs the Objects *ids* still hold frames of, newest first (a run per reference it started from)."""
    wanted = set(ids)
    tally: Dict[Tuple[int, str], List[int]] = {}
    for o in objects:
        if o.id not in wanted:
            continue
        for fs in o.frames.values():
            og = fs.origin
            if og is None or fs.mask is None:
                continue
            t = tally.setdefault((og.run, og.ref), [0, 0, 0, 0])
            t[1 if og.forward else 0] += 1
            t[3 if og.forward else 2] = max(t[3 if og.forward else 2], og.step)
    return [RunSummary(run, ref, *t) for (run, ref), t in sorted(tally.items(), key=lambda kv: -kv[0][0])]


def run_frames(objects: Iterable, ids: Iterable[int], run: int, ref: str, direction: Direction,
               keep: int = 0) -> Dict[int, List[str]]:
    """{Object id: image keys} of *run* from *ref* in *direction*, more than *keep* frames from the reference:
    what clearing that run (from there on) removes. Frames edited since (★) have no origin, so they stay."""
    wanted = set(ids)
    out: Dict[int, List[str]] = {}
    for o in objects:
        if o.id not in wanted:
            continue
        for k, fs in o.frames.items():
            og = fs.origin
            if og is None or og.run != run or og.ref != ref or og.step <= keep:
                continue
            if direction == Direction.BOTH or og.forward == (direction == Direction.FORWARD):
                out.setdefault(o.id, []).append(k)
    return out


def is_anchor(fs) -> bool:
    """A frame propagation stops at (p159): a mask made or fixed here (★), or one imported as it was (↓; a batch
    report's propagated or warned frames come in as ✓ / ⚠, p150, and are carried over like any propagated one)."""
    return fs is not None and fs.mask is not None and fs.status in (FrameStatus.MANUAL, FrameStatus.IMPORTED)


def anchor_span(frames: dict, keys: Sequence[str], ref: int) -> Tuple[int, int]:
    """Start..End from *ref* out to just before the nearest anchor (:func:`is_anchor`) either way, inside
    *ref*'s camera folder (``cam0/`` of a rig): the frames a fix on *ref* should carry to (Correction Anchor)."""
    folder = keys[ref].rpartition("/")[0]

    def stop(i: int) -> bool:
        return keys[i].rpartition("/")[0] != folder or is_anchor(frames.get(keys[i]))

    lo = ref
    while lo > 0 and not stop(lo - 1):
        lo -= 1
    hi = ref
    while hi < len(keys) - 1 and not stop(hi + 1):
        hi += 1
    return lo, hi


def next_run(objects: Iterable) -> int:
    """The number for a new propagation run: one more than any run still on a frame."""
    return 1 + max((fs.origin.run for o in objects for fs in o.frames.values() if fs.origin is not None),
                   default=0)


# A propagated mask whose area drifts this far from the reference is flagged.
WARN_AREA_RATIO = 4.0
# SAM2's object score (0..1) under this on a frame with a mask: it is unsure the object is there (p153).
# At 0.5 or below SAM2 empties the mask itself (✕). Measured on 0022 / 0015 (p156, 2,385 propagated frames, SAM2
# tiny): a good run sits at 0.999+, the few frames under 0.8 are mostly lost or partial; under 0.6 adds nothing to the
# area rule and over 0.8 only adds false alarms.
LOW_SCORE = 0.8


def grade(mask: np.ndarray, reference_area: int, score: Optional[float] = None) -> FrameStatus:
    """Classify a propagated mask: FAILED if empty, WARNING if its area jumped or SAM2's object score is low."""
    area = int(mask.sum())
    if area == 0:
        return FrameStatus.FAILED
    if score is not None and score < LOW_SCORE:
        return FrameStatus.WARNING
    if reference_area > 0:
        ratio = area / reference_area
        if ratio > WARN_AREA_RATIO or ratio < 1.0 / WARN_AREA_RATIO:
            return FrameStatus.WARNING
    return FrameStatus.PROPAGATED


def existing_targets(frames_by_obj: dict, keys: List[str], plan: PropagationPlan) -> List[str]:
    """Image keys inside the plan's targets where any given Object already has a mask."""
    hit = []
    for i in plan.targets:
        k = keys[i]
        if any(frames.get(k) is not None and frames[k].mask is not None for frames in frames_by_obj.values()):
            hit.append(k)
    return hit


def reference_mask(frames: dict, key: str) -> Optional[np.ndarray]:
    fs = frames.get(key)
    return fs.mask if fs is not None else None


def parse_id_range(text: str, count: int) -> Tuple[int, int]:
    """``"5 ~ 45"`` (1-based image IDs; ``~`` or ``-``) -> 0-based ``(start, end)``.

    A single ID means just that image. Raises ValueError with a readable message.
    """
    parts = [t for t in text.replace("~", "-").replace(" ", "").split("-") if t]
    if len(parts) not in (1, 2) or not all(t.isdigit() for t in parts):
        raise ValueError(f"Type the range as image IDs, e.g. 5 ~ 45 (1 ~ {count})")
    a, b = int(parts[0]), int(parts[-1])
    a, b = min(a, b), max(a, b)
    if a < 1 or b > count:
        raise ValueError(f"Image IDs go from 1 to {count}")
    return a - 1, b - 1


def format_ids(indices) -> str:
    """0-based indices -> compact 1-based IDs: ``[2, 3, 4, 11] -> "3–5, 12"``."""
    ids = sorted({i + 1 for i in indices})
    out, run = [], []
    for i in ids:
        if run and i == run[-1] + 1:
            run.append(i)
            continue
        if run:
            out.append(f"{run[0]}–{run[-1]}" if len(run) > 1 else str(run[0]))
        run = [i]
    if run:
        out.append(f"{run[0]}–{run[-1]}" if len(run) > 1 else str(run[0]))
    return ", ".join(out)


def parse_id_list(text: str, count: int) -> List[int]:
    """``"1-4, 35, 23"`` (1-based IDs and ID ranges, any order) -> sorted 0-based indices.

    Raises ValueError with a readable message.
    """
    out = set()
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        a, b = parse_id_range(part, count)
        out.update(range(a, b + 1))
    if not out:
        raise ValueError(f"Type image IDs, e.g. 1-4, 35, 23 (1 ~ {count})")
    return sorted(out)


def parse_id(text: str, count: int) -> int:
    """One 1-based image ID -> 0-based index."""
    t = text.strip()
    if not t.isdigit() or not 1 <= int(t) <= count:
        raise ValueError(f"Image IDs go from 1 to {count}")
    return int(t) - 1
