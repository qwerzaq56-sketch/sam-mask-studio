# SAM Mask Studio — development notes

Custom masking tool built on top of `catfield123/sam-mask-gui` (history kept, MIT).
Goal: one workspace where **SAM3 finds, SAM2 cuts/refines**, and the user thinks only in:

- **Detection** — a SAM3 text-prompt candidate (not yet an Object)
- **Object** — an independent segmentation target the user works on
- **Variant** — one of an Object's mask candidates on an image (one selected per Object)
- **Final Mask** — union of the *included* (checked) Objects

Flow: find → select → refine → combine → save.

## Spec summary (from the three planning docs)

### GUI / UX
- Layout: toolbar (Open, Save, Undo, Redo, Export, [ERP later]) · left **Objects** ·
  center canvas · right **Properties** (selected Object, Variants, Points) ·
  bottom **Prompt / Detection / Status / Logs**.
- Objects are created **only** two ways:
  1. SAM3 text prompt → Detection list with checkboxes → **Add Selected as Objects**
     (over-detections such as "person on a sign" are simply left unchecked).
  2. **+ New Object from Points** (explicit mode), then click / drag a box on the canvas → SAM2.
- A plain canvas click must never silently create an Object.
- Per Object: **checkbox = include in Final Mask**, **[Edit] = the one Object being edited**,
  **[×]/[···] = delete/rename/duplicate**. Only one Object is in Edit at a time.
- Edit mode: left click = positive point, right click = negative point, click a point to
  select it, **Delete removes the selected point** (not only undo), Clear Points,
  Finish Editing, Ctrl+Z / Ctrl+Y.
- SAM3-created Objects can be refined with SAM2 points (SAM3 mask used as the SAM2 prior).
- Variants: pick one per Object; Objects: many may be checked.
- Final Mask: Preview + PNG Export.
- ERP / 360°: later. Internals would project to perspective views and merge back;
  the Object model and UX stay identical.

### Object management
- Rename, Duplicate (copies masks, points, variants, frame masks; independent afterwards),
  Delete (with confirm; removes its frame masks), **Merge** (union per frame over every
  frame where any member has a mask → a new confirmed Object; members removed; no
  variant combinations in MVP; can be edited/propagated afterwards).
- Merge ≠ Final Mask selection: merge fuses Objects permanently, checkboxes only include.

### Propagation
- **Current image = reference**; Start/End only **bound** the range; Current must be inside.
- Direction Both / Forward (Current→End) / Backward (Current→Start); Current is never
  re-processed or overwritten.
- Only checked Objects propagate, each from its **currently selected Variant** on Current.
- Confirm before overwriting frames that already have masks (list them).
- Progress (per direction), per-frame status ✓ ok / ⚠ warning / ✕ failed / ★ reference,
  clicking a frame navigates to it. Fix a frame, make it Current, propagate again.

## Design decisions

| Topic | Decision |
|---|---|
| Coordinates | Everything (canvas, prompts, masks) is in **working resolution** (longer side ≤ `max_side`, default 1024). Only export upsamples to the original size. |
| Mask arrays | `bool`, **read-only / immutable** (`core.project.freeze`). Edits build new arrays and new `FrameState`s. Undo snapshots are therefore shallow reference tuples — cheap even after propagating hundreds of frames. Never mutate a mask in place. |
| Undo | `Project` records one snapshot per mutating call (add, merge, propagate result, variant select, …). Global, not per image. |
| SAM2 refinement | Recomputed from the frame's full prompt set every time: `predict(points, box, seed=base_mask)`. Deleting any point just re-runs. `base_mask` = SAM3 detection / propagated / merged / brushed mask. |
| SAM3 | Text → Detections only (point prompts on SAM3 stay off; SAM2 does refinement). Loaded lazily. SAM2 tiny + SAM3 together use ~4 GB VRAM. |
| Persistence | Sidecar **beside** the image folder: `<dir>.sms/project.json` + `objects/<id>/<image name>.png` (current mask per frame, working res). Not inside the image folder because COLMAP/3DGS loaders scan it recursively. Autosave writes only masks whose array identity changed. Variants other than the selected one are not persisted (reload = selected mask as the only Variant). |
| Export | `<dir>_masks/` by default; `{stem}.png` or COLMAP-style `{name}.png`; optional invert (object black / keep white); optional empty masks for images without Objects. |
| Propagation engine | SAM2 video predictor over the plan's window only. SAM2 reads a folder of numbered JPEGs, so frames are written there at working resolution (**copies, not symlinks** — symlinks need admin/Developer Mode on Windows; the upstream app's propagation used `os.symlink` and fails there). All Objects propagate in one pass. |
| Bulk Object ops | Merge / Duplicate / Delete act on **row selection** (Ctrl/Shift-click rows) so they don't conflict with the include checkboxes. |
| Windows | Unicode paths: read/write images via `np.fromfile` + `cv2.imdecode` / `imencode().tofile`. |

## Module map

```
src/core/project.py      Project, MaskObject, FrameState, Variant, Point, Detection, undo/redo   (Qt-free)
src/core/propagation.py  PropagationPlan (Start/End/Current/Direction), grade(), existing_targets()
src/core/storage.py      ProjectStore (autosave/load sidecar), export_final_masks(), ExportOptions
src/engine/imageio.py    find_images, read_rgb (Unicode-safe), working_size/to_working, resize_mask
src/engine/inference.py  InferenceEngine: load_sam2/load_sam3, set_image, predict(points, box, seed), detect(text)
src/engine/video.py      propagate(ckpt, paths, plan, seeds, max_side, …) -> yields (index, {obj_id: mask})
src/sam2/, src/sam3/     upstream model wrappers (reused)
src/utils/               upstream decord/triton import stubs + package checks (reused)
```

Upstream GUI code (`src/gui/**`, `src/models/image_state.py`, `session_models.py`,
`src/services/mask_service.py`, controllers) is superseded and should be deleted once the
new GUI replaces `src/main.py`.

## Status

Done (tests: `tests/unit/test_project.py`, `tests/unit/test_storage_and_plan.py`, 14 passing):
data model incl. merge/duplicate/undo, storage roundtrip + incremental save + export,
propagation planning and grading, inference + video engine code.

Not yet verified on GPU: `InferenceEngine.predict/detect`, `engine.video.propagate`.

### Remaining work (in order)

1. **GUI package `src/app/`** replacing `src/gui/`:
   - `canvas.py` (from upstream `gui/widgets/image_viewer`, reuse `CoordinateMapper`,
     `BrushEngine`): modes IDLE / NEW_OBJECT / EDIT; per-Object colored overlays
     (editing Object stronger + outline, unchecked hidden or faint); Detection candidate
     overlays while the Detection list is open; point hit-test + selected-point ring;
     box drag (NEW and EDIT); Shift brush on the editing Object; Final Mask preview
     (toggle + hold Alt); zoom/pan as upstream.
   - `objects_panel.py` (checkbox, color, name w/ double-click rename, [Edit], [···] menu,
     row multi-select, + New Object from Points, Merge/Duplicate/Delete).
   - `properties_panel.py` (Variants with thumbnail+score radio, positive/negative point
     list with select/delete, Clear Points, Finish Editing).
   - `detection_panel.py` (prompt field, Detect, checkable results with score, select
     all/none, Add Selected as Objects).
   - `propagation_panel.py` (Start/End combos, Current label, direction radios,
     Propagate Selected Objects, overwrite confirm, progress, per-frame status list →
     click to navigate, Cancel).
   - image list (left, below Objects) with a marker for images that have masks.
   - `main_window.py`: toolbar, shortcuts (Ctrl+Z/Y, Delete, Esc, N, E, ←/→, Ctrl+S,
     Ctrl+E, F), autosave (debounced QTimer + on image change/close), export dialog,
     model loading and SAM3 detect / propagation in `QThread` workers, status bar mode text.
   - `src/main.py` entry point; `run.bat`.
2. Headless GUI tests with a fake engine (`QT_QPA_PLATFORM=offscreen`).
3. Delete superseded upstream GUI modules and their tests; README for the new tool.
4. **Local only (needs the RTX 2060S + gated SAM3 weights):** GPU smoke tests of the
   engine, full GUI walkthrough on Windows.

## Running

Local Windows env (not in git): `.venv` (Python 3.12.10, torch 2.14 cu130),
`.tools/env.ps1`, checkpoints in `checkpoints/sam2/sam2.1_hiera_tiny.pt` and
`checkpoints/sam3/sam3.pt`.

```bash
python -m pytest tests/unit -q
```

Cloud / CPU-only sessions can run all `tests/unit` and offscreen GUI tests with a fake
engine; they cannot run SAM2/SAM3 (no GPU, SAM3 weights are gated).
