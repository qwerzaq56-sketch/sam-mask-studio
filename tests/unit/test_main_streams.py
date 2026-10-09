"""Started by SplatBatch (no console, output not redirected) the app has no stdout / stderr, and SAM2's
frame-loading progress bar failed the propagation ('NoneType' object has no attribute 'write')."""

import sys

from tqdm import tqdm

from src.main import ensure_std_streams


def test_progress_bars_work_when_started_without_output(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    try:
        list(tqdm(range(3), desc="frame loading (JPEG)"))
    except AttributeError as e:          # what the deployed v0.6.0 logged
        assert "write" in str(e)
    else:
        raise AssertionError("expected the bare tqdm to fail without stderr")
    ensure_std_streams()
    assert sys.stdout is not None and sys.stderr is not None
    assert list(tqdm(range(3), desc="frame loading (JPEG)")) == [0, 1, 2]
    sys.stdout.close(), sys.stderr.close()


def test_streams_left_alone_when_present():
    out, err = sys.stdout, sys.stderr
    ensure_std_streams()
    assert sys.stdout is out and sys.stderr is err
