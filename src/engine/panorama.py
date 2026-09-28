"""ERP (360°) support for SAM: every model call runs on a perspective view.

* SAM2 prompts: a view is chosen around the prompt points/box, SAM2 runs on
  it, and the result replaces that view's area of the ERP mask (the rest of
  the Object's mask, e.g. from SAM3, is kept).
* SAM3 text: the ERP is covered by a preset of views (cube map by default);
  detections are projected back and merged across views.
* Propagation: each Object is tracked in a fixed view centred on its
  reference mask, and the results are projected back.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from src.core.erp import (
    View,
    erp_point_to_view,
    merge_view_detections,
    paste_view_mask,
    preset_views,
    render_view,
    touches_view_edge,
    view_coverage,
    view_for_mask,
    view_for_points,
    view_mask_to_erp,
    view_mask_touches_border,
)
from src.core.project import Box, Detection, Point, Variant, freeze, mask_box
from src.core.propagation import PropagationPlan

VIEW_SIZE = 1024


class ViewCache:
    """Keeps rendered views alive so the engine's embedding cache (by array identity) hits."""

    def __init__(self, size: int = 8):
        self._size = size
        self._items: "OrderedDict[tuple, np.ndarray]" = OrderedDict()

    def get(self, erp: np.ndarray, view: View) -> np.ndarray:
        k = (id(erp), erp.shape, view.key())
        img = self._items.get(k)
        if img is None:
            img = render_view(erp, view)
            self._items[k] = img
            if len(self._items) > self._size:
                self._items.popitem(last=False)
        else:
            self._items.move_to_end(k)
        return img


_cache = ViewCache()


def _box_edge_points(box: Box, n: int = 16) -> List[Tuple[float, float]]:
    x0, y0, x1, y1 = box
    ts = np.linspace(0, 1, n)
    return (
        [(x0 + t * (x1 - x0), y0) for t in ts]
        + [(x0 + t * (x1 - x0), y1) for t in ts]
        + [(x0, y0 + t * (y1 - y0)) for t in ts]
        + [(x1, y0 + t * (y1 - y0)) for t in ts]
    )


def prompt_view(points: Sequence[Point], box: Optional[Box], hw: Tuple[int, int]) -> View:
    """The view SAM2 sees for a frame's prompts (all points and the box inside)."""
    uv = [(p.x, p.y) for p in points]
    if box is not None:
        uv += _box_edge_points(box, 4)
    return view_for_points(uv, hw, size=VIEW_SIZE)


def _box_in_view(box: Box, hw: Tuple[int, int], view: View) -> Optional[Box]:
    pts = [erp_point_to_view(u, v, hw, view) for u, v in _box_edge_points(box)]
    pts = [p for p in pts if p is not None]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    clip = lambda a, hi: float(min(max(a, 0.0), hi - 1))  # noqa: E731
    return (clip(min(xs), view.width), clip(min(ys), view.height), clip(max(xs), view.width), clip(max(ys), view.height))


def erp_predict(
    engine,
    erp: np.ndarray,
    points: Sequence[Point],
    box: Optional[Box] = None,
    seed_mask: Optional[np.ndarray] = None,
) -> Tuple[Variant, ...]:
    """SAM2 for ERP prompts; Variants are ERP masks (outside the view the seed is kept)."""
    hw = erp.shape[:2]
    if not points and box is None:
        return (Variant(freeze(seed_mask), 1.0),) if seed_mask is not None else ()
    view = prompt_view(points, box, hw)
    variants = _predict_in(engine, erp, view, points, box, seed_mask)
    # An object bigger than the prompt view is cut at its edge: re-centre the view on what
    # was found (wider, up to 120°) and run the same prompts again.
    for _ in range(3):
        if not variants or not view_mask_touches_border(variants[0][1]):
            break
        found = view_mask_to_erp(variants[0][1], view, hw)
        # widen by at least 20° each round so a long object is reached in a few steps
        wider = view_for_mask(found, min_fov=min(120.0, view.fov + 20.0), max_fov=120.0, margin=15.0, size=VIEW_SIZE)
        if wider is None or not _covers_points(wider, points, hw):
            break
        if wider.key() == view.key():
            break
        view = wider
        variants = _predict_in(engine, erp, view, points, box, seed_mask)
    out = []
    for v, view_mask in variants:
        m = paste_view_mask(seed_mask, view_mask, view, hw)
        out.append(Variant(freeze(m), v.score))  # view logits don't apply to the ERP
    return tuple(out)


def _covers_points(view: View, points: Sequence[Point], hw: Tuple[int, int]) -> bool:
    for p in points:
        q = erp_point_to_view(p.x, p.y, hw, view)
        if q is None or not (0 <= q[0] < view.width and 0 <= q[1] < view.height):
            return False
    return True


def _predict_in(engine, erp, view, points, box, seed_mask):
    """SAM2 in one view -> [(variant, view-space mask)]."""
    hw = erp.shape[:2]
    image = _cache.get(erp, view)
    view_points = []
    for p in points:
        q = erp_point_to_view(p.x, p.y, hw, view)
        if q is not None:
            view_points.append(Point(q[0], q[1], p.positive))
    view_box = _box_in_view(box, hw, view) if box is not None else None
    view_seed = render_view(seed_mask, view) if seed_mask is not None else None
    engine.set_image(image)
    return [(v, v.mask) for v in engine.predict(view_points, view_box, view_seed)]


def erp_detect(
    engine, erp: np.ndarray, labels: Sequence[str], views: Sequence[View], refine: bool = True
) -> List[Detection]:
    """SAM3 over the views; per-view detections are projected back and merged per object.

    With *refine*, every object that reaches the edge of a view it was found in
    (i.e. an object split across cube faces, of which a face may have seen only
    a part — or none) is detected again in a view centred on it that holds it
    whole, and replaced by that result.
    """
    hw = erp.shape[:2]
    items = []
    for vi, view in enumerate(views):
        for d in engine.detect_many(render_view(erp, view), labels):
            m = view_mask_to_erp(d.mask, view, hw)
            if m.any():
                items.append((d.label, d.score, m, vi))
    merged = merge_view_detections(items)
    if refine:
        merged = merge_view_detections(
            [(lb, s, m, i) for i, (lb, s, m) in enumerate(_refine_cut(engine, erp, merged, views))], overlap=0.3
        )
    order = {lb: i for i, lb in enumerate(labels)}
    merged.sort(key=lambda t: (order.get(t[0], 99), -t[1]))
    return [Detection(lb, float(s), freeze(m), mask_box(m)) for lb, s, m in merged]


def _refine_cut(engine, erp, merged, views):
    """Re-detect objects cut by view edges in a view centred on each (see ``erp_detect``)."""
    hw = erp.shape[:2]
    out = []
    for label, score, mask in merged:
        if not touches_view_edge(mask, views):
            out.append((label, score, mask))
            continue
        view = view_for_mask(mask, min_fov=90.0, max_fov=120.0, margin=15.0, size=VIEW_SIZE)
        if view is None:
            out.append((label, score, mask))
            continue
        cover = view_coverage(view, hw)
        hits = []
        for d in engine.detect_many(render_view(erp, view), [label]):
            m = view_mask_to_erp(d.mask, view, hw)
            inter = int((m & mask).sum())
            if inter and inter / max(1, min(int(m.sum()), int(mask.sum()))) >= 0.2:
                hits.append((d.score, m))
        if not hits:
            out.append((label, score, mask))
            continue
        full = np.zeros(hw, bool)
        for _, m in hits:
            full |= m
        # inside the centred view trust the new result; outside it keep what the faces saw
        out.append((label, max(score, max(s for s, _ in hits)), full | (mask & ~cover)))
    return out


def erp_detector(views: Sequence[View]) -> Callable:
    """A ``detect(image, labels)`` for batch masking in ERP mode."""

    def detect(engine, image, labels):
        return erp_detect(engine, image, labels, views)

    return detect


def propagate_erp(
    sam2_ckpt: str,
    image_paths: List[Path],
    plan: PropagationPlan,
    seeds: Dict[int, np.ndarray],
    max_side: int,
    device: str = "cuda",
    cancel: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[str, int, int], None]] = None,
) -> Iterator[Tuple[int, Dict[int, np.ndarray]]]:
    """Propagate each Object in its own fixed view (centred on its reference mask)."""
    from src.engine.video import propagate

    for n, (oid, seed) in enumerate(seeds.items()):
        view = view_for_mask(seed, size=VIEW_SIZE)
        if view is None:
            continue
        hw = seed.shape[:2]

        def report(phase, done, total, _n=n):
            if progress:
                progress(f"{phase} (Object {_n + 1}/{len(seeds)})", done, total)

        yield from propagate(
            sam2_ckpt,
            image_paths,
            plan,
            {oid: render_view(seed, view)},
            max_side,
            device=device,
            cancel=cancel,
            progress=report,
            transform=lambda img, _v=view: render_view(img, _v),
            untransform=lambda m, _hw, _v=view, _h=hw: view_mask_to_erp(m, _v, _h),
        )
        if cancel and cancel():
            return


__all__ = [
    "VIEW_SIZE",
    "erp_predict",
    "erp_detect",
    "erp_detector",
    "propagate_erp",
    "prompt_view",
    "preset_views",
]
