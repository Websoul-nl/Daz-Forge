import pytest

from forge.material_converter.iray_translation import (
    Transfer, audit_iray_skin_channels, translated_iray_skin_tints, translated_iray_skin_values,
)
from forge.material_converter.pbr_presets import SurfaceMaterial, build_g9_material_preset, extract_surfaces


def test_translation_carries_values_without_source_maps_or_legacy_enums():
    source = SurfaceMaterial(shader_type="studio/material/uber_iray", channels={
        "Top Coat Color": {"value": [.75, .88, 1], "image_file": "/Runtime/Textures/G8/coat.jpg"},
        "Transmitted Color": {"value": [.98, .48, .35]},
        "Top Coat Color Effect": {"value": 1},
        "Top Coat Weight": {"value": .15},
        "Translucency Color": {"value": [1, 1, 1], "image": "#legacy"},
        "Glossy Roughness": {"value": .6},
        "Metallicity": {"value": 0},
    })
    target = SurfaceMaterial(channels={
        "Top Coat Color": {"value": [1, 1, 1], "image_file": "/Runtime/Textures/G9/coat.jpg"},
        "Transmitted Color": {"value": [0, 0, 0]},
        "Top Coat Weight": {"value": .25},
        "Metallicity": {"value": 0},
    })
    patches = translated_iray_skin_tints(source, target)
    assert patches == {"Top Coat Color": {"value": [.75, .88, 1]}, "Transmitted Color": {"value": [.98, .48, .35]}}
    patches["Top Coat Color"]["value"][0] = 0
    assert source.channels["Top Coat Color"]["value"][0] == .75
    assert target.channels["Top Coat Color"]["image_file"].endswith("G9/coat.jpg")
    audit = {k: v.transfer for k, v in audit_iray_skin_channels(source, target).items()}
    assert audit == {
        "Top Coat Color": Transfer.TINT, "Transmitted Color": Transfer.TINT,
        "Top Coat Color Effect": Transfer.UNMAPPED, "Top Coat Weight": Transfer.REVIEW,
        "Translucency Color": Transfer.REMAP, "Glossy Roughness": Transfer.REVIEW,
        "Metallicity": Transfer.REVIEW,
    }


@pytest.mark.parametrize("shader,value", [
    ("studio/material/daz_brick", [0., .5, 1.]),
    ("studio/material/uber_iray", [0., .5, float("nan")]),
    ("studio/material/uber_iray", [True, .5, 1.]),
    ("studio/material/uber_iray", [.5, 1.]),
])
def test_non_uber_and_invalid_tints_are_not_translated(shader, value):
    source = SurfaceMaterial(shader_type=shader, channels={"Top Coat Color": {"value": value}})
    target = SurfaceMaterial(channels={"Top Coat Color": {"value": [1, 1, 1]}})
    assert translated_iray_skin_tints(source, target) == {}


@pytest.mark.parametrize("coat,translucency,expected", [
    (0, .6, {"Top Coat Weight": 0, "Top Coat Enable": False}),
    (.25, 0, {"Translucency Weight": 0}),
    (0, 0, {"Top Coat Weight": 0, "Top Coat Enable": False, "Translucency Weight": 0}),
    (.25, .6, {}),
    (None, None, {}),
    (False, False, {}),
])
def test_off_states_are_independent_and_survive_preset_export(coat, translucency, expected):
    source = SurfaceMaterial(shader_type="studio/material/uber_iray", channels={
        "Top Coat Weight": {"value": coat},
        "Translucency Weight": {"value": translucency},
    })
    baseline = {"Top Coat Weight": .25, "Top Coat Enable": True,
                "Translucency Weight": .6, "Translucency Enable": True}
    target = SurfaceMaterial(channels={name: {"value": value} for name, value in baseline.items()})
    patches = translated_iray_skin_values(source, target)
    assert patches == {name: {"value": value} for name, value in expected.items()}
    audit = audit_iray_skin_channels(source, target)
    for channel in source.channels:
        assert audit[channel].transfer is (Transfer.ZERO if channel in expected else Transfer.REVIEW)
    preset = build_g9_material_preset(
        {"Head": target}, {"Head": "Head"}, asset_id="/People/Genesis 9/Materials/Test.duf",
        overrides={"Head": patches},
    )
    saved = extract_surfaces(preset)["Head"].channels
    assert {name: saved[name]["value"] for name in baseline} == baseline | expected


def test_mapped_and_non_uber_zero_are_not_translated():
    target = SurfaceMaterial(channels={"Top Coat Weight": {}, "Top Coat Enable": {}, "Translucency Weight": {}})
    source = SurfaceMaterial(shader_type="studio/material/uber_iray", channels={
        "Top Coat Weight": {"value": 0, "image": "#coat"},
        "Translucency Weight": {"value": 0, "image_file": "/Runtime/Textures/G8/translucency.png"},
    })
    assert translated_iray_skin_values(source, target) == {}
    source.shader_type = "studio/material/daz_brick"
    source.channels["Top Coat Weight"] = {"value": 0}
    assert translated_iray_skin_values(source, target) == {}
