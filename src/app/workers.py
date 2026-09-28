"""Background threads for model loading, SAM3 detection, export and propagation."""

from __future__ import annotations

import traceback
from typing import Any, Callable, Dict

from PyQt6.QtCore import QThread, pyqtSignal

from src.logging_config import get_logger

logger = get_logger(__name__)


class Task(QThread):
    """Runs ``fn()`` off the UI thread; emits ``done(result)`` or ``failed(message)``."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as e:  # reported to the UI, not raised in the thread
            logger.error("task_failed", error=str(e), trace=traceback.format_exc())
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.done.emit(result)


class PropagationWorker(QThread):
    """Drives a propagation generator; results are collected and handed back at the end.

    ``frame_done(index, {obj_id: mask})`` fires for each frame so the UI can
    mark progress; ``finished_ok(results, cancelled)`` delivers everything so
    the window can store it as one undo step.
    """

    progress = pyqtSignal(str, int, int)
    frame_done = pyqtSignal(int, object)
    finished_ok = pyqtSignal(object, bool)
    failed = pyqtSignal(str, object)  # message, partial results

    def __init__(self, run: Callable[..., Any], parent=None):
        super().__init__(parent)
        self._run = run  # called as run(cancel=..., progress=...) -> iterator of (index, masks)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    @property
    def cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:
        results: Dict[int, Dict[int, Any]] = {}
        try:
            for idx, masks in self._run(cancel=lambda: self._cancel, progress=self.progress.emit):
                # ERP propagation yields each frame once per Object: merge, don't overwrite
                results.setdefault(idx, {}).update(masks)
                self.frame_done.emit(idx, masks)
                if self._cancel:
                    break
        except Exception as e:
            logger.error("propagation_failed", error=str(e), trace=traceback.format_exc())
            self.failed.emit(f"{type(e).__name__}: {e}", results)
            return
        self.finished_ok.emit(results, self._cancel)
