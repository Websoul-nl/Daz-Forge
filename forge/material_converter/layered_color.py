"""Rebase supported editable color stacks onto converted skin textures."""

from copy import deepcopy
from pathlib import PurePosixPath
from urllib.parse import unquote


LIE_PRESET_TYPE = "preset_layered_image"
LIE_COLOR_SLOTS = ("diffuse", "Translucency Color")
_IMAGE_PATHS = {
    "diffuse/image",
    "extra/studio_material_channels/channels/Translucency Color/image",
}


def _is_underlay(layer: dict) -> bool:
    return bool(layer.get("url") and layer.get("operation") == "alpha_blend" and layer.get("transparency") == 1)


def rebase_color_stack(definition: dict, base: dict) -> dict:
    """Replace the stock underlay without altering any of the paint layers."""
    layers = definition.get("map", ())
    if not layers or definition.get("map_gamma", 0) != 0:
        raise ValueError("Expected a layered color image with default gamma")
    if not _is_underlay(layers[0]):
        raise ValueError("Expected a full-opacity alpha-blend underlay")
    url = base.get("image_file")
    if not url or base.get("image") or base.get("default_image_gamma", 0) != 0:
        raise ValueError("Expected a single converted color texture with default gamma")

    updated = deepcopy(definition)
    updated["map"][0].update(url=url, label=PurePosixPath(unquote(url)).name)
    return updated


def as_native_lie_preset(document: dict) -> dict:
    """Make an image-only G9 preset layer over the texture already in each slot.

    The first entry is a fallback underlay, not a paint layer. DAZ substitutes
    the selected material's current image for this entry on native LIE load.
    """
    scene = document.get("scene", {})
    if (document.get("asset_info", {}).get("type") != "preset_material"
            or set(scene) != {"animations"} or document.get("material_library")):
        raise ValueError("Expected an image-only selection material preset")
    images = {}
    for row in document.get("image_library", ()):
        layers = row.get("map", ())
        if len(layers) < 2 or not _is_underlay(layers[0]):
            raise ValueError("Each LIE stack needs a fallback underlay and at least one paint layer")
        ref = unquote(row["id"])
        if ref in images:
            raise ValueError("Duplicate LIE image ID")
        images[ref] = row
    used = set()
    targets = set()
    for row in scene["animations"]:
        url = unquote(row["url"])
        zone, sep, channel = url.removeprefix("name://@selection#materials/").partition(":?")
        keys = row.get("keys", ())
        if (not url.startswith("name://@selection#materials/") or not zone or not sep
                or channel not in _IMAGE_PATHS or len(keys) != 1 or len(keys[0]) != 2 or keys[0][0] != 0
                or not isinstance(keys[0][1], str) or not keys[0][1].startswith("#")):
            raise ValueError("Only static Base Color and Translucency Color layer bindings are supported")
        if (zone, channel) in targets:
            raise ValueError("Duplicate LIE target")
        targets.add((zone, channel))
        used.add(unquote(keys[0][1][1:]))
    if not used or used != images.keys():
        raise ValueError("Expected exactly the referenced local LIE image definitions")
    result = deepcopy(document)
    result["asset_info"]["type"] = LIE_PRESET_TYPE
    return result
