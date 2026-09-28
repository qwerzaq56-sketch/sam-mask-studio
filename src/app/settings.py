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


@dataclass
class Settings:
    sam2_checkpoint: str = str(ROOT / "checkpoints" / "sam2" / "sam2.1_hiera_tiny.pt")
    sam3_checkpoint: str = str(ROOT / "checkpoints" / "sam3" / "sam3.pt")
    max_side: int = DEFAULT_MAX_SIDE
    last_dir: Optional[str] = None
    autosave_ms: int = 1500

    @staticmethod
    def load(path: Path = DEFAULT_PATH) -> "Settings":
        s = Settings()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                known = {f.name for f in fields(Settings)}
                s = Settings(**{k: v for k, v in data.items() if k in known})
            except (ValueError, TypeError, OSError) as e:
                logger.warning("settings_unreadable", path=str(path), error=str(e))
        return s

    def save(self, path: Path = DEFAULT_PATH) -> None:
        try:
            path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            logger.warning("settings_not_saved", path=str(path), error=str(e))
