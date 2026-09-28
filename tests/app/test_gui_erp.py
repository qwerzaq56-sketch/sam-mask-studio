"""360° folders in the window: Open as ERP, perspective view, clicks/brush mapped back to ERP."""

import numpy as np
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest

from src.app.main_window import MainWindow
from src.app.settings import Settings
from tests.fakes import FakeEngine, fake_propagate, make_images


@pytest.fixture
def win(qapp, tmp_path):
    make_images(tmp_path / "pano", n=3, hw=(300, 600))
    asked = []
    w = MainWindow(
        settings=Settings(sam2_checkpoint=str(tmp_path / "none.pt"), erp_max_side=512),
        engine=FakeEngine(),
        propagate_fn=fake_propagate,
        settings_path=tmp_path / "config.json",
    )
    w.ask = lambda title, text, ok: asked.append(title) or True
    w.warn = w.log
    w.resize(1200, 800)
    w.show()
    assert w.open_folder(tmp_path / "pano")
    qapp.processEvents()
    w.asked = asked
    yield w
    w._autosave.stop()
    w.close()


def center(win) -> QPoint:
    return QPoint(win.canvas.width() // 2, win.canvas.height() // 2)


def test_2to1_folder_is_offered_as_erp(win):
    assert "360° panorama?" in win.asked and win.session.erp
    assert win.act_pano.isEnabled() and not win.act_pano.isChecked()


def test_perspective_view_click_lands_in_erp(win, qapp):
    win.act_pano.trigger()
    assert win.canvas.pano and win.display_view() is not None
    v = win.display_view()
    assert win.canvas.image.shape[:2] == (v.height, v.width)
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(win))
    s = win.session
    assert len(s.project.objects) == 1
    p = s.editing_frame().points[0]
    assert abs(p.x - 256) < 3 and abs(p.y - 128) < 3  # view centre = ERP centre at yaw 0
    assert s.editing_frame().mask[128, 256]
    assert len(win.canvas.points) == 1  # drawn in the view


def test_look_around_and_fov(win, qapp):
    win.act_pano.trigger()
    yaw0 = win._look[0]
    win.on_look(-100, 0)  # drag left -> look right
    assert win._look[0] > yaw0
    win.on_look(0, 10_000)
    assert win._look[1] == pytest.approx(89.9)
    fov0 = win._look[2]
    ev = QWheelEvent(QPointF(center(win)), QPointF(), QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    qapp.sendEvent(win.canvas, ev)
    assert win._look[2] < fov0 and win.canvas.zoom == 1.0


def test_look_behind_click_across_seam(win):
    win.act_pano.trigger()
    win._look = [180.0, 0.0, 90.0]
    win._show_image()
    win.refresh()
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(win))
    p = win.session.editing_frame().points[0]
    assert p.x < 3 or p.x > 509  # behind the camera = the ERP seam


def test_brush_in_view_edits_erp_layer(win):
    win.act_pano.trigger()
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center(win))
    s = win.session
    win.act_brush.trigger()
    q = center(win) + QPoint(120, 0)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q)
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q)
    fs = s.editing_frame()
    assert fs.edit is not None and fs.edit.added > 0 and fs.edit.removed == 0
    ys, xs = np.nonzero(fs.edit.add)
    assert xs.mean() > 256  # right of centre in the view = right of centre in ERP


def test_select_point_in_view(win):
    win.act_pano.trigger()
    c = center(win)
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c)
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c + QPoint(150, 40))
    QTest.mouseClick(win.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c + QPoint(150, 40))
    assert win.session.selected_point == 1
    win.delete_key()
    assert len(win.session.editing_frame().points) == 1


def test_view_off_returns_to_erp(win):
    win.act_pano.trigger()
    win.act_pano.trigger()
    assert not win.canvas.pano and win.canvas.image.shape[:2] == (256, 512)


def test_normal_folder_disables_360_view(qapp, tmp_path):
    make_images(tmp_path / "flat", n=2, hw=(60, 80))
    w = MainWindow(settings=Settings(sam2_checkpoint=str(tmp_path / "none.pt")), engine=FakeEngine(),
                   settings_path=tmp_path / "c.json")
    w.ask = lambda *a: True
    w.open_folder(tmp_path / "flat")
    assert not w.session.erp and not w.act_pano.isEnabled()
    w._autosave.stop()
    w.close()
