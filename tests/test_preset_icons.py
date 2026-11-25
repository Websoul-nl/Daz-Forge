import os
from zipfile import ZipFile

import pytest
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtWidgets import QApplication

from forge.material_converter.package import build_material_package
from forge.material_converter.preset_icons import write_preset_icons


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families() and "WINDIR" in os.environ:
        QFontDatabase.addApplicationFont(os.path.join(os.environ["WINDIR"], "Fonts", "segoeuib.ttf"))
    return app


def test_icons_follow_duf_name_and_ship_in_package(qt_app, tmp_path):
    root = tmp_path / "Content"
    product = "People/Genesis 9/Materials/Example"
    preset = root / product / "Native Detail.duf"
    preset.parent.mkdir(parents=True)
    preset.write_text('{"asset_info": {"type": "preset_material"}, "scene": {}}', encoding="utf-8")
    artwork = tmp_path / "art.png"
    photo = QImage(256, 256, QImage.Format.Format_RGB32)
    photo.fill(0xff9a6145)
    assert photo.save(str(artwork))

    icon, tip = write_preset_icons(
        preset, "G9 Native", "Normals", accent="#80c7c7", artwork=artwork,
    )
    assert (icon.name, tip.name) == ("Native Detail.png", "Native Detail.tip.png")
    for path, size in ((icon, 91), (tip, 256)):
        image = QImage(str(path))
        assert image.size().width() == image.size().height() == size
        assert image.pixelColor(size//2, size//3) == photo.pixelColor(0, 0)
        assert sum(
            image.pixelColor(x, y).value() > 150
            for y in range(int(size*.84), int(size*.96)) for x in range(size)
        ) > size
    original = icon.read_bytes()
    with pytest.raises(FileExistsError):
        write_preset_icons(preset, "Different", "Normals", accent="#ffffff")
    assert icon.read_bytes() == original

    archive_path = tmp_path / "example.zip"
    build_material_package(root, product, archive_path, product_name="Example")
    with ZipFile(archive_path) as archive:
        for path in (icon, tip):
            assert archive.read(f"Content/{product}/{path.name}") == path.read_bytes()


@pytest.mark.parametrize("extension", [".png", ".duf.png"])
def test_copies_original_pair_to_converted_name_without_rendering(tmp_path, extension):
    source = tmp_path / "Original.duf"
    target = tmp_path / "Converted.duf"
    source.touch()
    target.touch()
    (tmp_path / f"Original{extension}").write_bytes(b"source icon")
    source.with_suffix(".tip.png").write_bytes(b"source tip")
    icon, tip = write_preset_icons(target, "", "", accent="", source_preset=source)
    assert icon.read_bytes() == b"source icon"
    assert tip.read_bytes() == b"source tip"


def test_keeps_original_icon_when_tip_is_missing(qt_app, tmp_path):
    source = tmp_path / "Original.duf"
    target = tmp_path / "Converted.duf"
    source.touch()
    target.touch()
    source.with_suffix(".png").write_bytes(b"source icon")
    icon, tip = write_preset_icons(target, "Converted", "Option", accent="#80c7c7", source_preset=source)
    assert icon.read_bytes() == b"source icon"
    assert QImage(str(tip)).width() == 256
