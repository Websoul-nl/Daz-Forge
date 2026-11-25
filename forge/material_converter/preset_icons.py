"""Preserve original DAZ preset art and render missing sidecars."""

from pathlib import Path
import shutil

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QImage, QPainter


def _caption(painter: QPainter, rect: QRectF, text: str, size: int, color: QColor) -> None:
    font = QFont("Segoe UI")
    font.setBold(True)
    while size > 1:
        font.setPixelSize(size)
        if QFontMetricsF(font).horizontalAdvance(text) <= rect.width():
            break
        size -= 1
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


def original_preset_icons(source_preset: Path | None) -> tuple[Path | None, Path | None]:
    if source_preset is None:
        return None, None
    if source_preset.suffix.casefold() != ".duf" or not source_preset.is_file():
        raise ValueError(f"Expected an original DUF preset: {source_preset}")
    icon = next((p for p in (source_preset.with_suffix(".png"), Path(f"{source_preset}.png"))
                 if p.is_file()), None)
    tip = source_preset.with_suffix(".tip.png")
    return icon, tip if tip.is_file() else None


def write_preset_icons(
    preset: Path,
    title: str,
    category: str,
    *,
    accent: str,
    artwork: Path | None = None,
    symbol: str = "",
    source_preset: Path | None = None,
) -> tuple[Path, Path]:
    """Copy the matching source icon and tip, rendering only missing images."""
    if preset.suffix.casefold() != ".duf" or not preset.is_file():
        raise ValueError(f"Expected an existing DUF preset: {preset}")
    paths = preset.with_suffix(".png"), preset.with_suffix(".tip.png")
    if any(path.exists() for path in paths):
        raise FileExistsError(f"Preset artwork already exists for {preset}")
    originals = original_preset_icons(source_preset)
    photo = QImage()
    text_available = isinstance(QGuiApplication.instance(), QGuiApplication) and bool(QFontDatabase.families())
    if None in originals and artwork is not None:
        photo = QImage(str(artwork))
        if photo.isNull():
            raise ValueError(f"Cannot read preset artwork: {artwork}")

    color = QColor(accent)
    for path, original, size in zip(paths, originals, (91, 256), strict=True):
        if original is not None:
            shutil.copyfile(original, path)
            continue
        image = QImage(size, size, QImage.Format.Format_RGB32)
        image.fill(QColor("#263039"))
        with QPainter(image) as painter:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.scale(size / 256, size / 256)
            if not photo.isNull():
                # Show a centered cover crop; both resolutions use the same framing.
                width = min(photo.width(), photo.height() * 256 / 186)
                height = width * 186 / 256
                painter.drawImage(
                    QRectF(0, 0, 256, 186), photo,
                    QRectF((photo.width()-width)/2, (photo.height()-height)/2, width, height),
                )
            else:
                painter.fillRect(QRectF(18, 30, 7, 126), color)
                if text_available:
                    _caption(painter, QRectF(36, 22, 200, 145), symbol or category, 71, color)
                else:
                    painter.fillRect(QRectF(89, 49, 88, 88), color)
                    painter.fillRect(QRectF(108, 68, 50, 50), QColor("#263039"))
            painter.fillRect(QRectF(0, 186, 256, 70), QColor("#182027"))
            painter.fillRect(QRectF(0, 186, 256, 3), color)
            if text_available:
                _caption(painter, QRectF(12, 193, 231, 21), category.upper(), 16, color)
                _caption(painter, QRectF(12, 214, 231, 35), title, 30, QColor("#f5f7f8"))
        if not image.save(str(path), "PNG"):
            raise OSError(f"Could not write preset thumbnail: {path}")
    return paths
