"""Verify PBRSkin continuity checks against emitted G9 presets."""

from copy import deepcopy
from urllib.parse import unquote

import pytest

from forge.material_converter import (
    SurfaceMaterial, build_g9_material_preset, build_g9_skin_preset, extract_surfaces,
)
from forge.material_converter.g9_presets import G9_FIGURE, bind_g9_material_hierarchy
from forge.material_converter.skin_readiness import (
    LIP_ROUGHNESS, SKIN_ZONES, check_skin_readiness, with_skin_map_clears,
)


ASSET = "/People/Genesis 9/Materials/Skin.duf"
WEIGHT = "Translucency Weight"
SPECULAR = "Dual Lobe Specular Weight"
COLOR = "Translucency Color"
LIPS = "/Runtime/Textures/Trial/Lips_1001.png"


@pytest.fixture
def skin():
    return {
        zone: SurfaceMaterial(channels={
            "diffuse": {"value": [1, 1, 1], "image_file": f"/Runtime/Textures/Trial/{zone}.jpg"},
            "Translucency Enable": {"value": True},
            WEIGHT: {"value": 0.9},
            COLOR: {"type": "color", "value": [0.96, 1, 1], "image_file":
                    f"/Runtime/Textures/Trial/{zone}_trans.jpg", "default_image_gamma": 0},
            "Dual Lobe Specular Enable": {"value": True},
            SPECULAR: {"value": 0.37},
            LIP_ROUGHNESS: {"value": 0.67},
            "Top Coat Enable": {"value": False},
            "Top Coat Weight": {"value": 0.5 if zone == "Body" else 0},
        }, slots={"diffuse": "diffuse"})
        for zone in SKIN_ZONES
    }


def build(skin, builder=build_g9_material_preset):
    return builder(skin, {zone: zone for zone in skin}, asset_id=ASSET)


def issues(result):
    return {(issue.channel, issue.kind): issue.surfaces for issue in result.issues}


@pytest.mark.parametrize("hierarchical", [False, True])
def test_full_preset_clears_stale_maps_and_keeps_lips_and_tile_bindings(skin, hierarchical):
    skin["Head"].channels[LIP_ROUGHNESS]["image_file"] = LIPS
    preset = build(skin)
    if hierarchical:
        eye = build({"Eye": SurfaceMaterial(channels={"diffuse": {"value": [1, 1, 1]}})})
        preset = bind_g9_material_hierarchy({G9_FIGURE: preset, "Genesis9Eyes": eye}, asset_id=ASSET)
    owner = G9_FIGURE if hierarchical else None
    old = issues(check_skin_readiness(preset, allow_head_lip_map=True))
    assert set(old[WEIGHT, "stale_map_risk"]) == set(SKIN_ZONES)
    assert set(old[LIP_ROUGHNESS, "stale_map_risk"]) == {"Body", "Arms", "Legs"}
    snapshot = deepcopy(preset)
    fixed = with_skin_map_clears(preset)
    assert check_skin_readiness(fixed, allow_head_lip_map=True).ready
    assert set(issues(check_skin_readiness(fixed))) == {(LIP_ROUGHNESS, "mixed_map_bindings")}
    assert with_skin_map_clears(fixed) == fixed
    assert preset == snapshot
    new_animations = fixed["scene"]["animations"][len(preset["scene"]["animations"]):]
    assert all(row["keys"] == [[0, None]] and "#materials/Eye" not in row["url"] for row in new_animations)
    assert any(unquote(row["url"]).endswith(f"#materials/Head:?extra/studio_material_channels/channels/{WEIGHT}/image")
               for row in new_animations)
    before = extract_surfaces(preset, owner=owner)
    after = extract_surfaces(fixed, owner=owner)
    for zone in SKIN_ZONES:
        for key in ("diffuse", COLOR):
            assert before[zone].channels[key] == after[zone].channels[key]
    assert before["Head"].channels[LIP_ROUGHNESS] == after["Head"].channels[LIP_ROUGHNESS]


def test_reports_surface_values_map_roles_and_image_settings(skin):
    skin["Head"].channels[LIP_ROUGHNESS]["image_file"] = LIPS
    skin["Head"].channels[WEIGHT]["image_file"] = "/Runtime/Textures/Trial/Head_trans_weight.png"
    skin["Body"].channels[LIP_ROUGHNESS]["image_file"] = "/Runtime/Textures/Trial/Body_rough.png"
    skin["Arms"].channels[SPECULAR]["value"] = 0.48
    skin["Legs"].channels[COLOR]["default_image_gamma"] = 1
    skin["Arms"].channels[COLOR]["value"] = [0.8, 1, 1]
    result = issues(check_skin_readiness(build(skin, build_g9_skin_preset), allow_head_lip_map=True))
    assert result[WEIGHT, "mixed_map_bindings"] == {"Body": False, "Head": True, "Arms": False, "Legs": False}
    assert result[LIP_ROUGHNESS, "mixed_map_bindings"]["Body"] is True
    assert result[SPECULAR, "mixed_values"]["Arms"] == 0.48
    assert result[COLOR, "mixed_values"]["Arms"] == [0.8, 1, 1]
    assert result[COLOR, "mixed_map_settings"]["Legs"]["gamma"] == 1
    assert not any(key == "Top Coat Weight" for key, _ in result)


def test_lip_map_exception_does_not_hide_head_value_mismatch(skin):
    skin["Head"].channels[LIP_ROUGHNESS].update(value=0.56, image_file=LIPS)
    report = check_skin_readiness(build(skin, build_g9_skin_preset), allow_head_lip_map=True)
    assert set(issues(report)) == {(LIP_ROUGHNESS, "mixed_values")}


def test_partial_preset_is_not_a_full_skin(skin):
    preset = build({"Head": skin["Head"]})
    assert not check_skin_readiness(preset).applicable
    assert with_skin_map_clears(preset) == preset
