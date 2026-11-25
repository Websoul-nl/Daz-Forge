import pytest

from forge.material_converter.pbr_presets import PBRSKIN_SHADER_URL, SurfaceMaterial
from forge.material_converter.source_pbr import Preservation, bind_pbr_preservation, pbr_preservation_map, rebind_pbr_skin


def test_native_pbr_keeps_authored_values_and_only_converted_paths():
    source = SurfaceMaterial(shader_url=PBRSKIN_SHADER_URL, channels={
        "Transmitted Color": {"value": [1, .6, .5]},
        "Diffuse Roughness": {"value": .47, "image": "#rough"},
        "Detail Enable": {"value": True},
        "Detail Normal Map": {"value": 2, "image_file": "/Runtime/Textures/G8/old.png"},
    }, images={"rough": {"map": [{"url": "/Runtime/Textures/G8/rough.png"}]}})
    result = rebind_pbr_skin(source, {"Diffuse Roughness": "/Runtime/Textures/G9/rough.png"}, native_detail=False)
    assert result.channels["Transmitted Color"]["value"] == [1, .6, .5]
    assert result.channels["Diffuse Roughness"] == {"value": .47, "image_file": "/Runtime/Textures/G9/rough.png"}
    assert result.channels["Detail Enable"]["value"] is False
    assert result.channels["Detail Normal Map"] == {"value": 2}
    assert not result.images and source.images
    assert source.channels["Detail Enable"]["value"] is True


def test_uber_shader_cannot_enter_native_pbr_path():
    with pytest.raises(ValueError, match="Expected an authored PBR Skin"):
        rebind_pbr_skin(SurfaceMaterial(shader_type="studio/material/uber_iray"), {}, native_detail=True)


def test_preservation_distinguishes_direct_values_maps_regional_bakes_and_detail():
    def skin(roughness, coat):
        return SurfaceMaterial(shader_url=PBRSKIN_SHADER_URL, channels={
            "SSS Direction": {"value": -.4},
            "Specular Lobe 1 Roughness": {"value": roughness},
            "diffuse": {"value": [1,1,1], "image_file": "/Runtime/Textures/G8/color.jpg"},
            "Detail Specular Roughness Mult": {"value": .9, "image_file": "/Runtime/Textures/G8/detail.png"},
            "Normal Map": {"value": 1, "image_file": "/Runtime/Textures/G8/normal.png"},
            "Top Coat Enable": {"value": False},
            "Top Coat Color": {"value": coat},
        })
    source = {"Face":skin(.67,[1,1,1]), "Lips":skin(.49,[.8,1,1])}
    schema = SurfaceMaterial(channels={name:{"type":"float","mappable":True} for name in source["Face"].channels})
    result, rules = bind_pbr_preservation(
        source, schema, native_detail=True,
        remapped={"diffuse":"/Runtime/Textures/G9/color.jpg"},
        baked={"Specular Lobe 1 Roughness":"/Runtime/Textures/G9/gloss.png"},
    )
    expected = {"SSS Direction":Preservation.COPY, "diffuse":Preservation.REMAP,
                "Specular Lobe 1 Roughness":Preservation.BAKE, "Normal Map":Preservation.REPLACED,
                "Top Coat Color":Preservation.INACTIVE, "Detail Specular Roughness Mult":Preservation.REVIEW}
    assert {k:rules[k].action for k in expected} == expected
    rough = result.channels["Specular Lobe 1 Roughness"]
    assert (rough["value"],rough["default_image_gamma"],rough["image_file"]) == (1,1,"/Runtime/Textures/G9/gloss.png")
    assert result.channels["Detail Specular Roughness Mult"]["image_file"] is None
    assert result.channels["SSS Direction"] == {"value": -.4}
    assert source["Face"].channels["Specular Lobe 1 Roughness"]["value"] == .67


def test_nonuniform_enum_and_tiled_texture_are_not_silently_transferred():
    def skin(choice):
        return SurfaceMaterial(shader_url=PBRSKIN_SHADER_URL, channels={
            "Metallicity Enable": {"value": choice},
            "diffuse": {"value": [1,1,1], "image_file": "/Runtime/Textures/tiled.jpg",
                        "image_modification":{"horizontal_tiles":3}},
            "Detail Weight": {"value": .5},
        })
    regions = {"Face":skin(False),"Lips":skin(True)}
    schema = SurfaceMaterial(channels={"Metallicity Enable":{"type":"bool","mappable":False},
                                        "diffuse":{"type":"color","mappable":True}})
    rules = pbr_preservation_map(regions,schema,native_detail=True)
    assert all(r.action is Preservation.REVIEW for r in rules.values())


@pytest.mark.parametrize(("face","lips","slider","face_texel","lip_texel"), [
    (.67, .49, .67, 1, .49/.67),
    (.49, .67, 1, .49, .67),
    (0, .4, 1, 0, .4),
])
def test_head_keeps_face_and_encodes_only_the_lip_roughness_difference(face,lips,slider,face_texel,lip_texel):
    rough = "Specular Lobe 1 Roughness"
    weight = "Dual Lobe Specular Weight"
    def skin(r,w):
        return SurfaceMaterial(shader_url=PBRSKIN_SHADER_URL, channels={rough:{"value":r},weight:{"value":w}})
    regions = {"Lips":skin(lips,.5), "Face":skin(face,.3), "Ears":skin(.8,.6)}
    schema = SurfaceMaterial(channels={n:{"mappable":True,"type":"float"} for n in (rough,weight)})
    result,rules = bind_pbr_preservation(
        regions,schema,native_detail=True,remapped={},baked={rough:"/Runtime/Textures/Lips.png"},target_surface="Head",
    )
    bake = rules[rough].bake
    assert bake.slider == result.channels[rough]["value"] == slider
    assert bake.texels == {"Face":face_texel,"Lips":lip_texel,"Ears":face_texel}
    assert bake.slider*bake.texels["Face"] == pytest.approx(face)
    assert bake.slider*bake.texels["Lips"] == pytest.approx(lips)
    assert rules[weight].action is Preservation.REVIEW
    assert result.channels[weight]["value"] == .3


def test_head_with_equal_face_and_lip_roughness_does_not_make_a_map():
    name = "Specular Lobe 1 Roughness"
    skin = SurfaceMaterial(shader_url=PBRSKIN_SHADER_URL,channels={name:{"value":.67}})
    schema = SurfaceMaterial(channels={name:{"mappable":True,"type":"float"}})
    rules = pbr_preservation_map({"Face":skin,"Lips":skin},schema,native_detail=True,target_surface="Head")
    assert rules[name].action is Preservation.COPY
    assert rules[name].bake is None
