"""Qt-free editing session: the open image folder, the current image and the edit state.

The GUI is a thin view over this class. Every user action (click a point,
delete a point, add detections, propagate, ...) is a method here that updates
the ``Project`` and the small amount of UI state the model does not own
(current image, which Object is in Edit, selected point, open Detections).
That keeps the interaction rules testable without a display or a GPU.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

import numpy as np

from src.core.project import (
    Box,
    Detection,
    EditLayer,
    FrameState,
    FrameStatus,
    Point,
    Project,
    Source,
    Variant,
)
from src.core.propagation import Direction, PropagationPlan, existing_targets, grade
from src.core.refine import fill_holes, grow_to_edges, remove_specks, within
from src.core.storage import ExportOptions, ProjectStore, export_final_masks
from src.engine.batch import LabelHit
from src.engine.imageio import find_images, read_rgb, to_working

DEFAULT_MAX_SIDE = 1024


class Engine(Protocol):
    """What the session needs from ``src.engine.inference.InferenceEngine``."""

    @property
    def sam2_ready(self) -> bool: ...

    @property
    def sam3_ready(self) -> bool: ...

    def set_image(self, image: np.ndarray) -> None: ...

    def predict(
        self, points: Sequence[Point], box: Optional[Box] = None, seed_mask: Optional[np.ndarray] = None
    ) -> Tuple[Variant, ...]: ...

    def detect(self, text: str) -> List[Detection]: ...

    def detect_many(self, image: np.ndarray, labels: Sequence[str]) -> List[Detection]: ...


class Mode(str, Enum):
    IDLE = "idle"  # clicks never create or change anything (except the very first Object)
    NEW_OBJECT = "new"  # the next click / box creates an Object
    EDIT = "edit"  # clicks add prompts to the Object being edited


def original_size(path: Path) -> Tuple[int, int]:
    """(height, width) of an image file, reading only its header when possible."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
        return h, w
    except Exception:
        h, w = read_rgb(path).shape[:2]
        return h, w


class Session:
    """One open image folder and everything being edited in it."""

    def __init__(self, engine: Optional[Engine] = None, max_side: int = DEFAULT_MAX_SIDE):
        self.engine = engine
        self.max_side = max_side
        self.image_dir: Optional[Path] = None
        self.paths: List[Path] = []
        self.store: Optional[ProjectStore] = None
        self.project = Project([])
        self.index = -1
        self.image: Optional[np.ndarray] = None  # working-resolution RGB of the current image
        self.mode = Mode.IDLE
        self.editing: Optional[int] = None  # id of the one Object in Edit
        self.selected_point: Optional[int] = None
        # Box region the whole-mask tool buttons are limited to (None: the whole mask).
        # UI state for the Object in Edit on this image: not saved, not undone.
        self.region: Optional[np.ndarray] = None
        # Region changes join Ctrl+Z / Ctrl+Y: each entry remembers the project's
        # history position, so region and project steps undo in the order they happened.
        self._region_undo: List[Tuple[int, Optional[np.ndarray]]] = []  # (depth, region before)
        self._region_redo: List[Tuple[int, int, Optional[np.ndarray]]] = []  # (depth, actions, region)
        self.detections: List[Detection] = []
        self.detection_checked: List[bool] = []
        # Detection results are kept per image (spec 01 §15: Image -> DetectionResults).
        self._detections_by_key: Dict[str, Tuple[List[Detection], List[bool]]] = {}
        self._sizes: Dict[str, Tuple[int, int]] = {}

    # ------------------------------------------------------------------
    # Folder / navigation
    # ------------------------------------------------------------------

    @property
    def keys(self) -> List[str]:
        return self.project.image_keys

    @property
    def key(self) -> Optional[str]:
        return self.keys[self.index] if 0 <= self.index < len(self.keys) else None

    def open_folder(self, image_dir: Path) -> int:
        """Open *image_dir* (loading its sidecar project, if any). Returns the image count."""
        paths = find_images(image_dir)
        if not paths:
            raise FileNotFoundError(f"No images found in {image_dir}")
        self.image_dir = image_dir
        self.paths = paths
        self.store = ProjectStore(image_dir, self.max_side)
        self.project = self.store.load([p.name for p in paths])
        self.max_side = self.store.max_side  # an existing project keeps its working resolution
        self._sizes.clear()
        self._detections_by_key.clear()
        self.clear_detections()
        self.index = -1
        self.go_to(0)
        return len(paths)

    def go_to(self, index: int) -> bool:
        """Make image *index* current. Leaves Edit/New mode; Detections stay with their image."""
        if not (0 <= index < len(self.paths)) or index == self.index:
            return False
        if self.key is not None:
            if self.detections:
                self._detections_by_key[self.key] = (self.detections, self.detection_checked)
            else:
                self._detections_by_key.pop(self.key, None)
        self.index = index
        self.image = to_working(read_rgb(self.paths[index]), self.max_side)
        if self.engine is not None:
            self.engine.set_image(self.image)
        self.cancel_mode()
        self.detections, self.detection_checked = self._detections_by_key.pop(self.key, ([], []))
        return True

    def step(self, delta: int) -> bool:
        return self.go_to(max(0, min(len(self.paths) - 1, self.index + delta)))

    def working_hw(self) -> Tuple[int, int]:
        assert self.image is not None
        return self.image.shape[0], self.image.shape[1]

    def original_size(self, key: str) -> Tuple[int, int]:
        if key not in self._sizes:
            assert self.image_dir is not None
            self._sizes[key] = original_size(self.image_dir / key)
        return self._sizes[key]

    # ------------------------------------------------------------------
    # Modes
    # ------------------------------------------------------------------

    def start_new_object(self) -> None:
        """Arm "+ New Object from Points": the next click or box creates an Object."""
        self.mode = Mode.NEW_OBJECT
        self.editing = None
        self.selected_point = None
        self._reset_region()

    def edit(self, obj_id: int) -> None:
        if self.project.get(obj_id) is None:
            return
        if obj_id != self.editing:
            self._reset_region()
        self.mode = Mode.EDIT
        self.editing = obj_id
        self.selected_point = None

    def cancel_mode(self) -> None:
        """Finish Editing / leave New Object mode."""
        self.mode = Mode.IDLE
        self.editing = None
        self.selected_point = None
        self._reset_region()

    finish_editing = cancel_mode

    @property
    def effective_mode(self) -> Mode:
        """The mode clicks act in.

        While the project has no Objects at all, a click or box in IDLE starts
        the first one (there is nothing it could be refining yet).
        """
        if self.mode == Mode.IDLE and self.key is not None and not self.project.objects:
            return Mode.NEW_OBJECT
        return self.mode

    def sync(self) -> None:
        """Drop edit state that no longer matches the project (after undo/redo/delete)."""
        if self.editing is not None and self.project.get(self.editing) is None:
            self.cancel_mode()
        fs = self.editing_frame()
        if self.selected_point is not None and (fs is None or self.selected_point >= len(fs.points)):
            self.selected_point = None

    def editing_frame(self) -> Optional[FrameState]:
        if self.editing is None or self.key is None:
            return None
        obj = self.project.get(self.editing)
        return obj.frame(self.key) if obj else None

    # ------------------------------------------------------------------
    # SAM2 prompts
    # ------------------------------------------------------------------

    def _require_sam2(self) -> Engine:
        if self.engine is None or not self.engine.sam2_ready:
            raise RuntimeError("SAM2 is not loaded yet.")
        return self.engine

    def _run(self, fs: FrameState) -> FrameState:
        """Recompute a frame's Variants from its full prompt set (seeded by its base mask)."""
        variants = self._require_sam2().predict(fs.points, fs.box, fs.base_mask) if fs.has_prompts else ()
        if not variants and fs.base_mask is not None:
            variants = (Variant(fs.base_mask, 1.0),)
        return dataclasses.replace(fs, variants=tuple(variants), selected=0, status=FrameStatus.MANUAL)

    def _create(self, fs: FrameState, source: Source) -> int:
        fs = self._run(fs)
        assert self.key is not None
        oid = self.project.add_object(self.key, fs, source)
        self.edit(oid)
        return oid

    def _update(self, change: Callable[[FrameState], FrameState]) -> None:
        assert self.editing is not None and self.key is not None
        fs = self.editing_frame() or FrameState()
        self.project.set_frame(self.editing, self.key, self._run(change(fs)))

    def click(self, x: float, y: float, positive: bool = True) -> Optional[int]:
        """A canvas click in working-resolution pixels. Returns the Object id it affected.

        In IDLE nothing happens once Objects exist: a plain click never silently
        creates an Object that could have been meant as a refinement.
        """
        mode = self.effective_mode
        if self.key is None or mode == Mode.IDLE:
            return None
        p = Point(float(x), float(y), positive)
        if mode == Mode.NEW_OBJECT:
            if not positive:
                return None  # an Object cannot start from a background point
            return self._create(FrameState(points=(p,)), Source.SAM2_POINT)
        self._update(lambda fs: dataclasses.replace(fs, points=fs.points + (p,)))
        self.selected_point = None
        return self.editing

    def drag_box(self, box: Box) -> Optional[int]:
        """A box dragged on the canvas: creates an Object (New) or sets the edited frame's box."""
        x0, y0, x1, y1 = box
        box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        mode = self.effective_mode
        if self.key is None or mode == Mode.IDLE:
            return None
        if mode == Mode.NEW_OBJECT:
            return self._create(FrameState(box=box), Source.SAM2_BOX)
        self._update(lambda fs: dataclasses.replace(fs, box=box))
        return self.editing

    def select_point(self, index: Optional[int]) -> None:
        fs = self.editing_frame()
        self.selected_point = index if fs is not None and index is not None and 0 <= index < len(fs.points) else None

    def delete_point(self, index: Optional[int] = None) -> bool:
        """Delete one point (default: the selected one) and re-run SAM2 on the rest."""
        index = self.selected_point if index is None else index
        fs = self.editing_frame()
        if fs is None or index is None or not (0 <= index < len(fs.points)):
            return False
        self._update(lambda f: dataclasses.replace(f, points=f.points[:index] + f.points[index + 1 :]))
        self.selected_point = None
        return True

    def clear_points(self) -> bool:
        """Remove every point and the box of the edited frame (its base mask stays)."""
        fs = self.editing_frame()
        if fs is None or not fs.has_prompts:
            return False
        self._update(lambda f: dataclasses.replace(f, points=(), box=None))
        self.selected_point = None
        return True

    def clear_box(self) -> bool:
        fs = self.editing_frame()
        if fs is None or fs.box is None:
            return False
        self._update(lambda f: dataclasses.replace(f, box=None))
        return True

    def select_variant(self, index: int, obj_id: Optional[int] = None) -> None:
        """Pick the Variant that becomes the Object's mask on this image (default: the edited Object)."""
        obj_id = self.editing if obj_id is None else obj_id
        if obj_id is not None and self.key is not None:
            self.project.select_variant(obj_id, self.key, index)

    # ------------------------------------------------------------------
    # Edit layer (brush, hole filling) — kept apart from the prompt-based mask
    # ------------------------------------------------------------------

    def _set_target(self, target: np.ndarray) -> bool:
        """Make the edited frame show *target* by storing its difference as the edit layer."""
        if self.editing is None or self.key is None:
            return False
        fs = self.editing_frame() or FrameState()
        layer = EditLayer.between(fs.prompt_mask, target)
        if layer is None and fs.edit is None:
            return False
        self.project.set_frame(self.editing, self.key, dataclasses.replace(fs, edit=layer, status=FrameStatus.MANUAL))
        return True

    def brush(self, mask: np.ndarray) -> bool:
        """A finished brush stroke: *mask* is what the edited frame should now show.

        The change goes into the edit layer; the points, box and Variants stay,
        so deleting the layer returns to the prompt-based mask.
        """
        return self._set_target(mask)

    def set_region(self, region: Optional[np.ndarray]) -> None:
        """Limit the whole-mask tools to *region* (a bool mask); None or empty = everywhere. Undoable."""
        region = region if region is not None and region.any() else None
        if region is None and self.region is None:
            return
        self._region_undo.append((self.project.undo_depth, self.region))
        self._region_redo.clear()
        self.region = region

    def _reset_region(self) -> None:
        """Leaving the edit target ends its region and the region's history."""
        self.region = None
        self._region_undo.clear()
        self._region_redo.clear()

    def add_region_box(self, box: Box, subtract: bool = False) -> None:
        """Add a dragged box to the tool region (or cut it out with *subtract*)."""
        if self.image is None:
            return
        h, w = self.working_hw()
        x0, y0, x1, y1 = (int(round(v)) for v in box)
        x0, x1 = sorted((max(0, x0), min(w - 1, x1)))
        y0, y1 = sorted((max(0, y0), min(h - 1, y1)))
        region = self.region.copy() if self.region is not None else np.zeros((h, w), bool)
        region[y0 : y1 + 1, x0 : x1 + 1] = not subtract
        self.set_region(region)

    def tool_result(
        self,
        tool: str,
        max_area: int = 200,
        max_grow: int = 20,
        sensitivity: int = 50,
        restore: str = "both",
    ) -> Optional[np.ndarray]:
        """The edited mask with *tool* applied everywhere (None when there is nothing to do).

        ``fill_holes`` | ``remove_specks`` | ``object_fill`` | ``restore``. Brush
        tools apply it only where a stroke passed; the buttons inside the region.
        ``restore`` undoes the edit layer: ``added`` drops the pixels it added,
        ``removed`` brings back the pixels it removed, ``both`` does both.
        """
        fs = self.editing_frame()
        if fs is None:
            return None
        if tool == "restore":
            if fs.edit is None:
                return None
            if restore == "added":
                return fs.mask & ~fs.edit.add
            if restore == "removed":
                return fs.mask | fs.edit.sub
            p = fs.prompt_mask
            return p if p is not None else np.zeros(fs.edit.add.shape, bool)
        if fs.mask is None:
            return None
        m = fs.mask
        if tool == "fill_holes":
            return fill_holes(m, max_area)
        if tool == "remove_specks":
            return remove_specks(m, max_area)
        if tool == "object_fill":
            return grow_to_edges(self.image, m, max_grow, sensitivity) if self.image is not None else None
        raise ValueError(f"Unknown tool: {tool}")

    def tool_stroke(self, tool: str, area: np.ndarray, **settings) -> bool:
        """A tool brush stroke: apply *tool* only inside the brushed *area*."""
        target = self.tool_result(tool, **settings)
        fs = self.editing_frame()
        if target is None or fs is None or not area.any():
            return False
        before = fs.mask if fs.mask is not None else np.zeros(area.shape, bool)
        return self._set_target(within(area, before, target))

    def _tool(self, tool: str, **settings) -> bool:
        """Apply a tool to the edited frame (inside the region, if any) as part of the edit layer."""
        target = self.tool_result(tool, **settings)
        fs = self.editing_frame()
        if target is None or fs is None:
            return False
        return self._set_target(within(self.region, fs.mask, target))

    def fill_holes(self, max_area: int) -> bool:
        """Fill enclosed holes up to *max_area* px."""
        return self._tool("fill_holes", max_area=max_area)

    def remove_specks(self, max_area: int) -> bool:
        """Remove separate pieces up to *max_area* px (the main piece stays)."""
        return self._tool("remove_specks", max_area=max_area)

    def object_fill(self, max_grow: int, sensitivity: int = 50) -> bool:
        """Grow the mask outward (at most *max_grow* px) to the object's edges in the image."""
        return self._tool("object_fill", max_grow=max_grow, sensitivity=sensitivity)

    def discard_edit(self) -> bool:
        """Delete the edit layer: back to the points/prompt-based mask."""
        fs = self.editing_frame()
        if fs is None or fs.edit is None:
            return False
        assert self.editing is not None and self.key is not None
        self.project.set_frame(self.editing, self.key, dataclasses.replace(fs, edit=None))
        return True

    def apply_edit(self) -> bool:
        """Bake the edit layer in: the edited mask becomes the frame's main mask.

        It becomes the base mask (SAM2's prior), the old prompts are cleared,
        and new points refine from the edited result.
        """
        fs = self.editing_frame()
        if fs is None or fs.edit is None or fs.mask is None:
            return False
        assert self.editing is not None and self.key is not None
        m = fs.mask
        self.project.set_frame(
            self.editing,
            self.key,
            FrameState(base_mask=m, variants=(Variant(m, 1.0),), status=FrameStatus.MANUAL),
        )
        self.selected_point = None
        return True

    def remove_frame(self, obj_id: int) -> None:
        """Remove an Object's mask on the current image only."""
        if self.key is not None:
            self.project.set_frame(obj_id, self.key, None)

    # ------------------------------------------------------------------
    # Object operations
    # ------------------------------------------------------------------

    def delete_objects(self, ids: Iterable[int]) -> None:
        self.project.remove_objects(ids)
        self.sync()

    def merge(self, ids: Sequence[int]) -> Optional[int]:
        new = self.project.merge(ids)
        self.sync()
        return new

    @property
    def can_undo(self) -> bool:
        return self.project.can_undo or self._region_step_undo()

    @property
    def can_redo(self) -> bool:
        return self.project.can_redo or self._region_step_redo()

    def _region_step_undo(self) -> bool:
        """The next undo is a region change (made after the project's current state)."""
        return bool(self._region_undo) and self._region_undo[-1][0] == self.project.undo_depth

    def _region_step_redo(self) -> bool:
        top = self._region_redo[-1] if self._region_redo else None
        return top is not None and top[0] == self.project.undo_depth and top[1] == self.project.actions

    def undo(self) -> bool:
        if self._region_step_undo():
            depth, before = self._region_undo.pop()
            self._region_redo.append((depth, self.project.actions, self.region))
            self.region = before
            return True
        ok = self.project.undo()
        self.sync()
        return ok

    def redo(self) -> bool:
        if self._region_step_redo():
            depth, _, after = self._region_redo.pop()
            self._region_undo.append((depth, self.region))
            self.region = after
            return True
        ok = self.project.redo()
        self.sync()
        return ok

    # ------------------------------------------------------------------
    # SAM3 detections
    # ------------------------------------------------------------------

    def set_detections(self, detections: List[Detection]) -> None:
        self.detections = list(detections)
        self.detection_checked = [True] * len(self.detections)

    def clear_detections(self) -> None:
        self.detections = []
        self.detection_checked = []

    def add_checked_detections(self) -> List[int]:
        """Turn the checked Detections into Objects and close the Detection list."""
        if self.key is None:
            return []
        chosen = [d for d, c in zip(self.detections, self.detection_checked, strict=True) if c]
        ids = self.project.add_detections(self.key, chosen)
        self.clear_detections()
        return ids

    def batch_indices(self, scope: str, start: int = 0, end: int = -1, selected: Sequence[int] = ()) -> List[int]:
        """Image indices for a batch run: ``current`` | ``all`` | ``range`` (start..end) | ``selected``."""
        n = len(self.keys)
        if scope == "current":
            return [self.index] if self.key is not None else []
        if scope == "all":
            return list(range(n))
        if scope == "range":
            end = n - 1 if end < 0 else end
            lo, hi = max(0, min(start, end)), min(n - 1, max(start, end))
            return list(range(lo, hi + 1))
        if scope == "selected":
            return sorted({i for i in selected if 0 <= i < n})
        raise ValueError(f"Unknown batch scope: {scope}")

    def apply_batch(self, results: Dict[int, Dict[str, "LabelHit"]]) -> Dict[str, int]:
        """Store batch detections as one Object per label (one undo step). Returns {label: object id}."""
        by_label: Dict[str, Dict[str, FrameState]] = {}
        for idx, hits in results.items():
            key = self.keys[idx]
            for label, hit in hits.items():
                by_label.setdefault(label, {})
                if hit.mask is not None:
                    by_label[label][key] = FrameState.from_mask(
                        hit.mask, score=hit.best_score, status=FrameStatus.PROPAGATED
                    )
        ids = self.project.add_label_objects(by_label, Source.SAM3_BATCH)
        created = [label for label, frames in by_label.items() if frames]
        self.sync()
        return dict(zip(created, ids, strict=True))

    # ------------------------------------------------------------------
    # Propagation
    # ------------------------------------------------------------------

    def plan(self, start: int, end: int, direction: Direction) -> PropagationPlan:
        return PropagationPlan(start=start, end=end, current=self.index, direction=direction)

    def seeds(self) -> Dict[int, np.ndarray]:
        """Checked Objects' selected masks on the current image (the reference)."""
        out = {}
        for o in self.project.objects:
            m = o.mask(self.key) if (o.included and self.key) else None
            if m is not None and m.any():
                out[o.id] = m
        return out

    def overwrite_targets(self, plan: PropagationPlan, obj_ids: Iterable[int]) -> List[str]:
        """Target images where one of *obj_ids* already has a mask (confirm before overwriting)."""
        frames = {oid: self.project.get(oid).frames for oid in obj_ids if self.project.get(oid)}
        return existing_targets(frames, self.keys, plan)

    def apply_propagation(
        self, results: Dict[int, Dict[int, np.ndarray]], reference: Dict[int, np.ndarray]
    ) -> Dict[int, FrameStatus]:
        """Store propagated masks (``{index: {obj_id: mask}}``) as one undo step.

        Returns each frame's worst status (FAILED > WARNING > PROPAGATED).
        """
        rank = {FrameStatus.PROPAGATED: 0, FrameStatus.WARNING: 1, FrameStatus.FAILED: 2}
        ref_area = {oid: int(m.sum()) for oid, m in reference.items()}
        updates: Dict[int, Dict[str, FrameState]] = {}
        per_frame: Dict[int, FrameStatus] = {}
        for idx, by_obj in results.items():
            key = self.keys[idx]
            worst = FrameStatus.PROPAGATED
            for oid, m in by_obj.items():
                st = grade(m, ref_area.get(oid, 0))
                updates.setdefault(oid, {})[key] = FrameState.from_mask(m, status=st)
                if rank[st] > rank[worst]:
                    worst = st
            per_frame[idx] = worst
        self.project.set_frames(updates)
        self.sync()
        return per_frame

    # ------------------------------------------------------------------
    # Save / export
    # ------------------------------------------------------------------

    def save(self, force: bool = False) -> bool:
        return self.store.save(self.project, force=force) if self.store is not None else False

    def export(self, options: ExportOptions, progress: Optional[Callable[[int, int], None]] = None) -> List[Path]:
        assert self.image_dir is not None
        return export_final_masks(self.project, self.image_dir, self.original_size, options, progress=progress)
