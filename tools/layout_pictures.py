"""Reference pictures of the pinhole view layouts (docs/specs/08 8.4): for each layout, the map of the views
(the sphere laid flat) beside the views as numbered virtual cameras in 3D, as the Export window draws them.

    python tools/layout_pictures.py [out_dir] [--fov 90]

Writes ``layout_<key>.png`` per layout (360 and fisheye) into *out_dir* (default docs/manual/img). No GPU.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPalette  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.app.view_preview import DOWN, LEVEL, UP, RigPreview, ViewPreview  # noqa: E402
from src.core.reproject import FISHEYE_LAYOUTS, VIEW_LAYOUTS  # noqa: E402


def picture(key: str, fov: float, source: str) -> QImage:
    lay = {**VIEW_LAYOUTS, **FISHEYE_LAYOUTS}[key]
    pairs = lay.pairs()
    W, H = 1100, 512
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Base, QColor("white"))
    pal.setColor(QPalette.ColorRole.Text, QColor(30, 30, 30))
    flat, rig = ViewPreview(), RigPreview()
    for w in (flat, rig):
        w.setPalette(pal)
        f = w.font()
        f.setPointSizeF(11)
        w.setFont(f)
    flat.setFixedSize(700, 360)
    rig.setFixedSize(370, 370)
    flat.set_views(pairs, fov)
    rig.set_views(pairs, fov, source=source)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    title = QFont(flat.font())
    title.setPointSizeF(15)
    title.setBold(True)
    p.setFont(title)
    p.setPen(QColor(30, 30, 30))
    p.drawText(QPointF(16, 32), f"{lay.label}  ·  FOV {fov:.0f}°")
    body = QFont(flat.font())
    body.setPointSizeF(10.5)
    p.setFont(body)
    p.setPen(QColor(90, 90, 90))
    p.drawText(QRectF(16, 40, W - 32, 40), Qt.TextFlag.TextWordWrap, lay.purpose)
    flat.render(p, flat.rect().topLeft() + QPointF(10, 92).toPoint())
    rig.render(p, QPointF(720, 86).toPoint())
    p.setPen(QColor(90, 90, 90))
    p.drawText(QPointF(24, 474), "Left: the sphere laid flat (middle = front, top = up), true outlines.  Right: the "
                                 "same views around the camera, seen from in front (left, above): tiles drawn smaller.")
    x = 24
    for color, name in ((UP, "looks up"), (LEVEL, "level"), (DOWN, "looks down")):
        p.fillRect(QRectF(x, 488, 12, 12), color)
        p.drawText(QPointF(x + 17, 499), name)
        x += 110
    if source != "360":
        p.fillRect(QRectF(x, 493, 18, 2), QColor(200, 60, 60))
        p.drawText(QPointF(x + 24, 499), "where the lens ends" if source == "fisheye" else "where the two lenses meet")
    p.end()
    return img


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", default=str(ROOT / "docs" / "manual" / "img"))
    ap.add_argument("--fov", type=float, default=90.0)
    a = ap.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for key in VIEW_LAYOUTS:
        picture(key, a.fov, "360").save(str(out / f"layout_{key}.png"))
        print(out / f"layout_{key}.png")
    for key in FISHEYE_LAYOUTS:
        picture(key, a.fov, "fisheye").save(str(out / f"layout_{key}.png"))
        print(out / f"layout_{key}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
