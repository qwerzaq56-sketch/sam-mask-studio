"""SAM Mask Studio entry point: ``python -m src.main [image_folder] [--debug]``."""

import argparse
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from src.logging_config import configure_logging, get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="SAM Mask Studio — SAM3 finds, SAM2 cuts and refines")
    parser.add_argument("folder", nargs="?", help="Image folder to open")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    configure_logging(debug=args.debug)
    logger.info("app_started", log_level="DEBUG" if args.debug else "INFO")

    from src.app.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("SAM Mask Studio")
    window = MainWindow()
    window.show()
    if args.folder:
        window.open_folder(Path(args.folder))
    elif not Path(window.settings.sam2_checkpoint).is_file():
        window.show_settings()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
