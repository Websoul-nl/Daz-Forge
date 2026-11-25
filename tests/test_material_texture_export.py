from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

from forge.material_converter.texture_export import export_color_jpeg


def source_image(path: Path, alpha: int = 255) -> bytes:
    image = QImage(32, 24, QImage.Format.Format_RGBA64)
    image.fill(QColor(160, 90, 60))
    image.setPixelColor(0, 0, QColor(160, 90, 60, alpha))
    assert image.save(str(path))
    return path.read_bytes()


def test_opaque_color_exports_at_full_dimensions_and_leaves_master_unchanged(tmp_path):
    source = tmp_path / "master.png"
    original = source_image(source)
    dest = tmp_path / "color.jpg"
    export_color_jpeg(source, dest)
    loaded = QImage(str(dest))
    assert (loaded.width(), loaded.height()) == (32, 24)
    assert not loaded.hasAlphaChannel()
    assert abs(loaded.pixelColor(10, 10).red() - 160) <= 3
    assert source.read_bytes() == original
    with pytest.raises(FileExistsError):
        export_color_jpeg(source, dest)


@pytest.mark.parametrize(("alpha", "allow"), [(0, False), (128, False), (128, True)])
def test_jpeg_rejects_alpha_without_explicit_binary_coverage(tmp_path, alpha, allow):
    source = tmp_path / "master.png"
    source_image(source, alpha)
    dest = tmp_path / "color.jpg"
    with pytest.raises(ValueError, match="alpha"):
        export_color_jpeg(source, dest, uv_coverage_alpha=allow)
    assert not dest.exists()


def test_jpeg_can_drop_explicit_binary_uv_coverage_alpha(tmp_path):
    source = tmp_path / "master.png"
    source_image(source, alpha=0)
    dest = tmp_path / "color.jpg"
    export_color_jpeg(source, dest, uv_coverage_alpha=True)
    assert not QImage(str(dest)).hasAlphaChannel()
