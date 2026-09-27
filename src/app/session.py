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

from src.core.project import Box, Detection, FrameState, FrameStatus, Point, Project, Source, Variant, freeze
from src.core.propagation import Direction, PropagationPlan, existing_targets, grade
from src.core.storage import ExportOptions, ProjectStore, export_final_masks
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


class Mode(str, Enum):
    IDLE = "idle"  # clicks never create or change anything
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

    def edit(self, obj_id: int) -> None:
        if self.project.get(obj_id) is None:
            return
        self.mode = Mode.EDIT
        self.editing = obj_id
        self.selected_point = None

    def cancel_mode(self) -> None:
        """Finish Editing / leave New Object mode."""
        self.mode = Mode.IDLE
        self.editing = None
        self.selected_point = None

    finish_editing = cancel_mode

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

        In IDLE nothing happens: a plain click never silently creates an Object.
        """
        if self.key is None or self.mode == Mode.IDLE:
            return None
        p = Point(float(x), float(y), positive)
        if self.mode == Mode.NEW_OBJECT:
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
        if self.key is None or self.mode == Mode.IDLE:
            return None
        if self.mode == Mode.NEW_OBJECT:
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

    def brush(self, mask: np.ndarray) -> bool:
        """Replace the edited frame's mask with a brushed one.

        The brushed mask becomes the frame's base mask (the prior for later SAM2
        clicks), and the prompts are cleared so the mask shown is exactly what
        was painted.
        """
        if self.editing is None or self.key is None:
            return False
        fs = self.editing_frame() or FrameState()
        m = freeze(mask)
        self.project.set_frame(
            self.editing,
            self.key,
            dataclasses.replace(
                fs, points=(), box=None, base_mask=m, variants=(Variant(m, 1.0),), selected=0, status=FrameStatus.MANUAL
            ),
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

    def undo(self) -> bool:
        ok = self.project.undo()
        self.sync()
        return ok

    def redo(self) -> bool:
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
