"""User settings (checkpoints, working resolution, last folder) in ``config.local.json``."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

from src.app.session import DEFAULT_MAX_SIDE
from src.logging_config import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "config.local.json"


PATH_FIELDS = ("sam2_checkpoint", "sam3_checkpoint", "sky_checkpoint")


@dataclass
class Settings:
    sam2_checkpoint: str = str(ROOT / "checkpoints" / "sam2" / "sam2.1_hiera_tiny.pt")
    sam3_checkpoint: str = str(ROOT / "checkpoints" / "sam3" / "sam3.pt")
    sky_checkpoint: str = str(ROOT / "checkpoints" / "sky" / "skyseg.onnx")  # the Sky special Object's model
    max_side: int = DEFAULT_MAX_SIDE
    use_cpu: bool = False  # SAM2 / SAM3 on the CPU: the GPU is left to a training (p120; also main.py --cpu)
    last_dir: Optional[str] = None
    recent_dirs: list = field(default_factory=list)  # the folders opened last, newest first (the start screen, U13)
    autosave_ms: int = 1500
    outline_visible: bool = True  # white outline around the edited mask
    outline_width: float = 1.0  # screen px
    overlay_opacity: int = 100  # % of each overlay's own opacity (mask colors, tool tints), 10-200
    show_edit_changes: bool = False  # tint what the edit layer added (green) / removed (red)
    frame_list_names: bool = True  # the Frame List shows file names (else only IDs and marks)
    marks_one_object: bool = False  # frame marks for the shown Object only (else every Object)
    tool_settings_open: bool = True  # Properties > Edit Layer: the Settings section unfolded
    layer_section_open: bool = True  # Properties > Edit Layer: the Layer section unfolded
    preview_object: bool = False  # Mask Preview shows the selected Object's mask (else the Final Mask)
    preview_style: str = "mask"  # Mask Preview: mask (black and white) | cutout (the image inside) | outside
    cutout_fill: str = "mask"  # the cut-out previews' rest: mask (its black / white) | checker
    cutout_side: str = "cutout"  # the cut-out side: cutout (inside the mask) | outside (C switches; X back to black and white)
    export_sky_edges: bool = True  # Export: Sky Objects' edges at full resolution (src/core/sky_edges.py)
    export_target: str = "brush"  # the Export window's trainer for a COLMAP scene (src/core/presets.py)
    color_presets: dict = field(default_factory=dict)  # By Color filter presets: name -> its settings (p105)
    color_last: dict = field(default_factory=dict)  # By Color's settings as last left, put back at start (p106)

    def __post_init__(self) -> None:
        self.removed_presets: set = set()  # By Color presets deleted here: not merged back from the file (p107)

    @staticmethod
    def load(path: Path = DEFAULT_PATH) -> "Settings":
        s = Settings()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {f.name for f in fields(Settings)}
                s = Settings(**{k: v for k, v in data.items() if k in known})
                for name in PATH_FIELDS:  # stored relative to the app folder when inside it
                    value = getattr(s, name)
                    if value and not Path(value).is_absolute():
                        setattr(s, name, str(ROOT / value))
            except (ValueError, TypeError, OSError) as e:
                logger.warning("settings_unreadable", path=str(path), error=str(e))
        return s

    def _merge_presets(self, path: Path) -> None:
        """By Color presets in the file but not here (written while this app ran, e.g. by another app or by
        hand) are kept, unless deleted here (p107)."""
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8")).get("color_presets") or {}
        except (ValueError, OSError, AttributeError):
            return
        if not isinstance(on_disk, dict):
            return
        for name, values in on_disk.items():
            if name not in self.color_presets and name not in self.removed_presets and isinstance(values, dict):
                self.color_presets[name] = values

    def save(self, path: Path = DEFAULT_PATH) -> None:
        if path.is_file():
            self._merge_presets(path)
        data = asdict(self)
        for name in PATH_FIELDS:  # relative inside the app folder, so the folder can be moved (portable)
            value = data[name]
            if value:
                try:
                    data[name] = Path(value).resolve().relative_to(ROOT.resolve()).as_posix()
                except ValueError:
                    pass  # elsewhere: keep it absolute
        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.warning("settings_not_saved", path=str(path), error=str(e))
