"""v0.4: the GPT review follow-ups (one section per phase, so each can be reverted with it)."""

from tests.app.test_gui import folder, win  # noqa: F401  (fixtures)
from tests.app.test_v03_features import make_objects


# --- p1: the work bar and the clearer names ----------------------------------


def test_work_bar_shows_frame_object_and_mode(qapp, win):
    ids = make_objects(win, 1)
    s = win.session
    text = win.work_bar.text()
    assert f"Frame 1 / {len(s.keys)}" in text and "Object: —" in text and "Mode: View" in text
    win.toggle_edit(ids[0])
    text = win.work_bar.text()
    assert s.project.get(ids[0]).name in text and "(SAM2)" in text and "Mode: Points" in text
    win.set_brush_tool("fill_holes")
    assert "Mode: Auto · Fill Holes (Fill)" in win.work_bar.text()
    win.set_brush_tool("paint")
    assert "Mode: Paint" in win.work_bar.text()
    win.escape()
    win.escape()
    win.go_to(1)
    assert "Frame 2 /" in win.work_bar.text()


def test_renamed_buttons(qapp, win):
    make_objects(win, 1)
    assert win.act_changes.text() == "Show Changes"
    assert win.properties_panel.recompute_btn.text().replace("&&", "&") == "Apply & Continue"
    oid = win.session.project.objects[0].id
    from PyQt6.QtWidgets import QPushButton

    assert win.objects_panel.tree.findChild(QPushButton, f"edit_{oid}").text() == "Points"


# --- p2: frame marks per Object, colors, counts, [ / ] ------------------------


def _set_status(win, oid, key, status):
    import dataclasses

    p = win.session.project
    p.set_frame(oid, key, dataclasses.replace(p.get(oid).frame(key), status=status))


def test_marks_counts_and_problem_navigation(qapp, win):
    from src.core.project import FrameStatus

    ids = make_objects(win, 2)  # both on image 0 (★)
    s = win.session
    k0, k2 = s.keys[0], s.keys[2]
    p = s.project
    p.set_frame(ids[0], k2, p.get(ids[0]).frame(k0))
    _set_status(win, ids[0], k2, FrameStatus.WARNING)
    win.refresh()
    panel = win.images_panel
    assert panel.status_mark(2) == "⚠" and panel.status_mark(0) == "★"
    assert "⚠1" in panel._summaries[0].text() and "★1" in panel._summaries[0].text()
    assert panel.list.item(2).foreground().color().name() == "#d78200"
    win.step_problem(1)
    assert s.index == 2
    win.step_problem(1)  # wraps around to the only problem again
    assert s.index == 2

    # one-Object marks: only Object 2 (on image 0 only) -> – everywhere else
    win.go_to(0)
    win.objects_panel.select_ids([ids[1]])
    win.marks_btn.setChecked(True)
    win.refresh()
    assert win.shown_object_id() == ids[1]
    assert panel.status_mark(0) == "★" and panel.status_mark(2) == "–"
    assert "–4" in panel._summaries[0].text()
    win.step_problem(1)
    assert s.index == 1  # the next image without the Object
    win.marks_btn.setChecked(False)
    assert win.settings.marks_one_object is False


# --- p3: the check before Export ----------------------------------------------


def test_check_export_counts_and_clashes(qapp, win):
    import dataclasses

    import numpy as np

    from src.core.project import FrameState, FrameStatus
    from src.core.storage import check_export

    ids = make_objects(win, 1)
    p = win.session.project
    k = win.session.keys
    fs = p.get(ids[0]).frame(k[0])
    p.set_frame(ids[0], k[1], dataclasses.replace(fs, status=FrameStatus.WARNING))
    p.set_frame(ids[0], k[2], FrameState.from_mask(np.zeros_like(fs.mask), status=FrameStatus.FAILED))
    c = check_export(p)
    assert c.images == len(k)
    assert c.with_mask == [k[0], k[1]] and c.empty == [k[2]] and c.without_mask == k[3:]
    assert c.warning == [k[1], k[2]] and c.clashes == []
    assert c.problems == k[1:]
    p.image_keys = list(p.image_keys) + ["frame_000.jpg"]  # frame_000.png + .jpg -> the same {stem}.png
    assert check_export(p, "{stem}.png").clashes == [[k[0], "frame_000.jpg"]]
    assert check_export(p, "{name}.png").clashes == []


def test_export_dialog_shows_the_check_and_opens_a_problem(qapp, win):
    from src.app.dialogs import ExportDialog
    from src.core.storage import check_export

    make_objects(win, 1)
    s = win.session
    dlg = ExportDialog(win.session.image_dir, win, check=lambda pat: check_export(s.project, pat))
    text = dlg.summary.text()
    assert "Images without a mask: 4" in text and "for <b>5</b> image(s)" in text
    assert dlg.problems.count() == 4
    dlg.empty.setChecked(True)
    assert "<b>5</b> file(s)" in dlg.summary.text()
    dlg._open_problem(dlg.problems.item(1))
    assert dlg.goto == s.keys[2]


# --- p4: foldable Settings / Layer sections -------------------------------------


def test_edit_layer_sections_fold_and_remember(qapp, win):
    from src.app.settings import Settings

    pp = win.properties_panel
    assert pp.layer_box.is_open() and pp.settings_box.is_open()
    pp.layer_box.header.click()
    assert not pp.layer_box.is_open() and pp.layer_box.body.isHidden()
    assert Settings.load(win.settings_path).layer_section_open is False
    pp.layer_box.header.click()
    assert pp.layer_box.is_open() and not pp.layer_box.body.isHidden()
    pp.settings_box.setTitle("Grow settings")
    assert pp.settings_box.title() == "Grow settings"


# --- fix: a folded Frame List starts narrow ---------------------------------------


def test_folded_frame_list_starts_narrow(qapp, folder, tmp_path):
    import time

    from src.app.main_window import MainWindow
    from src.app.settings import Settings
    from tests.app.test_gui import FakeEngine, fake_propagate

    w = MainWindow(
        settings=Settings(sam2_checkpoint=str(tmp_path / "none.pt"), frame_list_names=False),
        engine=FakeEngine(),
        propagate_fn=fake_propagate,
        settings_path=tmp_path / "config.json",
    )
    w.resize(1200, 800)
    w.show()
    for _ in range(20):
        qapp.processEvents()
        time.sleep(0.01)
    try:
        assert not w.names_btn.isChecked()
        assert w._list_dock.width() < 150
        assert w._list_summary.isHidden()  # folded: no wrapped counts (the strip keeps them)
        w.names_btn.setChecked(True)
        assert not w._list_summary.isHidden() and not w._list_summary.wordWrap()
    finally:
        w._autosave.stop()
        w.close()


# --- UI audit bugs: buttons never squeezed to nothing -----------------------------


def test_batch_and_detection_buttons_keep_their_width(qapp, win):
    import time

    win.tabs.setCurrentWidget(win.batch_panel)
    for _ in range(10):
        qapp.processEvents()
        time.sleep(0.01)
    bp = win.batch_panel
    assert bp.batch_btn.width() >= bp.batch_btn.sizeHint().width() - 2  # was 0 next to the prompt
    assert bp.stop_btn.isHidden() or bp.stop_btn.width() > 30
    win.tabs.setCurrentWidget(win.detection_panel)
    qapp.processEvents()
    assert win.detection_panel.detect_btn.width() > 30


# --- UI audit polish: nothing empty or jumping --------------------------------------


def test_empty_states_and_steady_panel_widths(qapp, win):
    import time

    from PyQt6.QtWidgets import QDockWidget

    def pump():
        for _ in range(10):
            qapp.processEvents()
            time.sleep(0.01)

    pp = win.properties_panel
    assert pp.tabs.isHidden() and not pp.hint.isHidden()  # nothing selected: only the how-to
    assert win.propagation_panel.run_view.isHidden()  # no run yet: no progress / lists
    assert win.batch_panel.progress.isHidden() and win.batch_panel.results.isHidden()
    ids = make_objects(win, 1)
    pump()
    widths = [d.width() for d in win.findChildren(QDockWidget)]
    win.toggle_edit(ids[0])
    pp.tabs.setCurrentIndex(pp.layer_tab)
    win.set_brush_tool("object_fill")
    win.set_region_mode(True)
    pump()
    assert not pp.tabs.isHidden()
    assert [d.width() for d in win.findChildren(QDockWidget)] == widths  # a long work bar never pushes docks
    assert win.canvas.banner == ""


# --- p8: , / . keyframes, F reference, R Show Changes, V Mask Preview mode ---------


def test_keyframe_and_reference_keys(qapp, win):
    import dataclasses

    from src.core.project import FrameStatus

    ids = make_objects(win, 1)  # ★ on image 0
    s = win.session
    p = s.project
    fs = p.get(ids[0]).frame(s.keys[0])
    p.set_frame(ids[0], s.keys[3], fs)  # ★ on 3
    p.set_frame(ids[0], s.keys[2], dataclasses.replace(fs, status=FrameStatus.PROPAGATED))  # ✓ is not a keyframe
    win.refresh()
    win.step_keyframe(1)
    assert s.index == 3
    win.step_keyframe(1)  # none later: stays
    assert s.index == 3
    win.step_keyframe(-1)
    assert s.index == 0
    win.go_to_reference()  # no reference yet: stays
    assert s.index == 0
    win.set_reference(4)
    win.go_to(1)
    win.go_to_reference()
    assert s.index == 4
    assert win.act_changes.shortcut().toString() == "R"


def test_mask_preview_final_or_object(qapp, win):
    import numpy as np

    ids = make_objects(win, 2)
    s = win.session
    assert win.act_final.text() == "Mask Preview"
    assert win.act_preview_mode.shortcut().toString() == "V"
    final = s.project.final_mask(s.key)
    assert np.array_equal(win.canvas._final, final) and win.canvas._final_label == "FINAL MASK"
    win.objects_panel.select_ids([ids[0]])
    win.refresh()
    win.act_preview_mode.trigger()
    assert win.settings.preview_object and win.act_preview_mode.text() == "Preview: Object"
    one = s.project.get(ids[0])
    assert win.canvas._final is one.mask(s.key) and win.canvas._final_label == one.name
    assert not np.array_equal(win.canvas._final, final)  # the other Object is left out
    win.act_preview_mode.trigger()
    assert not win.settings.preview_object and win.canvas._final_label == "FINAL MASK"


# --- p9: Enter makes the current image the reference -----------------------------


def test_enter_sets_the_reference(qapp, win):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    win.activateWindow()
    win.canvas.setFocus()
    qapp.processEvents()
    enter = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    win.go_to(2)
    assert win.eventFilter(win.canvas, enter)
    assert win._reference == 2
    win.go_to(0)
    win.go_to_reference()
    assert win.session.index == 2
    assert win.eventFilter(win.canvas, enter)  # again on the reference: back to none
    assert win._reference is None


# --- p10: every auto tool starts in Fill mode --------------------------------------


def test_auto_tool_starts_in_fill_mode(qapp, win):
    ids = make_objects(win, 1)
    win.toggle_edit(ids[0])
    s = win.session
    p = win.properties_panel
    p.tool_btns["grow"].click()
    p.mode_paint_btn.click()
    assert s.auto_mode == "paint" and win.canvas.brush_mode
    p.tool_btns["shrink"].click()  # another auto tool: back to Fill
    assert s.auto_mode == "fill" and p.mode_fill_btn.isChecked() and not win.canvas.brush_mode
    p.mode_paint_btn.click()
    win.escape()
    p.tool_btns["grow"].click()  # after leaving too
    assert s.auto_mode == "fill"
