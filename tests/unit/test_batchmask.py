"""Masking presets (src/batchmask/presets.py), probe (src/batchmask/probe.py) and the preset / probe / run
commands (src/cli.py)."""

import json

import cv2
import numpy as np
import pytest

from src import cli
from src.batchmask import presets as P
from src.batchmask.probe import circle, pick_frames

from tests.unit.test_people import FakeEngine, read


@pytest.fixture
def mine(tmp_path, monkeypatch):
    folder = tmp_path / "mask_presets"
    monkeypatch.setenv(P.ENV, str(folder))
    return folder


def test_builtin_presets_read_and_say_what_they_were_checked_on(mine):
    names = {p.name: p for p in P.list_presets()}
    osmo = names["osmo360-selfie-stick"]
    assert osmo.builtin and osmo.steps == ["person", "lens", "sky"]
    assert osmo.person.labels == ["person", "black pole"] and osmo.person.attach == ["bag", "cane"]
    assert osmo.person.steady == ["handcart"] and osmo.person.steady_frames == 5  # p145
    assert osmo.checked_on and "0022" in osmo.checked_on[0]
    assert names["people-only"].steps == ["person"] and not names["people-only"].checked_on
    assert not P.broken_presets()


def test_save_find_and_change(mine, tmp_path):
    osmo = P.find_preset("osmo360-selfie-stick")
    # p131: masks/ = Spirula's own circle, fixed (the lenses' overlap kept for training); SplatBatch's rim95
    # (188/188) is the SfM circle, masks_sfm/ (p130)
    assert (osmo.lens.radius, osmo.lens.cx, osmo.lens.cy, osmo.lens.margin) == (98.0, 0.34, -3.16, 0.0)
    assert (osmo.lens.sfm_radius, osmo.lens.sfm_cx, osmo.lens.sfm_cy) == (95.0, 0.0, 0.0)
    assert "SfM circle radius 95.0 %" in osmo.summary()
    with pytest.raises(ValueError, match="built-in"):
        P.save_preset(osmo)
    mine_ = P.with_changes(osmo, name="silver-stick", person={"labels": ["person", "silver pole"]}, lens=None)
    assert mine_.person.attach == ["bag", "cane"] and mine_.lens is None and mine_.sky is not None
    path = P.save_preset(mine_)
    assert path == mine / "silver-stick.json"
    with pytest.raises(FileExistsError):
        P.save_preset(mine_)
    back = P.find_preset("silver-stick")
    assert back.person.labels == ["person", "silver pole"] and not back.builtin
    assert P.find_preset(str(path)).name == "silver-stick"  # by its path, anywhere
    assert [p.name for p in P.list_presets()][0] == "silver-stick"  # yours first

    (mine / "bad.json").write_text('{"name": "bad", "person": {"lables": ["x"]}}', encoding="utf-8")
    assert any("lables" in b for b in P.broken_presets())
    with pytest.raises(ValueError, match="no preset named"):
        P.find_preset("nope")
    with pytest.raises(ValueError, match="file name"):
        P.check_name("a/b")
    text = P.MaskPreset.from_dict({"name": "t", "person": {"labels": "person; black pole"}, "sky": True})
    assert text.person.labels == ["person", "black pole"] and text.sky == P.SkyStep()


def test_pick_frames_and_circle():
    keys = [f"cam0/{i:03d}.jpg" for i in range(10)] + ["cam1/a.jpg", "cam1/b.jpg"]
    got = pick_frames(keys, 3)
    assert got == ["cam0/000.jpg", "cam0/004.jpg", "cam0/009.jpg", "cam1/a.jpg", "cam1/b.jpg"]
    c = circle((100, 200), 50)
    assert c[50, 100] and not c[50, 140] and not c[5, 100]


def _frames(tmp_path, monkeypatch):
    from tests.fakes import fake_propagate
    monkeypatch.setattr(cli, "_engine", lambda model, device: FakeEngine())
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 7.0)
    monkeypatch.setattr(cli, "_default_propagate", lambda: fake_propagate)  # the OSMO preset's union (p142)
    model = tmp_path / "sam3.pt"
    model.write_bytes(b"x")
    images = tmp_path / "images" / "cam0"
    images.mkdir(parents=True)
    img = np.full((400, 400, 3), 120, np.uint8)
    cv2.circle(img, (200, 200), 190, (200, 200, 200), -1)  # a bright image circle, black corners
    for i in range(3):
        cv2.imencode(".jpg", img)[1].tofile(str(images / f"{i:05d}.jpg"))
    return images.parent, model


def test_person_takes_a_preset_and_the_options_change_it(tmp_path, monkeypatch, mine):
    images, model = _frames(tmp_path, monkeypatch)
    seen = []
    real = FakeEngine.detect_many
    monkeypatch.setattr(FakeEngine, "detect_many", lambda self, image, labels: seen.append(list(labels)) or real(self, image, labels))
    out = tmp_path / "p"
    assert cli.main(["person", str(images), "--out", str(out), "--recursive", "--model", str(model),
                     "--preset", "people-only"]) == 0
    assert seen[-1] == ["person"]
    out2 = tmp_path / "p2"
    rep = tmp_path / "r.json"
    assert cli.main(["person", str(images), "--out", str(out2), "--recursive", "--model", str(model),
                     "--preset", "osmo360-selfie-stick", "--attach", "", "--grow", "0", "--report", str(rep)]) == 0
    assert seen[-1] == ["person", "black pole", "handcart"]  # --attach "" leaves the preset's steady
    s = json.loads(rep.read_text(encoding="utf-8"))["settings"]
    assert s["attach"] == [] and s["grow"] == 0
    with pytest.raises(SystemExit):
        cli.main(["person", str(images), "--out", str(tmp_path / "p3"), "--model", str(model), "--preset", "nope"])


def test_osmo_preset_runs_union_and_keyframes_0_turns_it_off(tmp_path, monkeypatch, mine):
    osmo = P.find_preset("osmo360-selfie-stick")
    assert (osmo.person.keyframes, osmo.person.union) == (10, True)
    assert "propagation from every 10th (union)" in osmo.summary()
    assert "keyframes" not in P.find_preset("people-only").summary()
    images, model = _frames(tmp_path, monkeypatch)
    rep = tmp_path / "r.json"
    assert cli.main(["person", str(images), "--out", str(tmp_path / "p"), "--recursive", "--model", str(model),
                     "--preset", "osmo360-selfie-stick", "--report", str(rep)]) == 0
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert r["settings"]["keyframes"] == 10 and r["settings"]["union"] is True
    rep2 = tmp_path / "r2.json"
    assert cli.main(["person", str(images), "--out", str(tmp_path / "p2"), "--recursive", "--model", str(model),
                     "--preset", "osmo360-selfie-stick", "--keyframes", "0", "--report", str(rep2)]) == 0
    s = json.loads(rep2.read_text(encoding="utf-8"))["settings"]
    assert "keyframes" not in s and "union" not in s
    with pytest.raises(SystemExit):
        cli.main(["person", str(images), "--out", str(tmp_path / "p3"), "--model", str(model),
                  "--preset", "people-only", "--union"])


def test_probe_scores_against_a_reference_and_saves_a_preset(tmp_path, monkeypatch, mine, capsys):
    images, model = _frames(tmp_path, monkeypatch)
    ref = tmp_path / "masks" / "cam0"
    ref.mkdir(parents=True)
    for i in range(3):  # the reference: what FakeEngine finds as "person", black = ignored
        m = np.full((400, 400), 255, np.uint8)
        m[100:200, 133:200] = 0
        cv2.imencode(".png", m)[1].tofile(str(ref / f"{i:05d}.jpg.png"))
    out = tmp_path / "probe"
    assert cli.main(["probe", str(images), "--recursive", "--out", str(out), "--model", str(model),
                     "--labels", "person", "--attach", "", "--grow", "0", "--also", "black pole;tripod",
                     "--frames", "2", "--reference", str(tmp_path / "masks"), "--inside", "95",
                     "--save-preset", "my-rig"]) == 0
    r = json.loads((out / "probe.json").read_text(encoding="utf-8"))
    assert r["frames_tried"] == 2 and r["sheets"] == ["sheet_01.jpg"] and (out / "sheet_01.jpg").is_file()
    assert r["prompts"]["person"]["found_in"] == 2 and r["prompts"]["tripod"]["found_in"] == 0
    assert r["prompts"]["black pole"]["role"] == "also"
    assert r["against_reference"]["iou_mean"] > 0.95
    printed = capsys.readouterr().out
    assert "black pole" in printed and "IoU" in printed
    saved = P.find_preset("my-rig")
    assert saved.person.labels == ["person"] and saved.person.attach == [] and saved.checked_on
    assert "IoU" in saved.checked_on[0]


def test_preset_command_list_show_save(mine, capsys):
    assert cli.main(["preset", "list"]) == 0
    assert "osmo360-selfie-stick" in capsys.readouterr().out
    assert cli.main(["preset", "show", "osmo360-selfie-stick"]) == 0
    assert "black pole" in capsys.readouterr().out
    assert cli.main(["preset", "save", "pinhole-people", "--from", "osmo360-selfie-stick", "--no-lens",
                     "--labels", "person;tripod", "--checked-on", "scene X: looked at"]) == 0
    pr = P.find_preset("pinhole-people")
    assert pr.lens is None and pr.person.labels == ["person", "tripod"] and pr.person.attach == ["bag", "cane"]
    assert pr.checked_on == ["scene X: looked at"]  # not the built-in's
    capsys.readouterr()
    with pytest.raises(SystemExit):
        cli.main(["preset", "save", "osmo360-selfie-stick"])
    assert cli.main(["preset", "show", "pinhole-people", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["lens"] is None


def test_run_makes_masks_from_every_step_and_never_overwrites(tmp_path, monkeypatch, mine):
    images, model = _frames(tmp_path, monkeypatch)
    sky_calls = []
    monkeypatch.setattr(cli, "sky_folder", lambda images, out, **kw: sky_calls.append(out) or
                        {"written": 0, "skipped_existing": 0, "failed": [], "seconds": 0})
    pr = P.with_changes(P.find_preset("osmo360-selfie-stick"), name="t", lens={"radius": 95.0, "sfm_radius": 80.0})
    path = P.save_preset(pr)
    scene = tmp_path / "scene"
    sky_model = tmp_path / "sky.onnx"
    sky_model.write_bytes(b"x")
    args = ["run", str(images), "--preset", str(path), "--out", str(scene), "--recursive",
            "--sam3-model", str(model), "--sky-model", str(sky_model)]
    rep = tmp_path / "run.json"
    assert cli.main(args + ["--report", str(rep)]) == 0
    both = read(scene / "masks" / "cam0" / "00000.jpg.png")
    assert not both[150, 150] and not both[3, 3] and both[300, 300]  # person out, corner out, the rest kept
    assert (scene / "people_masks" / "cam0" / "00000.jpg.png").is_file()
    assert sky_calls == [scene / "sky_masks"]
    r = json.loads(rep.read_text(encoding="utf-8"))
    assert set(r["steps"]) == {"person", "lens", "sfm", "sky"} and r["written"] == 9 and r["preset"]["name"] == "t"
    sfm = read(scene / "masks_sfm" / "cam0" / "00000.jpg.png")  # p130: the tighter circle for SfM, people in too
    assert not sfm[150, 150] and not sfm[200, 375] and sfm[200, 340] and both[200, 375]
    assert r["folders"]["sfm"] == str(scene / "masks_sfm")

    before = (scene / "masks" / "cam0" / "00000.jpg.png").read_bytes()
    with pytest.raises(SystemExit, match="already there"):
        cli.main(args)
    assert (scene / "masks" / "cam0" / "00000.jpg.png").read_bytes() == before
    assert cli.main(args + ["--skip-existing"]) == 0


def test_run_refuses_a_busy_gpu_before_anything(tmp_path, monkeypatch, mine):
    images, model = _frames(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 1.0)
    with pytest.raises(SystemExit, match="GPU memory"):
        cli.main(["run", str(images), "--preset", "people-only", "--out", str(tmp_path / "s"), "--recursive",
                  "--sam3-model", str(model)])
    assert not (tmp_path / "s").exists()


def test_run_with_by_color_sky_checks_the_gpu_for_sam2(tmp_path, monkeypatch, mine, capsys):
    """p111: a preset whose sky has By Color runs SAM2 after it, so run asks for (1 GB of) free GPU too."""
    images, model = _frames(tmp_path, monkeypatch)
    sam2 = tmp_path / "sam2.pt"
    sam2.write_bytes(b"x")
    monkeypatch.setattr(cli, "SAM2_MODEL", sam2)
    devices = []
    monkeypatch.setattr(cli, "sky_folder", lambda images, out, **kw: devices.append(kw["device"]) or
                        {"written": 0, "skipped_existing": 0, "failed": [], "seconds": 0})
    path = P.save_preset(P.MaskPreset.from_dict({"name": "sky-color", "sky": {"color": {"color_tol": 7}}}))
    sky_model = tmp_path / "sky.onnx"
    sky_model.write_bytes(b"x")
    args = ["run", str(images), "--preset", str(path), "--recursive", "--sky-model", str(sky_model)]
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 0.5)
    with pytest.raises(SystemExit, match="GPU memory"):
        cli.main(args + ["--out", str(tmp_path / "a")])
    monkeypatch.setattr(cli, "gpu_free_gb", lambda: 1.5)  # enough for SAM2 alone (not for SAM3)
    assert cli.main(args + ["--out", str(tmp_path / "b")]) == 0
    assert "On the CPU" not in capsys.readouterr().out
    assert cli.main(args + ["--out", str(tmp_path / "c"), "--cpu"]) == 0
    assert devices == ["cuda", "cpu"] and "On the CPU" in capsys.readouterr().out  # p113: said at the start
