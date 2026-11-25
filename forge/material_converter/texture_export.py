"""Compact delivery encoding for color maps; keep authored/baked masters intact."""

from pathlib import Path

import numpy as np
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColorSpace, QImage, QImageReader, QImageWriter


def export_color_jpeg(
    source: Path,
    destination: Path,
    *,
    quality: int = 90,
    uv_coverage_alpha: bool = False,
) -> None:
    """Encode an sRGB color-only map. Never infer that binary alpha is disposable."""
    if not isinstance(quality, int) or not 1 <= quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100.")
    if destination.suffix.casefold() not in {".jpg", ".jpeg"}:
        raise ValueError("Use a .jpg or .jpeg destination.")
    reader = QImageReader(str(source))
    image = reader.read()
    if image.isNull():
        raise ValueError(f"Cannot read color map: {reader.errorString()}")
    if image.hasAlphaChannel():
        rgba = image.convertToFormat(QImage.Format.Format_RGBA64)
        stride = rgba.bytesPerLine() // 2
        pixels = np.frombuffer(rgba.constBits(), dtype=np.uint16).reshape(rgba.height(), stride)
        alpha = pixels[:, 3:rgba.width() * 4:4]
        opaque = alpha == 65535
        if not opaque.all() and not (
            uv_coverage_alpha and opaque.any() and np.all(opaque | (alpha == 0))
        ):
            raise ValueError("JPEG would discard meaningful alpha from this color map.")

    srgb = QColorSpace(QColorSpace.NamedColorSpace.SRgb)
    if image.colorSpace().isValid() and image.colorSpace() != srgb:
        image = image.convertedToColorSpace(srgb)
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    image.setColorSpace(srgb)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QImageWriter(buffer, b"jpeg")
    writer.setQuality(quality)
    if not writer.write(image):
        raise OSError(writer.errorString())
    with destination.open("xb") as stream:
        stream.write(bytes(buffer.data()))
