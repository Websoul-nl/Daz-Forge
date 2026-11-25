"""G9 presets that target fitted accessories and existing shape controls."""

from collections.abc import Mapping
from copy import deepcopy
from urllib.parse import unquote

from forge.material_converter.pbr_presets import SurfaceMaterial, _content_path, build_g9_material_preset


G9_FIGURE = "Genesis9"
G9_MALE_ANATOMY = "Genesis9MaleGenitalia"
G9_FEMALE_ANATOMY = "Genesis9FemaleGenitalia"
G9_MATERIAL_OWNERS = {G9_FIGURE, G9_MALE_ANATOMY, G9_FEMALE_ANATOMY,
                      "Genesis9Eyes", "Genesis9Mouth", "Genesis9Eyelashes", "Genesis9Tear"}
TRANSLUCENCY_WEIGHT = "Translucency Weight"
G9_UNCIRCUMCISED_MORPH = "body_bs_Uncircumcised_HD3"
G9_UNCIRCUMCISED_CONTROL = "body_ctrl_Uncircumcised_HD3"


def bind_g9_material_hierarchy(presets: Mapping[str, dict], *, asset_id: str) -> dict:
    """Combine converted selection presets under a G9 root and existing fitted nodes."""
    if not presets or presets.keys() - G9_MATERIAL_OWNERS:
        raise ValueError("Choose supported native Genesis 9 material owners")
    asset_id = _content_path(asset_id)
    if not asset_id.casefold().endswith(".duf"):
        raise ValueError("Material preset asset_id must end in .duf")
    scene = {"nodes": [], "animations": []}
    result = {
        "file_version": "0.6.0.0",
        "asset_info": {"id": asset_id, "type": "preset_hierarchical_material"},
        "scene": scene,
    }

    def selection_node(name):
        bound = {"id": name, "url": f"name://@selection/{name}:"}
        if name != G9_FIGURE:
            bound["parent"] = f"#{G9_FIGURE}"
        return bound

    scene["nodes"].append(selection_node(G9_FIGURE))
    for owner in (G9_FIGURE, *(name for name in presets if name != G9_FIGURE)):
        if owner not in presets:
            continue
        doc = deepcopy(presets[owner])
        block = doc["scene"]
        if (
            doc["asset_info"]["type"] != "preset_material"
            or doc.keys() - {"file_version", "asset_info", "scene", "image_library", "material_library"}
            or block.keys() - {"materials", "animations"}
        ):
            raise ValueError("Expected a converted selection-targeted material document")
        for key in ("contributor", "revision"):
            if key in doc["asset_info"]:
                result["asset_info"].setdefault(key,doc["asset_info"][key])
        node = scene["nodes"][0] if owner == G9_FIGURE else selection_node(owner)
        if owner != G9_FIGURE:
            scene["nodes"].append(node)
        images = doc.get("image_library", [])
        names = {unquote(image["id"]): f"{owner}-map-{index}" for index,image in enumerate(images)}
        if len(names) != len(images):
            raise ValueError("Duplicate local material image ID")
        for image in images:
            image["id"] = names[unquote(image["id"])]
            result.setdefault("image_library", []).append(image)

        def image_ref(value):
            return None if value is None else "#" + names[unquote(value.removeprefix("#"))]

        def rebind_images(obj):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key == "image":
                        obj[key] = image_ref(value)
                    else:
                        rebind_images(value)
            elif isinstance(obj, list):
                for value in obj:
                    rebind_images(value)

        declarations = doc.get("material_library", [])
        local_materials = {unquote(row["id"]): f"{owner}-material-{index}" for index, row in enumerate(declarations)}
        if len(local_materials) != len(declarations) or any(row.get("url") for row in declarations):
            raise ValueError("Expected distinct inline material declarations")
        for row in declarations:
            row["id"] = local_materials[unquote(row["id"])]
            rebind_images(row)
            result.setdefault("material_library", []).append(row)

        if block.get("materials"):
            geometry_id = f"{owner}-1"
            node["geometries"] = [{"id":geometry_id,"url":f"name://@selection#geometries/{owner}:"}]
            for index, material in enumerate(block["materials"]):
                rebind_images(material)
                if material.get("url", "").startswith("#"):
                    ref = unquote(material["url"][1:])
                    if ref not in local_materials:
                        raise ValueError(f"Unknown inline material reference: {ref}")
                    material["url"] = "#" + local_materials[ref]
                material["id"] = f"{owner}-mat-{index}"
                material["geometry"] = "#" + geometry_id
                scene.setdefault("materials", []).append(material)
        for animation in block.get("animations", []):
            url = animation["url"]
            if not url.startswith("name://@selection#materials/"):
                raise ValueError("Only selection-targeted material properties can be bound")
            animation["url"] = owner + url.removeprefix("name://@selection")
            if url.endswith("/image"):
                for key in animation["keys"]:
                    key[1] = image_ref(key[1])
            scene["animations"].append(animation)
    return result


def build_g9_translucency_preset(
    skin: Mapping[str, float], anatomy: float, *, asset_id: str,
) -> dict:
    """Set skin and the fitted male accessory's weight, without changing shaders."""
    zones = {G9_FIGURE: skin, G9_MALE_ANATOMY: {"Genitalia": anatomy}}
    if not skin or any(
        type(weight) not in (int, float) or not 0 <= weight <= 1
        for values in zones.values() for weight in values.values()
    ):
        raise ValueError("Translucency weights must be numbers from 0 to 1")
    animations = []
    for node, values in zones.items():
        materials = {surface: SurfaceMaterial(channels={TRANSLUCENCY_WEIGHT: {"value": value}})
                     for surface, value in values.items()}
        document = build_g9_material_preset(
            materials, {name: name for name in values}, asset_id=asset_id, shader_url=None,
        )
        for animation in document["scene"]["animations"]:
            animation["url"] = node + animation["url"].removeprefix("name://@selection")
            animations.append(animation)
    document["asset_info"]["type"] = "preset_hierarchical_material"
    document["scene"] = {
        "nodes": [
            {"id": G9_FIGURE, "url": f"name://@selection/{G9_FIGURE}:"},
            {"id": G9_MALE_ANATOMY, "url": f"name://@selection/{G9_MALE_ANATOMY}:", "parent": f"#{G9_FIGURE}"},
        ],
        "animations": animations,
    }
    return document


def with_g9_male_anatomy_shape(preset: dict, *, uncircumcised: bool, hierarchical: bool = False) -> dict:
    """Make a material preset also set the native graft's shape switch."""
    if type(uncircumcised) is not bool:
        raise ValueError("Expected an on/off anatomy shape")
    document = deepcopy(preset)
    scene = document["scene"]
    if document["asset_info"]["type"] != "preset_material" or not scene.get("materials") or any(
        material.get("groups") != ["Genitalia"] for material in scene["materials"]
    ):
        raise ValueError("Expected a selection-targeted male anatomy material preset")
    if hierarchical:
        document = bind_g9_material_hierarchy({G9_MALE_ANATOMY:document}, asset_id=document["asset_info"]["id"])
        target = G9_MALE_ANATOMY
    else:
        document["asset_info"]["type"] = "preset_properties"
        target = "name://@selection"
    # Reset the driven morph before setting its controller, as in native G9 presets.
    document["scene"]["animations"][:0] = [
        {"url": f"{target}#{name}:?value/value", "keys": [[0, value]]}
        for name, value in ((G9_UNCIRCUMCISED_MORPH, 0), (G9_UNCIRCUMCISED_CONTROL, uncircumcised))
    ]
    return document
