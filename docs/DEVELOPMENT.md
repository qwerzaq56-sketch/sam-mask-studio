# SAM Mask Studio — development notes

Custom masking tool built on top of `catfield123/sam-mask-gui` (history kept, MIT).
Goal: one workspace where **SAM3 finds, SAM2 cuts/refines**, and the user thinks only in:

- **Detection** — a SAM3 text-prompt candidate (not yet an Object)
- **Object** — an independent segmentation target the user works on
- **Variant** — one of an Object's mask candidates on an image (one selected per Object)
- **Final Mask** — union of the *included* (checked) Objects

Flow: find → select → refine → combine → save.

## Specs (source of truth)

The original planning documents are in `docs/specs/` and win over anything here:

- [`01-gui-ux.md`](specs/01-gui-ux.md) — concepts, layout, Object creation, Edit, Variants, Final Mask, ERP (later)
- [`02-propagation.md`](specs/02-propagation.md) — Current = reference, Start/End = bounds, directions, progress, ✓⚠✕★
- [`03-object-management.md`](specs/03-object-management.md) — rename, duplicate, merge, delete, Object × Propagation

### Where each spec item lives

| Spec | Implementation |
|---|---|
| 01 §5 layout: toolbar Open/Save/Undo/Redo/Export/ERP · Objects · Canvas · Properties · Prompt/Detection/Status/Logs | `app/main_window.py` (ERP action present but disabled — later) |
| 01 §6 Objects only via SAM3 Detection or **+ New Object from Points**; plain clicks never create | `Session.click` (IDLE → no-op), `start_new_object` |
| 01 §7 row: ☑ name [Edit] [×], Variant ●/○ rows under the Object; 03 §3 [···] + "Selected Objects: Merge/Duplicate/Delete" | `app/objects_panel.py` (both [×] and [···]) |
| 01 §8 one Object in Edit; left/right = +/− point; select a point, Delete removes it; Clear Points; Finish Editing; Ctrl+Z/Y | `Session.edit/click/select_point/delete_point/clear_points`, canvas hit-test, Properties point list |
| 01 §8.1 Positive / Negative point lists | `app/properties_panel.py` (grouped, numbered in placement order) |
| 01 §9 one Variant per Object, many Objects checked | Variant rows (Objects panel) and thumbnails (Properties) → `Session.select_variant(i, obj_id)` |
| 01 §10 over-detection left unchecked | Detection checkboxes → `add_checked_detections` |
| 01 §11 SAM3 Object refined by SAM2 | `predict(points, box, seed_mask=base_mask)` |
| 01 §12 Preview Final Mask / Export | toolbar `F` (+ hold Alt), Export dialog |
| 01 §15 Image → DetectionResults | Detections kept per image in `Session` (restored on navigating back; not persisted) |
| 02 §3 Current must be within Start~End; §8 Current never re-processed | `PropagationPlan`, `MainWindow.propagate` |
| 02 §6–7 only checked Objects, from their selected Variant | `Session.seeds()` |
| 02 §11 confirm overwrite, list the images | `Session.overwrite_targets` + dialog "Overwrite existing propagated masks?" |
| 02 §12 per-direction progress with the frame chain, per-Object status, "Current: …" | `app/propagation_panel.py` |
| 02 §13 ✓ ⚠ ✕ ★ per frame, click to navigate | frame list in the panel + marks in the image list |
| 03 §8–9 Merge = per-frame union, new confirmed Object, no Variant combinations | `Project.merge` |
| 03 §10 Duplicate copies masks/points/variants/selected/frames | `Project.duplicate` |
| 03 §12 `Delete "name"?` confirm, frame masks removed | `MainWindow.delete_objects` |

### Interpretations (where the specs leave room)

- **Merge / Duplicate / Delete act on row selection**, not on the include checkboxes, so choosing
  what goes into the Final Mask never doubles as choosing what to merge (03 §14 keeps them distinct).
- **Brush** (upstream feature, not in the specs) is kept for the Object in Edit: the painted mask
  becomes the frame's base mask and its points are cleared, so what you see is what was painted.
- **"Propagate Selected Objects"** propagates the *checked* Objects, as 02 §6 describes.
- 02 §12 shows Objects progressing one after another; SAM2's video predictor tracks all Objects in
  one pass, so every Object's percentage advances together.
- ⚠ is an area-jump heuristic (`WARN_AREA_RATIO`); automatic quality scoring is "later" in 02 §14.
- 01 §16 lists project save/restore and propagation as "later"; both are implemented already.

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
| Threads | SAM2 clicks run on the UI thread (fast once the embedding exists); model loading, SAM3 detect, export and propagation run in `QThread`s. `InferenceEngine.lock` serialises GPU use. While a long job runs, navigation and editing are disabled. |
| Settings | `config.local.json` (git-ignored): checkpoint paths, working max side, last folder, autosave delay. |
| Windows | Unicode paths: read/write images via `np.fromfile` + `cv2.imdecode` / `imencode().tofile`. |

## Module map

```
src/core/project.py      Project, MaskObject, FrameState, Variant, Point, Detection, undo/redo   (Qt-free)
src/core/propagation.py  PropagationPlan (Start/End/Current/Direction), grade(), existing_targets()
src/core/storage.py      ProjectStore (autosave/load sidecar), export_final_masks(), ExportOptions
src/engine/imageio.py    find_images, read_rgb (Unicode-safe), working_size/to_working, resize_mask
src/engine/inference.py  InferenceEngine: load_sam2/load_sam3, set_image, predict(points, box, seed), detect(text)
src/engine/video.py      propagate(ckpt, paths, plan, seeds, max_side, …) -> yields (index, {obj_id: mask})
src/app/session.py       Session: folder, current image, mode IDLE/NEW/EDIT, prompts, detections, propagation apply (Qt-free)
src/app/canvas.py        Canvas widget: overlays, points, box, brush, zoom/pan, Final Mask preview
src/app/*_panel.py       Objects, Properties, Detection, Propagation, Images panels
src/app/main_window.py   wiring, toolbar, shortcuts, autosave, workers (workers.py), dialogs.py, settings.py
src/main.py, run.bat     entry points
src/sam2/, src/sam3/     upstream model wrappers (reused); src/models/predictor_base.py their base class
src/utils/               upstream decord/triton import stubs + package checks (reused)
```

The upstream GUI (`src/gui`, `src/services`, upstream data models, the symlink-based
`src/sam2/video_predictor.py`) has been removed.

Qt note: panel signals that make the window rebuild the emitting list/tree are emitted on the
next event-loop turn (`objects_panel.later`); rebuilding inside the widget's own signal crashes Qt.

## Status

Done (cloud, CPU): data model, storage, propagation planning, engine code, the full GUI in
`src/app/`, entry points, README. Tests: `tests/unit` (model/storage/plan + upstream stubs) and
`tests/app` (Session rules and offscreen GUI flows with `tests/fakes.py`), all passing.

Verified locally (Windows 10, RTX 2060 Super 8 GB, torch 2.14 cu130, SAM2.1 tiny + SAM3), on a
20-frame 600×364 sequence in a Korean-named folder:

- Engine: SAM2 point → 3 Variants in 0.18 s, box and seed-mask + negative point OK; SAM3 load
  17 s, first detect 1.7 s then 0.2 s; propagation of 19 frames (both directions) 7.3 s, Current
  skipped, targets exact; peak VRAM 4.5 GB with SAM2 image + SAM3 + SAM2 video predictor.
- Real app driven with mouse events (offscreen Qt, real models): SAM3 detect → keep one →
  Object → SAM2 refine; New Object from Points → Variant choice → select a point and delete it;
  rename (Korean) / duplicate / delete with confirm; propagate Both → ★ untouched, every frame
  filled, ⚠/✕ where the object leaves the view; fix frame 15 → Forward re-propagate with the
  overwrite prompt, earlier frames untouched; merge; Final preview; COLMAP-named inverted export
  (20 files); close and reopen restores Objects and frames. `run.bat` launches the window.

### Remaining work

1. A hands-on walkthrough by the user on the real window (feel of the canvas, panel layout).
2. Later per specs: ERP / 360° input, keyframes, quality graph, Object split/groups.

## Running

Local Windows env (not in git): `.venv` (Python 3.12.10, torch 2.14 cu130),
`.tools/env.ps1`, checkpoints in `checkpoints/sam2/sam2.1_hiera_tiny.pt` and
`checkpoints/sam3/sam3.pt`.

```bash
python -m pytest tests -q          # GUI tests set QT_QPA_PLATFORM=offscreen themselves
python -m src.main [folder]        # or run.bat on Windows
```

Cloud / CPU-only sessions can run all `tests/unit` and offscreen GUI tests with a fake
engine; they cannot run SAM2/SAM3 (no GPU, SAM3 weights are gated).
