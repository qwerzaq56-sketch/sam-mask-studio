"""Qt-free data model: Objects, their per-image frames, Variants, and undo/redo.

Masks are ``bool`` arrays at the image's *working* resolution. They are treated
as immutable: an edit always builds a new array and a new ``FrameState``. That
lets an undo snapshot hold plain references instead of copies, so undoing a
propagation over hundreds of frames costs no extra memory.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

Box = Tuple[float, float, float, float]  # x0, y0, x1, y1 in working-resolution pixels

PALETTE: Tuple[Tuple[int, int, int], ...] = (
    (230, 25, 75),
    (60, 180, 75),
    (0, 130, 200),
    (245, 130, 48),
    (145, 30, 180),
    (70, 240, 240),
    (240, 50, 230),
    (210, 245, 60),
    (250, 190, 212),
    (0, 128, 128),
    (220, 190, 255),
    (170, 110, 40),
)


class Source(str, Enum):
    """How an Object was created."""

    SAM3_DETECTION = "SAM3_DETECTION"
    SAM3_BATCH = "SAM3_BATCH"  # one Object per label from a multi-image text prompt run
    SAM2_POINT = "SAM2_POINT"
    SAM2_BOX = "SAM2_BOX"
    MERGED = "MERGED"
    DUPLICATE = "DUPLICATE"


class FrameStatus(str, Enum):
    """Where a frame's mask came from / how trustworthy it is."""

    MANUAL = "manual"  # made or edited by the user on this image
    PROPAGATED = "propagated"
    WARNING = "warning"  # propagated, but looks suspicious
    FAILED = "failed"  # propagation produced an empty mask


def freeze(mask: np.ndarray) -> np.ndarray:
    """Return *mask* as a read-only ``bool`` array (copying only when needed)."""
    arr = mask if mask.dtype == np.bool_ else mask > (127 if mask.dtype == np.uint8 else 0)
    if arr.flags.writeable:
        arr = arr.copy() if arr is mask else arr
        arr.flags.writeable = False
    return arr


@dataclass(frozen=True)
class Point:
    """A SAM2 prompt point in working-resolution pixels."""

    x: float
    y: float
    positive: bool = True


@dataclass(frozen=True)
class Variant:
    """One mask candidate for an Object on one image."""

    mask: np.ndarray
    score: float = 1.0
    logits: Optional[np.ndarray] = None  # SAM2 low-res logits (1, 256, 256), if any

    @property
    def area(self) -> int:
        return int(self.mask.sum())


@dataclass(frozen=True)
class EditLayer:
    """Hand edits kept apart from the prompt-based mask (brush strokes, hole filling).

    Stored as a difference: ``add`` pixels are forced on, ``sub`` pixels forced
    off, on top of whatever the prompts produce. Deleting the layer therefore
    returns exactly to the prompt-based mask, and re-running SAM2 after a new
    point keeps the hand edits on top.
    """

    add: np.ndarray
    sub: np.ndarray

    @property
    def added(self) -> int:
        return int(self.add.sum())

    @property
    def removed(self) -> int:
        return int(self.sub.sum())

    @staticmethod
    def between(prompt: Optional[np.ndarray], target: np.ndarray) -> Optional["EditLayer"]:
        """The layer that turns *prompt* into *target* (None when they are equal)."""
        t = target.astype(bool)
        p = prompt if prompt is not None and prompt.shape == t.shape else np.zeros(t.shape, bool)
        add, sub = t & ~p, p & ~t
        if not add.any() and not sub.any():
            return None
        return EditLayer(freeze(add), freeze(sub))


@dataclass(frozen=True)
class FrameState:
    """An Object's prompts and mask candidates on one image.

    ``base_mask`` is a mask that did not come from this frame's prompts (a SAM3
    detection, a propagated, merged or applied-edit mask). SAM2 refinement uses
    it as the starting prior, and it is what the frame shows when there are no
    prompts. ``edit`` is an optional hand-edit layer applied on top.
    """

    points: Tuple[Point, ...] = ()
    box: Optional[Box] = None
    base_mask: Optional[np.ndarray] = None
    variants: Tuple[Variant, ...] = ()
    selected: int = 0
    status: FrameStatus = FrameStatus.MANUAL
    edit: Optional[EditLayer] = None

    @property
    def has_prompts(self) -> bool:
        return bool(self.points) or self.box is not None

    @property
    def prompt_mask(self) -> Optional[np.ndarray]:
        """The mask from prompts alone: the selected Variant, else the base mask."""
        if self.variants:
            return self.variants[min(self.selected, len(self.variants) - 1)].mask
        return self.base_mask

    @cached_property
    def mask(self) -> Optional[np.ndarray]:
        """The frame's current mask: the prompt mask with the edit layer applied.

        Cached, so repeated reads return the same (immutable) array — the
        autosaver relies on array identity to skip unchanged masks.
        """
        base = self.prompt_mask
        if self.edit is None:
            return base
        if base is None:
            return freeze(self.edit.add & ~self.edit.sub)
        return freeze((base | self.edit.add) & ~self.edit.sub)

    @staticmethod
    def from_mask(mask: np.ndarray, score: float = 1.0, status: FrameStatus = FrameStatus.MANUAL) -> "FrameState":
        m = freeze(mask)
        return FrameState(base_mask=m, variants=(Variant(m, score),), status=status)


@dataclass(frozen=True)
class MaskObject:
    """An independent segmentation target, with one FrameState per image key."""

    id: int
    name: str
    source: Source
    color: Tuple[int, int, int]
    included: bool = True  # part of the Final Mask
    frames: Dict[str, FrameState] = field(default_factory=dict)

    def frame(self, key: str) -> Optional[FrameState]:
        return self.frames.get(key)

    def mask(self, key: str) -> Optional[np.ndarray]:
        fs = self.frames.get(key)
        return fs.mask if fs is not None else None


@dataclass(frozen=True)
class Detection:
    """A SAM3 text-prompt candidate on one image (not yet an Object)."""

    label: str
    score: float
    mask: np.ndarray
    box: Box


def mask_box(mask: np.ndarray) -> Box:
    """Tight bounding box ``(x0, y0, x1, y1)`` of a mask (zeros if empty)."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))


def union(masks: Iterable[Optional[np.ndarray]]) -> Optional[np.ndarray]:
    """Pixel-wise OR of the non-None masks (None if there are none)."""
    out: Optional[np.ndarray] = None
    for m in masks:
        if m is None:
            continue
        out = m.copy() if out is None else (out | m if out.shape == m.shape else out)
    return freeze(out) if out is not None else None


class Project:
    """All Objects of an image sequence plus a snapshot-based undo/redo history.

    Every mutating method records one undo step. ``revision`` increases on each
    change so views and the autosaver can tell when they are stale.
    """

    MAX_HISTORY = 100

    def __init__(self, image_keys: Sequence[str]):
        self.image_keys: List[str] = list(image_keys)
        self.objects: List[MaskObject] = []
        self.next_id: int = 1
        self.label_counts: Dict[str, int] = {}
        self.revision: int = 0
        self._undo: List[tuple] = []
        self._redo: List[tuple] = []

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _state(self) -> tuple:
        # MaskObject is frozen and its frames dict is never mutated in place,
        # so a shallow tuple is a complete snapshot.
        return (tuple(self.objects), self.next_id, dict(self.label_counts))

    def _restore(self, state: tuple) -> None:
        objects, self.next_id, labels = state
        self.objects = list(objects)
        self.label_counts = dict(labels)
        self.revision += 1

    def _checkpoint(self) -> None:
        self._undo.append(self._state())
        if len(self._undo) > self.MAX_HISTORY:
            self._undo.pop(0)
        self._redo.clear()
        self.revision += 1

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._state())
        self._restore(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._state())
        self._restore(self._redo.pop())
        return True

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, obj_id: int) -> Optional[MaskObject]:
        for o in self.objects:
            if o.id == obj_id:
                return o
        return None

    def _index(self, obj_id: int) -> int:
        for i, o in enumerate(self.objects):
            if o.id == obj_id:
                return i
        raise KeyError(obj_id)

    def _replace(self, obj: MaskObject) -> None:
        self.objects[self._index(obj.id)] = obj

    def final_mask(self, key: str) -> Optional[np.ndarray]:
        """Union of the included Objects' masks on image *key*."""
        return union(o.mask(key) for o in self.objects if o.included)

    def keys_with_masks(self, included_only: bool = True) -> List[str]:
        """Image keys (in sequence order) where at least one Object has a mask."""
        present = set()
        for o in self.objects:
            if included_only and not o.included:
                continue
            present.update(k for k, fs in o.frames.items() if fs.mask is not None)
        return [k for k in self.image_keys if k in present]

    # ------------------------------------------------------------------
    # Object lifecycle
    # ------------------------------------------------------------------

    def _new_name(self, label: str) -> str:
        n = self.label_counts.get(label, 0) + 1
        self.label_counts[label] = n
        return f"{label} #{n}"

    def _alloc(self, name: str, source: Source, frames: Dict[str, FrameState]) -> MaskObject:
        oid = self.next_id
        self.next_id += 1
        return MaskObject(id=oid, name=name, source=source, color=PALETTE[(oid - 1) % len(PALETTE)], frames=frames)

    def add_object(self, key: str, frame: FrameState, source: Source, label: str = "Object") -> int:
        """Create an Object with one frame on image *key*; returns its id."""
        self._checkpoint()
        obj = self._alloc(self._new_name(label), source, {key: frame})
        self.objects.append(obj)
        return obj.id

    def add_detections(self, key: str, detections: Sequence[Detection]) -> List[int]:
        """Turn SAM3 detections into Objects (one undo step for all)."""
        if not detections:
            return []
        self._checkpoint()
        ids = []
        for d in detections:
            fs = FrameState.from_mask(d.mask, d.score)
            obj = self._alloc(self._new_name(d.label), Source.SAM3_DETECTION, {key: fs})
            self.objects.append(obj)
            ids.append(obj.id)
        return ids

    def add_label_objects(self, frames_by_label: Dict[str, Dict[str, FrameState]], source: Source) -> List[int]:
        """Create one Object per label with frames on many images (one undo step for all)."""
        filled = {label: frames for label, frames in frames_by_label.items() if frames}
        if not filled:
            return []
        self._checkpoint()
        ids = []
        for label, frames in filled.items():
            ordered = {k: frames[k] for k in self.image_keys if k in frames}
            obj = self._alloc(self._new_name(label), source, ordered)
            self.objects.append(obj)
            ids.append(obj.id)
        return ids

    def remove_objects(self, obj_ids: Iterable[int]) -> None:
        ids = set(obj_ids)
        if not ids:
            return
        self._checkpoint()
        self.objects = [o for o in self.objects if o.id not in ids]

    def rename(self, obj_id: int, name: str) -> None:
        obj = self.get(obj_id)
        name = name.strip()
        if obj is None or not name or name == obj.name:
            return
        self._checkpoint()
        self._replace(dataclasses.replace(obj, name=name))

    def set_included(self, obj_id: int, included: bool) -> None:
        obj = self.get(obj_id)
        if obj is None or obj.included == included:
            return
        self._checkpoint()
        self._replace(dataclasses.replace(obj, included=included))

    def duplicate(self, obj_ids: Iterable[int]) -> List[int]:
        """Copy Objects (frames, prompts, variants); the copies are independent."""
        src = [o for o in self.objects if o.id in set(obj_ids)]
        if not src:
            return []
        self._checkpoint()
        new_ids = []
        for o in src:
            copy = self._alloc(f"{o.name} (copy)", Source.DUPLICATE, dict(o.frames))
            copy = dataclasses.replace(copy, included=o.included)
            self.objects.insert(self._index(o.id) + 1, copy)
            new_ids.append(copy.id)
        return new_ids

    def merge(self, obj_ids: Sequence[int], name: Optional[str] = None) -> Optional[int]:
        """Union two or more Objects frame by frame into one new Object.

        On every image where any of them has a mask, the merged Object gets the
        union of the masks that exist there. The originals are removed. It is
        named after the first id in *obj_ids* (the first one the user picked).
        """
        chosen = [o for o in self.objects if o.id in set(obj_ids)]
        if len(chosen) < 2:
            return None
        self._checkpoint()
        keys = [k for k in self.image_keys if any(k in o.frames for o in chosen)]
        frames: Dict[str, FrameState] = {}
        for k in keys:
            m = union(o.mask(k) for o in chosen)
            if m is None:
                continue
            manual = any(k in o.frames and o.frames[k].status == FrameStatus.MANUAL for o in chosen)
            frames[k] = FrameState.from_mask(m, status=FrameStatus.MANUAL if manual else FrameStatus.PROPAGATED)
        first = next(o for o in (self.get(i) for i in obj_ids) if o is not None)
        merged = self._alloc(name or first.name, Source.MERGED, frames)
        merged = dataclasses.replace(merged, included=any(o.included for o in chosen))
        at = min(self._index(o.id) for o in chosen)
        self.objects = [o for o in self.objects if o not in chosen]
        self.objects.insert(at, merged)
        return merged.id

    # ------------------------------------------------------------------
    # Frame edits
    # ------------------------------------------------------------------

    def set_frame(self, obj_id: int, key: str, frame: Optional[FrameState]) -> None:
        """Replace (or with ``None`` remove) an Object's frame on image *key*."""
        obj = self.get(obj_id)
        if obj is None:
            return
        self._checkpoint()
        frames = dict(obj.frames)
        if frame is None:
            frames.pop(key, None)
        else:
            frames[key] = frame
        self._replace(dataclasses.replace(obj, frames=frames))

    def set_frames(self, updates: Dict[int, Dict[str, FrameState]]) -> None:
        """Apply many frame updates across Objects as one undo step (propagation)."""
        if not updates:
            return
        self._checkpoint()
        for obj_id, per_key in updates.items():
            obj = self.get(obj_id)
            if obj is None:
                continue
            frames = dict(obj.frames)
            frames.update(per_key)
            self._replace(dataclasses.replace(obj, frames=frames))

    def select_variant(self, obj_id: int, key: str, index: int) -> None:
        obj = self.get(obj_id)
        fs = obj.frame(key) if obj else None
        if fs is None or not (0 <= index < len(fs.variants)) or fs.selected == index:
            return
        self.set_frame(obj_id, key, dataclasses.replace(fs, selected=index, status=FrameStatus.MANUAL))
