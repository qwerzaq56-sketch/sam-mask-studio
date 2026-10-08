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

from src.core.special import Special

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
    IMPORTED = "IMPORTED"  # read from a mask folder (a COLMAP scene's masks/)
    SPECIAL = "SPECIAL"  # made from settings (sky, lens edge: src/core/special.py)


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
class PromptLayer:
    """Points / a box of their own on top of an Object's mask (docs/specs/10-prompt-layers.md):
    SAM2's piece from these prompts alone (no seed), added to the mask or (*subtract*) taken out."""

    points: Tuple[Point, ...] = ()
    box: Optional[Box] = None
    subtract: bool = False
    mask: Optional[np.ndarray] = None

    @property
    def has_prompts(self) -> bool:
        return bool(self.points) or self.box is not None


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
    layers: Tuple[PromptLayer, ...] = ()  # point layers over the prompt mask (Original)

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
    def layered_mask(self) -> Optional[np.ndarray]:
        """The prompt mask (Original) with the point layers: every added piece, then every subtracted one."""
        base = self.prompt_mask
        pieces = [ly for ly in self.layers if ly.mask is not None]
        if not pieces:
            return base
        out = base.copy() if base is not None else np.zeros(pieces[0].mask.shape, bool)
        for ly in pieces:
            if not ly.subtract and ly.mask.shape == out.shape:
                out |= ly.mask
        for ly in pieces:
            if ly.subtract and ly.mask.shape == out.shape:
                out &= ~ly.mask
        return freeze(out)

    @cached_property
    def mask(self) -> Optional[np.ndarray]:
        """The frame's current mask: the layered mask with the edit layer applied.

        Cached, so repeated reads return the same (immutable) array — the
        autosaver relies on array identity to skip unchanged masks.
        """
        base = self.layered_mask
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
    locked: bool = False  # 🔒: never deleted (Delete, Merge skip / refuse it)
    special: Optional[Special] = None  # masks made from settings; None once applied (an ordinary Object)

    def frame(self, key: str) -> Optional[FrameState]:
        return self.frames.get(key)

    def mask(self, key: str) -> Optional[np.ndarray]:
        fs = self.frames.get(key)
        return fs.mask if fs is not None else None


@dataclass(frozen=True)
class MaskBar:
    """One mask the Export window writes (one folder): its Objects and its colours (plan Export 9).

    ``ids`` None = the checked Objects (the Final Mask). ``invert`` True = Objects black; None = not set yet,
    the trainer preset decides. ``flipped``: Objects taken the other way round before the union (what is
    outside them; an image where one has no mask is all outside). ``on``: written by the next Export."""

    name: str = ""
    ids: Optional[Tuple[int, ...]] = None
    invert: Optional[bool] = None
    flipped: Tuple[int, ...] = ()
    on: bool = True


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
        # named mask sets for export (docs/specs/06-colmap.md 4): name -> Object ids; the Final Mask is the unnamed one
        self.mask_sets: Dict[str, Tuple[int, ...]] = {}
        # the Export window's masks (plan Export 9); empty = not set up yet (bars_or_default)
        self.mask_bars: Tuple[MaskBar, ...] = ()
        # images left out of a dataset export (docs/specs/07 6); the source scene is never changed
        self.excluded: frozenset = frozenset()
        self.revision: int = 0
        self._undo: List[tuple] = []
        self._redo: List[tuple] = []
        self._dropped = 0  # undo steps dropped off the front (MAX_HISTORY)
        self.actions = 0  # new changes made (undo/redo do not count)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def _state(self) -> tuple:
        # MaskObject is frozen and its frames dict is never mutated in place,
        # so a shallow tuple is a complete snapshot.
        return (tuple(self.objects), self.next_id, dict(self.label_counts), dict(self.mask_sets), self.excluded,
                self.mask_bars)

    def _restore(self, state: tuple) -> None:
        objects, self.next_id, labels, sets, self.excluded, self.mask_bars = state
        self.objects = list(objects)
        self.label_counts = dict(labels)
        self.mask_sets = dict(sets)
        self.revision += 1

    def _checkpoint(self) -> None:
        self._undo.append(self._state())
        if len(self._undo) > self.MAX_HISTORY:
            self._undo.pop(0)
            self._dropped += 1
        self._redo.clear()
        self.revision += 1
        self.actions += 1

    @property
    def undo_depth(self) -> int:
        """Position in the history: +1 per change or redo, -1 per undo (never reused by trimming)."""
        return self._dropped + len(self._undo)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def forget_history(self) -> None:
        """Start the history here: what is loaded now is what Ctrl+Z goes back to (a scene's masks, found
        as it opens). The depth keeps counting, so a save made earlier never looks current again."""
        self._dropped += len(self._undo)
        self._undo.clear()
        self._redo.clear()

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

    def final_mask(self, key: str, ids: Optional[Iterable[int]] = None,
                   flipped: Iterable[int] = ()) -> Optional[np.ndarray]:
        """Union of the included Objects' masks on image *key* (*ids*: those Objects instead, a mask set).

        *flipped*: those of them count the other way round (what is outside them); one with no mask on *key*
        covers the whole image (its size from another mask there, else 1 x 1: only "has pixels" is known)."""
        use, flip = self.members(ids), set(flipped)
        m = union(o.mask(key) for o in self.objects if use(o) and o.id not in flip)
        for o in self.objects:
            if not (use(o) and o.id in flip):
                continue
            om = o.mask(key)
            if om is None:
                shape = m.shape if m is not None else next(
                    (x.shape for x in (p.mask(key) for p in self.objects) if x is not None), (1, 1))
                return freeze(np.ones(shape, bool))
            m = ~om if m is None else (m | ~om if m.shape == om.shape else m)
        return freeze(m) if m is not None else None

    def members(self, ids: Optional[Iterable[int]]):
        if ids is None:
            return lambda o: o.included
        wanted = set(ids)
        return lambda o: o.id in wanted

    def keys_with_masks(self, included_only: bool = True, ids: Optional[Iterable[int]] = None,
                        flipped: Iterable[int] = ()) -> List[str]:
        """Image keys (in sequence order) where at least one Object has a mask (*ids*: of those Objects).
        A *flipped* one among them gives every image a mask (where it has none, all of the image is outside it)."""
        present = set()
        use = self.members(ids) if included_only or ids is not None else (lambda o: True)
        flip = set(flipped)
        if flip and any(use(o) and o.id in flip for o in self.objects):
            return list(self.image_keys)
        for o in self.objects:
            if not use(o):
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

    def remove_objects(self, obj_ids: Iterable[int]) -> List[int]:
        """Remove the Objects (locked ones stay); returns the ids removed."""
        obj_ids = list(obj_ids)
        ids = {o.id for o in self.objects if o.id in set(obj_ids) and not o.locked}
        if not ids:
            return []
        self._checkpoint()
        self.objects = [o for o in self.objects if o.id not in ids]
        return [i for i in obj_ids if i in ids]

    def set_locked(self, obj_ids: Iterable[int], locked: bool) -> List[int]:
        """Lock / unlock Objects (one undo step); returns the ids that changed."""
        change = [o for o in self.objects if o.id in set(obj_ids) and o.locked != locked]
        if not change:
            return []
        self._checkpoint()
        for o in change:
            self._replace(dataclasses.replace(o, locked=locked))
        return [o.id for o in change]

    def set_mask_set(self, name: str, ids: Optional[Iterable[int]]) -> bool:
        """Save (*ids*) or delete (None) the mask set *name* — one undo step."""
        name = name.strip()
        new = tuple(sorted(set(ids))) if ids is not None else None
        if not name or self.mask_sets.get(name) == new:
            return False
        self._checkpoint()
        if new is None:
            self.mask_sets.pop(name, None)
        else:
            self.mask_sets[name] = new
        return True

    def bars_or_default(self) -> Tuple[MaskBar, ...]:
        """The Export window's masks; not set up yet: the Final Mask, then the old named sets (off)."""
        if self.mask_bars:
            return self.mask_bars
        return (MaskBar(),) + tuple(MaskBar(name, ids, on=False) for name, ids in sorted(self.mask_sets.items()))

    def set_mask_bars(self, bars: Iterable[MaskBar]) -> bool:
        """The Export window's masks, as one undo step (False: nothing changed)."""
        new = tuple(bars)
        if new == self.bars_or_default():
            return False
        self._checkpoint()
        self.mask_bars = new
        return True

    def set_excluded(self, keys: Iterable[str], excluded: bool) -> List[str]:
        """Leave images out of (or take them back into) a new dataset — one undo step; returns the keys changed."""
        keys = [k for k in keys if (k in self.excluded) != excluded]
        if not keys:
            return []
        self._checkpoint()
        self.excluded = self.excluded - set(keys) if not excluded else self.excluded | set(keys)
        return keys

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

    def duplicate(self, obj_ids: Iterable[int], key: Optional[str] = None) -> List[int]:
        """Copy Objects (frames, prompts, variants); the copies are independent.

        With *key* only that image's frame is copied, and Objects without a
        mask there are skipped; without it every linked frame is copied.
        """
        src = [o for o in self.objects if o.id in set(obj_ids)]
        if key is not None:
            src = [o for o in src if o.mask(key) is not None]
        if not src:
            return []
        self._checkpoint()
        new_ids = []
        for o in src:
            frames = {key: o.frames[key]} if key is not None else dict(o.frames)
            copy = self._alloc(f"{o.name} (copy)", Source.DUPLICATE, frames)
            copy = dataclasses.replace(copy, included=o.included)
            self.objects.insert(self._index(o.id) + 1, copy)
            new_ids.append(copy.id)
        return new_ids

    @staticmethod
    def _added(frames: Sequence[FrameState]) -> Optional[FrameState]:
        """One frame holding the union of *frames*' masks (★ if any of them was edited by hand)."""
        m = union(fs.mask for fs in frames)
        if m is None:
            return None
        manual = any(fs.status == FrameStatus.MANUAL for fs in frames)
        return FrameState.from_mask(m, status=FrameStatus.MANUAL if manual else FrameStatus.PROPAGATED)

    def copy_into(self, src_id: int, dst_id: int, replace: bool, keys: Optional[Iterable[str]] = None,
                  move: bool = False) -> List[str]:
        """Copy (*move*: move) Object *src*'s masks into Object *dst*; returns the image keys changed.

        Only images where *src* has a mask are touched (*keys* narrows them,
        e.g. to the current image). ``replace``: *dst*'s frame becomes a copy
        of *src*'s (prompts included); else the two masks are added (union).
        *dst*'s other images keep their masks. *move* also takes those frames
        off *src*; *src* stays, empty if nothing is left (docs/specs/05).
        """
        src, dst = self.get(src_id), self.get(dst_id)
        if src is None or dst is None or src is dst:
            return []
        wanted = set(keys) if keys is not None else None
        changed = [
            k for k in self.image_keys
            if src.mask(k) is not None and (wanted is None or k in wanted)
        ]
        if not changed:
            return []
        self._checkpoint()
        frames = dict(dst.frames)
        for k in changed:
            old = frames.get(k)
            if replace or old is None or old.mask is None:
                frames[k] = src.frames[k]
            else:
                frames[k] = self._added([old, src.frames[k]])
        self._replace(dataclasses.replace(dst, frames=frames))
        if move:
            self._replace(dataclasses.replace(src, frames={k: f for k, f in src.frames.items() if k not in changed}))
        return changed

    MERGE_ADD = "add"  # every image: the union of the masks there
    MERGE_OVERRIDE = "override"  # every image: the mask of the first id in the order that has one

    def merge_blocked(self, obj_ids: Sequence[int]) -> List[MaskObject]:
        """The locked Objects a merge would remove."""
        return [o for o in (self.get(i) for i in dict.fromkeys(obj_ids)) if o is not None and o.locked]

    def merge(self, obj_ids: Sequence[int], name: Optional[str] = None, how: str = MERGE_ADD) -> Optional[int]:
        """Fuse two or more Objects frame by frame into one new Object.

        ``add``: on every image where any of them has a mask, the merged Object
        gets the union of the masks there. ``override``: it gets the frame of
        the first Object in *obj_ids* that has one there (kept as it is, with
        its prompts), so the earlier Objects win where they overlap. The
        originals are removed. It is named after the first id in *obj_ids*
        (the first one the user picked, or the winner of an override).
        Nothing happens when one of them is locked. (Keeping the others as
        empty Objects is Move, not Merge: docs/specs/05.)
        """
        chosen = [o for o in self.objects if o.id in set(obj_ids)]
        if len(chosen) < 2 or self.merge_blocked(obj_ids):
            return None
        order = [o for o in (self.get(i) for i in dict.fromkeys(obj_ids)) if o is not None]
        self._checkpoint()
        keys = [k for k in self.image_keys if any(k in o.frames for o in chosen)]
        frames: Dict[str, FrameState] = {}
        for k in keys:
            if how == self.MERGE_OVERRIDE:
                fs = next((o.frames[k] for o in order if o.mask(k) is not None), None)
            else:
                fs = self._added([o.frames[k] for o in chosen if o.mask(k) is not None])
            if fs is not None:
                frames[k] = fs
        first = order[0]
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

    def clear_frames(self, obj_ids: Iterable[int], keys: Iterable[str]) -> int:
        """Empty the Objects' masks on images *keys*, as one undo step; returns how many masks went."""
        wanted, ids = set(keys), set(obj_ids)
        hits = [o for o in self.objects if o.id in ids and wanted & set(o.frames)]
        if not hits:
            return 0
        self._checkpoint()
        gone = 0
        for o in hits:
            gone += len(wanted & set(o.frames))
            self._replace(dataclasses.replace(o, frames={k: f for k, f in o.frames.items() if k not in wanted}))
        return gone

    def add_special(self, special: Special, label: str) -> int:
        """A special Object (no masks yet); returns its id."""
        self._checkpoint()
        obj = dataclasses.replace(self._alloc(self._new_name(label), Source.SPECIAL, {}), special=special)
        self.objects.append(obj)
        return obj.id

    def set_special(self, obj_id: int, special: Optional[Special],
                    frames: Optional[Dict[str, Optional[FrameState]]] = None) -> bool:
        """A special Object's settings and the masks they make, as one undo step (*frames*: key -> frame,
        None removes it). *special* None: Apply, an ordinary Object from now on."""
        obj = self.get(obj_id)
        if obj is None:
            return False
        self._checkpoint()
        new = dict(obj.frames)
        for k, fs in (frames or {}).items():
            if fs is None:
                new.pop(k, None)
            else:
                new[k] = fs
        ordered = {k: new[k] for k in self.image_keys if k in new}
        self._replace(dataclasses.replace(obj, special=special, frames=ordered))
        return True

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
