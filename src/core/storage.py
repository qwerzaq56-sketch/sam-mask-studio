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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from src.core.project import EditLayer, FrameState, FrameStatus, MaskObject, Point, Project, Source, Variant, freeze

FORMAT_VERSION = 1


def sidecar_dir(image_dir: Path) -> Path:
    return image_dir.parent / f"{image_dir.name}.sms"


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
                sel = fs.variants[min(fs.selected, len(fs.variants) - 1)] if fs.variants else None
                frames_json[key] = {
                    "points": [[p.x, p.y, 1 if p.positive else 0] for p in fs.points],
                    "box": list(fs.box) if fs.box else None,
                    "status": fs.status.value,
                    "score": sel.score if sel else None,
                    "has_mask": m is not None,
                    "edit": fs.edit is not None,
                }
            objects_json.append(
                {
                    "id": o.id,
                    "name": o.name,
                    "source": o.source.value,
                    "color": list(o.color),
                    "included": o.included,
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
                frames[key] = FrameState(
                    points=points,
                    box=box,
                    base_mask=mask,
                    variants=variants,
                    status=FrameStatus(fj.get("status", "manual")),
                    edit=edit,
                )
            project.objects.append(
                MaskObject(
                    id=oid,
                    name=oj["name"],
                    source=Source(oj.get("source", Source.SAM2_POINT.value)),
                    color=tuple(oj.get("color", (230, 25, 75))),
                    included=bool(oj.get("included", True)),
                    frames=frames,
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


def export_final_masks(
    project: Project,
    image_dir: Path,
    original_size: Callable[[str], Tuple[int, int]],
    options: ExportOptions,
    keys: Optional[List[str]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[Path]:
    """Write each image's Final Mask at its original resolution. Returns written paths."""
    if keys is None:
        keys = list(project.image_keys) if options.include_empty else project.keys_with_masks()
    written = []
    for i, key in enumerate(keys):
        h0, w0 = original_size(key)
        m = project.final_mask(key)
        if m is None:
            if not options.include_empty:
                continue
            full = np.zeros((h0, w0), dtype=np.uint8)
        else:
            full = m.astype(np.uint8) * 255
            if full.shape != (h0, w0):
                full = cv2.resize(full, (w0, h0), interpolation=cv2.INTER_NEAREST)
        if options.invert:
            full = 255 - full
        stem = Path(key).stem
        out = options.out_dir / options.name_pattern.format(stem=stem, name=key)
        _write_png(out, full)
        written.append(out)
        if progress:
            progress(i + 1, len(keys))
    return written
