from copy import deepcopy

import pytest

from forge.material_converter.layered_color import as_native_lie_preset, rebase_color_stack
from forge.material_converter.package import _references
from forge.material_converter.pbr_presets import SurfaceMaterial, build_g9_material_preset


@pytest.fixture
def definition():
    return {
        "id": "colorido",
        "map_size": [2048, 2048],
        "map_gamma": 0,
        "map": [
            {"url": "/Runtime/Textures/Stock.jpg", "label": "Stock", "operation": "alpha_blend", "transparency": 1},
            {"url": "/Runtime/Textures/Paint.png", "operation": "multiply", "transparency": 0.6},
            {"url": "/Runtime/Textures/Paint.png", "operation": "alpha_blend", "transparency": 0.5},
        ],
    }


def test_rebase_preserves_paint_order_opacity_and_canvas(definition):
    base = {"image_file": "/Runtime/Textures/Pablo%20G9.jpg", "value": [1, 1, 1]}
    snapshot = deepcopy(definition)
    rebased = rebase_color_stack(definition, base)
    assert rebased["map"][0] == {
        "url": base["image_file"], "label": "Pablo G9.jpg", "operation": "alpha_blend", "transparency": 1,
    }
    assert rebased["map"][1:] == definition["map"][1:]
    assert rebased["map_size"] == definition["map_size"]
    assert rebased["map_gamma"] == definition["map_gamma"]
    assert definition == snapshot


@pytest.mark.parametrize("base", [
    {},
    {"image": "#another-stack"},
    {"image_file": "/Runtime/Textures/Pablo.jpg", "default_image_gamma": 1},
])
def test_rebase_rejects_unsupported_underlay_inputs(definition, base):
    with pytest.raises(ValueError, match="converted color texture"):
        rebase_color_stack(definition, base)


def test_rebase_does_not_replace_first_layer_if_it_is_also_paint(definition):
    definition["map"][0]["transparency"] = 0.5
    with pytest.raises(ValueError, match="full-opacity"):
        rebase_color_stack(definition, {"image_file": "/Runtime/Textures/Pablo.jpg"})


@pytest.fixture
def fixed_preset(definition):
    head = SurfaceMaterial(
        channels={"diffuse": {"image": "#colorido"}, "Translucency Color": {"image": "#colorido"}},
        images={"colorido": definition},
        slots={"diffuse": "diffuse"},
    )
    return build_g9_material_preset(
        {"Head": head}, {"Head": "Head"}, asset_id="/People/Paint.duf", shader_url=None,
    )


def test_native_lie_keeps_placeholder_and_both_paint_passes(fixed_preset):
    result = as_native_lie_preset(fixed_preset)
    assert result["asset_info"]["type"] == "preset_layered_image"
    assert result["image_library"] == fixed_preset["image_library"]
    assert result["scene"] == fixed_preset["scene"]
    assert fixed_preset["asset_info"]["type"] == "preset_material"
    assert _references(result) == ({"Runtime/Textures/Stock.jpg", "Runtime/Textures/Paint.png"}, set())


def test_native_lie_rejects_multiply_as_the_discardable_first_layer(fixed_preset):
    fixed_preset["image_library"][0]["map"].pop(0)
    with pytest.raises(ValueError, match="fallback underlay"):
        as_native_lie_preset(fixed_preset)


def test_native_lie_does_not_pass_scalar_changes_through(fixed_preset):
    fixed_preset["scene"]["animations"].append({
        "url": "name://@selection#materials/Head:?diffuse/value", "keys": [[0, [1, 1, 1]]],
    })
    with pytest.raises(ValueError, match="Only static Base Color"):
        as_native_lie_preset(fixed_preset)


def test_native_lie_rejects_missing_image_binding(fixed_preset):
    fixed_preset["scene"]["animations"][0]["keys"] = [[0, "#missing"]]
    with pytest.raises(ValueError, match="referenced local LIE"):
        as_native_lie_preset(fixed_preset)
