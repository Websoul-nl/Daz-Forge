import math

import numpy as np
import pytest

from forge.material_converter.iray_optics import (
    DAZ_SWATCH_GAMMA, IRAY_UBER, bake_diffuse_split, diffuse_plan,
)
from forge.material_converter.iray_translation import (
    Transfer, audit_iray_skin_channels, translated_iray_skin_values,
)
from forge.material_converter.pbr_presets import (
    PBRSKIN_SHADER_URL, SurfaceMaterial, build_g9_material_preset, extract_surfaces,
)


PAIR = ("/Runtime/Textures/Trial/Color.png", "/Runtime/Textures/Trial/Weight.png")


@pytest.fixture
def uber():
    return SurfaceMaterial(shader_type=IRAY_UBER, channels={k: {"value": v} for k, v in {
        "Thin Walled": False, "Cutout Opacity": 1, "Refraction Weight": 0,
        "Base Mixing": 0, "Base Color Effect": 1, "Translucency Weight": .60,
        "Metallic Weight": 0, "Diffuse Overlay Weight": 0, "Diffuse Strength": 1, "Diffuse Weight": 1,
        "diffuse": [1, 1, 1], "Diffuse Roughness": .2, "Invert Transmission Normal": True,
        "SSS Reflectance Tint": [1, .9, .8], "SSS Mode": 0, "SSS Amount": .69,
        "SSS Color": [.98, .5, .4], "Scattering Measurement Distance": .12, "SSS Direction": -.65,
        "Transmitted Color": [.98, .8, .7], "Transmitted Measurement Distance": .3,
    }.items()})


@pytest.fixture
def pbr():
    values = {
        "Translucency Enable": True, "diffuse": [1, 1, 1], "Diffuse Roughness": 0,
        "Invert Transmission Normal": False, "Translucency Weight": .8, "Transmission Enable": False,
        "Transmitted Color": [1, 1, 1], "Transmitted Measurement Distance": .12,
        "Sub Surface Enable": False, "Scattering Measurement Distance": .01,
        "SSS Color": [.8, .6, .5], "SSS Direction": 0,
    }
    return SurfaceMaterial(shader_url=PBRSKIN_SHADER_URL, slots={"diffuse": "diffuse"}, channels={
        k: {"value": v, "type": "color" if isinstance(v, list) else "bool" if type(v) is bool else "float"}
        for k, v in values.items()
    })


@pytest.mark.parametrize("mode", [0, 1])
def test_volume_coefficients_and_audit(uber, pbr, mode):
    uber.channels["SSS Mode"]["value"] = mode
    result = translated_iray_skin_values(uber, pbr)
    assert result["Transmission Enable"]["value"] is True
    assert result["Transmitted Color"]["value"] == [.98, .8, .7]
    assert result["Transmitted Measurement Distance"]["value"] == .3
    assert result["Sub Surface Enable"]["value"] is True
    assert result["SSS Direction"]["value"] == -.65
    distance = result["Scattering Measurement Distance"]["value"]
    color = result["SSS Color"]["value"]
    audit = audit_iray_skin_channels(uber, pbr)
    assert distance == .12
    assert audit["SSS Mode"].transfer is Transfer.CALCULATE
    if mode == 0:
        assert -math.log(color[0] ** DAZ_SWATCH_GAMMA) / distance == pytest.approx(.69 / .12)
        assert len(set(color)) == 1
        assert audit["SSS Amount"].transfer is Transfer.CALCULATE
    else:
        assert color == uber.channels["SSS Color"]["value"]
        assert audit["SSS Color"].transfer is Transfer.CALCULATE
        assert audit["SSS Amount"].transfer is Transfer.REVIEW
    assert pbr.channels["Sub Surface Enable"]["value"] is False


@pytest.mark.parametrize("mode", [1, 2])
def test_paired_maps_match_source_diffuse_split_and_round_trip(uber, pbr, mode):
    uber.channels["Base Color Effect"]["value"] = mode
    uber.channels["diffuse"]["value"] = [.8, .9, 1]
    plan = diffuse_plan(uber)
    assert plan is not None
    assert "Translucency Weight" not in translated_iray_skin_values(uber, pbr)
    assert "Translucency Weight" not in translated_iray_skin_values(uber, pbr, baked_pair=(PAIR[0], PAIR[0]))
    rgb = np.array([[[.4, .2, .1], [0, 0, 0]]], dtype=np.float32)
    color, weight = bake_diffuse_split(plan, rgb)
    effective = rgb[0, 0] * np.array([.8, .81, .8]) ** DAZ_SWATCH_GAMMA
    mono = effective.mean() if mode == 1 else effective.max()
    np.testing.assert_allclose(color[0, 0], effective / effective.max(), rtol=2e-6)
    assert weight[0, 0] == pytest.approx(1 - .4 * mono)
    assert weight[0, 1] == 1
    assert np.isfinite(color).all()

    patches = translated_iray_skin_values(uber, pbr, baked_pair=PAIR)
    for shader in (PBRSKIN_SHADER_URL, None):
        doc = build_g9_material_preset(
            {"Head": pbr}, {"Head": "Head"}, asset_id="/People/Genesis 9/Materials/Test.duf",
            shader_url=shader, overrides={"Head": patches},
        )
        saved = extract_surfaces(doc)["Head"]
        for channel, url, gamma in zip(("diffuse", "Translucency Weight"), PAIR, (0, 1), strict=True):
            prop = saved.channels[channel]
            if shader:
                assert prop["image_file"] == url
                assert prop["default_image_gamma"] == gamma
            else:
                image = saved.images[prop["image"].removeprefix("#")]
                assert image["map"][0]["url"] == url
                assert image["map_gamma"] == gamma
    audit = audit_iray_skin_channels(uber, pbr, baked_pair=PAIR)
    assert audit["SSS Reflectance Tint"].transfer is Transfer.CALCULATE
    assert audit["Base Color Effect"].transfer is Transfer.CALCULATE


def test_scatter_only_keeps_scalar_without_replacing_color_map(uber, pbr):
    uber.channels["Base Color Effect"]["value"] = 0
    result = translated_iray_skin_values(uber, pbr)
    assert result["Translucency Weight"]["value"] == .6
    assert result["Invert Transmission Normal"]["value"] is True
    assert result["Diffuse Roughness"]["value"] == .2
    assert "diffuse" not in result


@pytest.mark.parametrize("name,change", [
    ("Thin Walled", {"value": True}),
    ("Refraction Weight", {"value": .5}),
    ("Translucency Weight", {"image": "#mapped"}),
    ("Cutout Opacity", {"value": .5}),
])
def test_unverified_volumes_and_splits_fall_back(uber, pbr, name, change):
    uber.channels[name].update(change)
    result = translated_iray_skin_values(uber, pbr, baked_pair=PAIR)
    assert "SSS Color" not in result
    assert "Transmission Enable" not in result
    assert "diffuse" not in result
    assert "Translucency Weight" not in result


def test_unsupported_image_transform_does_not_prevent_volume_transfer(uber, pbr):
    uber.channels["diffuse"]["image_modification"] = {"horizontal_tiles": 2}
    result = translated_iray_skin_values(uber, pbr, baked_pair=PAIR)
    assert "SSS Color" in result
    assert "Translucency Weight" not in result
