"""SAM2 (point/box refinement) and SAM3 (text detection) behind one interface.

Both models receive the same working-resolution RGB image, so every prompt
and mask in the app lives in a single coordinate system.
"""

from __future__ import annotations

import threading
from typing import List, Optional, Sequence, Tuple

import numpy as np
import torch

from src.core.project import Box, Detection, Point, Variant, freeze, mask_box
from src.logging_config import get_logger

logger = get_logger(__name__)


class InferenceEngine:
    """Owns the SAM2 image predictor and a lazily built SAM3 text predictor."""

    def __init__(self, sam2_ckpt: str, sam3_ckpt: Optional[str], device: str = "cuda"):
        if device == "cuda" and not torch.cuda.is_available():
            device = "cpu"
        self.device = device
        self.sam2_ckpt = sam2_ckpt
        self.sam3_ckpt = sam3_ckpt
        self._sam2 = None  # SAM2PredictorWrapper
        self._sam3 = None  # SAM3PredictorWrapper
        self._image: Optional[np.ndarray] = None
        self._sam2_image: Optional[np.ndarray] = None  # image whose embedding SAM2 holds
        self._sam3_image: Optional[np.ndarray] = None
        # Serialises GPU work between the UI thread (SAM2 clicks) and workers (SAM3, loading).
        self.lock = threading.RLock()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @property
    def sam2_ready(self) -> bool:
        return self._sam2 is not None

    @property
    def sam3_ready(self) -> bool:
        return self._sam3 is not None

    def load_sam2(self) -> None:
        from src.sam2.predictor import SAM2PredictorWrapper

        with self.lock:
            if self._sam2 is None:
                self._sam2 = SAM2PredictorWrapper(self.sam2_ckpt, device=self.device)
                self._sam2_image = None

    def load_sam3(self) -> None:
        from src.utils.check_packages import check_sam3_installed

        ok, err = check_sam3_installed()  # also installs the decord/triton import stubs
        if not ok:
            raise ImportError(f"SAM3 is not installed: {err}")
        from src.sam3.predictor import SAM3PredictorWrapper

        with self.lock:
            if self._sam3 is None:
                self._sam3 = SAM3PredictorWrapper(self.sam3_ckpt or None, None, device=self.device)
                self._sam3_image = None

    # ------------------------------------------------------------------
    # Image
    # ------------------------------------------------------------------

    def set_image(self, image: np.ndarray) -> None:
        """Set the working-resolution RGB image. Embeddings are computed on demand."""
        self._image = image

    def _ensure_sam2_image(self) -> None:
        if self._sam2 is None:
            raise RuntimeError("SAM2 is not loaded yet.")
        if self._image is None:
            raise RuntimeError("No image set.")
        if self._sam2_image is not self._image:
            self._sam2.set_image_from_array(self._image, 0)
            self._sam2_image = self._image

    def _ensure_sam3_image(self) -> None:
        if self._sam3 is None:
            raise RuntimeError("SAM3 is not loaded yet.")
        if self._image is None:
            raise RuntimeError("No image set.")
        if self._sam3_image is not self._image:
            self._sam3.set_image_from_array(self._image, 0)
            self._sam3_image = self._image

    def prepare_sam2(self) -> None:
        """Compute the SAM2 embedding for the current image now (e.g. on navigation)."""
        with self.lock:
            self._ensure_sam2_image()

    # ------------------------------------------------------------------
    # SAM2
    # ------------------------------------------------------------------

    def predict(
        self,
        points: Sequence[Point],
        box: Optional[Box] = None,
        seed_mask: Optional[np.ndarray] = None,
    ) -> Tuple[Variant, ...]:
        """Run SAM2 on the current image and return Variants sorted by score.

        ``seed_mask`` (a SAM3 detection, propagated, merged or brushed mask) is
        passed as SAM2's low-resolution mask prior so refinement starts from it.
        With no points and no box there is nothing to run: the seed itself is
        returned as the only Variant.
        """
        if not points and box is None:
            return (Variant(freeze(seed_mask), 1.0),) if seed_mask is not None else ()
        with self.lock:
            self._ensure_sam2_image()
            p = self._sam2.predictor
            coords = np.array([[pt.x, pt.y] for pt in points], dtype=np.float32) if points else None
            labels = np.array([1 if pt.positive else 0 for pt in points], dtype=np.int32) if points else None
            mask_input = self._sam2.mask_to_logits(seed_mask.astype(np.uint8) * 255) if seed_mask is not None else None
            masks, scores, logits = p.predict(
                point_coords=coords,
                point_labels=labels,
                box=np.array(box, dtype=np.float32) if box is not None else None,
                mask_input=mask_input,
                multimask_output=True,
                normalize_coords=True,
            )
        order = np.argsort(scores)[::-1]
        return tuple(Variant(freeze(masks[i] > 0), float(scores[i]), logits[i : i + 1]) for i in order)

    # ------------------------------------------------------------------
    # SAM3
    # ------------------------------------------------------------------

    def detect(self, text: str) -> List[Detection]:
        """SAM3 text prompt on the current image -> candidate Detections (score-sorted)."""
        if self._image is None:
            raise RuntimeError("No image set.")
        return self.detect_many(self._image, [text])

    def detect_many(self, image: np.ndarray, labels: Sequence[str]) -> List[Detection]:
        """SAM3 on any working-resolution image, one text prompt per label.

        Does not touch the image SAM2 is editing, so it can run over other
        frames (batch masking) while the current image stays as it is.
        Detections are grouped by label in the given order, score-sorted within.
        """
        labels = [t.strip() for t in labels if t and t.strip()]
        if not labels:
            return []
        out: List[Detection] = []
        with self.lock:
            if self._sam3 is None:
                raise RuntimeError("SAM3 is not loaded yet.")
            if self._sam3_image is not image:
                self._sam3.set_image_from_array(image, 0)
                self._sam3_image = image
            for label in labels:
                masks, scores = self._sam3.predict_mask_from_text(label)
                dets = []
                for m, s in zip(masks, scores, strict=False):
                    mb = freeze(m)
                    if mb.any():
                        dets.append(Detection(label=label, score=float(s), mask=mb, box=mask_box(mb)))
                dets.sort(key=lambda d: d.score, reverse=True)
                out.extend(dets)
        return out

    def release(self) -> None:
        with self.lock:
            for p in (self._sam2, self._sam3):
                if p is not None and hasattr(p, "release"):
                    p.release()
            self._sam2 = self._sam3 = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
