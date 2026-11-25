"""Rebind converted G9 UV maps to an authored Iray Uber material."""

from collections.abc import Mapping
from copy import deepcopy

from forge.material_converter.pbr_presets import SurfaceMaterial, build_g9_material_preset


IRAY_UBER = "studio/material/uber_iray"


def rebind_iray_uber(
    source: SurfaceMaterial, maps: Mapping[str, str], *, omit_maps: frozenset[str] = frozenset(),
) -> SurfaceMaterial:
    """Keep authored values; require a converted binding or explicit omission for every image."""
    if source.shader_type != IRAY_UBER:
        raise ValueError("Expected an authored Iray Uber surface")
    mapped = {key for key, prop in source.channels.items() if prop.get("image") or prop.get("image_file")}
    if (mapped != maps.keys() | omit_maps or maps.keys() & omit_maps
            or any(not isinstance(path, str) or not path for path in maps.values())):
        raise ValueError("Every source map needs a converted binding or an explicit omission")
    result = deepcopy(source)
    result.images.clear()
    result.shader_url = None
    for key, prop in result.channels.items():
        prop.pop("image", None)
        prop.pop("image_modification", None)
        if key in mapped:
            prop["image_file"] = maps.get(key)
    return result


def build_g9_iray_uber_preset(surfaces: Mapping[str, SurfaceMaterial], *, asset_id: str) -> dict:
    """Emit MDL material declarations without importing geometry or G8 UV assets."""
    if any(surface.shader_type != IRAY_UBER for surface in surfaces.values()):
        raise ValueError("Iray Uber presets only accept Iray Uber materials")
    return build_g9_material_preset(
        surfaces, {zone: zone for zone in surfaces}, asset_id=asset_id,
        shader_url=None, embed_iray_uber=True,
    )
