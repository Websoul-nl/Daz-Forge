"""Verify the G8F-to-G9 PBR Skin detail policy in emitted presets."""

from copy import deepcopy

import pytest

from forge.material_converter import SurfaceMaterial, build_g9_skin_preset, extract_surfaces


ASSET_ID = "/People/Genesis 9/Materials/Converted.duf"
DETAIL_DIR = "/Runtime/Textures/Daz/Characters/Genesis9/Base/Skin_Details/"
BUMP = "/Runtime/Textures/Converted/Bump.png"
NORMAL = "/Runtime/Textures/Converted/Normal.png"


def fixture_surface() -> SurfaceMaterial:
    return SurfaceMaterial(channels={
        "Bump Strength": {"value": 5, "image_file": BUMP},
        "Normal Map": {"value": 0.7, "image": "#source-normal"},
        "Detail Enable": {"value": False},
        "Detail Weight": {"value": 0.6, "image_file": BUMP},
        "Detail Normal Map": {"value": 0.2, "image_file": NORMAL},
        "Detail Horizontal Tiles": {"value": 80},
        "Detail Vertical Tiles": {"value": 70},
        "Detail Horizontal Offset": {"value": 0.5},
        "Detail Vertical Offset": {"value": 0.5},
        "Detail Specular Roughness Mult": {"value": 0.25, "image_file": BUMP},
        "diffuse": {"value": [0.5, 0.3, 0.2], "image_file": "/Runtime/Textures/Converted/Color.png"},
        "Top Coat Roughness": {"value": 0.55},
    }, slots={"diffuse": "diffuse"}, images={
        "source-normal": {"id": "source-normal", "map_gamma": 1, "map": [{"url": NORMAL}]},
    })


@pytest.mark.parametrize(("target", "filename"), [
    ("Head", "Genesis9_Head_NM_1001.jpg"),
    ("Body", "Genesis9_BodyF_NM_1002.jpg"),
    ("Arms", "Genesis9_Arms_NM_1004.jpg"),
    ("Legs", "Genesis9_Legs_NM_1003.jpg"),
    ("Fingernails", "Genesis9_Nails_NM_1005.jpg"),
    ("Toenails", "Genesis9_Nails_NM_1005.jpg"),
    ("Genitalia", "Genesis9_GensF_NM_1001.jpg"),
])
def test_native_default_maps_supported_skin_without_double_detail(target, filename):
    source = {"Source": fixture_surface()}
    snapshot = deepcopy(source)
    preset = build_g9_skin_preset(source, {target: "Source"}, asset_id=ASSET_ID)
    material = extract_surfaces(preset)[target]
    channels = material.channels
    for channel, strength in [
        ("Bump Strength", 0), ("Normal Map", 1), ("Detail Weight", 1),
        ("Detail Specular Roughness Mult", 1),
    ]:
        assert channels[channel]["value"] == strength
        assert channels[channel]["image_file"] is None
        assert "image" not in channels[channel]
    for channel, value in {
        "Bump Enable": True, "Detail Enable": True, "Detail Normal Map Mode": 1,
        "Detail Horizontal Tiles": 1, "Detail Vertical Tiles": 1,
        "Detail Horizontal Offset": 0, "Detail Vertical Offset": 0,
    }.items():
        assert channels[channel]["value"] == value
    assert channels["Detail Normal Map"]["value"] == 1
    assert channels["Detail Normal Map"]["image_file"] == DETAIL_DIR + filename
    assert channels["Detail Normal Map"]["default_image_gamma"] == 1
    assert channels["diffuse"]["image_file"].endswith("/Color.png")
    assert channels["Top Coat Roughness"]["value"] == 0.55
    assert not material.images
    assert source == snapshot


def test_explicit_original_preserves_maps_and_strengths():
    source = fixture_surface()
    preset = build_g9_skin_preset(
        {"Source": source}, {"Body": "Source"}, asset_id=ASSET_ID, detail_mode="original",
        overrides={"Body": {"Bump Strength": {"value": 2}}},
    )
    body = extract_surfaces(preset)["Body"]
    assert body.channels["Bump Strength"] == {"id": "Bump Strength", "value": 2, "image_file": BUMP}
    assert body.channels["Normal Map"]["value"] == 0.7
    ref = body.channels["Normal Map"]["image"].removeprefix("#")
    assert body.images[ref]["map"][0]["url"] == NORMAL
    assert body.channels["Detail Enable"]["value"] is False
    assert body.channels["Detail Horizontal Tiles"]["value"] == 80


def test_native_leaves_non_skin_surfaces_and_unrelated_variant_overrides_alone():
    surfaces = {"Source": fixture_surface()}
    preset = build_g9_skin_preset(
        surfaces, {"Head": "Source", "Mouth Cavity": "Source"},
        asset_id=ASSET_ID, overrides={"Head": {"diffuse": {"value": [1, 0.5, 0]}}},
    )
    materials = extract_surfaces(preset)
    assert set(materials) == {"Head", "Mouth Cavity"}
    assert materials["Head"].channels["diffuse"]["value"] == [1, 0.5, 0]
    assert materials["Mouth Cavity"].channels["Bump Strength"]["image_file"] == BUMP
    assert materials["Mouth Cavity"].channels["Detail Enable"]["value"] is False


def test_native_policy_wins_over_base_bump_override():
    preset = build_g9_skin_preset(
        {"Source": fixture_surface()}, {"Body": "Source"}, asset_id=ASSET_ID,
        overrides={"Body": {
            "Bump Strength": {"current_value": 7, "image_file": BUMP},
            "Normal Map": {"image": "#source-normal"},
        }},
    )
    body = extract_surfaces(preset)["Body"]
    assert body.channels["Bump Strength"]["value"] == 0
    assert body.channels["Normal Map"]["image_file"] is None
    assert not body.images


def test_unknown_detail_mode_is_rejected():
    with pytest.raises(ValueError, match="detail mode"):
        build_g9_skin_preset(
            {"Source": fixture_surface()}, {"Body": "Source"},
            asset_id=ASSET_ID, detail_mode="typo",
        )


def test_masculine_profile_uses_male_body_map_without_guessing_anatomy_variant():
    source = {"Source": fixture_surface()}
    preset = build_g9_skin_preset(
        source, {zone: "Source" for zone in ("Head", "Body", "Genitalia")},
        asset_id=ASSET_ID, skin_profile="masculine",
    )
    targets = extract_surfaces(preset)
    assert targets["Body"].channels["Detail Normal Map"]["image_file"] == (
        DETAIL_DIR + "Genesis9_BodyM_NM_1002.jpg"
    )
    assert targets["Head"].channels["Detail Normal Map"]["image_file"] == (
        DETAIL_DIR + "Genesis9_Head_NM_1001.jpg"
    )
    assert targets["Genitalia"].channels["Bump Strength"]["image_file"] == BUMP


def test_unknown_skin_profile_is_rejected():
    with pytest.raises(ValueError, match="skin profile"):
        build_g9_skin_preset(
            {"Source": fixture_surface()}, {"Body": "Source"},
            asset_id=ASSET_ID, skin_profile="other",
        )
