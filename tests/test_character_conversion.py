import json
import os
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QMimeData, QPointF, QTimer, Qt, QUrl
from PySide6.QtGui import QDropEvent, QFontDatabase
from PySide6.QtWidgets import QApplication

from forge.material_converter.atlas import write_pixels
from forge.material_converter.character import (
    PBR, UBER, SHADER_FILE, SkinSource, TransferBundle, convert_character, has_bundled_transfers, inspect_skin,
)
from forge.material_converter.layered_color import as_native_lie_preset
from forge.material_converter.pbr_presets import SurfaceMaterial, build_g9_material_preset, extract_surfaces, read_dson
from forge.material_converter.product import load_character_product
from forge.material_converter.source_iray import IRAY_UBER, build_g9_iray_uber_preset
from forge.ui.main_window import MainWindow
from forge.ui.pages.character_conversion_page import CharacterConversionPage


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    if not QFontDatabase.families() and "WINDIR" in os.environ:
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts/segoeuib.ttf"))
    return app


@pytest.fixture
def trial(tmp_path, qapp):
    library = tmp_path / "Library"
    texture = library / "Runtime/Textures/Skin.png"
    texture.parent.mkdir(parents=True)
    pixels = np.full((4, 4, 4), .5, np.float32)
    pixels[..., 3] = 1
    write_pixels(texture, pixels, True)
    skin = SurfaceMaterial(shader_type=IRAY_UBER, channels={
        "diffuse": {"value": [1, 1, 1], "image_file": "/Runtime/Textures/Skin.png", "type": "color", "mappable": True},
        "Translucency Weight": {"value": 0},
        "Top Coat Weight": {"value": 0},
    }, slots={"diffuse":"diffuse"})
    zones = dict.fromkeys(("Face", "Torso", "Arms", "Legs"), skin)
    presets = library / "People"
    presets.mkdir()
    uber = build_g9_iray_uber_preset(zones, asset_id="/People/Iray.duf")
    pbr = build_g9_material_preset(zones, {z:z for z in zones}, asset_id="/People/PBR.duf")
    for data in (uber, pbr):
        for material in data["scene"]["materials"]:
            material["uv_set"] = "/data/Daz 3D/Genesis 8/Male/UV Sets/DAZ 3D/Base/Base Male.dsf#Base Male"
    (presets / "Iray.duf").write_text(json.dumps(uber))
    (presets / "PBR.duf").write_text(json.dumps(pbr))
    schema_file = library / SHADER_FILE
    schema_file.parent.mkdir(parents=True)
    schema = build_g9_material_preset({"PBRSkin": skin}, {"PBRSkin":"PBRSkin"}, asset_id="/People/Schema.duf")
    schema_file.write_text(json.dumps(schema))
    transfer = tmp_path / "Bundles"
    transfer.mkdir()
    np.savez(transfer / "tile.npz", uv=np.zeros((4, 4, 2), np.uint16), source_id=np.ones((4, 4), np.uint8))
    profile = {"schema": "daz-forge-uv-transfer/1", "generation": "G8", "source_uv": "Base Male",
               "target_uv": "Base Multi UDIM",
               "parts": {z: {"file":"tile.npz", "slots":{"1": donor}} for z, donor in (
                   ("Head", "Face"), ("Body", "Torso"), ("Arms", "Arms"), ("Legs", "Legs"),
               )}}
    (transfer / "G8 Base Male.json").write_text(json.dumps(profile))
    out = tmp_path / "Exports"
    out.mkdir()
    return presets, library, transfer, out


def test_uber_primary_is_real_uber_and_pbr_requires_opt_in(trial):
    presets, *args = trial
    result = convert_character(presets/"Iray.duf", *args, character_name="Primary")
    assert len(result.presets) == 1
    surfaces = extract_surfaces(read_dson(result.folder / "Content" / result.presets[0]))
    assert all(s.shader_type == IRAY_UBER for s in surfaces.values())
    with ZipFile(result.archive) as z:
        assert z.testzip() is None
        assert all("Content/" + name in z.namelist() for name in result.presets)
    assert json.loads(result.report.read_text())["review"]
    with pytest.raises(FileExistsError):
        convert_character(presets/"Iray.duf", *args, character_name="Primary")
    optional = convert_character(presets/"Iray.duf", *args, character_name="With PBR", include_pbr=True)
    assert [Path(path).name for path in optional.presets] == ["01 Skin - Iray Uber.duf", "01 Skin - PBRSkin.duf"]


def test_pbr_does_not_export_uber_even_if_option_supplied(trial):
    presets, *args = trial
    result = convert_character(presets/"PBR.duf", *args, character_name="PBR source", include_pbr=True)
    assert [Path(path).name for path in result.presets] == ["01 Skin - PBRSkin.duf"]


def test_optional_route_failure_keeps_the_uber_export_and_records_review(trial):
    presets, library, transfer, out = trial
    (library / SHADER_FILE).unlink()
    result = convert_character(presets/"Iray.duf", library, transfer, out,
                               character_name="No shader", include_pbr=True)
    assert [Path(path).name for path in result.presets] == ["01 Skin - Iray Uber.duf"]
    report = json.loads(result.report.read_text())
    assert any(r["route"] == PBR and r["target"] == "Optional skin" for r in report["review"])


def _make_overlay(presets):
    source = SurfaceMaterial(
        channels={"diffuse": {"image": "#paint"}},
        slots={"diffuse":"diffuse"},
        images={"paint": {"map": [
            {"url": "/Runtime/Textures/SourcePlaceholder.jpg", "operation": "alpha_blend", "transparency": 1},
            {"url": "/Runtime/Textures/Skin.png", "operation": "alpha_blend", "transparency": .6},
        ]}},
    )
    variant = presets / "Variant"
    variant.mkdir()
    fixed = build_g9_material_preset({"Face":source}, {"Face":"Face"}, asset_id="/People/T04.duf", shader_url=None)
    (variant / "T04.duf").write_text(json.dumps(as_native_lie_preset(fixed)))
    return variant / "T04.duf"


def test_native_overlay_is_exported_by_type_and_uses_converted_skin(trial):
    presets, library, transfer, out = trial
    paint = _make_overlay(presets)
    result = convert_character(presets/"Iray.duf", library, transfer, out, character_name="Paint",
                               variants_folder=paint.parent)
    [base, overlay] = (read_dson(result.folder / "Content" / path) for path in result.presets)
    assert overlay["asset_info"]["type"] == "preset_layered_image"
    assert extract_surfaces(overlay)["Head"].channels.keys() == {"diffuse"}
    [definition] = overlay["image_library"]
    [underlay, ink] = definition["map"]
    assert underlay["url"] in {m["url"] for image in base["image_library"] for m in image["map"]}
    assert ink["transparency"] == .6


def _make_product(presets, library):
    overlay = _make_overlay(presets)
    (overlay.parent / "Unlisted.duf").write_bytes(overlay.read_bytes())
    actor = read_dson(presets / "Iray.duf")
    actor["asset_info"]["type"] = "character"
    (presets / "Actor.duf").write_text(json.dumps(actor))
    dsx = library / "Runtime/Support/Example.dsx"
    dsx.parent.mkdir()
    dsx.write_text("""<ContentDBInstall><Products><Product VALUE="Example">
      <Assets><Asset VALUE="/People/Iray.duf"/><Asset VALUE="People/PBR.duf"/>
        <Asset VALUE="People/Actor.duf"/><Asset VALUE="People/Variant/T04.duf"/><Asset VALUE="People/Missing.duf"/>
        <Asset VALUE="People/%2e%2e/Outside.duf"/></Assets>
      </Product></Products></ContentDBInstall>""")
    return dsx


def test_dsx_uses_bundled_transfer_and_only_exports_declared_variants(trial, monkeypatch):
    presets, library, transfer, out = trial
    dsx = _make_product(presets, library)
    product = load_character_product(dsx)
    assert [row.path.name for row in product.skins] == ["Iray.duf", "PBR.duf"]
    assert [path.name for path in product.variants] == ["T04.duf"]
    assert product.missing == ("People/Missing.duf",)
    nested = transfer / "g8-base-male-to-g9"
    nested.mkdir()
    (transfer / "tile.npz").rename(nested / "tile.npz")
    (transfer / "G8 Base Male.json").rename(nested / "manifest.json")
    monkeypatch.setattr("forge.material_converter.character.BUNDLED_TRANSFERS", transfer)
    result = convert_character(presets/"Iray.duf", library, None, out, character_name="Product", product_dsx=dsx)
    assert [Path(path).name for path in result.presets] == ["01 Skin - Iray Uber.duf", "T04.duf"]
    report = json.loads(result.report.read_text())
    assert report["product_dsx"] == str(dsx)
    assert any("Missing.duf" in row["target"] for row in report["review"])
    assert any("PBR.duf" in row["target"] for row in report["review"])


def test_transfer_discovery_accepts_old_and_new_paths_and_prefers_new(trial):
    _, _, transfer, _ = trial
    source = SkinSource("G8", "Base Male", UBER, None, False)
    legacy = transfer / "G8 Base Male.json"
    assert TransferBundle(transfer, source).manifest == legacy
    nested = transfer / "g8-base-male-to-g9"
    nested.mkdir()
    manifest = nested / "manifest.json"
    manifest.write_bytes(legacy.read_bytes())
    assert has_bundled_transfers(transfer, source)
    assert TransferBundle(transfer, source).manifest == legacy
    (nested / "tile.npz").write_bytes((transfer / "tile.npz").read_bytes())
    assert has_bundled_transfers(transfer, source)
    for location in (transfer, nested, manifest):
        bundle = TransferBundle(location, source)
        assert bundle.manifest == manifest
        assert bundle.load("Head")[2] == {1: "Face"}
    assert TransferBundle(legacy, source).manifest == legacy
    with pytest.raises(ValueError, match="does not match"):
        TransferBundle(nested, SkinSource("G8.1", "Base Male", UBER, None, False))


def test_character_tab_offers_override_for_missing_specific_bundle(trial, monkeypatch):
    presets, _, transfer, _ = trial
    monkeypatch.setattr("forge.ui.pages.character_conversion_page.BUNDLED_TRANSFERS", transfer)
    page = CharacterConversionPage()
    page.set_source(presets / "Iray.duf")
    assert not page.form.isRowVisible(page.transfer_row)
    (transfer / "tile.npz").unlink()
    page.inspect()
    assert page.form.isRowVisible(page.transfer_row)
    page.close()


def test_character_tab_accepts_dsx_drop_and_requires_a_choice(trial):
    presets, library, _, _ = trial
    dsx = _make_product(presets, library)
    window = MainWindow()
    page = window.character_conversion_page
    window.tabs.setCurrentWidget(page)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(dsx))])
    drop = QDropEvent(QPointF(), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    window.dropEvent(drop)
    assert drop.isAccepted()
    assert page.skin_choices.count() == 2 and not page.convert_button.isEnabled()
    page.skin_choices.setCurrentIndex(1)
    assert page.convert_button.isEnabled() and page.route.text() == PBR
    window.close()


def test_missing_uv_needs_confirmation_and_mixed_uv_rejected(trial):
    doc = read_dson(trial[0]/"Iray.duf")
    for row in doc["scene"]["materials"]:
        row.pop("uv_set")
    with pytest.raises(ValueError, match="does not state its UVs"):
        inspect_skin(doc)
    assert inspect_skin(doc, "Base Male").routes == (UBER, PBR)
    rows = doc["scene"]["materials"]
    for row in rows:
        row["uv_set"] = "/data/Daz 3D/Genesis 8/Male/Base.dsf#Base Male"
    rows[1]["uv_set"] = "/data/Daz 3D/Genesis 8/Female/Base.dsf#Base Female"
    with pytest.raises(ValueError, match="mixed UVs"):
        inspect_skin(doc)


def test_export_choices_follow_source_shader(trial):
    page = CharacterConversionPage()
    page.preset.setText(str(trial[0]/"Iray.duf"))
    page.inspect()
    assert page.route.text() == UBER
    assert not page.include_pbr.isHidden() and not page.include_pbr.isChecked()
    page.include_pbr.setChecked(True)
    page.preset.setText(str(trial[0]/"PBR.duf"))
    page.inspect()
    assert page.route.text() == PBR
    assert page.include_pbr.isHidden() and not page.include_pbr.isChecked()
    page.close()


@pytest.mark.parametrize("with_bundle", (False, True))
def test_character_tab_exports_on_worker_and_displays_review(trial, monkeypatch, with_bundle):
    presets, library, transfer, out = trial
    root = transfer if with_bundle else transfer / "Absent"
    monkeypatch.setattr("forge.ui.pages.character_conversion_page.BUNDLED_TRANSFERS", root)
    monkeypatch.setattr("forge.material_converter.character.BUNDLED_TRANSFERS", root)
    page = CharacterConversionPage()
    page.preset.setText(str(presets/"Iray.duf"))
    page.name.setText("Worker Test")
    page.library.setText(str(library))
    page.transfer.setText(str(transfer / "Stale" if with_bundle else transfer))
    page.output.setText(str(out))
    page.inspect_button.click()
    page.convert_button.click()
    loop = QEventLoop()
    page.thread.finished.connect(loop.quit)
    QTimer.singleShot(15_000, loop.quit)
    loop.exec()
    if page.is_running():
        page.thread.quit()
        page.thread.wait()
        pytest.fail(f"Character export did not finish: {page.status.text()}")
    assert page.open_button.isEnabled(), page.status.text()
    assert page.report_path.is_file()
    assert "No variant folder selected" in page.review.toPlainText()
    page.close()
