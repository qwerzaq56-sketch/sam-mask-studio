"""Offscreen Qt for GUI tests (no display needed)."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def wait_until(app, cond, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not cond():
        app.processEvents()
        if time.monotonic() > end:
            raise TimeoutError("condition not met")
        time.sleep(0.005)
    app.processEvents()
