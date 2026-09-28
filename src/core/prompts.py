"""Text prompt parsing for SAM3 detection."""

from __future__ import annotations

import re
from typing import List

# Comma, semicolon, full-width comma, ideographic comma, or a newline separate labels.
_SEPARATORS = re.compile(r"[,;，、\n]+")


def split_labels(text: str) -> List[str]:
    """``"person, car ,tripod"`` -> ``["person", "car", "tripod"]`` (unique, order kept)."""
    out: List[str] = []
    seen = set()
    for part in _SEPARATORS.split(text or ""):
        label = " ".join(part.split())
        if label and label.lower() not in seen:
            seen.add(label.lower())
            out.append(label)
    return out
