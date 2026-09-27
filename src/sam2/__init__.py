"""SAM2 integration layer."""

from .config import IMG_EXTS, cfg_for_ckpt
from .predictor import SAM2PredictorWrapper

__all__ = ["SAM2PredictorWrapper", "IMG_EXTS", "cfg_for_ckpt"]
