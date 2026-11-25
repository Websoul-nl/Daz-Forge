import pytest

from forge.material_converter import SurfaceMaterial, build_g9_material_preset, extract_surfaces
from forge.material_converter.g9_presets import (
    G9_FIGURE,
    G9_MALE_ANATOMY,
    G9_UNCIRCUMCISED_CONTROL,
    G9_UNCIRCUMCISED_MORPH,
    TRANSLUCENCY_WEIGHT,
    bind_g9_material_hierarchy,
    build_g9_translucency_preset,
    with_g9_male_anatomy_shape,
)
from forge.material_converter.package import _references


ID = "/People/Genesis 9/Materials/Example/Apply.duf"


def test_hierarchical_translucency_sets_only_weights_on_existing_nodes():
    doc = build_g9_translucency_preset({"Head": .6, "Body": .65}, .5, asset_id=ID)
    assert doc["asset_info"]["type"] == "preset_hierarchical_material"
    assert doc["scene"]["nodes"] == [
        {"id": G9_FIGURE, "url": "name://@selection/Genesis9:"},
        {"id": G9_MALE_ANATOMY, "url": "name://@selection/Genesis9MaleGenitalia:", "parent": "#Genesis9"},
    ]
    assert set(doc["scene"]) == {"nodes", "animations"}
    for owner, expected in ((G9_FIGURE, {"Head": .6, "Body": .65}), (G9_MALE_ANATOMY, {"Genitalia": .5})):
        materials = extract_surfaces(doc, owner=owner)
        assert {k:m.channels for k,m in materials.items()} == {
            k: {TRANSLUCENCY_WEIGHT: {"id": TRANSLUCENCY_WEIGHT, "value": value}} for k,value in expected.items()
        }
    assert _references(doc) == (set(), set())


@pytest.mark.parametrize("install_node", [True, False])
def test_hierarchical_package_rejects_external_nodes_and_undeclared_targets(install_node):
    doc = build_g9_translucency_preset({"Body": .6}, .6, asset_id=ID)
    if install_node:
        doc["scene"]["nodes"][1]["url"] = "/data/Mesh.dsf#Node"
    else:
        doc["scene"]["animations"][0]["url"] = doc["scene"]["animations"][0]["url"].replace(G9_FIGURE, "Unknown")
    with pytest.raises(ValueError, match="Hierarchical material"):
        _references(doc)


def test_full_hmat_binds_existing_geometry_and_keeps_partial_eye_shader():
    head = build_g9_material_preset(
        {"Head": SurfaceMaterial(channels={"diffuse": {"image_file": "/Runtime/Textures/Head.jpg"}})},
        {"Head": "Head"}, asset_id=ID,
    )
    eye = build_g9_material_preset(
        {"Eye Left": SurfaceMaterial(channels={"diffuse": {"image_file": "/Runtime/Textures/Eye.jpg"}})},
        {"Eye Left": "Eye Left"}, asset_id=ID, shader_url=None,
    )
    lash = build_g9_material_preset(
        {"Eyelashes Upper": SurfaceMaterial(channels={"Cutout Opacity": {"image_file": "/Runtime/Textures/Lash.png"}})},
        {"Eyelashes Upper": "Eyelashes Upper"}, asset_id=ID, shader_url=None,
    )
    doc = bind_g9_material_hierarchy(
        {G9_FIGURE: head, "Genesis9Eyes": eye, "Genesis9Eyelashes": lash}, asset_id=ID,
    )
    assert doc["asset_info"]["type"] == "preset_hierarchical_material"
    assert doc["scene"]["nodes"][0]["geometries"] == [
        {"id": "Genesis9-1", "url": "name://@selection#geometries/Genesis9:"},
    ]
    assert doc["scene"]["materials"][0]["geometry"] == "#Genesis9-1"
    assert len(doc["scene"]["materials"]) == 1
    assert doc["scene"]["nodes"][2]["parent"] == "#Genesis9"
    eye_image = extract_surfaces(doc, owner="Genesis9Eyes")["Eye Left"]
    assert eye_image.images["Genesis9Eyes-map-0"]["map"] == [{"url": "/Runtime/Textures/Eye.jpg"}]
    assert eye_image.shader_url is None
    assert "file-map-0" in eye["image_library"][0]["id"]
    assert _references(doc)[0] == {"Runtime/Textures/Head.jpg", "Runtime/Textures/Eye.jpg", "Runtime/Textures/Lash.png"}


def test_full_hmat_cannot_instantiate_external_geometry():
    preset = build_g9_material_preset({"Head": SurfaceMaterial(channels={"diffuse": {"value": [1,1,1]}})},
                                      {"Head":"Head"}, asset_id=ID)
    doc = bind_g9_material_hierarchy({G9_FIGURE:preset}, asset_id=ID)
    doc["scene"]["nodes"][0]["geometries"][0]["url"] = "/data/Mesh.dsf#Geometry"
    with pytest.raises(ValueError, match="geometry must bind"):
        _references(doc)


@pytest.mark.parametrize("state", [False, True])
def test_anatomy_properties_preset_keeps_materials_and_sets_native_switch(state):
    source = {"Genitalia": SurfaceMaterial(channels={"diffuse": {"value": [1,1,1]}})}
    original = build_g9_material_preset(source, {"Genitalia": "Genitalia"}, asset_id=ID)
    result = with_g9_male_anatomy_shape(original, uncircumcised=state)
    assert result["asset_info"]["type"] == "preset_properties"
    assert original["asset_info"]["type"] == "preset_material"
    assert result["scene"]["animations"][:2] == [
        {"url": f"name://@selection#{G9_UNCIRCUMCISED_MORPH}:?value/value", "keys": [[0, 0]]},
        {"url": f"name://@selection#{G9_UNCIRCUMCISED_CONTROL}:?value/value", "keys": [[0, state]]},
    ]
    assert result["scene"]["animations"][2:] == original["scene"]["animations"]
    assert result["scene"]["materials"] == original["scene"]["materials"]
    assert _references(result) == _references(original)


def test_hierarchical_anatomy_keeps_native_switch_on_fitted_owner():
    source = {"Genitalia": SurfaceMaterial(channels={"diffuse": {"value": [1,1,1]}})}
    original = build_g9_material_preset(source, {"Genitalia": "Genitalia"}, asset_id=ID)
    result = with_g9_male_anatomy_shape(original, uncircumcised=True, hierarchical=True)
    assert result["asset_info"]["type"] == "preset_hierarchical_material"
    animations = result["scene"]["animations"]
    assert animations[1] == {
        "url": f"{G9_MALE_ANATOMY}#{G9_UNCIRCUMCISED_CONTROL}:?value/value", "keys": [[0, True]],
    }
    assert "Genitalia" in extract_surfaces(result, owner=G9_MALE_ANATOMY)
    assert _references(result) == _references(original)
    animations[1]["keys"] = [[0, 1]]
    with pytest.raises(ValueError, match="undeclared node or property"):
        _references(result)
    animations[1]["url"] = f"{G9_FIGURE}#{G9_UNCIRCUMCISED_CONTROL}:?value/value"
    animations[1]["keys"] = [[0, True]]
    with pytest.raises(ValueError, match="undeclared node or property"):
        _references(result)
