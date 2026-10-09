"""Qt-free editing session: the open image folder, the current image and the edit state.

The GUI is a thin view over this class. Every user action (click a point,
delete a point, add detections, propagate, ...) is a method here that updates
the ``Project`` and the small amount of UI state the model does not own
(current image, which Object is in Edit, selected point, open Detections).
That keeps the interaction rules testable without a display or a GPU.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Protocol, Sequence, Set, Tuple

import numpy as np

from src.core.project import (
    Box,
    Detection,
    EditLayer,
    FrameState,
    FrameStatus,
    MaskObject,
    Point,
    Project,
    PromptLayer,
    Source,
    Variant,
    freeze,
    union,
)
from src.core.propagation import (Direction, PropagationPlan, RunSummary, existing_targets, grade, origins,
                                  run_frames, run_summaries)
from src.core.special import LABELS as SPECIAL_LABELS
from src.core.special import LENS_EDGE, SKY, Special, lens_edge_mask, sky_maps, sky_mask
from src.core.refine import (
    RANGE_KEYS, apply_by_color, close_gaps, fill_holes, grow_mask, grow_to_edges, near_edge, range_selection,
    remove_specks, select_range, shrink_mask,
    within,
)
from src.core.storage import ExportOptions, ProjectStore, export_final_masks
from src.engine.batch import LabelHit
from src.engine.imageio import find_images, image_key, original_size, read_rgb, resize_mask, to_working, working_size

DEFAULT_MAX_SIDE = 1024
# auto tool -> the settings it uses (Grow and Shrink share one amount)
AUTO_PARAMS = {
    "object_fill": ("max_grow", "sensitivity"),
    "fill_holes": ("fill_area",),
    "remove_specks": ("speck_area",),
    "grow": ("amount",),
    "shrink": ("amount",),
    "close_gaps": ("gap",),
    "invert": (),
    "by_color": ("color_band", "color_band_on", "color_action", "color_samples", "color_tol", "color_use", "color_not",
                 "color_samples_out", "color_tol_out", "bright_range", "bright_use", "bright_not", "range_join", "color_invert"),
}
IMAGE_TOOLS = ("object_fill", "by_color")  # auto tools that read the image (computed off the UI thread)


def compute_tool(tool: str, base: np.ndarray, image: Optional[np.ndarray], settings: dict) -> np.ndarray:
    """Auto tool *tool* on mask *base* everywhere (*image*: only the IMAGE_TOOLS read it)."""
    if tool == "fill_holes":
        return fill_holes(base, settings.get("fill_area", 200))
    if tool == "remove_specks":
        return remove_specks(base, settings.get("speck_area", 200))
    if tool == "object_fill":
        return grow_to_edges(image, base, settings.get("max_grow", 20), settings.get("sensitivity", 50))
    if tool == "grow":
        return grow_mask(base, settings.get("amount", 3))
    if tool == "shrink":
        return shrink_mask(base, settings.get("amount", 3))
    if tool == "close_gaps":
        return close_gaps(base, settings.get("gap", 10))
    if tool == "invert":
        return ~base
    if tool == "by_color":  # Range only (the Auto ways went in p97, BC-P5)
        return apply_by_color(base, image, settings)
    raise ValueError(f"Unknown auto tool: {tool}")


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


class Session:
    """One open image folder and everything being edited in it."""

    def __init__(self, engine: Optional[Engine] = None, max_side: int = DEFAULT_MAX_SIDE):
        self.engine = engine
        # While SAM2 loads, prompts are kept (the points show) and run once it is ready
        self.defer_prompts = False
        self.pending: Set[Tuple[int, str]] = set()  # (Object id, image key) whose prompts wait for SAM2
        self._deferred = False
        self.max_side = max_side
        self.image_dir: Optional[Path] = None
        self.paths: List[Path] = []
        self.mask_reports: Dict[int, Path] = {}  # the last import's batch reports: Object id -> report file
        self.store: Optional[ProjectStore] = None
        self.project = Project([])
        self.index = -1
        self.image: Optional[np.ndarray] = None  # working-resolution RGB of the current image
        self.mode = Mode.IDLE
        self.editing: Optional[int] = None  # id of the one Object in Edit
        self.selected_point: Optional[int] = None
        self.active_layer: Optional[int] = None  # clicks go to: 0 = Original, n = Layer n; None = automatic
        # Box region the whole-mask tool buttons are limited to (None: the whole mask).
        # UI state for the Object in Edit on this image: not saved, but undoable (below).
        self.region: Optional[np.ndarray] = None
        # Region and Paint-mode pick changes join Ctrl+Z / Ctrl+Y: each entry remembers the
        # project's history position, so they undo in order with the project's own steps.
        self._ui_undo: List[Tuple[int, str, Optional[np.ndarray]]] = []  # (depth, kind, value before)
        self._ui_redo: List[Tuple[int, int, str, Optional[np.ndarray]]] = []  # (depth, actions, kind, value)
        # Auto tools (object_fill | fill_holes | remove_specks): one result computed from the
        # mask. Fill takes all of it; Paint takes the parts picked with strokes (the rest is
        # gray). Nothing is written until the tool closes; switching modes keeps both.
        self.auto_tool: Optional[str] = None
        self.auto_mode = "fill"
        # By Color Range's picked colors and left-out colors (the panel holds them; kept here too so a change is
        # an undo step, p92; both in one value so one step covers either, p98)
        self._colors: Tuple[tuple, tuple] = ((), ())
        self._picked: Optional[np.ndarray] = None  # Paint mode: the area strokes picked
        self._result: Optional[Tuple[str, np.ndarray, List[np.ndarray]]] = None  # (tool, target, masks it fits)
        self._auto_cache: Optional[tuple] = None  # ((tool, settings), base, target)
        self._area_cache: Optional[tuple] = None  # (base, band, By Color's Near edge area)
        self._ab_cache: Optional[tuple] = None  # (filter settings, image, By Color Range's A, overlap)
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
        from src.core.colmap import scene_root

        from src.core.rig import is_rig, rig_images

        root = scene_root(image_dir)
        if root is not None and root != image_dir:
            paths = find_images(image_dir, recursive=True)  # cam0/, cam1/ of a scene
        elif is_rig(image_dir):
            paths = rig_images(image_dir)  # a rig without a model: its camera folders only (06 2.1)
        else:
            paths = find_images(image_dir)
        if not paths:
            raise FileNotFoundError(f"No images found in {image_dir}")
        self.image_dir = image_dir
        self.paths = paths
        self.store = ProjectStore(image_dir, self.max_side)
        self.project = self.store.load([image_key(image_dir, p) for p in paths])
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
            self.run_pending()
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
        self.active_layer = None

    def cancel_mode(self) -> None:
        """Finish Editing / leave New Object mode."""
        self.mode = Mode.IDLE
        self.editing = None
        self.selected_point = None
        self.active_layer = None
        self._reset_region()

    finish_editing = cancel_mode

    @property
    def effective_mode(self) -> Mode:
        """The mode clicks act in. A plain click never creates an Object, not even the first
        one: New Object (N) does (the v0.2 "first click" shortcut was removed on request)."""
        return self.mode

    def sync(self) -> None:
        """Drop edit state that no longer matches the project (after undo/redo/delete)."""
        if self.editing is not None and self.project.get(self.editing) is None:
            self.cancel_mode()
        fs = self.editing_frame()
        if fs is None or (self.active_layer is not None and self.active_layer > len(fs.layers)):
            self.active_layer = None
        if self.selected_point is not None and self.selected_point >= len(self.active_prompts()[0]):
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
        """Recompute a frame's Variants from its full prompt set (seeded by its base mask).

        While SAM2 is still loading (``defer_prompts``) the prompts are kept as they
        are and the frame is queued; ``run_pending`` computes it once SAM2 is ready.
        """
        if self.defer_prompts and fs.has_prompts and (self.engine is None or not self.engine.sam2_ready):
            self._deferred = True
            return dataclasses.replace(fs, status=FrameStatus.MANUAL)
        variants = self._require_sam2().predict(fs.points, fs.box, fs.base_mask) if fs.has_prompts else ()
        if not variants and fs.base_mask is not None:
            variants = (Variant(fs.base_mask, 1.0),)
        return dataclasses.replace(fs, variants=tuple(variants), selected=0, status=FrameStatus.MANUAL)

    def _create(self, fs: FrameState, source: Source) -> int:
        self._deferred = False
        fs = self._run(fs)
        assert self.key is not None
        oid = self.project.add_object(self.key, fs, source)
        if self._deferred:
            self.pending.add((oid, self.key))
        self.edit(oid)
        return oid

    def _update(self, change: Callable[[FrameState], FrameState]) -> None:
        assert self.editing is not None and self.key is not None
        fs = self.editing_frame() or FrameState()
        self._deferred = False
        self.project.set_frame(self.editing, self.key, self._run(change(fs)))
        if self._deferred:
            self.pending.add((self.editing, self.key))

    def run_pending(self) -> int:
        """SAM2 is ready: compute the queued prompts on the current image (one undo step).

        Frames queued on other images run when those images open (``go_to``).
        Returns how many frames were computed.
        """
        if self.key is None or self.engine is None or not self.engine.sam2_ready:
            return 0
        here = [(oid, k) for oid, k in self.pending if k == self.key]
        updates: Dict[int, Dict[str, FrameState]] = {}
        for oid, key in here:
            self.pending.discard((oid, key))
            obj = self.project.get(oid)
            fs = obj.frame(key) if obj is not None else None
            if fs is not None and fs.has_prompts:
                updates.setdefault(oid, {})[key] = self._run(fs)
        self.project.set_frames(updates)
        return sum(len(v) for v in updates.values())

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
        self._update_prompts(lambda pts, box: (pts + (p,), box))
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
        self._update_prompts(lambda pts, _old: (pts, box))
        return self.editing

    def select_point(self, index: Optional[int]) -> None:
        pts = self.active_prompts()[0]
        self.selected_point = index if index is not None and 0 <= index < len(pts) else None

    def delete_point(self, index: Optional[int] = None) -> bool:
        """Delete one point of the current layer (default: the selected one) and re-run SAM2 on the rest."""
        index = self.selected_point if index is None else index
        pts = self.active_prompts()[0]
        if self.editing_frame() is None or index is None or not (0 <= index < len(pts)):
            return False
        self._update_prompts(lambda p, box: (p[:index] + p[index + 1 :], box))
        self.selected_point = None
        return True

    def move_point(self, index: int, x: float, y: float) -> bool:
        """Move one point of the current layer (dragged on the image) and re-run SAM2."""
        pts = self.active_prompts()[0]
        if self.editing_frame() is None or not (0 <= index < len(pts)):
            return False
        moved = Point(float(x), float(y), pts[index].positive)
        self._update_prompts(lambda p, box: (p[:index] + (moved,) + p[index + 1 :], box))
        self.selected_point = index
        return True

    def clear_points(self) -> bool:
        """Remove every point and the box of the current layer (Original: its base mask stays)."""
        pts, box = self.active_prompts()
        if self.editing_frame() is None or not (pts or box is not None):
            return False
        self._update_prompts(lambda _p, _b: ((), None))
        self.selected_point = None
        return True

    def clear_box(self) -> bool:
        if self.editing_frame() is None or self.active_prompts()[1] is None:
            return False
        self._update_prompts(lambda p, _b: (p, None))
        return True

    # ------------------------------------------------------------------
    # Point layers (docs/specs/10-prompt-layers.md)
    # ------------------------------------------------------------------

    def current_layer(self) -> int:
        """Where clicks go: 0 = Original, n = Layer n, len(layers) + 1 = a new layer the next click makes.

        Automatic (none picked): a frame whose mask came without prompts of its own (imported,
        propagated, applied) gets point layers, the last one or a new Layer 1; else the Original."""
        fs = self.editing_frame()
        if fs is None:
            return 0
        if self.active_layer is not None and self.active_layer <= len(fs.layers):
            return self.active_layer
        if fs.layers:
            return len(fs.layers)
        return 1 if fs.mask is not None and not fs.has_prompts else 0

    def active_prompts(self) -> Tuple[Tuple[Point, ...], Optional[Box]]:
        """The current layer's points and box (a layer not made yet: none)."""
        fs = self.editing_frame()
        if fs is None:
            return (), None
        i = self.current_layer()
        if i == 0:
            return fs.points, fs.box
        if i <= len(fs.layers):
            return fs.layers[i - 1].points, fs.layers[i - 1].box
        return (), None

    def _update_prompts(self, change: Callable[[Tuple[Point, ...], Optional[Box]], tuple]) -> None:
        """Change the current layer's (points, box) and compute its mask (one undo step)."""
        i = self.current_layer()
        if i == 0:
            self._update(lambda f: dataclasses.replace(f, **dict(zip(("points", "box"), change(f.points, f.box)))))
            return
        assert self.editing is not None and self.key is not None
        fs = self.editing_frame() or FrameState()
        layers = list(fs.layers)
        if i > len(layers):
            layers.append(PromptLayer())
        ly = layers[i - 1]
        pts, box = change(ly.points, ly.box)
        mask = None
        if pts or box is not None:  # the piece from this layer's prompts alone (no seed)
            variants = self._require_sam2().predict(pts, box, None)
            mask = variants[0].mask if variants else None
        layers[i - 1] = dataclasses.replace(ly, points=pts, box=box, mask=mask)
        self.active_layer = i
        self.project.set_frame(self.editing, self.key,
                               dataclasses.replace(fs, layers=tuple(layers), status=FrameStatus.MANUAL))

    def _set_layers(self, layers: Sequence[PromptLayer]) -> None:
        fs = self.editing_frame()
        assert fs is not None and self.editing is not None and self.key is not None
        self.project.set_frame(self.editing, self.key, dataclasses.replace(fs, layers=tuple(layers)))

    def select_layer(self, index: int) -> bool:
        """Clicks go to layer *index* from now on (0 = Original)."""
        fs = self.editing_frame()
        if fs is None or not (0 <= index <= len(fs.layers)):
            return False
        self.active_layer = index
        self.selected_point = None
        return True

    def add_layer(self, subtract: bool = False) -> int:
        """A new, empty point layer, made the current one (one undo step); returns its number."""
        fs = self.editing_frame()
        if fs is None:
            return 0
        self._set_layers(fs.layers + (PromptLayer(subtract=subtract),))
        self.active_layer = len(fs.layers) + 1
        self.selected_point = None
        return self.active_layer

    def toggle_layer_subtract(self, index: Optional[int] = None) -> bool:
        """Layer *index* (default: the current one) adds <-> subtracts its piece."""
        fs = self.editing_frame()
        index = self.current_layer() if index is None else index
        if fs is None or not (1 <= index <= len(fs.layers)):
            return False
        layers = list(fs.layers)
        layers[index - 1] = dataclasses.replace(layers[index - 1], subtract=not layers[index - 1].subtract)
        self._set_layers(layers)
        return True

    def remove_layer(self, index: Optional[int] = None) -> bool:
        """Remove point layer *index* (default: the current one); the one before becomes current."""
        fs = self.editing_frame()
        index = self.current_layer() if index is None else index
        if fs is None or not (1 <= index <= len(fs.layers)):
            return False
        self._set_layers(fs.layers[: index - 1] + fs.layers[index:])
        self.active_layer = index - 1
        self.selected_point = None
        return True

    def delete_prompt(self, layer: int, index: Optional[int]) -> bool:
        """× in the Points list: point *index* (None: the box) of *layer*."""
        if not self.select_layer(layer):
            return False
        return self.delete_point(index) if index is not None else self.clear_box()

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
        layer = EditLayer.between(fs.layered_mask, target)  # hand edits sit on top of the point layers
        if layer is None and fs.edit is None:
            return False
        self.project.set_frame(self.editing, self.key, dataclasses.replace(fs, edit=layer, status=FrameStatus.MANUAL))
        return True

    def segment_edit(self, x: float, y: float, add: bool = True) -> bool:
        """Ctrl+click while editing: the piece SAM2 sees at (x, y) on its own (no other prompt, no seed),
        added to the edited mask or (*add* False) taken out of it, inside the region if there is one.

        Kept in the edit layer like a brush stroke: the rest of the mask, its points and Variants
        stay as they are (a new point would re-run SAM2 and redraw the whole mask instead).
        """
        if self.editing is None or self.key is None:
            return False
        variants = self._require_sam2().predict((Point(float(x), float(y), True),), None, None)
        if not variants:
            return False
        piece = variants[0].mask
        cur, area = self._edit_area()
        return self._set_target(cur | (piece & area) if add else cur & ~(piece & area))

    def brush(self, mask: np.ndarray) -> bool:
        """A finished brush stroke: *mask* is what the edited frame should now show.

        The change goes into the edit layer; the points, box and Variants stay,
        so deleting the layer returns to the prompt-based mask.
        """
        return self._set_target(mask)

    def _edit_area(self) -> Tuple[np.ndarray, np.ndarray]:
        """(the edited frame's mask, where whole-mask edits apply: the region, else everywhere)."""
        fs = self.editing_frame()
        cur = fs.mask if fs is not None and fs.mask is not None else np.zeros(self.working_hw(), bool)
        area = self.region if self.region is not None else np.ones(cur.shape, bool)
        return cur, area

    def import_masks(self, folders, progress=None) -> List[int]:
        """Mask folders as Objects (one per folder, named after it): [(folder, black_is_object)].

        Each image's mask file (``a.jpg.png`` or ``a.png``) is read, flipped when black
        marks the object, and brought to the working resolution. Images with an empty
        mask get no frame. One undo step for all; returns the new ids.

        A batch run's report for the folder (src/core/mask_report.py, p150) marks its
        propagated frames ✓ and the ones worth a look ⚠ (an empty one kept, to be found),
        with the reason in the frame's note; the reports used are in ``self.mask_reports``.
        """
        from src.core import mask_report
        from src.core.colmap import matched, read_mask

        frames_by_label: Dict[str, Dict[str, FrameState]] = {}
        todo = [(Path(d), black, matched(Path(d), list(self.keys))) for d, black in folders]
        total, done = sum(len(m) for _, _, m in todo), 0
        reports: Dict[str, Path] = {}
        for folder, black, files in todo:
            hit = mask_report.find(folder)
            notes = mask_report.notes_for(files, hit[1], hit[2]) if hit else {}
            if notes:
                reports[folder.name] = hit[0]
            frames: Dict[str, FrameState] = {}
            for key, path in files.items():
                m = read_mask(path)
                done += 1
                if progress:
                    progress(done, total)
                if m is None:
                    continue
                if black:
                    m = ~m
                note = notes.get(key) or {}
                warn = mask_report.warned(note)
                if not m.any() and not warn:
                    continue
                h0, w0 = self.original_size(key)
                if m.shape != (h0, w0):
                    m = resize_mask(m, (h0, w0))  # a mask saved at another size: match the image first
                m = resize_mask(m, working_size(h0, w0, self.max_side))
                status = (FrameStatus.WARNING if warn else FrameStatus.PROPAGATED if mask_report.propagated(note)
                          else FrameStatus.IMPORTED)  # ↓, not ✓ (U2), unless the report says propagated
                frames[key] = FrameState.from_mask(m, status=status, note=mask_report.describe(note))
            frames_by_label[folder.name] = frames
        ids = self.project.add_label_objects(frames_by_label, Source.IMPORTED)
        filled = [label for label, frames in frames_by_label.items() if frames]  # add_label_objects' order
        self.mask_reports = {oid: reports[label] for oid, label in zip(ids, filled) if label in reports}
        self.sync()
        return ids

    def invert_mask(self) -> bool:
        """Ctrl+I: flip the edited mask on this image (inside the region only, when there is one)."""
        if self.editing is None or self.key is None:
            return False
        cur, area = self._edit_area()
        return self._set_target(cur ^ area)

    def clear_mask(self) -> bool:
        """Ctrl+Backspace: empty the edited mask on this image (inside the region only, when there is one)."""
        if self.editing is None or self.key is None:
            return False
        cur, area = self._edit_area()
        return self._set_target(cur & ~area)

    def set_region(self, region: Optional[np.ndarray]) -> None:
        """Limit the whole-mask tools to *region* (a bool mask); None or empty = everywhere. Undoable."""
        region = region if region is not None and region.any() else None
        if region is None and self.region is None:
            return
        self._record("region")
        self.region = region

    UI_STATE = {"region": "region", "picks": "_picked", "colors": "_colors"}  # undoable UI state -> attribute

    @property
    def color_samples(self) -> tuple:
        return self._colors[0]

    @property
    def color_samples_out(self) -> tuple:
        """By Color's left-out colors (right-click while picking, BC-P4 b)."""
        return self._colors[1]

    def set_color_samples(self, colors, out=None) -> None:
        """The picked (and left-out, *out*; None: as they are) colors changed (a click on the image, Shift+click,
        a swatch, Clear): one undo step."""
        def clean(cs):
            return tuple(tuple(int(v) for v in c) for c in cs)
        new = (clean(colors), self._colors[1] if out is None else clean(out))
        if new != self._colors:
            self._record("colors")
            self._colors = new

    def _record(self, kind: str) -> None:
        """Remember the current *kind* value as an undo step (before it changes)."""
        self._ui_undo.append((self.project.undo_depth, kind, getattr(self, self.UI_STATE[kind])))
        self._ui_redo.clear()

    def _forget(self, kind: Optional[str] = None) -> None:
        """Drop the history of *kind* (all UI state but the picked colors when None): it no longer means
        anything. The picked colors stay with the tool across frames and edit targets, so does their history."""
        def keep(k: str) -> bool:
            return k == "colors" if kind is None else k != kind
        self._ui_undo = [e for e in self._ui_undo if keep(e[1])]
        self._ui_redo = [e for e in self._ui_redo if keep(e[2])]

    def _reset_region(self) -> None:
        """Leaving the edit target ends its region, the region's history and any auto-tool result."""
        self.region = None
        self._forget()
        self._result = None
        self._picked = None

    # ------------------------------------------------------------------
    # Auto tools: one result, shown as a Fill preview or a Brush guide
    # ------------------------------------------------------------------

    def set_auto_tool(self, tool: Optional[str]) -> None:
        if tool != self.auto_tool:
            self._result = None
            self._picked = None
            self._forget("picks")
        self.auto_tool = tool

    def set_auto_mode(self, mode: str) -> None:
        """Fill <-> Paint: the same result and the same picks, shown the other way."""
        self.auto_mode = mode

    def auto_base(self) -> Optional[np.ndarray]:
        fs = self.editing_frame()
        return fs.mask if fs is not None else None

    def auto_area(self, settings: dict) -> Optional[np.ndarray]:
        """Where By Color decides pixels again: the Near edge band around the mask (inside the region if any);
        None when it is the whole image (or region) or another tool is in use."""
        base = self.auto_base()
        if self.auto_tool != "by_color" or base is None or not settings.get("color_band_on", True):
            return None
        band = settings.get("color_band", 30)
        if band <= 0:
            return None
        c = self._area_cache
        if c is None or c[0] is not base or c[1] != band:
            c = self._area_cache = (base, band, near_edge(base, band))
        return c[2] & self.region if self.region is not None else c[2]

    def auto_ab(self, settings: dict) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """By Color Range's (A, B) where it decides (the Near edge area if on, inside the region if any):
        A = what the filter catches (after Swap), B = the rest. None for other tools."""
        if self.auto_tool != "by_color" or self.image is None:
            return None
        a = self._range(settings)[0]
        area = self.auto_area(settings)
        if area is None and self.region is not None:
            area = self.region
        if area is None:
            return a, ~a
        return a & area, ~a & area

    def _range(self, settings: dict) -> tuple:
        """By Color Range's A, overlap (picked and left-out colors both claim it) and what the color condition
        alone takes (None: not in use), on the whole image, cached."""
        key = tuple((k, settings.get(k)) for k in RANGE_KEYS)
        c = self._ab_cache
        if c is None or c[0] != key or c[1] is not self.image:
            c = self._ab_cache = (key, self.image) + range_selection(self.image, settings, with_parts=True)
        return c[2], c[3], c[4]

    def auto_color_cover(self, settings: dict) -> Optional[float]:
        """The share (0-1) of the pixels By Color decides that the color condition alone takes; None when it is
        not in use. Near 0 or 1 the colors decide nothing: the tolerance is off (p99: 100 took everything)."""
        if self.auto_tool != "by_color" or self.image is None:
            return None
        color = self._range(settings)[2]
        if color is None:
            return None
        area = self.auto_area(settings)
        if area is None and self.region is not None:
            area = self.region
        part = color[area] if area is not None else color
        return float(part.mean()) if part.size else None

    def auto_overlap(self, settings: dict) -> Optional[np.ndarray]:
        """Where a picked and a left-out color both claim pixels (the nearer one decided), inside the area By
        Color decides; None when there is none or the tool is not By Color (BC-P4 b)."""
        if self.auto_tool != "by_color" or self.image is None:
            return None
        overlap = self._range(settings)[1]
        area = self.auto_area(settings)
        if area is None and self.region is not None:
            area = self.region
        if area is not None:
            overlap = overlap & area
        return overlap if overlap.any() else None

    def auto_stale(self) -> bool:
        """The mask changed by something other than this tool's strokes (undo, a click, ...)."""
        if self.auto_tool is None:
            return False
        m = self.auto_base()
        if m is None:
            return False
        return self._result is None or self._result[0] != self.auto_tool or all(m is not k for k in self._result[2])

    @staticmethod
    def _auto_key(tool: str, settings: dict) -> tuple:
        """The settings *tool* actually uses (others changing must not invalidate its result)."""
        return (tool, tuple((k, settings.get(k)) for k in AUTO_PARAMS[tool]))

    def auto_cached(self, tool: str, base: np.ndarray, settings: dict) -> Optional[np.ndarray]:
        c = self._auto_cache
        if c is not None and c[0] == self._auto_key(tool, settings) and c[1] is base:
            return c[2]
        return None

    def auto_compute(self, tool: str, base: np.ndarray, **settings) -> np.ndarray:
        """*tool* applied to *base* everywhere (thread-safe: reads only the image)."""
        target = self.auto_cached(tool, base, settings)
        if target is not None:
            return target
        target = compute_tool(tool, base, self.image, settings)
        self._auto_cache = (self._auto_key(tool, settings), base, target)
        return target

    def auto_apply(self, base: np.ndarray, target: np.ndarray) -> None:
        """Keep a computed result for the current tool (nothing is written yet)."""
        self._result = (self.auto_tool, target, [base])

    def auto_changes(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """(added, removed): everything the result would change, inside the region."""
        fs = self.editing_frame()
        r = self._result
        if fs is None or fs.mask is None or r is None or r[0] != self.auto_tool:
            return None, None
        m, target = fs.mask, r[1]
        inside = self.region if self.region is not None else True
        return target & ~m & inside, m & ~target & inside

    def auto_taken(self) -> Optional[np.ndarray]:
        """Where the result will be written when the tool closes (Fill: all of it; Paint: the picks)."""
        added, removed = self.auto_changes()
        if added is None:
            return None
        changed = added | removed
        if self.auto_mode == "fill":
            return changed
        return changed & self._picked if self._picked is not None else np.zeros_like(changed)

    def pick(self, area: np.ndarray, unpick: bool = False) -> bool:
        """A Paint-mode stroke: pick (or with *unpick*, drop) *area* of the result."""
        if self._result is None:
            return False
        picked = self._picked if self._picked is not None else np.zeros(area.shape, bool)
        self._record("picks")
        self._picked = picked & ~area if unpick else picked | area
        return True

    @property
    def has_picks(self) -> bool:
        """Paint mode has picks of its own (kept while going to Fill and back)."""
        return self._picked is not None

    def pick_everything(self) -> bool:
        """Pick the whole result (entering Paint mode from Fill with A keeps what Fill showed)."""
        if self._result is None:
            return False
        fs = self.editing_frame()
        if fs is None or fs.mask is None:
            return False
        self._record("picks")
        self._picked = np.ones(fs.mask.shape, bool)
        return True

    def pick_all(self) -> bool:
        """Paint mode (A): pick the whole result, or drop every pick when all of it is picked already."""
        added, removed = self.auto_changes()
        if added is None:
            return False
        changed = added | removed
        everything = self._picked is not None and not (changed & ~self._picked).any()
        self._record("picks")
        self._picked = np.zeros(added.shape, bool) if everything else np.ones(added.shape, bool)
        return True

    def apply_auto(self) -> bool:
        """Write what the auto tool takes in (one undo step) and keep the tool on.

        The picks are cleared; the result no longer fits the new mask, so it is
        recomputed and the next application is shown.
        """
        taken, fs, r = self.auto_taken(), self.editing_frame(), self._result
        self._picked = None
        self._forget("picks")  # applied: Ctrl+Z now undoes the application itself
        if taken is None or fs is None or not taken.any():
            return False
        return self._set_target(freeze(np.where(taken, r[1], fs.mask)))

    def auto_all_keys(self) -> List[str]:
        """Apply to Frames: the images where the edited Object has a mask (others stay empty)."""
        o = self.project.get(self.editing) if self.editing is not None else None
        if o is None:
            return []
        return [k for k in self.keys if o.mask(k) is not None]

    def auto_targets(self, tool: str, settings: dict, keys: Sequence[str], progress=None,
                     cancelled=None) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
        """*tool* with *settings* on the edited Object's mask on each of *keys*: {key: (that mask, the result
        bit-packed)}. Safe off the UI thread (reads masks and images only)."""
        o = self.project.get(self.editing) if self.editing is not None else None
        out: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
        if o is None:
            return out
        for n, key in enumerate(keys):
            if cancelled is not None and cancelled():
                break
            base = o.mask(key)
            if base is not None:
                image = None
                if tool in IMAGE_TOOLS:
                    image = self.image if key == self.key else self.working_image(key)
                out[key] = (base, np.packbits(compute_tool(tool, base, image, settings), axis=None))
            if progress:
                progress(n + 1, len(keys))
        return out

    def apply_auto_all(self, results: Dict[str, Tuple[np.ndarray, np.ndarray]]) -> Tuple[int, int]:
        """Write *results* (from :meth:`auto_targets`) into the edited Object as one undo step, each into that
        frame's edit layer like Fill does on one image, inside the region when there is one. A frame whose mask
        changed meanwhile, or (with a region) of another size, is left alone. Returns (changed, skipped)."""
        o = self.project.get(self.editing) if self.editing is not None else None
        if o is None:
            return 0, 0
        per: Dict[str, FrameState] = {}
        skipped = 0
        for key, (base, packed) in results.items():
            fs = o.frame(key)
            if fs is None or fs.mask is not base:
                skipped += 1
                continue
            target = np.unpackbits(packed, count=base.size).reshape(base.shape).astype(bool)
            if self.region is not None:
                if self.region.shape != base.shape:
                    skipped += 1
                    continue
                target = np.where(self.region, target, base)
            if (target == base).all():
                continue
            layer = EditLayer.between(fs.layered_mask, freeze(target))
            per[key] = dataclasses.replace(fs, edit=layer, status=FrameStatus.MANUAL)
        if per:
            self.project.set_frames({o.id: per})
            self.sync()
        return len(per), skipped

    def close_auto(self, apply: bool) -> bool:
        """Leave the auto tool; with *apply*, write what it takes in first."""
        done = self.apply_auto() if apply else False
        self._result = self._picked = None
        self._forget("picks")
        self.auto_tool = None
        return done

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
            p = fs.layered_mask
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

    def run_summaries(self, ids: Iterable[int]) -> List[RunSummary]:
        return run_summaries(self.project.objects, ids)

    def run_frames(self, ids: Iterable[int], run: int, ref: str, direction: Direction,
                   keep: int = 0) -> Dict[int, List[str]]:
        return run_frames(self.project.objects, ids, run, ref, direction, keep)

    def clear_run(self, frames: Dict[int, List[str]]) -> int:
        """Remove a propagation run's frames ({Object id: keys}, from run_frames) as one undo step."""
        gone = self.project.remove_frames(frames)
        self.sync()
        return gone

    def clear_frames(self, ids: Iterable[int], rows: Iterable[int]) -> int:
        """Empty the Objects' masks on the images *rows* (one undo step); returns how many masks went."""
        gone = self.project.clear_frames(ids, [self.keys[i] for i in rows])
        self.sync()
        return gone

    def stamp_frames(self, ids: Iterable[int], source: int, rows: Iterable[int],
                     replace: bool = False) -> Dict[int, List[str]]:
        """Each Object's mask on image *source*, copied onto the images *rows* (one undo step): added to the
        mask there, or (*replace*) instead of it. {Object id: image keys changed}."""
        if not (0 <= source < len(self.keys)):
            return {}
        skey = self.keys[source]
        rows = list(rows)
        updates: Dict[int, Dict[str, FrameState]] = {}
        for oid in ids:
            o = self.project.get(oid)
            m = o.mask(skey) if o is not None else None
            if m is None:
                continue
            per: Dict[str, FrameState] = {}
            for i in rows:
                k = self.keys[i]
                if k == skey:
                    continue
                size = working_size(*self.original_size(k), self.max_side)
                src = m if m.shape == tuple(size) else resize_mask(m, size)
                old = o.frame(k)
                if replace or old is None or old.mask is None:
                    per[k] = FrameState.from_mask(src, status=FrameStatus.PROPAGATED)
                else:
                    kept = FrameStatus.MANUAL if old.status == FrameStatus.MANUAL else FrameStatus.PROPAGATED
                    per[k] = FrameState.from_mask(union([old.mask, src]), status=kept)
            if per:
                updates[oid] = per
        self.project.set_frames(updates)
        self.sync()
        return {oid: list(per) for oid, per in updates.items()}

    # ------------------------------------------------------------------
    # Special Objects: masks made from settings (docs/specs/09-special-objects.md)
    # ------------------------------------------------------------------

    def add_special(self, kind: str) -> int:
        oid = self.project.add_special(Special.new(kind), SPECIAL_LABELS[kind])
        self.sync()
        return oid

    def sky_cache(self, key: str, refined: bool) -> Path:
        """The sky map of image *key* (working size), kept beside the project so settings move freely."""
        return self.store.root / "special" / ("sky_refined" if refined else "sky") / f"{key}.png"

    def sky_missing(self, keys: Iterable[str]) -> List[str]:
        return [k for k in keys if not (self.sky_cache(k, False).is_file() and self.sky_cache(k, True).is_file())]

    def working_image(self, key: str) -> np.ndarray:
        return to_working(read_rgb(self.paths[self.keys.index(key)]), self.max_side)

    def compute_sky(self, keys: Sequence[str], model, progress=None, cancelled=None) -> int:
        """Run the sky model on *keys* and cache its map, raw and refined (safe off the UI thread:
        it reads images and writes cache files only). Returns how many were done."""
        import cv2

        done = 0
        for n, key in enumerate(keys):
            if cancelled is not None and cancelled():
                break
            prob, refined_map = sky_maps(model, self.working_image(key))
            for refined, m in ((False, prob), (True, refined_map)):
                path = self.sky_cache(key, refined)
                path.parent.mkdir(parents=True, exist_ok=True)
                ok, buf = cv2.imencode(".png", m)
                buf.tofile(str(path))
            done += 1
            if progress:
                progress(n + 1, len(keys))
        return done

    def _sky_map(self, key: str, refined: bool) -> Optional[np.ndarray]:
        return _read_gray(self.sky_cache(key, refined))

    # the finish (By Color + tree tips + SAM2 at full resolution, as `cli sky --color-preset`): slow (seconds a
    # frame), so it runs on Make Masks only and is kept per settings ("fingerprint"); moving a setting shows
    # the model's mask until the frames are finished again, going back shows the kept finish at once
    def sky_finish_print(self, sp: Special) -> str:
        """The finish's fingerprint: every value its pixels depend on."""
        from src.core.refine import TREE_TIPS
        from src.core.sky_sam2 import SAM2_TILES, SKY_SAM2

        fin = sp.finish_values or {}
        d = {k: sp.get(k) for k in ("threshold", "refine", "grow", "top_only")}
        d.update(color=fin.get("color"), tree_tips=bool(fin.get("tree_tips", True)), tips=TREE_TIPS,
                 tiles=SAM2_TILES, sam2=SKY_SAM2.name, max_side=self.max_side)
        return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]

    def sky_finished(self, key: str, fingerprint: str, full: bool) -> Path:
        """Image *key*'s finished sky: at its original resolution (*full*, what Export writes) or the working size."""
        return self.store.root / "special" / "sky_finished" / fingerprint / ("full" if full else "work") / f"{key}.png"

    def sky_unfinished(self, keys: Iterable[str], sp: Special) -> List[str]:
        """The *keys* without *sp*'s finish ([] when it has none)."""
        if sp.kind != SKY or not sp.finish:
            return []
        fp = self.sky_finish_print(sp)
        return [k for k in keys if not self.sky_finished(k, fp, False).is_file()]

    def finish_sky(self, keys: Sequence[str], sp: Special, engine, progress=None, cancelled=None) -> int:
        """Finish *sp*'s sky on *keys* (their sky maps made) with SAM2 *engine* and keep it, at the original
        resolution and the working size (safe off the UI thread: reads images, writes cache files only). The
        same pixels as ``cli sky --color-preset`` (src/core/sky_sam2.py ``finish_sky``). Returns how many."""
        from src.core.sky_edges import sky_edges
        from src.core.sky_sam2 import finish_sky

        fin = sp.finish_values
        fp = self.sky_finish_print(sp)
        done = 0
        for n, key in enumerate(keys):
            if cancelled is not None and cancelled():
                break
            prob = self._sky_map(key, bool(sp.get("refine")))
            if prob is not None:
                rgb = read_rgb(self.paths[self.keys.index(key)])
                full, _clicks = finish_sky(sky_edges(sky_mask(prob, sp), rgb), rgb, fin["color"],
                                           bool(fin.get("tree_tips", True)), engine)
                size = working_size(rgb.shape[0], rgb.shape[1], self.max_side)
                _write_mask(self.sky_finished(key, fp, True), full)
                _write_mask(self.sky_finished(key, fp, False), resize_mask(full, size))  # last: it marks "done"
                done += 1
            if progress:
                progress(n + 1, len(keys))
        return done

    def finished_sky_full(self, key: str, o: MaskObject) -> Optional[np.ndarray]:
        """A Sky Object's finished mask of *key* at the original resolution (Export), None = not finished."""
        sp = o.special
        if sp is None or sp.kind != SKY or not sp.finish or key not in sp.keys:
            return None
        m = _read_gray(self.sky_finished(key, self.sky_finish_print(sp), True))
        return None if m is None else m > 127

    def special_mask(self, key: str, sp: Special) -> Optional[np.ndarray]:
        """*sp*'s mask on image *key* at the working size (None: the sky map is not made yet)."""
        size = working_size(*self.original_size(key), self.max_side)
        if sp.kind == LENS_EDGE:
            return lens_edge_mask(size[0], size[1], sp)
        if sp.finish:
            done = _read_gray(self.sky_finished(key, self.sky_finish_print(sp), False))
            if done is not None:
                m = done > 127
                return m if m.shape == tuple(size) else resize_mask(m, size)
        prob = self._sky_map(key, bool(sp.get("refine")))
        if prob is None:
            return None
        m = sky_mask(prob, sp)
        return m if m.shape == tuple(size) else resize_mask(m, size)

    def update_special(self, obj_id: int, params: Optional[dict] = None,
                       keys: Optional[Iterable[str]] = None) -> bool:
        """New settings (*params*) and / or more images (*keys*) for a special Object; its masks are
        made again on every image it covers, as one undo step."""
        o = self.project.get(obj_id)
        if o is None or o.special is None:
            return False
        params = dict(params or {})
        sp = o.special.with_finish(params.pop("finish")) if "finish" in params else o.special
        sp = sp.with_params(**params) if params else sp
        if keys is not None:
            sp = sp.with_keys(set(sp.keys) | set(keys), self.keys)
        frames: Dict[str, Optional[FrameState]] = {}
        same: Dict[tuple, Optional[FrameState]] = {}  # lens edge: one mask per image size, shared by its frames
        for k in sp.keys:
            size = tuple(working_size(*self.original_size(k), self.max_side)) if sp.kind == LENS_EDGE else None
            if size is not None and size in same:
                frames[k] = same[size]
                continue
            m = self.special_mask(k, sp)
            if m is None:
                continue  # its sky map is missing: the frame stays as it was
            frames[k] = FrameState.from_mask(m, status=FrameStatus.PROPAGATED) if m.any() else None
            if size is not None:
                same[size] = frames[k]
        self.project.set_special(obj_id, sp, frames)
        self.sync()
        return True

    def apply_special(self, obj_id: int) -> bool:
        """Apply: an ordinary Object with the masks it has now (Ctrl+Z makes it special again)."""
        o = self.project.get(obj_id)
        if o is None or o.special is None:
            return False
        self.project.set_special(obj_id, None)
        self.sync()
        return True

    def remove_frame(self, obj_id: int) -> None:
        """Remove an Object's mask on the current image only."""
        if self.key is not None:
            self.project.set_frame(obj_id, self.key, None)

    # ------------------------------------------------------------------
    # Object operations
    # ------------------------------------------------------------------

    def delete_objects(self, ids: Iterable[int]) -> List[int]:
        """Delete the Objects that are not locked; returns the ids deleted."""
        gone = self.project.remove_objects(list(ids))
        self.sync()
        return gone

    def set_locked(self, ids: Iterable[int], locked: bool) -> List[int]:
        changed = self.project.set_locked(ids, locked)
        self.sync()
        return changed

    def merge(self, ids: Sequence[int], how: str = "add") -> Optional[int]:
        """``add``: union per image · ``override``: the first id's mask wins where both have one."""
        new = self.project.merge(ids, how=how)
        self.sync()
        return new

    def duplicate(self, ids: Iterable[int], all_frames: bool = False) -> List[int]:
        """Copy Objects: only their mask on the current image, or (*all_frames*) every linked mask."""
        if not all_frames and self.key is None:
            return []
        new = self.project.duplicate(ids, None if all_frames else self.key)
        self.sync()
        return new

    def copy_into(self, src: int, dst: int, replace: bool, all_frames: bool = False, move: bool = False) -> List[str]:
        """Copy (*move*: move) Object *src* into *dst* (Replace or Add) on the current image,
        or on all of *src*'s images."""
        if not all_frames and self.key is None:
            return []
        changed = self.project.copy_into(src, dst, replace, None if all_frames else [self.key], move=move)
        self.sync()
        return changed

    @property
    def can_undo(self) -> bool:
        return self.project.can_undo or self._ui_step_undo()

    @property
    def can_redo(self) -> bool:
        return self.project.can_redo or self._ui_step_redo()

    def _ui_step_undo(self) -> bool:
        """The next undo is a region / pick change (made after the project's current state)."""
        return bool(self._ui_undo) and self._ui_undo[-1][0] == self.project.undo_depth

    def _ui_step_redo(self) -> bool:
        top = self._ui_redo[-1] if self._ui_redo else None
        return top is not None and top[0] == self.project.undo_depth and top[1] == self.project.actions

    def undo(self) -> bool:
        if self._ui_step_undo():
            depth, kind, before = self._ui_undo.pop()
            attr = self.UI_STATE[kind]
            self._ui_redo.append((depth, self.project.actions, kind, getattr(self, attr)))
            setattr(self, attr, before)
            return True
        ok = self.project.undo()
        self.sync()
        return ok

    def redo(self) -> bool:
        if self._ui_step_redo():
            depth, _, kind, after = self._ui_redo.pop()
            attr = self.UI_STATE[kind]
            self._ui_undo.append((depth, kind, getattr(self, attr)))
            setattr(self, attr, after)
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

    def add_checked_detections(self, how: str = "each") -> List[int]:
        """Turn the checked Detections into Objects (one undo step) and close the Detection list.

        ``each``: one Object per candidate · ``merged``: all of them as one Object
        (named after the first label) · ``per_label``: one Object per prompt.
        """
        if self.key is None:
            return []
        chosen = [d for d, c in zip(self.detections, self.detection_checked, strict=True) if c]
        if not chosen:
            return []
        if how == "each":
            ids = self.project.add_detections(self.key, chosen)
        else:
            groups: Dict[str, List[Detection]] = {}
            for d in chosen:
                groups.setdefault(chosen[0].label if how == "merged" else d.label, []).append(d)
            frames = {
                label: {self.key: FrameState.from_mask(union(d.mask for d in dets), score=max(d.score for d in dets))}
                for label, dets in groups.items()
            }
            ids = self.project.add_label_objects(frames, Source.SAM3_DETECTION)
        self.clear_detections()
        return ids

    def detection_at(self, x: float, y: float) -> Optional[int]:
        """The candidate under (x, y): the smallest one there, when several overlap."""
        xi, yi = int(x), int(y)
        best, best_area = None, None
        for i, d in enumerate(self.detections):
            if 0 <= yi < d.mask.shape[0] and 0 <= xi < d.mask.shape[1] and d.mask[yi, xi]:
                area = int(d.mask.sum())
                if best_area is None or area < best_area:
                    best, best_area = i, area
        return best

    def check_detections(self, indices: Iterable[int], op) -> bool:
        """Check (``add`` / True), uncheck (``remove`` / False) or ``toggle`` candidates.

        True when anything changed.
        """
        changed = False
        for i in indices:
            if not 0 <= i < len(self.detection_checked):
                continue
            old = self.detection_checked[i]
            new = (not old) if op == "toggle" else op in (True, "add")
            if new != old:
                self.detection_checked[i] = new
                changed = True
        return changed

    def detections_in_box(self, box: Box) -> List[int]:
        """Candidates the drag box touches at all (any pixel of the mask inside *box*)."""
        x0, y0, x1, y1 = box
        x0, x1 = sorted((int(x0), int(x1)))
        y0, y1 = sorted((int(y0), int(y1)))
        out = []
        for i, d in enumerate(self.detections):
            if d.mask[max(0, y0) : y1 + 1, max(0, x0) : x1 + 1].any():
                out.append(i)
        return out

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

    def plan(self, start: int, end: int, direction: Direction, reference: Optional[int] = None) -> PropagationPlan:
        ref = self.index if reference is None else reference
        return PropagationPlan(start=start, end=end, current=ref, direction=direction)

    def seeds(self, index: Optional[int] = None, ids: Optional[Iterable[int]] = None) -> Dict[int, np.ndarray]:
        """Masks on the reference image (default: the current one) of the checked Objects
        (or of *ids*, whatever their check box)."""
        key = self.keys[index] if index is not None and 0 <= index < len(self.keys) else self.key
        wanted = set(ids) if ids is not None else None
        out = {}
        for o in self.project.objects:
            use = o.id in wanted if wanted is not None else o.included
            m = o.mask(key) if (use and key and o.special is None) else None  # special: made, not propagated
            if m is not None and m.any():
                out[o.id] = m
        return out

    def overwrite_targets(self, plan: PropagationPlan, obj_ids: Iterable[int]) -> List[str]:
        """Target images where one of *obj_ids* already has a mask (confirm before overwriting)."""
        frames = {oid: self.project.get(oid).frames for oid in obj_ids if self.project.get(oid)}
        return existing_targets(frames, self.keys, plan)

    def apply_propagation(
        self, results: Dict[int, Dict[int, np.ndarray]], reference: Dict[int, np.ndarray],
        origin: Optional[Tuple[int, PropagationPlan]] = None,
        scores: Optional[Dict[int, Dict[int, float]]] = None,
    ) -> Dict[int, FrameStatus]:
        """Store propagated masks (``{index: {obj_id: mask}}``) as one undo step.

        *origin*: (run number, the run's first plan): each frame records where it came from (p152).
        *scores*: ``{index: {obj_id: SAM2 object score}}``, kept as the frame's score; a low one warns (p153).
        Returns each frame's worst status (FAILED > WARNING > PROPAGATED).
        """
        where = origins(origin[1], origin[0], self.keys) if origin is not None else {}
        rank = {FrameStatus.PROPAGATED: 0, FrameStatus.WARNING: 1, FrameStatus.FAILED: 2}
        ref_area = {oid: int(m.sum()) for oid, m in reference.items()}
        updates: Dict[int, Dict[str, FrameState]] = {}
        per_frame: Dict[int, FrameStatus] = {}
        for idx, by_obj in results.items():
            key = self.keys[idx]
            worst = FrameStatus.PROPAGATED
            for oid, m in by_obj.items():
                sc = (scores or {}).get(idx, {}).get(oid)
                st = grade(m, ref_area.get(oid, 0), sc)
                updates.setdefault(oid, {})[key] = FrameState.from_mask(
                    m, score=1.0 if sc is None else sc, status=st, origin=where.get(idx))
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

    def export(self, options: ExportOptions, progress: Optional[Callable[[int, int], None]] = None,
               keys: Optional[List[str]] = None) -> List[Path]:
        """Write the masks (*keys*: only those images, e.g. the ones a new dataset keeps)."""
        assert self.image_dir is not None
        return export_final_masks(self.project, self.image_dir, self.original_size, options, keys=keys,
                                  progress=progress, finished=self.finished_sky_full)


def _read_gray(path: Path) -> Optional[np.ndarray]:
    import cv2

    if not path.is_file():
        return None
    data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) if data.size else None


def _write_mask(path: Path, mask: np.ndarray) -> None:
    """A bool mask as a PNG, written whole or not at all."""
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", mask.astype(np.uint8) * 255)
    tmp = path.with_name(path.name + ".tmp")
    buf.tofile(str(tmp))
    tmp.replace(path)
