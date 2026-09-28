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
| 01 §12 Preview Final Mask / Export | toolbar `X` (toggle) / hold Z; editing works in it; Export dialog |
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

### v0.2.0 (user requests after v0.1.0)

- **Edit layer** (`FrameState.edit`, `core/refine.py`): brush strokes and *Fill Holes / Remove
  Specks* are stored as add/sub pixels on top of the point/prompt mask. *Delete Layer* returns
  to the prompt mask; *Apply Layer* makes the edited mask the base mask (points cleared, new
  points refine from it). Saved as `<key>.add.png` / `<key>.sub.png` beside the main PNG.
- **Brush** (B): drag = add, Ctrl+drag = subtract (wheel/size: see v0.3); clicks add
  no points while it is on. Shift+drag still works as a quick brush.
- **Comma-separated prompts** (`core/prompts.py`): `person, car, tripod` is detected label by
  label; the Detection list is a tree grouped per label.
- **Batch masking** (`engine/batch.py`): all images / Start~End / images selected in the
  Images list → one Object per label, each image = union of that label's detections above a
  score threshold; one undo step; cancellable; per-image results clickable.
- **First Object from a plain click** while the project has no Objects (`Session.effective_mode`).
- A 360° (ERP) mode was tried and removed at the user's request (seam artefacts); the code is
  kept at tag `erp-experiment`.

### v0.3 (user requests after v0.2.0), built in phases

Each phase is a branch merged into `dev` with `--no-ff` and tagged `v0.3-pN`; each change
is one commit, so a phase (`git revert -m 1 <merge>`) or a single change can be undone.
The user's request list is `docs/specs/04-v0.3-requests.md`.

**P1 — responsiveness and small UX fixes** (`v0.3-p1`)
- Checking a detection candidate was slow: every checkbox change (and the tristate
  parent's) ran a full window refresh — N+1 refreshes for a label row. Now one coalesced
  signal that redraws only the candidate overlays (~0.8 s → ~0.02 s for 8 candidates).
- Canvas overlays are three cached images (Objects / edited mask / candidates), blended
  within each mask's bounding box; a change re-blends only its group.
- Outlines are vector polygons with a cosmetic pen: one white line, width and on/off in the
  toolbar (Outline, O). The edit layer's green/red tints are opt-in (Edit Changes).
- Objects panel updates rows in place; rebuilding it on selection deleted the row buttons
  between press and release, so a button on an unselected row needed two clicks.
- Wheel = zoom always; Ctrl+wheel (or Shift+wheel) = brush size in Edit.
- Batch masking / propagation: **Stop** keeps what is done, **Cancel** discards the run.
  Batch checks for a stop before each label.
- Autosave (and the save on image change) writes PNGs in a background thread: the first save
  after a batch/propagation used to block the window for seconds.

**P2 — edit layer tools** (`v0.3-p2`)
- Fill Holes and Remove Specks are separate buttons (shared max-area box).
- **Object Fill** (`core/refine.grow_to_edges`): grows the mask outward, at most N px, to where
  the object's colors end — GrabCut on a crop, mask = sure FG, an N-px band = probably BG,
  beyond = sure BG; only growth touching the mask is kept, never shrinks. No SAM run.
- **Paint Region** (replaced by Region Box in P2.1): a painted region the three tools act in
  (`refine.within`); without one they act on the whole mask. The region is UI state (`Session.region`): not saved, not undone,
  cleared when leaving Edit or changing image.

**P2.1 — feedback on P2** (`v0.3-p2.1`)
- Merge names the result after the first Object selected (the panel keeps selection order).
- Properties: Mask / Edit Layer tabs, each scrollable; the how-to shows only with nothing selected.
- Object Fill sensitivity (0-100): band pixels join when log p(object color) − log p(background
  color) from GrabCut's learned GMMs exceeds (50 − s)/8, smoothed and kept connected. Real
  photo check (mask eroded 10 px): s 20/50/80 → 78/93/96 % recovered, 1.6/3.6/9 % spill.
- **Tool brushes** (what the user meant by "paint versions"; P2.2: area on drag, run on release): Paint / Fill Holes / Remove
  Specks / Object Fill. A tool stroke shows the tool's full-mask result (computed at the press,
  `Session.tool_result`) only where the stroke passes, live; release commits it to the layer.
- Paint Region → **Region Box**: drag boxes to set the region (Ctrl+drag removes a box); the
  "Apply at once" buttons act inside it, or on the whole mask without one.

**P2.2 / P2.3 — brush feel** (`v0.3-p2.2`, `v0.3-p2.3`)
- Tool brushes no longer compute at the press or preview live: the drag shows the area
  (yellow) and the tool runs once inside it on release.
- Subtract is Alt+drag (was Ctrl); Region Box removes with Alt+drag (Ctrl still works).
- Final Mask preview: `X`, a toggle (Alt-hold peek removed). The brush circle, points, region
  and a live stroke are drawn over it and editing keeps working.
- **Restore** brush with a mode box: remove what the edit layer added / bring back what it
  removed / both (= the prompt mask) inside the brushed area.
- Toolbar: separator after Outline + width.

**P2.6 — auto tools without a confirm step** (`v0.3-p2.6`)
- Edit Layer tab: **Brush** (Add / Subtract, Restore + Add/Subtract/Both) acts as you paint;
  **Auto tools** (Object Fill, Fill Holes, Remove Specks) share a Mode (Brush | Fill) and the
  Region; a Settings box shows only the selected auto tool's parameters (Sensitivity is a slider).
- Picking an auto tool computes its result at once (Object Fill in a Task; stale results are
  dropped by a generation counter; results are cached per tool/settings/base mask).
- **Fill** writes the result into the mask right away (inside the region). Moving a setting or
  the region *amends that same undo step* (`Project.amend_frame`) as long as nothing else
  changed since (`Session._fill_live`: same Object/image/tool, `project.actions` and
  `undo_depth` unchanged), so there is nothing to confirm and Ctrl+Z removes the whole Fill.
  Changes since entering the tool are tinted green/red.
- **Brush** shows the result as a gray guide; strokes paint it in (inside the region).
- Leaving the tool, switching tools or Esc only drops the tint/guide.
- The Apply-at-once buttons are gone (Fill mode replaces them).

**P2.7 — tool exit as first proposed** (`v0.3-p2.7`; replaces P2.6's write-at-once Fill)
- One result per auto tool (`Session._result`), shown two ways: Fill = magenta/purple preview,
  Brush = gray guide. Switching Brush <-> Fill keeps the same area; nothing is written by it.
- A Fill preview is written in (one undo step) when the tool closes: clicking it again,
  another tool, Finish Editing, another Object / image, New Object. **Esc** drops the preview
  and leaves the tool; with no tool on, Esc finishes editing.
- Brush strokes write immediately; the guide keeps fitting the painted mask. If the mask
  changes otherwise (undo, a SAM2 click) the result is recomputed. `Project.amend_frame` gone.

**P2.8 — live brushes, Fill / Paint modes** (`v0.3-p2.8`)
- Brush group: **Paint** (was Add / Subtract; Alt+drag subtracts) and **Restore** are live
  while dragging (Restore's result comes from `Canvas.tool_target_fn` at the press).
- Auto tools in one row. Mode **Fill** (default) takes the whole result; **Paint** picks parts:
  a drag shows its area (yellow), release picks it (magenta / purple), Alt+drag unpicks (back to
  gray). Nothing is written until the tool closes (`Session.close_auto`, one undo step); the
  picks survive mode switches and setting changes. The selected mode button is highlighted and
  a line under it says what the mode does.
- Final Mask preview: `Z` toggles; holding **Space** peeks (an app-wide event filter, ignored
  in text boxes). Space+drag no longer pans (middle-drag does).

**P2.9 — sliders, Grow / Shrink, pick all** (`v0.3-p2.9`)
- Auto tool settings are `SliderField`s (slider + number box; log scale for sizes). Fill Holes
  and Remove Specks have separate max sizes; `Session.AUTO_PARAMS` lists what each tool uses, so
  an unrelated setting never invalidates a cached result.
- New auto tools **Grow** / **Shrink** (distance-transform dilation / erosion; the image border
  is not an edge) sharing one Amount.
- Paint mode: **A** picks the whole result, A again drops every pick (otherwise A = previous image).
- Mode buttons show the selection by color only; the brush circle is green over the Final Mask.

**P2.10 — keys and help** (`v0.3-p2.10`)
- Final Mask: hold **Z** to peek, **X** toggles (app-wide event filter; Ctrl+Z untouched).
  Space+drag pans again.
- The wheel over sliders / number boxes is forwarded to their parent (the panel scrolls, the
  value stays).
- Help > Keyboard Shortcuts (F1) lists `dialogs.SHORTCUTS`.
- Auto tools: an **Apply** button under Region writes the result in and leaves the tool; the
  Alt (unpick) stroke area is red.

Progress summary for the user (Korean): `docs/PROGRESS_v0.3.md`.

**P2.11 — click again = apply once more** (`v0.3-p2.11`)
- An auto tool's button is not a toggle: clicking the active one writes its result in
  (`Session.apply_auto`, one undo step), keeps the tool and recomputes, so N clicks apply N times.
- Leaving by another tool / Finish / another image / Apply writes the result in (Fill: all,
  Paint: the picks); only Esc drops it.

**P2.12 — undoable picks** (`v0.3-p2.12`)
- Region and Paint-mode picks share one UI undo history (`Session._ui_undo/_ui_redo`, entries keyed
  by the project's `undo_depth`). Pick history is dropped when the picks are applied or the tool
  changes, so Ctrl+Z then undoes the application itself.

**P2.13 — navigation, points, explicit apply** (`v0.3-p2.13`)
- Up / Down step through the Objects with a mask on this image (Edit follows); image changes are
  blocked while editing; a viewport click on empty space keeps the selection, the Objects panel's
  empty space clears it.
- Points: drag = move (SAM2 re-runs on release), double-click = delete.
- Auto tools: applying is explicit — the active mode button again or Enter (apply + recompute),
  or Apply & Close. Every other way out drops the result; the tool button again does nothing.
  A in Fill mode enters Paint mode with everything picked. Auto previews use their own styles
  (`auto_add` / `auto_sub`) drawn over the Edit Changes tints.

**P2.14** (`v0.3-p2.14`): Apply & Recompute / Apply & Close row under the mode buttons; Restore
strokes keep the Edit Changes tints (trimmed live); the Paint-mode guide is dark gray, alpha 210;
Paint brush shortcut B -> D.
Then: the mode buttons only switch modes; Apply & Recompute (or Enter) is the only apply-and-stay.

**P3 — detections** (`v0.3-p3`)
- Batch masking moved to its own `Batch` tab (`app/batch_panel.py`) with its own prompt.
- Detection tab: Preview on/off; Add Each / Add as One (merged, first label's name) / Add per Prompt
  (`Session.add_checked_detections(how)`, one undo step).
- Canvas (not in Edit, preview on): Shift+click / drag checks candidates, Ctrl unchecks
  (`Session.detection_at`: smallest mask under the point; `detections_in_box`: ≥ half inside).
- `later()` timers are children of their widget (a deleted widget's signal crashed the test run).

**P4 — Objects list** (`v0.3-p4`): the data model is unchanged (an Object spans every image, per
spec 03). The list shows only Objects with a mask on this image (plus the one in Edit); `Show all
Objects` lists every one. A second column shows `🔗 n` for Objects with masks on n > 1 images.

**P3.1** (`v0.3-p3.1`): Select on Image toggle (on after a detection; required for picking; Edit and
New Object are blocked while on): click / drag = add, Shift = toggle, Ctrl = remove; a drag box takes
every candidate it touches; unchecked candidates keep their outline. The v0.2 "first click creates
the first Object" rule is gone (`Session.effective_mode` == `mode`).

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
