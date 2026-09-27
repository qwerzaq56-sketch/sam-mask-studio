"""Pure propagation planning and result grading (no model code)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

import numpy as np

from src.core.project import FrameStatus


class Direction(str, Enum):
    BOTH = "both"
    FORWARD = "forward"
    BACKWARD = "backward"


@dataclass(frozen=True)
class PropagationPlan:
    """Sequence indices to fill, walking outward from ``current``.

    ``start``/``end`` only bound the range; ``current`` is the reference frame
    and is never re-processed.
    """

    start: int
    end: int
    current: int
    direction: Direction

    def __post_init__(self):
        if not (self.start <= self.current <= self.end):
            raise ValueError(f"Current image ({self.current}) must lie within Start..End ({self.start}..{self.end}).")

    @property
    def forward(self) -> List[int]:
        if self.direction == Direction.BACKWARD:
            return []
        return list(range(self.current + 1, self.end + 1))

    @property
    def backward(self) -> List[int]:
        if self.direction == Direction.FORWARD:
            return []
        return list(range(self.current - 1, self.start - 1, -1))

    @property
    def targets(self) -> List[int]:
        return self.backward[::-1] + self.forward

    @property
    def window(self) -> Tuple[int, int]:
        """The index range whose frames the model actually needs to load."""
        lo = self.current if self.direction == Direction.FORWARD else self.start
        hi = self.current if self.direction == Direction.BACKWARD else self.end
        return lo, hi


# A propagated mask whose area drifts this far from the reference is flagged.
WARN_AREA_RATIO = 4.0


def grade(mask: np.ndarray, reference_area: int) -> FrameStatus:
    """Classify a propagated mask: FAILED if empty, WARNING if its area jumped."""
    area = int(mask.sum())
    if area == 0:
        return FrameStatus.FAILED
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
