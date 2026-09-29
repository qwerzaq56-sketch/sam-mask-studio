"""Export presets per 3DGS trainer (docs/specs/07-export-presets.md).

The Objects in a Final Mask are what training should ignore (people, cars, the
tripod), so every preset writes them black on white. COLMAP, Brush and
LichtFeld Studio all read ``masks/<image name>.png`` (``a.jpg.png``) with black
= ignored, so one layout serves them; the presets differ in the notes shown
and the checks run. Rules verified against each project's source / README.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    folder: str = "masks"  # inside the scene
    pattern: str = "{name}.png"  # a.jpg -> a.jpg.png (COLMAP's own naming; Brush and LichtFeld read it too)
    object_black: bool = True  # black = ignored by the trainer; the Objects are what to ignore
    every_image: bool = True  # a mask for every image (all white where nothing is ignored)
    note: str = ""  # what to set in the trainer
    verified: str = ""
    unconfirmed_cameras: Tuple[str, ...] = ()  # camera models this trainer is not known to read


PRESETS: Tuple[Preset, ...] = (
    Preset(
        "brush", "Brush",
        note="Brush finds masks/ by itself: black is ignored, white is trained.",
        verified="Brush README and brush-dataset source (masks/img.png or masks/img.jpg.png)",
        unconfirmed_cameras=("SPHERICAL", "EQUIRECTANGULAR"),
    ),
    Preset(
        "lichtfeld", "LichtFeld Studio",
        note="In LichtFeld set Training > Mask Mode to Ignore (its default is None, which leaves masks unused).",
        verified="LichtFeld source: masks/ (also mask, segmentation), a.png or a.jpg.png; Ignore mode: black is ignored",
    ),
    Preset(
        "colmap", "COLMAP (feature extraction)",
        note="For COLMAP's --ImageReader.mask_path: no features are taken from black pixels.",
        verified="COLMAP documentation",
    ),
)
CUSTOM = "custom"  # the dialog's own choices (the export as before v0.4-p24)


def preset(key: Optional[str]) -> Optional[Preset]:
    return next((p for p in PRESETS if p.key == key), None)
