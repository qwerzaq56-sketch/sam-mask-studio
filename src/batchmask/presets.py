"""Masking presets: which steps a scene gets (people, lens edge, sky) and with what settings.

A preset is a JSON file::

    {
      "name": "osmo360-selfie-stick",
      "title": "OSMO 360 dual fisheye on a selfie stick",
      "description": "...",
      "checked_on": ["0022 cam0 94 frames: IoU 0.943 against hand-checked masks"],
      "person": {"labels": ["person", "black pole"], "attach": ["bag"], "threshold": 0.4, "grow": 2},
      "lens": {"radius": 98.0, "cx": 0.34, "cy": -3.16, "margin": 0.0, "sfm_radius": 95.0},
      "sky": {"threshold": 50}
    }

A step left out (or null) is not run; a setting left out takes the command's default. Built-in presets
ship in ``src/batchmask/builtin/``; your own go to ``mask_presets/`` in the app folder (or the folder in
the ``SMS_MASK_PRESETS`` environment variable), and any JSON file can be named by its path.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
BUILTIN_DIR = Path(__file__).resolve().parent / "builtin"
ENV = "SMS_MASK_PRESETS"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass
class PersonStep:
    """SAM3 text prompts: *labels* always masked, *attach* only where touching them (src/core/people.py)."""

    labels: List[str] = field(default_factory=lambda: ["person"])
    attach: List[str] = field(default_factory=list)
    threshold: float = 0.4
    touch: int = 16
    grow: int = 2
    max_side: int = 1024
    # p142: SAM3 on every frame stays the default; keyframes N > 1 adds SAM2 propagation from every N-th frame,
    # union keeps SAM3 on every frame and adds the propagation on top (src/cli.py ``person --keyframes --union``)
    keyframes: int = 0
    union: bool = False


@dataclass
class LensStep:
    """The fisheye image circle, found per camera folder unless *radius* is set (src/cli.py ``lens``)."""

    margin: float = 7.0  # src.core.special.LENS_MARGIN
    samples: int = 16
    radius: Optional[float] = None
    cx: float = 0.0
    cy: float = 0.0
    # p130: a second, tighter circle for SfM only (radius / center in %, fixed, no margin): ``run`` also writes
    # ``masks_sfm/`` with it. The wide circle above keeps the lenses' overlap for stitching and training;
    # this one leaves out the distorted rim the SfM splits on (src.core.special LENS_SFM). None = no SfM masks
    sfm_radius: Optional[float] = None
    sfm_cx: float = 0.0
    sfm_cy: float = 0.0


@dataclass
class SkyStep:
    """The Sky special Object's settings, with the edge decided at full resolution (src/cli.py ``sky``)."""

    threshold: float = 50.0
    grow: int = 0
    top_only: bool = False
    refine: bool = True
    edges: bool = True
    max_side: int = 1024
    # By Color on the full-size mask (p109): the settings as the app saves a By Color preset, None = none
    color: Optional[dict] = None
    # with By Color, also take out tree tips beyond its band (p110, src/core/refine.py ``tree_tips``)
    tree_tips: bool = True


STEPS = {"person": PersonStep, "lens": LensStep, "sky": SkyStep}


@dataclass
class MaskPreset:
    name: str
    title: str = ""
    description: str = ""
    checked_on: List[str] = field(default_factory=list)  # data the settings were checked on, with the result
    person: Optional[PersonStep] = None
    lens: Optional[LensStep] = None
    sky: Optional[SkyStep] = None
    path: Optional[Path] = field(default=None, compare=False)  # where it was read from
    builtin: bool = field(default=False, compare=False)

    @property
    def steps(self) -> List[str]:
        return [s for s in STEPS if getattr(self, s) is not None]

    def to_dict(self) -> dict:
        d = {"name": self.name, "title": self.title, "description": self.description,
             "checked_on": list(self.checked_on)}
        for s in STEPS:
            step = getattr(self, s)
            d[s] = None if step is None else asdict(step)
        return d

    @staticmethod
    def from_dict(d: dict, path: Optional[Path] = None, builtin: bool = False) -> "MaskPreset":
        where = f" in {path}" if path else ""
        if not isinstance(d, dict):
            raise ValueError(f"a preset is a JSON object{where}")
        known = {"name", "title", "description", "checked_on", *STEPS}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ValueError(f"unknown preset key(s){where}: {', '.join(unknown)} (known: {', '.join(sorted(known))})")
        name = d.get("name") or (path.stem if path else "")
        check_name(name)
        steps = {}
        for s, cls in STEPS.items():
            v = d.get(s)
            if v is None or v is False:
                steps[s] = None
                continue
            if v is True:
                v = {}
            if not isinstance(v, dict):
                raise ValueError(f"'{s}'{where} is an object of settings, true or null")
            allowed = {f.name for f in fields(cls)}
            bad = sorted(set(v) - allowed)
            if bad:
                raise ValueError(f"unknown '{s}' setting(s){where}: {', '.join(bad)} (known: {', '.join(sorted(allowed))})")
            v = dict(v)
            for key in ("labels", "attach"):
                if key in v and isinstance(v[key], str):
                    v[key] = split(v[key])
            steps[s] = cls(**v)
        checked = d.get("checked_on") or []
        return MaskPreset(name=name, title=d.get("title", ""), description=d.get("description", ""),
                          checked_on=[checked] if isinstance(checked, str) else list(checked),
                          path=path, builtin=builtin, **steps)

    def summary(self) -> str:
        """One line per step, for logs and lists."""
        lines = []
        if self.person:
            p = self.person
            lines.append(f"person: {'; '.join(p.labels)}" + (f" + touching {'; '.join(p.attach)}" if p.attach else "")
                         + f" (score >= {p.threshold}, grow {p.grow} px)"
                         + (f"; SAM3 every frame + propagation from every {p.keyframes}th (union)" if p.union and p.keyframes > 1
                            else f"; SAM3 every {p.keyframes}th frame, propagation between" if p.keyframes > 1 else ""))
        if self.lens:
            c = self.lens
            lines.append("lens: " + (f"radius {c.radius} %" if c.radius is not None else "circle found per camera folder")
                         + f", margin {c.margin} %"
                         + (f"; SfM circle radius {c.sfm_radius} % (masks_sfm/)" if c.sfm_radius is not None else ""))
        if self.sky:
            lines.append(f"sky: threshold {self.sky.threshold}" + ("" if self.sky.edges else ", no full-resolution edges"))
        return "\n".join(lines) or "(no steps)"


def split(text: str) -> List[str]:
    """``"person; black pole"`` -> ``["person", "black pole"]`` (also commas and new lines)."""
    from src.core.prompts import split_labels

    return split_labels(text)


def check_name(name: str) -> None:
    if not name or not _NAME.match(name):
        raise ValueError(f"preset name {name!r}: letters, digits, '.', '_' or '-' only (a file name)")


def user_dir() -> Path:
    return Path(os.environ[ENV]) if os.environ.get(ENV) else ROOT / "mask_presets"


def read_preset(path: Path, builtin: bool = False) -> MaskPreset:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: not valid JSON ({e})") from e
    return MaskPreset.from_dict(data, Path(path), builtin)


def list_presets() -> List[MaskPreset]:
    """Yours first, then the built-in ones (a file that does not read is left out, see :func:`broken_presets`)."""
    out: Dict[str, MaskPreset] = {}
    for folder, builtin in ((user_dir(), False), (BUILTIN_DIR, True)):
        if not folder.is_dir():
            continue
        for p in sorted(folder.glob("*.json")):
            try:
                pr = read_preset(p, builtin)
            except (ValueError, OSError, TypeError):
                continue
            out.setdefault(pr.name, pr)
    return list(out.values())


def broken_presets() -> List[str]:
    """Preset files that do not read, with why."""
    bad = []
    for folder in (user_dir(), BUILTIN_DIR):
        for p in sorted(folder.glob("*.json")) if folder.is_dir() else ():
            try:
                read_preset(p)
            except (ValueError, OSError, TypeError) as e:
                bad.append(f"{p}: {e}")
    return bad


def find_preset(name_or_path: str) -> MaskPreset:
    """A preset by name (yours, then built-in) or by the path of its JSON file."""
    p = Path(name_or_path)
    if p.suffix.lower() == ".json" or p.is_file():
        if not p.is_file():
            raise ValueError(f"no preset file {p}")
        return read_preset(p)
    for pr in list_presets():
        if pr.name == name_or_path:
            return pr
    names = ", ".join(pr.name for pr in list_presets()) or "none"
    raise ValueError(f"no preset named {name_or_path!r} (presets: {names}; or give a .json file's path)")


def save_preset(preset: MaskPreset, folder: Optional[Path] = None, overwrite: bool = False) -> Path:
    """Write *preset* as ``<name>.json`` in *folder* (your preset folder). A built-in name is refused: a copy
    of a built-in one is saved under a new name, so the shipped one always means what it says."""
    check_name(preset.name)
    if folder is None and any(pr.builtin and pr.name == preset.name for pr in list_presets()):
        raise ValueError(f"{preset.name!r} is a built-in preset: save your version under another name")
    folder = folder or user_dir()
    path = folder / f"{preset.name}.json"
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists (overwrite to replace it)")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(preset.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def with_changes(preset: MaskPreset, name: Optional[str] = None, steps: Sequence[str] = (), **changes) -> MaskPreset:
    """A copy of *preset*: *changes* like ``person={"labels": [...]}`` merged into a step (made if missing),
    ``lens=None`` dropping one; *name* renames it (and forgets where it came from)."""
    d = preset.to_dict()
    for s in steps:
        d[s] = d.get(s) or {}
    for s, v in changes.items():
        if s not in STEPS:
            d[s] = v
        elif v is None:
            d[s] = None
        else:
            d[s] = dict(d.get(s) or {}, **v)
    if name:
        d["name"] = name
    return MaskPreset.from_dict(d, None if name else preset.path, False if name else preset.builtin)
