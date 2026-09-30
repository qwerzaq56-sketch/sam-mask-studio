"""Export presets per 3DGS trainer (docs/specs/07-export-presets.md).

The Objects in a Final Mask are what training should ignore (people, cars, the
tripod). COLMAP, Brush, LichtFeld Studio and Spirula all read
``masks/<image name>.png`` (``a.jpg.png``) with black = ignored, so one layout
serves them; those presets differ only in the notes shown and the checks run.
Postshot ignores the white parts instead, so it gets its own folder. Rules verified against each project's source / README.
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
    either_name: bool = True  # reads a.png as well as a.jpg.png: into a scene, follow the masks already there


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
        "spirula", "Spirula Studio",
        note="Spirula uses the masks/ beside images/ as they are (0 = ignored, nonzero = trained); "
             "it will not AI-mask over them.",
        verified="Spirula source: DatasetParser mask_dir = masks, sfm/core/Mask.h (a.png or a.jpg.png, 0 = ignore)",
    ),
    Preset(
        "postshot", "Postshot",
        folder="masks_postshot",
        pattern="{stem}.png",
        object_black=False,
        note="Postshot's Remove Occluders ignores the WHITE parts, the other way round from the rest, so these go "
             "to their own folder: drop the files on the Image Set's Image Masks and set Mask Mode = Remove Occluders.",
        verified="Postshot User Guide (Image Set > Mask Mode); how files pair with images is not documented — "
                 "named like the images (a.png), check that they pair",
        either_name=False,
    ),
    Preset(
        "colmap", "COLMAP (feature extraction)",
        note="For COLMAP's --ImageReader.mask_path: no features are taken from black pixels.",
        verified="COLMAP documentation",
        either_name=False,  # COLMAP reads a.jpg.png only
    ),
)
CUSTOM = "custom"  # the dialog's own choices (the export as before v0.4-p24)


def preset(key: Optional[str]) -> Optional[Preset]:
    return next((p for p in PRESETS if p.key == key), None)
