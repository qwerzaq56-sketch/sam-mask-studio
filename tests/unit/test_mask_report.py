"""p150: a batch run's report read back for an imported mask folder (src/core/mask_report.py)."""

import json

from src.core import mask_report as R
from src.core.project import FrameState, FrameStatus, Project
from src.core.storage import ProjectStore


def _write(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report), encoding="utf-8")


def test_a_person_report_next_to_the_scene_is_found_and_keyed_by_mask_file(tmp_path):
    out = tmp_path / "scene" / "people"
    (out / "cam0").mkdir(parents=True)
    _write(tmp_path / "scene" / "report.json", {"command": "person", "out": str(out), "frames": {
        "cam0/00001.jpg": {"source": "keyframe"},
        "cam0/00002.jpg": {"source": "propagated", "from": [{"key": "cam0/00001.jpg", "dir": "fwd"}]},
    }})
    hit = R.find(out / "cam0")  # the camera folder alone: the report's out holds it
    assert hit is not None and hit[0] == tmp_path / "scene" / "report.json"
    files = {"00001.jpg": out / "cam0" / "00001.jpg.png", "00002.jpg": out / "cam0" / "00002.jpg.png",
             "00003.jpg": out / "cam0" / "00003.jpg.png"}
    notes = R.notes_for(files, hit[1], hit[2])
    assert set(notes) == {"00001.jpg", "00002.jpg"}
    assert R.propagated(notes["00002.jpg"]) and not R.propagated(notes["00001.jpg"])
    assert R.describe(notes["00002.jpg"]) == "propagated from cam0/00001 forward"


def test_stem_names_and_a_report_for_another_folder(tmp_path):
    out = tmp_path / "masks"
    out.mkdir()
    _write(tmp_path / "other_report.json", {"out": str(tmp_path / "elsewhere"), "frames": {"a.jpg": {"source": "sam3"}}})
    assert R.find(out) is None  # its out is not this folder
    _write(tmp_path / "people_report.json", {"out": str(out), "frames": {"a.jpg": {"source": "union", "warn": ["added_big"]}}})
    _write(tmp_path / "notes.json", {"out": str(out), "frames": {"a.jpg": {"source": "sam3"}}})  # not a report
    hit = R.find(out)
    assert hit[0].name == "people_report.json"
    notes = R.notes_for({"a.jpg": out / "a.png"}, hit[1], hit[2])  # --names stem: a.png
    assert R.warned(notes["a.jpg"])
    assert R.describe(notes["a.jpg"]) == "SAM3 + propagated · ⚠ " + R.WARNINGS["added_big"]


def test_a_run_report_lends_the_people_notes_to_masks_but_not_to_sky(tmp_path):
    scene = tmp_path / "data" / "scene"
    for d in ("people_masks", "masks", "sky_masks"):
        (scene / d).mkdir(parents=True)
    frames = {"a.jpg": {"source": "propagated"}}
    _write(tmp_path / "runs" / "splatbatch" / "masks_report.json", {"command": "run", "steps": {
        "person": {"out": str(scene / "people_masks"), "frames": frames},
        "lens": {"out": str(scene / "masks"), "frames": {"a.jpg": {"kept": 0.9}}},
        "sky": {"out": str(scene / "sky_masks"), "frames": {"a.jpg": {"sky": 0.3}}},
    }})
    hit = R.find(scene / "masks")  # SplatBatch's report, two folders up
    assert R.propagated(R.notes_for({"a.jpg": scene / "masks" / "a.jpg.png"}, hit[1], hit[2])["a.jpg"])
    hit = R.find(scene / "sky_masks")
    assert R.notes_for({"a.jpg": scene / "sky_masks" / "a.jpg.png"}, hit[1], hit[2])["a.jpg"] == {"sky": 0.3}


def test_a_note_is_saved_and_dropped_when_the_frame_is_edited_here(tmp_path):
    import dataclasses

    import numpy as np

    from src.core.project import Source

    m = np.zeros((4, 4), bool)
    m[1, 1] = True
    p = Project(["a.jpg"])
    oid = p.add_label_objects({"people": {"a.jpg": FrameState.from_mask(m, status=FrameStatus.WARNING,
                                                                         note="⚠ why")}}, Source.IMPORTED)[0]
    (tmp_path / "images").mkdir()
    assert ProjectStore(tmp_path / "images", 1024).save(p)
    again = ProjectStore(tmp_path / "images", 1024).load(["a.jpg"])
    assert again.objects[0].frames["a.jpg"].note == "⚠ why"
    fs = p.get(oid).frames["a.jpg"]
    p.set_frame(oid, "a.jpg", dataclasses.replace(fs, status=FrameStatus.MANUAL))
    assert p.get(oid).frames["a.jpg"].note == ""


def test_a_batch_score_and_low_score_in_the_tooltip():
    """p157 / p158: the batch notes the lowest SAM2 object score carried to a frame and warns low_score."""
    note = {"source": "propagated", "from": [{"key": "cam0/00001.jpg", "dir": "fwd"}], "score": 0.634, "warn": ["low_score"]}
    assert R.warned(note)
    assert R.describe(note) == "propagated from cam0/00001 forward · score 0.63 · ⚠ SAM2 is unsure it is there (low score)"
    assert R.describe({"source": "keyframe"}) == "SAM3 (keyframe)"  # no score: nothing added
