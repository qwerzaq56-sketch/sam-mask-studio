"""Centralized structured logging configuration (python-observability patterns).

Configure once at application startup. Use get_logger(__name__) in modules.
Supports structured key-value logs and optional JSON output for production.

Public API:
    - configure_logging(): call once at startup
    - get_logger(name): use in every module
    - timed_operation(): context manager for timed operations (Pattern 7)
"""

__all__ = ["configure_logging", "get_logger", "timed_operation", "install_qt_message_handler",
           "disable_console_quickedit", "log_file"]

import atexit
import logging
import logging.config
import logging.handlers
import os
import queue
import sys
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import structlog


def configure_logging(
    level: Optional[str] = None,
    debug: bool = False,
    json_format: Optional[bool] = None,
    log_path: Optional[Path] = None,
) -> None:
    """Configure structured logging for the application (Pattern 1).

    Call this once at application startup, before creating the GUI.

    Args:
        level: Override log level (e.g. "INFO", "DEBUG"). If None, uses DEBUG
            when debug is True, else INFO.
        debug: When True, set level to DEBUG; ignored if level is provided.
        json_format: When True, emit JSON logs (machine-readable). When False,
            use human-readable console output. When None, follow LOG_FORMAT env
            (e.g. LOG_FORMAT=json) or default to console.
    """
    if level is None:
        level = "DEBUG" if debug else "INFO"
    log_level = getattr(logging, level.upper(), logging.INFO)

    use_json = json_format if json_format is not None else (os.environ.get("LOG_FORMAT", "").lower() == "json")

    # Shared processors for structlog event dict (Pattern 1)
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        timestamper,
    ]

    console = sys.stdout if sys.stdout is not None else sys.stderr  # None under pythonw: no console
    if use_json:
        renderer: Any = structlog.processors.JSONRenderer()
        file_renderer: Any = renderer
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=bool(console is not None and console.isatty()))
        file_renderer = structlog.dev.ConsoleRenderer(colors=False)

    # Pre-chain for log records that did not come from structlog (e.g. third-party)
    foreign_pre_chain = [
        structlog.stdlib.add_log_level,
        timestamper,
    ]

    def formatter(proc: Any) -> logging.Formatter:
        return structlog.stdlib.ProcessorFormatter(processor=proc, foreign_pre_chain=foreign_pre_chain)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(log_level)

    # 1. A log file, written right away (a disk write does not hang).
    path = log_path or log_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(log_level)
        fh.setFormatter(formatter(file_renderer))
        root.addHandler(fh)
    except OSError:
        pass  # a read-only folder: console only

    # 2. The console, never written from the calling (GUI) thread: a paused console window (a click in it
    #    with QuickEdit on, or the Pause key) blocks every write to it, and a blocked GUI thread is a hung
    #    app (2026-10-02). Records are formatted here and written by a listener thread; when the console
    #    stays blocked the bounded queue fills and later records are dropped from the console only.
    if console is not None:
        stream = logging.StreamHandler(console)
        stream.setFormatter(logging.Formatter("%(message)s"))
        q: "queue.Queue[logging.LogRecord]" = queue.Queue(maxsize=10_000)
        qh = _DroppingQueueHandler(q)
        qh.setLevel(log_level)
        qh.setFormatter(formatter(renderer))
        root.addHandler(qh)
        global _listener
        if _listener is not None:
            _listener.stop()
        _listener = logging.handlers.QueueListener(q, stream)
        _listener.start()
        atexit.register(_stop_listener)

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Reduce noise from third-party loggers (semantic levels: keep app logs focused)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


_listener: Optional[logging.handlers.QueueListener] = None


class _DroppingQueueHandler(logging.handlers.QueueHandler):
    """Hands records to the console's listener thread; never waits (a full queue drops the record)."""

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            pass


def _stop_listener() -> None:
    if _listener is not None:
        try:
            _listener.stop()
        except Exception:
            pass


def log_file() -> Path:
    """``logs/sam-mask-studio.log`` in the app folder (rotated at 2 MB, 3 kept)."""
    return Path(__file__).resolve().parents[1] / "logs" / "sam-mask-studio.log"


def install_qt_message_handler() -> None:
    """Qt's own warnings into this log instead of straight to stderr (where a paused console would hang
    the GUI thread). The same message is logged once, then only counted."""
    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

    seen: dict = {}
    log = structlog.get_logger("qt")
    levels = {QtMsgType.QtDebugMsg: "debug", QtMsgType.QtInfoMsg: "info", QtMsgType.QtWarningMsg: "warning",
              QtMsgType.QtCriticalMsg: "error", QtMsgType.QtFatalMsg: "critical"}

    def handler(kind, _context, message) -> None:
        key = (kind, message)
        n = seen.get(key, 0) + 1
        seen[key] = n
        if n == 1 or n in (10, 100, 1000):
            getattr(log, levels.get(kind, "warning"))("qt_message", message=message, **({"times": n} if n > 1 else {}))

    qInstallMessageHandler(handler)


def disable_console_quickedit() -> bool:
    """Windows: turn QuickEdit off for the console this app runs in (if any), so a stray click in that
    window does not start a selection, which pauses the console's output. True when it was changed."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        if not k.GetConsoleWindow():
            return False
        h = k.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = wintypes.DWORD()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        new = (mode.value | 0x0080) & ~0x0040  # ENABLE_EXTENDED_FLAGS on, ENABLE_QUICK_EDIT_MODE off
        return new != mode.value and bool(k.SetConsoleMode(h, new))
    except Exception:
        return False


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger for the given module name (Pattern 2).

    Use in every module: logger = get_logger(__name__).
    Log with structured fields: logger.info("event_name", key=value, ...).
    """
    return structlog.get_logger(name)


@contextmanager
def timed_operation(operation: str, logger: Optional[structlog.stdlib.BoundLogger] = None, **extra: Any) -> Iterator[None]:
    """Context manager for timing and logging operations (Pattern 7).

    Usage:
        with timed_operation("load_model", checkpoint_path=path):
            load_model(path)
    """
    log = logger or structlog.get_logger(__name__)
    start = time.perf_counter()
    log.debug("operation_started", operation=operation, **extra)
    try:
        yield
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.error(
            "operation_failed",
            operation=operation,
            duration_ms=round(elapsed_ms, 2),
            error_type=type(e).__name__,
            error_message=str(e),
            **extra,
            exc_info=True,
        )
        raise
    else:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.info("operation_completed", operation=operation, duration_ms=round(elapsed_ms, 2), **extra)
