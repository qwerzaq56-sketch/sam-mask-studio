"""SAM Mask Studio entry point: ``python -m src.main [image_folder] [--debug]``."""

import argparse
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from src.logging_config import configure_logging, disable_console_quickedit, get_logger, install_qt_message_handler, log_file
from src.version import app_version

logger = get_logger(__name__)


def ensure_std_streams() -> None:
    """Started without a console and without redirected output (SplatBatch's CREATE_NO_WINDOW, pythonw), stdout
    and stderr are None, and the first progress bar (SAM2's tqdm "frame loading") fails the propagation."""
    import os
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def main() -> None:
    ensure_std_streams()
    parser = argparse.ArgumentParser(description="SAM Mask Studio — SAM3 finds, SAM2 cuts and refines")
    parser.add_argument("folder", nargs="?", help="Image folder to open")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--cpu", action="store_true",
                        help="Run SAM2 / SAM3 on the CPU this time (leaves the GPU to a training; much slower)")
    args = parser.parse_args()
    configure_logging(debug=args.debug)
    install_qt_message_handler()  # Qt warnings into the log, never straight to the console
    quickedit_off = disable_console_quickedit()  # a click in the console window must not pause it
    logger.info("app_started", version=app_version(), log_level="DEBUG" if args.debug else "INFO", log_file=str(log_file()),
                console_quickedit_off=quickedit_off)

    from src.app.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("SAM Mask Studio")
    app.setApplicationVersion(app_version())
    window = MainWindow(cpu=args.cpu)
    window.show()
    if args.folder:
        window.open_folder(Path(args.folder))
    elif not Path(window.settings.sam2_checkpoint).is_file():
        window.show_settings()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
