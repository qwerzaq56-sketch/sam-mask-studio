"""p152: where an in-app propagation's frames came from, and picking a run's frames to clear."""

import numpy as np

from src.core.project import FrameState, FrameStatus, Origin, Project, Source
from src.core.propagation import Direction, PropagationPlan, next_run, origins, run_frames, run_summaries
from src.core.storage import ProjectStore

KEYS = [f"f{i}.jpg" for i in range(6)]


def _mask():
    m = np.zeros((4, 4), bool)
    m[1, 1] = True
    return m


def _project(per_frame):
    p = Project(KEYS)
    frames = {KEYS[i]: FrameState.from_mask(_mask(), status=FrameStatus.PROPAGATED, origin=og)
              for i, og in per_frame.items()}
    oid = p.add_label_objects({"people": frames}, Source.SAM2_POINT)[0]
    return p, oid


def test_origins_count_out_from_the_reference_each_way():
    plan = PropagationPlan(0, 5, 2, Direction.BOTH)
    og = origins(plan, 3, KEYS)
    assert set(og) == {0, 1, 3, 4, 5}
    assert og[3] == Origin(3, "f2.jpg", True, 1) and og[5].step == 3
    assert og[1] == Origin(3, "f2.jpg", False, 1) and og[0].step == 2
    picked = origins(PropagationPlan.of_frames([0, 4], 2, Direction.BOTH), 1, KEYS)  # picked frames: one apart
    assert picked[4].step == 1 and picked[0].step == 1


def test_run_frames_by_direction_and_from_a_step_on():
    plan = PropagationPlan(0, 5, 2, Direction.BOTH)
    p, oid = _project(origins(plan, 1, KEYS))
    p2 = origins(PropagationPlan(2, 5, 4, Direction.FORWARD), 2, KEYS)
    p.set_frame(oid, KEYS[5], FrameState.from_mask(_mask(), status=FrameStatus.PROPAGATED, origin=p2[5]))
    runs = run_summaries(p.objects, [oid])
    assert [(r.run, r.ref, r.backward, r.forward, r.far_forward) for r in runs] == \
        [(2, "f4.jpg", 0, 1, 1), (1, "f2.jpg", 2, 2, 2)]
    assert next_run(p.objects) == 3
    assert run_frames(p.objects, [oid], 1, "f2.jpg", Direction.FORWARD) == {oid: ["f3.jpg", "f4.jpg"]}
    assert run_frames(p.objects, [oid], 1, "f2.jpg", Direction.BOTH, keep=1) == {oid: ["f0.jpg", "f4.jpg"]}
    assert run_frames(p.objects, [oid + 1], 1, "f2.jpg", Direction.BOTH) == {}
    assert p.remove_frames({oid: ["f0.jpg", "f4.jpg", "nope.jpg"]}) == 2
    assert sorted(p.get(oid).frames) == ["f1.jpg", "f3.jpg", "f5.jpg"]
    p.undo()
    assert "f0.jpg" in p.get(oid).frames


def test_an_origin_is_saved_and_dropped_when_the_frame_is_edited_here(tmp_path):
    import dataclasses

    p, oid = _project({1: Origin(4, "f0.jpg", True, 1)})
    (tmp_path / "images").mkdir()
    assert ProjectStore(tmp_path / "images", 1024).save(p)
    again = ProjectStore(tmp_path / "images", 1024).load(KEYS)
    assert again.objects[0].frames["f1.jpg"].origin == Origin(4, "f0.jpg", True, 1)
    fs = p.get(oid).frames["f1.jpg"]
    p.set_frame(oid, "f1.jpg", dataclasses.replace(fs, status=FrameStatus.MANUAL))
    assert p.get(oid).frames["f1.jpg"].origin is None
    assert next_run(p.objects) == 1
