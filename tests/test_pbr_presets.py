"""Synthetic DSON fixtures only; no third-party preset contents are embedded."""

from copy import deepcopy
import gzip
import json
from pathlib import Path

import pytest

from forge.material_converter import (
    PBRSKIN_SHADER_URL,
    SurfaceMaterial,
    build_g9_material_preset,
    extract_surfaces,
    read_dson,
)


ASSET_ID = "/People/Genesis 9/Materials/Test Skin.duf"
EXTRA = "extra/studio_material_channels/channels/"


def animation(surface: str, prop: str, value, owner="name://@selection") -> dict:
    return {"url": f"{owner}#materials/{surface}:?{prop}", "keys": [[0, value]]}


def extra_channels(*channels: dict) -> dict:
    return {"type": "studio_material_channels", "channels": [{"channel": c} for c in channels]}


@pytest.fixture
def document() -> dict:
    return {
        "file_version": "0.6.0.0",
        "asset_info": {
            "id": "/People/Genesis 8/Materials/Source.duf", "type": "preset_material",
            "contributor": {"author": "Synthetic Author", "website": "https://example.com"},
            "revision": "2.1", "modified": "2000-01-01T00:00:00Z",
        },
        "material_library": [
            {
                "id": "Skin Base",
                "diffuse": {"channel": {
                    "id": "diffuse", "type": "float_color", "label": "Base Color",
                    "value": [0.5, 0.5, 0.5], "image_file": "/Runtime/Textures/Test/old.jpg",
                }},
                "extra": [
                    {"type": "studio/material/uber_iray", "version": "1.0"},
                    extra_channels(
                        {"id": "Normal Map", "type": "float", "value": 1,
                         "image_file": "/Runtime/Textures/Test/normal.png"},
                        {"id": "Roughness", "type": "float", "label": "Roughness",
                         "value": 0.3, "min": 0, "max": 1},
                    ),
                ],
            },
            {"id": "Derived", "url": "#Skin%20Base", "extra": [
                extra_channels({"id": "Roughness", "value": 0.4}),
            ]},
        ],
        "scene": {
            "materials": [
                {"id": "Skin-instance", "url": "#Derived", "geometry": "#geometry",
                 "groups": ["Face", "Lips"], "uv_set": "/data/Old/UV.dsf#Old",
                 "extra": [extra_channels({"id": "Roughness", "type": "float"})]},
            ],
            "animations": [
                animation("Face", "diffuse/value", [1, 0.8, 0.7]),
                animation("Face", "diffuse/image_file", "/Runtime/Textures/Test/new face.jpg"),
                animation("Face", EXTRA + "Normal%20Map/image", None),
                animation("Face", EXTRA + "Roughness/value", 0.7),
                animation("Face", EXTRA + "Normal%20Map/image_modification/invert", True),
                animation("Face", "uv_set", "/data/Old/UV.dsf#Old"),
                {"url": "name://@selection#rotation/x/value", "keys": [[0, 42]]},
            ],
        },
    }


@pytest.mark.parametrize("compressed", [False, True])
def test_read_plain_and_gzip_bytes_and_paths(tmp_path: Path, compressed: bool) -> None:
    payload = b'\xef\xbb\xbf{"scene": {"materials": []}}'
    if compressed:
        payload = gzip.compress(payload)
    path = tmp_path / "material.duf"
    path.write_bytes(payload)
    assert read_dson(path) == read_dson(str(path)) == read_dson(payload) == {
        "scene": {"materials": []},
    }


@pytest.mark.parametrize("payload", [b"[]", b"not json", b"\xff", b"\x1f\x8bbroken"])
def test_read_rejects_invalid_dson(payload: bytes) -> None:
    with pytest.raises(ValueError):
        read_dson(payload)


def test_effective_library_instance_and_animation_layers(document: dict) -> None:
    original = deepcopy(document)
    surfaces = extract_surfaces(document)
    face, lips = surfaces["Face"], surfaces["Lips"]
    assert face.shader_url is None
    assert face.shader_type == "studio/material/uber_iray"
    assert face.channels["diffuse"]["value"] == [1, 0.8, 0.7]
    assert face.channels["diffuse"]["image_file"].endswith("new face.jpg")
    assert face.channels["Normal Map"]["image_file"] is None
    assert "image" not in face.channels["Normal Map"]
    assert face.channels["Normal Map"]["image_modification"] == {"invert": True}
    assert face.channels["Roughness"] == {
        "id": "Roughness", "type": "float", "label": "Roughness",
        "value": 0.7, "min": 0, "max": 1,
    }
    assert lips.channels["Roughness"]["value"] == 0.4
    assert lips.channels["Normal Map"]["image_file"].endswith("normal.png")
    assert face.slots == {"diffuse": "diffuse"}
    face.channels["diffuse"]["value"][0] = 9
    assert lips.channels["diffuse"]["value"][0] == 0.5
    assert document == original


def test_local_instance_and_definition_animation_addresses(document: dict) -> None:
    document["scene"]["animations"] = [
        {"url": "#Skin-instance?diffuse/value", "keys": [[0, [1, 1, 1]]]},
        {"url": "#Derived?" + EXTRA + "Roughness/value", "keys": [[0, 0.9]]},
    ]
    surfaces = extract_surfaces(document)
    assert all(m.channels["diffuse"]["value"] == [1, 1, 1] for m in surfaces.values())
    assert all(m.channels["Roughness"]["value"] == 0.9 for m in surfaces.values())


def test_ancestor_library_animation_and_group_precedence(document: dict) -> None:
    document["material_library"][1]["id"] = "Face"
    document["scene"]["materials"][0]["url"] = "#Face"
    document["scene"]["animations"] = [
        {"url": "#Skin%20Base?diffuse/value", "keys": [[0, [1, 1, 1]]]},
        animation("Face", EXTRA + "Roughness/value", 0.8),
    ]
    surfaces = extract_surfaces(document)
    assert all(s.channels["diffuse"]["value"] == [1, 1, 1] for s in surfaces.values())
    assert surfaces["Face"].channels["Roughness"]["value"] == 0.8
    assert surfaces["Lips"].channels["Roughness"]["value"] == 0.4


def test_animation_snapshot_is_step_sampled_and_handles_current_value(document: dict) -> None:
    document["scene"]["animations"] = [animation("Face", EXTRA + "Roughness/current_value", 0)]
    document["scene"]["animations"][0]["keys"] = [[2, 0.8], [0, 0.1], [1, 0.4]]
    assert extract_surfaces(document)["Face"].channels["Roughness"]["value"] == 0.1
    assert extract_surfaces(document, time=1.5)["Face"].channels["Roughness"]["value"] == 0.4
    assert extract_surfaces(document, time=-1)["Face"].channels["Roughness"]["value"] == 0.1
    with pytest.raises(ValueError, match="finite"):
        extract_surfaces(document, time=float("nan"))


def test_null_map_then_file_override_uses_animation_order(document: dict) -> None:
    document["scene"]["animations"] = [
        animation("Face", EXTRA + "Normal%20Map/image", None),
        animation("Face", EXTRA + "Normal%20Map/image_file", "/Runtime/Textures/Test/replacement.png"),
    ]
    normal = extract_surfaces(document)["Face"].channels["Normal Map"]
    assert normal["image_file"].endswith("replacement.png")
    assert "image" not in normal


def test_external_shader_has_no_invented_defaults_or_disk_reads() -> None:
    doc = {"scene": {"materials": [{"url": PBRSKIN_SHADER_URL, "groups": ["Body"]}],
                     "animations": [animation("Body", EXTRA + "Detail%20Weight/value", 0.2)]}}
    body = extract_surfaces(doc)["Body"]
    assert body.shader_url == PBRSKIN_SHADER_URL
    assert body.channels == {"Detail Weight": {"id": "Detail Weight", "value": 0.2}}


def test_library_only_and_missing_or_cyclic_refs(document: dict) -> None:
    document.pop("scene")
    assert extract_surfaces(document)["Derived"].channels["Roughness"]["value"] == 0.4
    document["material_library"][1]["url"] = "#Missing"
    with pytest.raises(ValueError, match="Missing or cyclic"):
        extract_surfaces(document)
    document["material_library"][1]["url"] = "#Derived"
    with pytest.raises(ValueError, match="Missing or cyclic"):
        extract_surfaces(document)


def test_owner_filter_separates_attached_figure_materials() -> None:
    doc = {"scene": {
        "nodes": [
            {"id": "Figure", "geometries": [{"id": "geometry"}]},
            {"id": "Lashes", "geometries": [{"id": "lashes"}]},
        ],
        "materials": [
            {"id": "Moisture-1", "geometry": "#geometry", "groups": ["EyeMoisture"]},
            {"id": "Moisture-2", "geometry": "#lashes", "groups": ["EyeMoisture"]},
        ],
        "animations": [
            animation("EyeMoisture", EXTRA + "Roughness/value", 0.1, owner="Figure"),
            animation("EyeMoisture", EXTRA + "Roughness/value", 0.9, owner="Lashes"),
        ],
    }}
    with pytest.raises(ValueError, match="Ambiguous surface"):
        extract_surfaces(doc)
    assert extract_surfaces(doc, owner="Figure")["EyeMoisture"].channels["Roughness"]["value"] == 0.1
    assert extract_surfaces(doc, owner="Lashes")["EyeMoisture"].channels["Roughness"]["value"] == 0.9
    with pytest.raises(ValueError, match="Unknown material owner"):
        extract_surfaces(doc, owner="Missing")
    doc["scene"]["materials"].pop()
    with pytest.raises(ValueError, match="Ambiguous animation owners"):
        extract_surfaces(doc)


def test_build_selection_targeted_external_shader_and_metadata(document: dict) -> None:
    surfaces = extract_surfaces(document)
    before = deepcopy(surfaces)
    original = deepcopy(document)
    preset = build_g9_material_preset(
        surfaces, {"Head": "Face", "Body": "Lips"}, asset_id=ASSET_ID,
        source_asset_info=document["asset_info"],
    )
    assert preset["asset_info"] == {
        "id": "/People/Genesis%209/Materials/Test%20Skin.duf", "type": "preset_material",
        "contributor": document["asset_info"]["contributor"], "revision": "2.1",
    }
    assert set(preset["scene"]) == {"materials", "animations"}
    assert "material_library" not in preset
    for material in preset["scene"]["materials"]:
        assert material["url"] == PBRSKIN_SHADER_URL
        assert "geometry" not in material and "uv_set" not in material
        assert material["extra"][0] == {"type": "studio/material/daz_brick"}
    restored = extract_surfaces(preset)
    assert restored["Head"].channels["Normal Map"]["image_file"] is None
    assert restored["Body"].channels["Roughness"]["value"] == 0.4
    assert restored["Head"].channels["diffuse"]["label"] == "Base Color"
    assert surfaces == before and document == original
    preset["asset_info"]["contributor"]["author"] = "Changed"
    restored["Head"].channels["diffuse"]["value"][0] = 99
    assert surfaces == before and document == original


def test_partial_preset_preserves_shader_with_diffuse_and_numeric_map_overrides() -> None:
    source = SurfaceMaterial(
        channels={
            "diffuse": {"id": "diffuse", "type": "float_color", "value": [1, 1, 1],
                        "image_file": "/Runtime/Textures/Test/old color.png"},
            "Cutout Opacity": {"id": "Cutout Opacity", "type": "float", "value": 1,
                               "image_file": "/Runtime/Textures/Test/old opacity.png"},
        },
        slots={"diffuse": "diffuse"},
        shader_url=PBRSKIN_SHADER_URL,
        shader_type="studio/material/daz_brick",
    )
    overrides = {"Eye Moisture": {
        "diffuse": {"value": [0.9, 0.8, 0.7], "image_file": "/Runtime/Textures/Test/eye color.png"},
        "Cutout Opacity": {"value": 0.75, "image_file": "/Runtime/Textures/Test/lash opacity.png"},
    }}
    original = deepcopy((source, overrides))
    preset = build_g9_material_preset(
        {"Source": source}, {"Eye Moisture": "Source"}, asset_id=ASSET_ID,
        overrides=overrides, shader_url=None,
    )
    assert set(preset["scene"]) == {"animations"}
    assert preset["image_library"] == [
        {"id": "file-map-0", "map_gamma": 0,
         "map": [{"url": "/Runtime/Textures/Test/eye%20color.png"}]},
        {"id": "file-map-1", "map_gamma": 1,
         "map": [{"url": "/Runtime/Textures/Test/lash%20opacity.png"}]},
    ]
    animations = {a["url"]: a["keys"] for a in preset["scene"]["animations"]}
    prefix = "name://@selection#materials/Eye%20Moisture:?"
    assert animations == {
        prefix + "diffuse/value": [[0, [0.9, 0.8, 0.7]]],
        prefix + "diffuse/image": [[0, "#file-map-0"]],
        prefix + EXTRA + "Cutout%20Opacity/value": [[0, 0.75]],
        prefix + EXTRA + "Cutout%20Opacity/image": [[0, "#file-map-1"]],
    }
    assert "material_library" not in preset
    assert "studio/material/" not in json.dumps(preset)
    assert all(not a["url"].endswith("/image_file") for a in preset["scene"]["animations"])
    restored = extract_surfaces(preset)["Eye Moisture"]
    assert restored.shader_url is None and restored.shader_type is None
    assert restored.channels["diffuse"]["value"] == [0.9, 0.8, 0.7]
    assert restored.channels["Cutout Opacity"]["value"] == 0.75
    assert (source, overrides) == original


@pytest.mark.parametrize("null_property", ["image", "image_file"])
@pytest.mark.parametrize("channel_id", ["diffuse", "Cutout Opacity"])
def test_partial_preset_null_map_removal_for_builtin_and_numeric_channels(
    null_property: str, channel_id: str,
) -> None:
    source = SurfaceMaterial(
        channels={channel_id: {"id": channel_id, "value": 1, "image": "#Map"}},
        slots={"diffuse": "diffuse"} if channel_id == "diffuse" else {},
        images={"Map": {"id": "Map", "map": [{"url": "/Runtime/Textures/Test/map.png"}]}},
    )
    preset = build_g9_material_preset(
        {"Source": source}, {"Eyelashes": "Source"}, asset_id=ASSET_ID,
        shader_url=None, overrides={"Eyelashes": {channel_id: {null_property: None}}},
    )
    assert set(preset["scene"]) == {"animations"}
    assert "image_library" not in preset
    if channel_id == "diffuse":
        path = "diffuse"
    else:
        path = EXTRA + "Cutout%20Opacity"
    assert animation("Eyelashes", path + "/image", None) in preset["scene"]["animations"]
    restored = extract_surfaces(preset)["Eyelashes"]
    assert restored.shader_url is None and restored.shader_type is None
    assert restored.channels[channel_id]["image_file"] is None
    assert restored.channels[channel_id]["value"] == 1
    assert source.channels[channel_id]["image"] == "#Map"


def test_partial_preset_keeps_texture_safety_validation() -> None:
    source = SurfaceMaterial(channels={"Cutout Opacity": {"value": 1}})
    with pytest.raises(ValueError, match="Unsafe content path"):
        build_g9_material_preset(
            {"Source": source}, {"Eyelashes": "Source"}, asset_id=ASSET_ID, shader_url=None,
            overrides={"Eyelashes": {"Cutout Opacity": {
                "image_file": "/Runtime/Textures/../private.png",
            }}},
        )


@pytest.mark.parametrize("channel_type,slot,gamma,expected", [
    ("float", None, None, 1),
    ("float_color", None, None, 0),
    ("color", None, None, 0),
    (None, "diffuse", None, 0),
    ("float", None, 0, 0),
    ("color", None, 2.2, 2.2),
])
def test_partial_image_file_gamma_uses_metadata_then_channel_type(
    channel_type: str | None, slot: str | None, gamma: float | None, expected: float,
) -> None:
    channel = {"image_file": "/Runtime/Textures/Test/new map.png"}
    if channel_type is not None:
        channel["type"] = channel_type
    if gamma is not None:
        channel["default_image_gamma"] = gamma
    source = SurfaceMaterial(channels={"Map": channel}, slots={"Map": slot} if slot else {})
    original = deepcopy(source)
    preset = build_g9_material_preset(
        {"Source": source}, {"Target": "Source"}, asset_id=ASSET_ID, shader_url=None,
    )
    assert set(preset["scene"]) == {"animations"}
    assert preset["image_library"] == [{
        "id": "file-map-0", "map_gamma": expected,
        "map": [{"url": "/Runtime/Textures/Test/new%20map.png"}],
    }]
    path = slot or EXTRA + "Map"
    assert preset["scene"]["animations"] == [animation("Target", path + "/image", "#file-map-0")]
    assert source == original


def test_partial_numeric_only_overrides_never_emit_material_or_image_definitions() -> None:
    preset = build_g9_material_preset(
        {"Native": SurfaceMaterial()}, {"Cornea": "Native", "EyeMoisture": "Native"},
        asset_id=ASSET_ID, shader_url=None, overrides={
            "Cornea": {"Refraction Weight": {"value": 1}},
            "EyeMoisture": {"Cutout Opacity": {"value": 0.8}},
        },
    )
    assert set(preset) == {"file_version", "asset_info", "scene"}
    assert preset["scene"] == {"animations": [
        animation("Cornea", EXTRA + "Refraction%20Weight/value", 1),
        animation("EyeMoisture", EXTRA + "Cutout%20Opacity/value", 0.8),
    ]}
    surfaces = extract_surfaces(preset)
    assert surfaces["Cornea"].channels["Refraction Weight"]["value"] == 1
    assert surfaces["EyeMoisture"].channels["Cutout Opacity"]["value"] == 0.8


def test_partial_mixed_existing_and_generated_images_are_unique_across_targets() -> None:
    source = SurfaceMaterial(channels={
        "Cutout Opacity": {"type": "float", "image_file": "/Runtime/Textures/Test/mask.png"},
        "Coat": {"image": "#Existing"},
    }, images={
        "Existing": {"id": "Existing", "map_gamma": 2.2,
                     "map": [{"url": "/Runtime/Textures/Test/coat.png"}]},
    })
    before = deepcopy(source)
    preset = build_g9_material_preset(
        {"Source": source}, {"UpperLashes": "Source", "LowerLashes": "Source"},
        asset_id=ASSET_ID, shader_url=None,
    )
    assert set(preset["scene"]) == {"animations"}
    images = {image["id"]: image for image in preset["image_library"]}
    assert len(images) == len(preset["image_library"]) == 2
    for entry in preset["scene"]["animations"]:
        assert entry["url"].endswith("/image")
        image = images[entry["keys"][0][1].removeprefix("#")]
        opacity = "Cutout%20Opacity" in entry["url"]
        assert image["map_gamma"] == (1 if opacity else 2.2)
        assert image["map"][0]["url"].endswith("mask.png" if opacity else "coat.png")
    assert source == before


def test_partial_same_bitmap_across_zones_and_color_channels_shares_one_id() -> None:
    source = SurfaceMaterial(channels={
        "diffuse": {"type": "float_color", "image_file": "/Runtime/Textures/Test/eye color.png"},
        "Translucency Color": {"type": "color", "image_file": "/Runtime/Textures/Test/eye%20color.png"},
    }, slots={"diffuse": "diffuse"})
    preset = build_g9_material_preset(
        {"Source": source}, {"EyeLeft": "Source", "EyeRight": "Source"},
        asset_id=ASSET_ID, shader_url=None,
    )
    assert set(preset["scene"]) == {"animations"}
    assert preset["image_library"] == [{
        "id": "file-map-0", "map_gamma": 0,
        "map": [{"url": "/Runtime/Textures/Test/eye%20color.png"}],
    }]
    assert len(preset["scene"]["animations"]) == 4
    assert all(a["url"].endswith("/image") and a["keys"] == [[0, "#file-map-0"]]
               for a in preset["scene"]["animations"])


@pytest.mark.parametrize("shader_url", [PBRSKIN_SHADER_URL, None])
def test_original_images_deduplicate_globally_excluding_id_and_normalizing_urls(shader_url: str | None) -> None:
    def surface(image_id, url, gamma):
        return SurfaceMaterial(channels={"Cutout Opacity": {"image": "#" + image_id}}, images={
            image_id: {"id": image_id, "map_gamma": gamma, "map": [{"url": url}]},
        })
    sources = {
        "Lower": surface("LowerMask", "/Runtime/Textures/Test/lash mask.png", 1),
        "Upper": surface("UpperMask", "/Runtime/Textures/Test/lash%20mask.png", 1.0),
    }
    before = deepcopy(sources)
    preset = build_g9_material_preset(
        sources, {"LowerLashes": "Lower", "UpperLashes": "Upper"},
        asset_id=ASSET_ID, shader_url=shader_url,
    )
    assert len(preset["image_library"]) == 1
    ref = "#" + preset["image_library"][0]["id"]
    assert all(a["keys"] == [[0, ref]] for a in preset["scene"]["animations"])
    if shader_url is not None:
        assert all(m["extra"][1]["channels"][0]["channel"]["image"] == ref
                   for m in preset["scene"]["materials"])
    assert sources == before


def test_partial_generated_and_original_image_definitions_share_one_id() -> None:
    source = SurfaceMaterial(channels={
        "Cutout Opacity": {"type": "float", "image_file": "/Runtime/Textures/Test/mask.png"},
        "Normal Map": {"image": "#Original"},
    }, images={"Original": {
        "id": "Original", "map_gamma": 1.0, "map": [{"url": "/Runtime/Textures/Test/mask.png"}],
    }})
    preset = build_g9_material_preset(
        {"Source": source}, {"LowerLashes": "Source", "UpperLashes": "Source"},
        asset_id=ASSET_ID, shader_url=None,
    )
    assert len(preset["image_library"]) == 1
    assert len(preset["scene"]["animations"]) == 4
    assert all(a["keys"] == [[0, "#file-map-0"]] for a in preset["scene"]["animations"])


@pytest.mark.parametrize("difference", ["gamma", "layer", "metadata"])
def test_same_texture_with_different_definition_semantics_remains_distinct(difference: str) -> None:
    first = {"id": "First", "map_gamma": 1, "map": [{"url": "/Runtime/Textures/Test/map.png"}]}
    second = deepcopy(first)
    second["id"] = "Second"
    if difference == "gamma":
        second["map_gamma"] = 0
    elif difference == "layer":
        second["map"][0]["opacity"] = 0.5
    else:
        second["name"] = "Different metadata"
    source = SurfaceMaterial(channels={
        "First": {"image": "#First"}, "Second": {"image": "#Second"},
    }, images={"First": first, "Second": second})
    preset = build_g9_material_preset(
        {"Source": source}, {"Target": "Source"}, asset_id=ASSET_ID, shader_url=None,
    )
    assert len(preset["image_library"]) == 2
    assert len({a["keys"][0][1] for a in preset["scene"]["animations"]}) == 2


def test_animation_only_extraction_filters_owners_without_material_declarations() -> None:
    doc = {"scene": {"animations": [
        animation("Eyelashes", EXTRA + "Cutout%20Opacity/value", 0.7, owner="Figure"),
        animation("Eyelashes", EXTRA + "Cutout%20Opacity/value", 0.1, owner="Other"),
    ]}}
    with pytest.raises(ValueError, match="Ambiguous animation owners"):
        extract_surfaces(doc)
    assert extract_surfaces(doc, owner="Figure")["Eyelashes"].channels["Cutout Opacity"]["value"] == 0.7


def test_renaming_merging_overrides_and_no_alias_mutation() -> None:
    surfaces = {
        "Face": SurfaceMaterial(channels={
            "Coat": {"value": 0.2, "type": "float", "image_file": "/Runtime/Textures/Test/coat.png"},
            "Face Only": {"value": [1, 2, 3]},
        }),
        "Lips": SurfaceMaterial(channels={"Coat": {"value": 0.8}, "Lip Only": {"value": 1}}),
    }
    overrides = {"Head": {"Coat": {"value": 0.5, "image_file": None}, "New": {"value": False}}}
    original = deepcopy((surfaces, overrides))
    result = build_g9_material_preset(surfaces, {"Head": ["Face", "Lips"], "Copy": "Face"},
                                     asset_id=ASSET_ID, overrides=overrides)
    effective = extract_surfaces(result)
    assert effective["Head"].channels["Coat"] == {
        "id": "Coat", "value": 0.5, "type": "float", "image_file": None,
    }
    assert set(effective["Head"].channels) == {"Coat", "Face Only", "Lip Only", "New"}
    assert effective["Copy"].channels["Coat"]["image_file"].endswith("coat.png")
    effective["Head"].channels["Face Only"]["value"][0] = 0
    assert effective["Copy"].channels["Face Only"]["value"][0] == 1
    assert (surfaces, overrides) == original


@pytest.mark.parametrize("null_property", ["image", "image_file"])
def test_explicit_null_removes_inherited_map_and_emits_null_animation(null_property: str) -> None:
    source = SurfaceMaterial(channels={"Normal Map": {"value": 1, "image": "#Map"}}, images={
        "Map": {"id": "Map", "map": [{"url": "/Runtime/Textures/Test/normal.png"}]},
    })
    preset = build_g9_material_preset({"Source": source}, {"Body": "Source"}, asset_id=ASSET_ID,
                                     overrides={"Body": {"Normal Map": {null_property: None}}})
    assert "image_library" not in preset
    assert any(a["url"].endswith("Normal%20Map/image") and a["keys"] == [[0, None]]
               for a in preset["scene"]["animations"])
    assert extract_surfaces(preset)["Body"].channels["Normal Map"]["image_file"] is None


def test_url_encoding_is_single_and_reserved_identifiers_round_trip() -> None:
    target = "Head / #1?"
    channel = "Coat / #1?"
    source = SurfaceMaterial(channels={channel: {
        "value": 1, "image_file": "/Runtime/Textures/Test%20Artist/skin #1? 100%.png",
    }})
    preset = build_g9_material_preset({"Face": source}, {target: "Face"}, asset_id=ASSET_ID,
                                     shader_url="/data/DAZ 3D/Test Shader/Test Skin.dsf#Test Skin")
    assert preset["scene"]["materials"][0]["url"] == "/data/DAZ%203D/Test%20Shader/Test%20Skin.dsf#Test%20Skin"
    assert all("Head%20%2F%20%231%3F" in a["url"] and "Coat%20%2F%20%231%3F" in a["url"]
               for a in preset["scene"]["animations"])
    effective = extract_surfaces(preset)[target].channels[channel]
    assert effective["image_file"] == "/Runtime/Textures/Test%20Artist/skin%20%231%3F%20100%25.png"
    assert "%2520" not in json.dumps(preset)


@pytest.mark.parametrize("shader_url", [PBRSKIN_SHADER_URL, None])
def test_image_library_layers_gamma_and_shared_refs_are_preserved(shader_url: str | None) -> None:
    doc = {"image_library": [{
        "id": "Map One", "name": "Layered map", "map_gamma": 2.2,
        "map": [
            {"url": "/Runtime/Textures/Test/layer one.png", "operation": "add"},
            {"url": "/Runtime/Textures/Test/layer2.png", "opacity": 0.5},
        ],
    }], "material_library": [{"id": "Face", "extra": [extra_channels(
        {"id": "Coat", "image": "#Map%20One"}, {"id": "Color", "image": "#Map%20One"},
    )]}]}
    original = deepcopy(doc)
    surfaces = extract_surfaces(doc)
    assert surfaces["Face"].images["Map One"]["map_gamma"] == 2.2
    preset = build_g9_material_preset(surfaces, {"Head": "Face", "Copy": "Face"},
                                     asset_id=ASSET_ID, shader_url=shader_url)
    assert len(preset["image_library"]) == 1
    assert preset["image_library"][0]["map"][0]["url"].endswith("layer%20one.png")
    assert preset["image_library"][0]["map_gamma"] == 2.2
    assert doc == original
    restored = extract_surfaces(preset)
    assert len(restored["Head"].images) == 1
    assert restored["Head"].channels["Color"]["image"] == restored["Head"].channels["Coat"]["image"]
    assert restored["Copy"].channels["Color"]["image"] == restored["Head"].channels["Color"]["image"]


@pytest.mark.parametrize("shader_url", [PBRSKIN_SHADER_URL, None])
def test_colliding_image_ids_from_merged_surfaces_are_namespaced(shader_url: str | None) -> None:
    def surface(channel, filename):
        return SurfaceMaterial(channels={channel: {"image": "#Map"}}, images={
            "Map": {"id": "Map", "map": [{"url": f"/Runtime/Textures/Test/{filename}.png"}]},
        })
    preset = build_g9_material_preset(
        {"Face": surface("Color", "face"), "Lips": surface("Coat", "lips")},
        {"Head": ["Face", "Lips"]}, asset_id=ASSET_ID, shader_url=shader_url,
    )
    assert len(preset["image_library"]) == 2
    assert len({i["id"] for i in preset["image_library"]}) == 2
    assert {i["map"][0]["url"] for i in preset["image_library"]} == {
        "/Runtime/Textures/Test/face.png", "/Runtime/Textures/Test/lips.png",
    }


@pytest.mark.parametrize("path", [
    "C:/Users/Someone/private.png", r"C:\Users\Someone\private.png",
    "//server/share/private.png", "/Users/Someone/private.png", "/etc/private.png",
    "/Runtime/Textures/../private.png", "/Runtime/Textures/%2e%2e/private.png",
    "/Runtime/Textures/%252e%252e/private.png", "/Runtime/Textures/a%2fb.png",
    "/Runtime/Textures/%5cprivate.png", "/Runtime//Textures/a.png",
    "https://example.com/private.png", "/Runtime/Textures/a\x00.png",
])
def test_unsafe_texture_paths_are_rejected(path: str) -> None:
    source = SurfaceMaterial(channels={"Coat": {"image_file": path}})
    with pytest.raises(ValueError):
        build_g9_material_preset({"Face": source}, {"Head": "Face"}, asset_id=ASSET_ID)


@pytest.mark.parametrize("shader", ["#PBRSkin", "C:/shader.dsf#Skin", "/data/test.dsf", "/tmp/test.dsf#Skin"])
def test_shader_must_be_external_content_asset(shader: str) -> None:
    with pytest.raises(ValueError):
        build_g9_material_preset({"Face": SurfaceMaterial()}, {"Head": "Face"},
                                 asset_id=ASSET_ID, shader_url=shader)


def test_invalid_builder_inputs_and_metadata_paths_are_rejected() -> None:
    surfaces = {"Face": SurfaceMaterial()}
    for groups in ({}, {"Head": []}, {"Head": "Missing"}, {"": "Face"}):
        with pytest.raises(ValueError):
            build_g9_material_preset(surfaces, groups, asset_id=ASSET_ID)
    with pytest.raises(ValueError, match="unselected"):
        build_g9_material_preset(surfaces, {"Head": "Face"}, asset_id=ASSET_ID,
                                 overrides={"Body": {}})
    with pytest.raises(ValueError, match="matching IDs"):
        build_g9_material_preset(surfaces, {"Head": "Face"}, asset_id=ASSET_ID,
                                 overrides={"Head": {"Coat": {"id": "Wrong"}}})
    for asset_id in ("C:/Users/Someone/output.duf", "/People/../output.duf", "/People/output.json"):
        with pytest.raises(ValueError):
            build_g9_material_preset(surfaces, {"Head": "Face"}, asset_id=asset_id)
    with pytest.raises(ValueError, match="host-absolute"):
        build_g9_material_preset(surfaces, {"Head": "Face"}, asset_id=ASSET_ID,
                                 source_asset_info={"contributor": {"author": "C:/Users/Someone"}})


def test_missing_image_refs_and_nonfinite_values_fail() -> None:
    with pytest.raises(ValueError, match="Missing local image"):
        extract_surfaces({"material_library": [{"id": "Face", "extra": [
            extra_channels({"id": "Coat", "image": "#Missing"}),
        ]}]})
    source = SurfaceMaterial(channels={"Coat": {"value": float("inf")}})
    with pytest.raises(ValueError):
        build_g9_material_preset({"Face": source}, {"Head": "Face"}, asset_id=ASSET_ID)


@pytest.mark.parametrize("slot", ["url", "geometry", "uv_set", "extra", "groups", "bad/slot"])
def test_channel_slots_cannot_replace_preset_structure(slot: str) -> None:
    source = SurfaceMaterial(channels={"Coat": {"value": 1}}, slots={"Coat": slot})
    with pytest.raises(ValueError, match="Invalid built-in channel slot"):
        build_g9_material_preset({"Face": source}, {"Head": "Face"}, asset_id=ASSET_ID)


def test_image_overrides_can_reference_source_image_ids_and_reject_collisions() -> None:
    source = SurfaceMaterial(channels={"Coat": {"value": 1}}, images={
        "Map": {"id": "Map", "map": [{"url": "/Runtime/Textures/Test/map.png"}]},
    })
    overrides = {"Head": {"Coat": {"image": "#Map"}}}
    original = deepcopy((source, overrides))
    preset = build_g9_material_preset({"Face": source}, {"Head": "Face"}, asset_id=ASSET_ID,
                                     overrides=overrides)
    assert len(preset["image_library"]) == 1
    assert (source, overrides) == original
    with pytest.raises(ValueError, match="ambiguous override image"):
        build_g9_material_preset({"Face": source, "Lips": deepcopy(source)},
                                 {"Head": ["Face", "Lips"]}, asset_id=ASSET_ID,
                                 overrides=overrides)


def test_nested_image_urls_are_validated_not_only_top_level_maps() -> None:
    source = SurfaceMaterial(channels={"Coat": {"image": "#Map"}}, images={
        "Map": {"id": "Map", "map": [{
            "url": "/Runtime/Textures/Test/map.png",
            "mask": {"url": "/Runtime/Textures/../private.png"},
        }]},
    })
    with pytest.raises(ValueError, match="Unsafe content path"):
        build_g9_material_preset({"Face": source}, {"Head": "Face"}, asset_id=ASSET_ID)


@pytest.mark.parametrize("keys", [[], [[]], [["bad", 0]], [[float("inf"), 1]]])
def test_bad_animation_keys_raise_value_error(document: dict, keys: list) -> None:
    document["scene"]["animations"][0]["keys"] = keys
    with pytest.raises(ValueError):
        extract_surfaces(document)
