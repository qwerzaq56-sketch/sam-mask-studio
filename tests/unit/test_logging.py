"""Logging never blocks the caller on a stuck console (the 2026-10-02 hang, v0.4-p59)."""

import logging
import sys
import threading
import time

from src.logging_config import configure_logging, get_logger


class StuckConsole:
    """A console whose output is paused: every write waits until released."""

    def __init__(self):
        self.release = threading.Event()
        self.lines = []

    def write(self, text):
        self.release.wait(10)
        self.lines.append(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def test_a_paused_console_does_not_block_logging(tmp_path, monkeypatch):
    console = StuckConsole()
    monkeypatch.setattr(sys, "stdout", console)
    log_path = tmp_path / "app.log"
    configure_logging(log_path=log_path)
    log = get_logger("test")
    start = time.perf_counter()
    for i in range(200):
        log.warning("event", n=i)
    assert time.perf_counter() - start < 2.0  # the caller (the GUI thread) went on
    for h in logging.getLogger().handlers:
        h.flush()
    text = log_path.read_text(encoding="utf-8")
    assert "event" in text and "n=199" in text  # the file has everything
    console.release.set()  # the console is unpaused: it catches up
    deadline = time.time() + 5
    while not any("n=199" in line for line in console.lines) and time.time() < deadline:
        time.sleep(0.05)
    assert any("n=199" in line for line in console.lines)
    configure_logging(log_path=tmp_path / "again.log")  # reconfiguring replaces the handlers cleanly
    assert len([h for h in logging.getLogger().handlers if isinstance(h, logging.handlers.QueueHandler)]) == 1


def test_qt_warnings_go_to_the_log_once(tmp_path, monkeypatch):
    from PyQt6.QtCore import qWarning
    from PyQt6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])

    from src.logging_config import install_qt_message_handler

    monkeypatch.setattr(sys, "stdout", None)  # like pythonw: no console at all
    log_path = tmp_path / "qt.log"
    configure_logging(log_path=log_path)
    install_qt_message_handler()
    for _ in range(12):
        qWarning("QWindowsWindow::setGeometry: Unable to set geometry (test)")
    for h in logging.getLogger().handlers:
        h.flush()
    text = log_path.read_text(encoding="utf-8")
    assert text.count("Unable to set geometry (test)") == 2  # the first time, then at the 10th with its count
    assert "times=10" in text
