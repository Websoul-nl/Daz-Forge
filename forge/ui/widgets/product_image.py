from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel


class ProductImageDropZone(QLabel):
    def __init__(self, on_image_selected: Callable[[Path], None], parent=None) -> None:
        super().__init__(parent)
        self.on_image_selected = on_image_selected
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(260)
        self.setText("Drop product image here")
        self.setProperty("imageDropZone", True)

    def set_image_path(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.setPixmap(QPixmap())
            self.setText("Drop product image here")
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.setPixmap(QPixmap())
            self.setText(f"Selected image:\n{path.name}")
            return
        scaled = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.setText("")

    def handle_dropped_path(self, path: Path) -> None:
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            self.on_image_selected(path)

    def dragEnterEvent(self, event) -> None:
        if _event_has_image_url(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        local_path = urls[0].toLocalFile()
        if local_path:
            self.handle_dropped_path(Path(local_path))
            event.acceptProposedAction()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)


def _event_has_image_url(event) -> bool:
    if not event.mimeData().hasUrls():
        return False
    for url in event.mimeData().urls():
        if Path(url.toLocalFile()).suffix.lower() in {".jpg", ".jpeg", ".png"}:
            return True
    return False
