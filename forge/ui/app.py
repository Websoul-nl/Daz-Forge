from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtWidgets import QApplication

from forge.settings import load_settings
from forge.ui.main_window import MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the Daz Forge review UI.")
    parser.add_argument("source", nargs="?", type=Path, help="Optional product folder or zip to analyze on launch.")
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.json"
    window = MainWindow(app_settings=load_settings(settings_path), settings_path=settings_path)
    if args.source is not None:
        window.set_source_path(args.source)
        window.analyze_current_source()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
