"""User settings (checkpoints, working resolution, last folder) in ``config.local.json``."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from src.app.session import DEFAULT_MAX_SIDE
from src.logging_config import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "config.local.json"


PATH_FIELDS = ("sam2_checkpoint", "sam3_checkpoint")


@dataclass
class Settings:
    sam2_checkpoint: str = str(ROOT / "checkpoints" / "sam2" / "sam2.1_hiera_tiny.pt")
    sam3_checkpoint: str = str(ROOT / "checkpoints" / "sam3" / "sam3.pt")
    max_side: int = DEFAULT_MAX_SIDE
    last_dir: Optional[str] = None
    autosave_ms: int = 1500
    outline_visible: bool = True  # white outline around the edited mask
    outline_width: float = 1.0  # screen px
    show_edit_changes: bool = False  # tint what the edit layer added (green) / removed (red)
    frame_list_names: bool = True  # the Frame List shows file names (else only IDs and marks)
    marks_one_object: bool = False  # frame marks for the shown Object only (else every Object)
    tool_settings_open: bool = True  # Properties > Edit Layer: the Settings section unfolded
    layer_section_open: bool = True  # Properties > Edit Layer: the Layer section unfolded
    preview_object: bool = False  # Mask Preview shows the selected Object's mask (else the Final Mask)
    export_target: str = "brush"  # the Export window's trainer for a COLMAP scene (src/core/presets.py)

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

    def save(self, path: Path = DEFAULT_PATH) -> None:
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
