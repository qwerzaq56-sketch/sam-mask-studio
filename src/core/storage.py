"""Autosave / load of a Project next to the image folder, and Final Mask export.

Layout, for an image folder ``D:/data/images``::

    D:/data/images.sms/project.json          objects, names, prompts, statuses
    D:/data/images.sms/objects/<id>/<image file name>.png
                                             each Object's current mask (working res)
    D:/data/images_masks/<stem>.png          exported Final Masks (original res)

The sidecar sits *beside* the image folder, not inside it, because COLMAP and
most 3DGS loaders scan the image folder recursively and would pick the PNGs up
as images.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.engine.imageio import key_stem, read_rgb
from src.core.sky_edges import sky_edges
from src.core.special import LABELS, SKY, Special
from src.core.project import (EditLayer, FrameState, FrameStatus, MaskBar, MaskObject, Point, Project, PromptLayer,
                              Source, Variant, freeze, union)

FORMAT_VERSION = 1


def sidecar_dir(image_dir: Path) -> Path:
    """``<folder>.sms`` beside the image folder; for a COLMAP scene's ``images/``, beside the
    scene (``<scene>.sms``) so trainers reading the scene never see it. A project already
    saved at the old place (inside the scene) keeps being used."""
    old = image_dir.parent / f"{image_dir.name}.sms"
    root = scene_root(image_dir)
    if root is None or root == image_dir:
        return old
    new = root.parent / f"{root.name}.sms"
    return old if old.is_dir() and not new.exists() else new


def scene_root(image_dir: Path):
    from src.core.colmap import scene_root as find  # late: colmap imports imageio only

    return find(image_dir)


def default_export_dir(image_dir: Path) -> Path:
    return image_dir.parent / f"{image_dir.name}_masks"


def _write_png(path: Path, mask: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", mask.astype(np.uint8) * 255 if mask.dtype == np.bool_ else mask)
    if not ok:
        raise IOError(f"PNG encode failed for {path}")
    buf.tofile(str(path))  # tofile handles non-ASCII Windows paths; cv2.imwrite does not


def _read_png(path: Path) -> Optional[np.ndarray]:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


@dataclass
class SaveJob:
    """The file work of one save, prepared on the UI thread and safe to run on another.

    Masks are immutable arrays, so the job can hold references to them while the
    user keeps editing.
    """

    writes: List[Tuple[Path, np.ndarray]] = field(default_factory=list)
    deletes: List[Path] = field(default_factory=list)
    dirs_to_remove: List[Path] = field(default_factory=list)
    json_path: Optional[Path] = None
    json_text: str = ""
    revision: int = -1
    written_keys: List[Tuple[int, str]] = field(default_factory=list)

    def run(self) -> None:
        for path, m in self.writes:
            _write_png(path, m)
        for p in self.deletes:
            if p.exists():
                p.unlink()
        for d in self.dirs_to_remove:
            shutil.rmtree(d, ignore_errors=True)
        if self.json_path is not None:
            _atomic_write_text(self.json_path, self.json_text)


class ProjectStore:
    """Saves a Project incrementally: only masks whose array changed are rewritten."""

    def __init__(self, image_dir: Path, max_side: int):
        self.image_dir = image_dir
        self.root = sidecar_dir(image_dir)
        self.max_side = max_side
        # (obj_id, key) -> the mask array last written for it. Masks are immutable, so
        # an identity check tells whether it changed. Holding the reference (not id())
        # keeps a freed array's id from being reused by a different mask.
        self._written: Dict[Tuple[int, str], np.ndarray] = {}
        self._saved_revision = -1

    def mask_path(self, obj_id: int, key: str) -> Path:
        return self.root / "objects" / str(obj_id) / f"{key}.png"

    def is_saved(self, project: Project) -> bool:
        """True when *project* has no changes since the last save/load."""
        return project.revision == self._saved_revision

    def exists(self) -> bool:
        return (self.root / "project.json").is_file()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, project: Project, force: bool = False) -> bool:
        """Write changes since the last save. Returns True if anything was written."""
        job = self.prepare(project, force)
        if job is None:
            return False
        try:
            job.run()
        except Exception:
            self.failed(job)
            raise
        return True

    def failed(self, job: SaveJob) -> None:
        """A prepared job did not finish: make the next save write its masks again."""
        for k in job.written_keys:
            self._written.pop(k, None)
        self._saved_revision = -1

    def prepare(self, project: Project, force: bool = False) -> Optional[SaveJob]:
        """Collect what a save must write (None when nothing changed); ``run()`` writes it.

        The store records the job as saved right away, so preparing the next one
        while this runs only picks up later changes.
        """
        if not force and project.revision == self._saved_revision:
            return None
        job = SaveJob(revision=project.revision)
        live: Dict[Tuple[int, str], np.ndarray] = {}
        objects_json = []
        for o in project.objects:
            frames_json = {}
            for key, fs in o.frames.items():
                # The main PNG is the prompt-based mask; an edit layer is stored beside it
                # as <key>.add.png / <key>.sub.png so it can still be deleted after a reload.
                m = fs.prompt_mask
                if m is not None:
                    live[(o.id, key)] = m
                if fs.edit is not None:
                    live[(o.id, key + ".add")] = fs.edit.add
                    live[(o.id, key + ".sub")] = fs.edit.sub
                for n, ly in enumerate(fs.layers, 1):  # point layers: <key>.L1.png ...
                    if ly.mask is not None:
                        live[(o.id, f"{key}.L{n}")] = ly.mask
                sel = fs.variants[min(fs.selected, len(fs.variants) - 1)] if fs.variants else None
                frames_json[key] = {
                    "points": [[p.x, p.y, 1 if p.positive else 0] for p in fs.points],
                    "box": list(fs.box) if fs.box else None,
                    "status": fs.status.value,
                    "score": sel.score if sel else None,
                    "has_mask": m is not None,
                    "edit": fs.edit is not None,
                    "layers": [
                        {"points": [[p.x, p.y, 1 if p.positive else 0] for p in ly.points],
                         "box": list(ly.box) if ly.box else None, "subtract": ly.subtract,
                         "has_mask": ly.mask is not None}
                        for ly in fs.layers
                    ],
                }
            objects_json.append(
                {
                    "id": o.id,
                    "name": o.name,
                    "source": o.source.value,
                    "color": list(o.color),
                    "included": o.included,
                    "locked": o.locked,
                    "special": o.special.to_json() if o.special is not None else None,
                    "frames": frames_json,
                }
            )

        for (oid, key), m in live.items():
            if force or self._written.get((oid, key)) is not m:
                job.writes.append((self.mask_path(oid, key), m))
                job.written_keys.append((oid, key))
                self._written[(oid, key)] = m
        for gone in [k for k in self._written if k not in live]:
            job.deletes.append(self.mask_path(*gone))
            del self._written[gone]
        live_ids = {str(o.id) for o in project.objects}
        obj_root = self.root / "objects"
        if obj_root.is_dir():
            job.dirs_to_remove = [d for d in obj_root.iterdir() if d.is_dir() and d.name not in live_ids]

        doc = {
            "version": FORMAT_VERSION,
            "image_dir": str(self.image_dir),
            "max_side": self.max_side,
            "next_id": project.next_id,
            "label_counts": project.label_counts,
            "mask_sets": {k: list(v) for k, v in project.mask_sets.items()},
            "mask_bars": [{"name": b.name, "ids": None if b.ids is None else list(b.ids), "invert": b.invert,
                           "flipped": list(b.flipped), "on": b.on} for b in project.mask_bars],
            "excluded": sorted(project.excluded),
            "objects": objects_json,
        }
        job.json_path = self.root / "project.json"
        job.json_text = json.dumps(doc, indent=1, ensure_ascii=False)
        self._saved_revision = project.revision
        return job

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, image_keys: List[str]) -> Project:
        """Load the sidecar project (or return an empty one)."""
        project = Project(image_keys)
        if not self.exists():
            return project
        doc = json.loads((self.root / "project.json").read_text(encoding="utf-8"))
        self.max_side = int(doc.get("max_side", self.max_side))
        project.next_id = int(doc.get("next_id", 1))
        project.label_counts = {k: int(v) for k, v in doc.get("label_counts", {}).items()}
        project.mask_sets = {k: tuple(int(i) for i in v) for k, v in doc.get("mask_sets", {}).items()}
        project.mask_bars = tuple(
            MaskBar(str(b.get("name", "")), None if b.get("ids") is None else tuple(int(i) for i in b["ids"]),
                    None if b.get("invert") is None else bool(b["invert"]),
                    tuple(int(i) for i in b.get("flipped", ())), bool(b.get("on", True)))
            for b in doc.get("mask_bars", []))
        project.excluded = frozenset(k for k in doc.get("excluded", []) if k in set(project.image_keys))
        known = set(image_keys)
        for oj in doc.get("objects", []):
            oid = int(oj["id"])
            frames: Dict[str, FrameState] = {}
            for key, fj in oj.get("frames", {}).items():
                if key not in known:
                    continue  # image was removed from the folder
                mask = None
                if fj.get("has_mask"):
                    raw = _read_png(self.mask_path(oid, key))
                    if raw is not None:
                        mask = freeze(raw)
                        self._written[(oid, key)] = mask
                edit = None
                if fj.get("edit"):
                    parts = []
                    for suffix in (".add", ".sub"):
                        raw = _read_png(self.mask_path(oid, key + suffix))
                        parts.append(freeze(raw) if raw is not None else None)
                        if raw is not None:
                            self._written[(oid, key + suffix)] = parts[-1]
                    if all(p is not None for p in parts):
                        edit = EditLayer(parts[0], parts[1])
                points = tuple(Point(float(x), float(y), bool(pos)) for x, y, pos in fj.get("points", []))
                box = tuple(fj["box"]) if fj.get("box") else None
                variants = (Variant(mask, float(fj.get("score") or 1.0)),) if mask is not None else ()
                layers = []
                for n, lj in enumerate(fj.get("layers") or [], 1):
                    lm = None
                    if lj.get("has_mask"):
                        raw = _read_png(self.mask_path(oid, f"{key}.L{n}"))
                        if raw is not None:
                            lm = freeze(raw)
                            self._written[(oid, f"{key}.L{n}")] = lm
                    layers.append(PromptLayer(
                        points=tuple(Point(float(x), float(y), bool(pos)) for x, y, pos in lj.get("points", [])),
                        box=tuple(lj["box"]) if lj.get("box") else None,
                        subtract=bool(lj.get("subtract", False)), mask=lm))
                frames[key] = FrameState(
                    points=points,
                    box=box,
                    base_mask=mask,
                    variants=variants,
                    status=FrameStatus(fj.get("status", "manual")),
                    edit=edit,
                    layers=tuple(layers),
                )
            project.objects.append(
                MaskObject(
                    id=oid,
                    name=oj["name"],
                    source=Source(oj.get("source", Source.SAM2_POINT.value)),
                    color=tuple(oj.get("color", (230, 25, 75))),
                    included=bool(oj.get("included", True)),
                    frames=frames,
                    locked=bool(oj.get("locked", False)),
                    special=Special.from_json(oj.get("special")),
                )
            )
        self._saved_revision = project.revision
        return project


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------


@dataclass
class ExportOptions:
    out_dir: Path
    name_pattern: str = "{stem}.png"  # or "{name}.png" (COLMAP style: image.jpg.png)
    invert: bool = False  # True: object = black, background = white (keep-mask convention)
    include_empty: bool = False  # also write masks for images with no object
    backup: bool = False  # files about to be overwritten are moved to <folder>_backup_<time>/ first (a scene)
    object_ids: Optional[List[int]] = None  # a mask set's Objects; None = the Final Mask (the checked ones)
    flipped: List[int] = field(default_factory=list)  # of those, the ones taken the other way round (MaskBar)
    sky_edges: bool = False  # Sky Objects' edges decided again on the full-resolution image (src/core/sky_edges.py)


NAME_STYLES = ("{stem}.png", "{name}.png")  # a.png, a.jpg.png: the two ways a mask pairs with a.jpg


def mask_files(out_dir: Path, keys: Sequence[str]) -> List[Path]:
    """The mask files in *out_dir* for *keys*, in either naming (a.png, a.jpg.png)."""
    out = []
    for k in keys:
        for style in NAME_STYLES:
            p = out_dir / style.format(stem=key_stem(k), name=k)
            if p.is_file() and p not in out:
                out.append(p)
    return out


def existing_style(out_dir: Path, keys: Sequence[str]) -> Optional[str]:
    """How the masks already in *out_dir* are named ("{stem}.png" or "{name}.png"); None: none there, or a tie."""
    counts = {style: sum(1 for k in keys if (out_dir / style.format(stem=key_stem(k), name=k)).is_file())
              for style in NAME_STYLES}
    a, b = counts[NAME_STYLES[0]], counts[NAME_STYLES[1]]
    return None if a == b else NAME_STYLES[0] if a > b else NAME_STYLES[1]


def backup_existing(out_dir: Path, names: List[str], keys: Sequence[str] = ()) -> Optional[Path]:
    """Move the files in *out_dir* that *names* would overwrite, and any other mask of *keys* (the other
    naming: a trainer might read that stale one), into ``<out_dir>_backup_<time>/``, sub-folders kept
    (cam0/, cam1/ hold the same names).

    Returns the backup folder, or None when nothing would be overwritten.
    """
    existing = [out_dir / n for n in names if (out_dir / n).is_file()]
    existing += [p for p in mask_files(out_dir, keys) if p not in existing]
    if not existing:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = out_dir.parent / f"{out_dir.name}_backup_{stamp}"
    n = 1
    while backup.exists():
        n += 1
        backup = out_dir.parent / f"{out_dir.name}_backup_{stamp}-{n}"
    backup.mkdir(parents=True)
    for p in existing:
        dest = backup / p.relative_to(out_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))
    return backup


def export_names(project: Project, options: "ExportOptions", keys: Optional[List[str]] = None) -> List[str]:
    """The file names an export writes, in order."""
    if keys is None:
        keys = (list(project.image_keys) if options.include_empty
                else project.keys_with_masks(ids=options.object_ids, flipped=options.flipped))
    return [options.name_pattern.format(stem=key_stem(k), name=k) for k in keys]


@dataclass
class ExportCheck:
    """What an export would write, and what may be wrong (checked before Export)."""

    images: int = 0
    with_mask: List[str] = field(default_factory=list)  # a non-empty Final Mask
    without_mask: List[str] = field(default_factory=list)  # no checked Object has a mask here
    empty: List[str] = field(default_factory=list)  # masks exist, but the Final Mask has no pixel
    warning: List[str] = field(default_factory=list)  # a checked Object's mask here is ⚠ / ✕
    clashes: List[List[str]] = field(default_factory=list)  # images that would write the same file

    @property
    def problems(self) -> List[str]:
        """Every image worth a look, in sequence order."""
        bad = set(self.without_mask) | set(self.empty) | set(self.warning) | {k for c in self.clashes for k in c}
        return [k for k in self.keys if k in bad]

    keys: List[str] = field(default_factory=list, repr=False)  # every image, in sequence order


def is_sky(o: MaskObject) -> bool:
    """A Sky special Object, or one applied from it (still named "Sky …")."""
    if o.special is not None:
        return o.special.kind == SKY
    return o.source == Source.SPECIAL and o.name.startswith(LABELS[SKY])


def has_sky(project: Project, ids: Optional[List[int]] = None) -> bool:
    use = project.members(ids)
    return any(use(o) and is_sky(o) for o in project.objects)


def full_mask(project: Project, key: str, original_size: Callable[[str], Tuple[int, int]],
              ids: Optional[List[int]] = None,
              image: Optional[Callable[[str], np.ndarray]] = None,
              finished: Optional[Callable[[str, MaskObject], Optional[np.ndarray]]] = None,
              flipped: Sequence[int] = ()) -> Optional[np.ndarray]:
    """The Final Mask (*ids*: a mask set's) of *key* at the image's original resolution (bool); None = no mask.

    *image*: key -> the full-resolution RGB image; given, the Sky Objects' edges are decided again on it
    (:func:`sky_edges`) instead of being scaled up, the other Objects are scaled up as always.
    *finished*: (key, Object) -> a Sky Object's finished mask, already at the original resolution
    (``Session.finished_sky_full``), used as it is; None for the others.
    *flipped*: those Objects count the other way round, each made at full size first (Sky edges too), then
    inverted (no mask on *key*: all of the image)."""
    h0, w0 = original_size(key)
    use = project.members(ids)
    flip = [o.id for o in project.objects if o.id in set(flipped) and use(o)]
    if flip:
        rest = [o.id for o in project.objects if use(o) and o.id not in flip]
        out = full_mask(project, key, original_size, rest, image, finished) if rest else None
        for oid in flip:
            m = full_mask(project, key, original_size, [oid], image, finished)
            outside = ~m if m is not None else np.ones((h0, w0), bool)
            out = outside if out is None else out | outside
        return out

    def up(m: np.ndarray) -> np.ndarray:
        if m.shape != (h0, w0):
            m = cv2.resize(m.astype(np.uint8), (w0, h0), interpolation=cv2.INTER_NEAREST) > 0
        return m

    use = project.members(ids)
    done = {}
    if finished is not None:
        for o in project.objects:
            if use(o) and is_sky(o) and (f := finished(key, o)) is not None:
                done[o.id] = up(f)
    objects = [o for o in project.objects if use(o) and o.id not in done]
    sky = union(o.mask(key) for o in objects if is_sky(o)) if image is not None else None
    if sky is None or not sky.any():
        m = union(o.mask(key) for o in objects)
        out = None if m is None else up(m)
    else:
        rgb = image(key)
        out = sky_edges(sky, rgb) if rgb.shape[:2] == (h0, w0) else up(sky)
        rest = union(o.mask(key) for o in objects if not is_sky(o))
        if rest is not None:
            out = out | up(rest)
    for f in done.values():
        out = f if out is None else out | f
    return out


def export_one_mask(project: Project, key: str, original_size: Callable[[str], Tuple[int, int]], out: Path,
                    ids: Optional[List[int]] = None, invert: bool = False,
                    image: Optional[Callable[[str], np.ndarray]] = None,
                    finished: Optional[Callable[[str, MaskObject], Optional[np.ndarray]]] = None) -> bool:
    """One image's mask to *out* at its original resolution (p104): the Final Mask, or (*ids*) just those
    Objects'. White = the mask (*invert*: black). Returns False when it is empty (an all-background PNG is
    still written, so the file always matches the image)."""
    m = full_mask(project, key, original_size, ids, image, finished)
    if m is None:
        h0, w0 = original_size(key)
        m = np.zeros((h0, w0), bool)
    full = m.astype(np.uint8) * 255
    _write_png(out, 255 - full if invert else full)
    return bool(m.any())


def check_export(project: Project, name_pattern: str = "{stem}.png", ids: Optional[List[int]] = None,
                 flipped: Sequence[int] = ()) -> ExportCheck:
    """Count the images with / without a Final Mask (*ids*: a mask set's, *flipped*: see MaskBar), empty
    masks, ⚠ / ✕ frames and file name clashes."""
    keys = list(project.image_keys)
    c = ExportCheck(images=len(keys), keys=keys)
    bad_status = (FrameStatus.WARNING, FrameStatus.FAILED)
    for key in keys:
        m = project.final_mask(key, ids, flipped)
        if m is None:
            c.without_mask.append(key)
        elif not m.any():
            c.empty.append(key)
        else:
            c.with_mask.append(key)
        if any(
            (o.included if ids is None else o.id in ids) and (fs := o.frames.get(key)) is not None and fs.mask is not None and fs.status in bad_status
            for o in project.objects
        ):
            c.warning.append(key)
    names: Dict[str, List[str]] = {}
    for key in keys:
        names.setdefault(name_pattern.format(stem=key_stem(key), name=key).lower(), []).append(key)
    c.clashes = [ks for ks in names.values() if len(ks) > 1]
    return c


def export_final_masks(
    project: Project,
    image_dir: Path,
    original_size: Callable[[str], Tuple[int, int]],
    options: ExportOptions,
    keys: Optional[List[str]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    finished: Optional[Callable[[str, MaskObject], Optional[np.ndarray]]] = None,
) -> List[Path]:
    """Write each image's Final Mask at its original resolution (*finished*: see :func:`full_mask`). Returns
    written paths."""
    if keys is None:
        keys = (list(project.image_keys) if options.include_empty
                else project.keys_with_masks(ids=options.object_ids, flipped=options.flipped))
    if options.backup:
        backup_existing(options.out_dir, export_names(project, options, keys), keys)
    written = []
    image = (lambda k: read_rgb(image_dir / k)) if options.sky_edges else None
    for i, key in enumerate(keys):
        h0, w0 = original_size(key)
        m = full_mask(project, key, original_size, options.object_ids, image, finished, options.flipped)
        if m is None:
            if not options.include_empty:
                continue
            full = np.zeros((h0, w0), dtype=np.uint8)
        else:
            full = m.astype(np.uint8) * 255
        if options.invert:
            full = 255 - full
        stem = key_stem(key)
        out = options.out_dir / options.name_pattern.format(stem=stem, name=key)
        _write_png(out, full)
        written.append(out)
        if progress:
            progress(i + 1, len(keys))
    return written
