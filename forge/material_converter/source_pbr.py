"""Rebind already-PBR Skin materials without translating Uber settings."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import unquote

from forge.material_converter.pbr_presets import PBRSKIN_SHADER_URL, SurfaceMaterial
from forge.material_converter.skin_detail import NATIVE_DETAIL_CHANNELS


class Preservation(StrEnum):
    COPY = "copy"
    REMAP = "remap"
    BAKE = "bake"
    REPLACED = "replaced by detail policy"
    INACTIVE = "inactive"
    REVIEW = "not preserved"


@dataclass(frozen=True)
class ScalarBake:
    slider: float
    texels: dict[str, float]


@dataclass(frozen=True)
class Rule:
    action: Preservation
    reason: str
    bake: ScalarBake | None = None


_IDENTITY_IMAGE_MODIFIERS = {
    "scale": 1, "offset": 0, "invert": False, "grayscale_mode": "average",
    "horizontal_tiles": 1, "horizontal_tiling_offset": 0,
    "vertical_tiles": 1, "vertical_tiling_offset": 0,
}
_LOBE_ROUGHNESS = "Specular Lobe 1 Roughness"


def _is_pbr(source):
    return unquote(source.shader_url or "").casefold() == unquote(PBRSKIN_SHADER_URL).casefold()


def has_texture(channel):
    return bool(channel.get("image") or channel.get("image_file"))


def _unit_scalar(value):
    return type(value) in (float, int) and 0 <= value <= 1


def _head_roughness_rule(values: dict, spec: dict) -> Rule:
    face, lips = values.get("Face"), values.get("Lips")
    if not (spec.get("mappable") and spec.get("type") == "float"
            and _unit_scalar(face) and _unit_scalar(lips) and face != lips):
        return Rule(Preservation.REVIEW, "Keep Face roughness; no separate compatible lip value to bake.")
    if 0 < face and lips <= face:
        return Rule(
            Preservation.BAKE,
            "Keep the Face slider and use a lip-only linear multiplier.",
            ScalarBake(face, {name:lips/face if name == "Lips" else 1 for name in values}),
        )
    return Rule(
        Preservation.BAKE,
        "A lip multiplier would exceed 1 or divide by zero; bake absolute Face and Lips values instead.",
        ScalarBake(1, {name:lips if name == "Lips" else face for name in values}),
    )


def pbr_preservation_map(
    regions: Mapping[str, SurfaceMaterial], schema: SurfaceMaterial, *, native_detail: bool,
    target_surface: str | None = None,
) -> dict[str, Rule]:
    """Classify authored channels for one target surface before producing maps."""
    if not regions or not all(_is_pbr(source) for source in regions.values()):
        raise ValueError("Choose authored PBR Skin donor surfaces")
    face_based = target_surface == "Head" and "Face" in regions
    all_names = {name for source in regions.values() for name in source.channels}
    rules = {}
    for name in sorted(all_names):
        definitions = [source.channels.get(name, {}) for source in regions.values()]
        values = [prop.get("value") for prop in definitions]
        mapped = [has_texture(prop) for prop in definitions]
        differs = any(value != values[0] for value in values[1:])
        spec = schema.channels.get(name)
        if spec is None:
            rules[name] = Rule(Preservation.REVIEW, "Not defined on the target PBR Skin shader.")
        elif name == "Detail Specular Roughness Mult" and any(mapped):
            rules[name] = Rule(Preservation.REVIEW, "Source roughness shares a Detail Weight with the replaced detail normals.")
        elif name in NATIVE_DETAIL_CHANNELS and (native_detail or name == "Normal Map" or name.startswith("Detail ")):
            reason = "Use native G9 detail." if native_detail else "No verified native G9 detail binding for this accessory."
            rules[name] = Rule(Preservation.REPLACED, reason)
        elif name.startswith("Top Coat ") and name != "Top Coat Enable" and (differs or any(mapped)) and all(
            source.channels.get("Top Coat Enable", {}).get("value") is False for source in regions.values()
        ):
            rules[name] = Rule(Preservation.INACTIVE, "Top Coat is off in every region; keep the primary value without a map.")
        elif any(mapped):
            if not spec.get("mappable") or not all(mapped) or differs or any(
                key not in _IDENTITY_IMAGE_MODIFIERS or value != _IDENTITY_IMAGE_MODIFIERS[key]
                for prop in definitions for key, value in (prop.get("image_modification") or {}).items()
            ):
                rules[name] = Rule(Preservation.REVIEW, "Image mix, multipliers or image modifiers need an explicit bake.")
            else:
                rules[name] = Rule(Preservation.REMAP, "Keep the multiplier and rebind a converted UV texture.")
        elif differs:
            by_region = dict(zip(regions, values, strict=True))
            if face_based and name == _LOBE_ROUGHNESS:
                rules[name] = _head_roughness_rule(by_region, spec)
            elif face_based:
                rules[name] = Rule(Preservation.REVIEW, "Keep the source Face value on the merged Head.")
            elif spec.get("mappable") and spec.get("type") == "float" and all(map(_unit_scalar, values)):
                rules[name] = Rule(Preservation.BAKE, "Store the source regional values in a linear G9 atlas.",
                                   ScalarBake(1, by_region))
            else:
                rules[name] = Rule(Preservation.REVIEW, "Conflicting region values cannot use one verified G9 setting.")
        else:
            rules[name] = Rule(Preservation.COPY, "Keep the authored value on the same shader channel.")
    return rules


def bind_pbr_preservation(
    regions: Mapping[str, SurfaceMaterial], schema: SurfaceMaterial,
    *, native_detail: bool, remapped: Mapping[str, str], baked: Mapping[str, str],
    target_surface: str | None = None,
) -> tuple[SurfaceMaterial, dict[str, Rule]]:
    """Apply the plan using resolved G9 texture paths, reporting missing bakes."""
    rules = pbr_preservation_map(regions, schema, native_detail=native_detail, target_surface=target_surface)
    if any(name not in rules or rules[name].action is not Preservation.REMAP for name in remapped) or any(
        name not in rules or rules[name].action is not Preservation.BAKE for name in baked
    ):
        raise ValueError("Supplied G9 images do not match the preservation plan")
    primary = regions["Face"] if target_surface == "Head" and "Face" in regions else next(iter(regions.values()))
    result = rebind_pbr_skin(primary, remapped, native_detail=native_detail)
    for name, rule in rules.items():
        if name not in schema.channels:
            result.channels.pop(name, None)
            result.slots.pop(name, None)
        elif rule.action in {Preservation.REMAP, Preservation.BAKE}:
            images = remapped if rule.action is Preservation.REMAP else baked
            if name not in images:
                rules[name] = Rule(Preservation.REVIEW, "No verified G9 texture was supplied for this channel.")
            elif rule.action is Preservation.BAKE:
                assert rule.bake is not None
                result.channels[name].update(value=rule.bake.slider, image_file=images[name],
                                             default_image_gamma=1, mappable=True)
    for name, rule in rules.items():
        if name in result.channels and rule.action in {Preservation.REVIEW, Preservation.INACTIVE, Preservation.REPLACED}:
            # Clear, rather than inherit, a source-only mapped setting on an already textured figure.
            if has_texture(primary.channels.get(name, {})) and schema.channels[name].get("mappable"):
                result.channels[name]["image_file"] = None
    return result, rules


def rebind_pbr_skin(
    source: SurfaceMaterial, converted_maps: Mapping[str, str], *, native_detail: bool,
) -> SurfaceMaterial:
    """Keep authored values but bind only caller-converted texture maps.

    The native skin detail builder supplies the G9 maps and resets detail
    tiling afterwards. On unsupported accessory surfaces, disable the old
    detail layer and keep any explicitly remapped base bump.
    """
    if not _is_pbr(source):
        raise ValueError("Expected an authored PBR Skin surface")
    if converted_maps.keys() - source.channels.keys():
        raise ValueError("Converted maps must target existing PBR Skin channels")
    result = deepcopy(source)
    result.images.clear()
    for name, channel in result.channels.items():
        for key in ("image", "image_file", "image_modification"):
            channel.pop(key, None)
        if name in converted_maps:
            channel["image_file"] = converted_maps[name]
    if not native_detail and "Detail Enable" in result.channels:
        result.channels["Detail Enable"]["value"] = False
    return result
