"""What a batch run's report says about the masks in a folder (p150).

``python -m src.cli person`` / ``run`` with ``--report`` notes for every frame where its people mask came
from (``source``: sam3, keyframe, propagated, union; ``from``: the keyframes propagation carried it from)
and why it is worth a look (``warn``: area_jump, empty, added_big; p149; low_score with ``score``, p157).
Importing the folder reads that back, so the Frame List shows ✓ for propagated frames and ⚠ for the ones to
look at, with the reason.

The report is found by walking up from the mask folder: a ``*report*.json`` there or in a folder above
(the ``--report`` file next to the scene: name it so), or SplatBatch's ``runs/splatbatch/masks_report.json``.
It counts only when its ``out`` folder holds the imported folder. Other JSON files are never opened.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LEVELS = 4  # how many folders above the mask folder to look in
MAX_BYTES = 64 * 1024 * 1024  # a report is a few MB at most: skip anything bigger
KNOWN = ("runs/splatbatch/masks_report.json",)  # SplatBatch: <job>/runs/splatbatch/, the masks in <job>/data/

SOURCES = {
    "sam3": "SAM3",
    "keyframe": "SAM3 (keyframe)",
    "propagated": "propagated",
    "union": "SAM3 + propagated",
}
WARNINGS = {
    "area_jump": "the people's area jumped from the frame before (over 4× either way)",
    "empty": "no people, the frame before had some",
    "added_big": "propagation added over 1 % of the frame to SAM3's",
    "low_score": "SAM2 is unsure it is there (low score)",  # p157: the batch's score under LOW_SCORE
}
PROPAGATED = ("propagated", "union")


def _inside(folder: Path, root: Path) -> bool:
    try:
        folder.relative_to(root)
        return True
    except ValueError:
        return False


def _sections(report: dict, where: Path) -> List[Tuple[str, Path, dict]]:
    """(step, out folder, frames) for each step in *report*: a ``person`` report has one, a ``run`` report
    one a step. A relative ``out`` is taken from the report's folder."""
    found = []
    steps = report.get("steps") if isinstance(report.get("steps"), dict) else {report.get("command", ""): report}
    for name, step in steps.items():
        if isinstance(step, dict) and isinstance(step.get("frames"), dict) and step.get("out"):
            out = Path(step["out"])
            found.append((name, (out if out.is_absolute() else where / out).resolve(), step["frames"]))
    return found


def _frames_for(report: dict, where: Path, folder: Path) -> Optional[Tuple[Path, dict]]:
    """The section whose ``out`` holds *folder*. ``run``'s ``masks/`` and ``masks_sfm/`` are the lens steps,
    the people in them: those take the ``person`` step's notes."""
    sections = [s for s in _sections(report, where) if _inside(folder, s[1])]
    if not sections:
        return None
    step, out, frames = max(sections, key=lambda s: len(s[1].parts))  # the closest
    person = (report.get("steps") or {}).get("person")
    if step in ("lens", "sfm") and isinstance(person, dict) and isinstance(person.get("frames"), dict):
        frames = person["frames"]
    return out, frames


def _candidates(folder: Path):
    seen = set()
    for up in [folder, *folder.parents][: LEVELS + 1]:
        for p in [*sorted(up.glob("*report*.json")), *(up / k for k in KNOWN)]:
            if p not in seen and p.is_file():
                seen.add(p)
                yield p


def find(folder: Path) -> Optional[Tuple[Path, Path, dict]]:
    """(report file, its out folder, its frames) for the mask folder *folder*, or None."""
    folder = Path(folder).resolve()
    for p in _candidates(folder):
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
            report = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            continue
        if not isinstance(report, dict):
            continue
        hit = _frames_for(report, p.parent, folder)
        if hit is not None:
            return (p, *hit)
    return None


def notes_for(files: Dict[str, Path], out: Path, frames: dict) -> Dict[str, dict]:
    """image key -> its report note, for the mask *files* (image key -> mask file) under *out*.

    The report keys its frames by the image's path in the folder it ran on (``cam0/00011.jpg``); the mask
    file is that + ``.png`` (``--names name``) or its stem + ``.png`` (``--names stem``).
    """
    by_stem: Dict[str, str] = {}
    for k in frames:
        by_stem.setdefault(k.rsplit(".", 1)[0] if "." in k.rsplit("/", 1)[-1] else k, k)
    notes = {}
    for key, path in files.items():
        try:
            rel = Path(path).resolve().relative_to(out).as_posix()
        except ValueError:
            continue
        rel = rel[:-4] if rel.lower().endswith(".png") else rel
        k = rel if rel in frames else by_stem.get(rel)
        if k is not None and isinstance(frames[k], dict):
            notes[key] = frames[k]
    return notes


def describe(note: dict) -> str:
    """One line for the Frame List's tooltip: ``propagated from cam0/00006 (forward) · ⚠ the people's area …``."""
    parts = []
    src = note.get("source")
    if src:
        text = SOURCES.get(src, src)
        came = [f"{Path(f['key']).with_suffix('').as_posix()}"
                + {"fwd": " forward", "back": " back"}.get(f.get("dir"), "")
                for f in note.get("from") or [] if isinstance(f, dict) and f.get("key")]
        if came:
            text += " from " + ", ".join(came)
        parts.append(text)
    if isinstance(note.get("score"), (int, float)):  # p157: the lowest SAM2 object score carried here
        parts.append(f"score {note['score']:.2f}")
    parts += ["⚠ " + WARNINGS.get(w, w) for w in note.get("warn") or []]
    return " · ".join(parts)


def propagated(note: dict) -> bool:
    return note.get("source") in PROPAGATED


def warned(note: dict) -> bool:
    return bool(note.get("warn"))
