import pytest

from forge.material_converter.g9_presets import G9_FIGURE, bind_g9_material_hierarchy
from forge.material_converter.package import _references
from forge.material_converter.pbr_presets import SurfaceMaterial, extract_surfaces
from forge.material_converter.source_iray import IRAY_UBER, build_g9_iray_uber_preset, rebind_iray_uber


def test_embedded_uber_round_trip_with_native_target_and_map_gamma():
    source = SurfaceMaterial(shader_type=IRAY_UBER, slots={"diffuse": "diffuse"}, channels={
        "diffuse": {"value": [.6, .5, .4], "type": "color", "image_file": "/Runtime/Textures/G8/F.jpg"},
        "Top Coat Roughness": {"value": .7, "image_file": "/Runtime/Textures/G8/S.jpg"},
        "Translucency Weight": {"value": .6},
        "SSS Amount": {"value": .69},
    })
    converted = rebind_iray_uber(source, {"diffuse": "/Runtime/Textures/G9/Head.jpg"},
                                 omit_maps=frozenset({"Top Coat Roughness"}))
    path = "/People/Genesis 9/Materials/Uber.duf"
    doc = build_g9_iray_uber_preset({"Head": converted}, asset_id=path)
    material, = doc["scene"]["materials"]
    assert material["url"] == "#Head" and "uv_set" not in material
    assert material["extra"][0] == {"type": IRAY_UBER, "version": "1.1.0.0"}
    assert doc["material_library"][0]["id"] == "Head"
    assert _references(doc) == ({"Runtime/Textures/G9/Head.jpg"}, set())
    hierarchy = bind_g9_material_hierarchy({G9_FIGURE: doc}, asset_id=path)
    result = extract_surfaces(hierarchy, owner=G9_FIGURE)["Head"]
    assert result.shader_type == IRAY_UBER
    assert result.channels["SSS Amount"]["value"] == .69
    diffuse = result.channels["diffuse"]
    assert diffuse["value"] == [.6, .5, .4]
    assert result.images[diffuse["image"][1:]]["map_gamma"] == 0
    assert result.channels["Top Coat Roughness"]["image_file"] is None
    assert source.channels["diffuse"]["image_file"].endswith("/F.jpg")


def test_unresolved_source_map_is_not_silently_kept():
    source = SurfaceMaterial(shader_type=IRAY_UBER, channels={"Normal Map": {"image": "#source"}})
    with pytest.raises(ValueError, match="Every source map"):
        rebind_iray_uber(source, {})
    with pytest.raises(ValueError, match="Iray Uber"):
        rebind_iray_uber(SurfaceMaterial(), {})
