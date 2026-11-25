"""Translate the compatible diffuse and volume terms of Iray Uber skin."""

from dataclasses import dataclass
import math

import numpy as np

from forge.material_converter.pbr_presets import PBRSKIN_SHADER_URL, SurfaceMaterial


IRAY_UBER = "studio/material/uber_iray"
DAZ_SWATCH_GAMMA = 2.2
COLOR_EFFECT = ("Scatter Only", "Scatter & Transmit", "Scatter & Transmit Intensity")
_IDENTITY_IMAGE_MODIFIERS = {
    "scale": 1, "offset": 0, "invert": False, "grayscale_mode": "average",
    "horizontal_tiles": 1, "vertical_tiles": 1, "horizontal_tiling_offset": 0, "vertical_tiling_offset": 0,
}


def has_image(prop):
    return bool(prop.get("image") or prop.get("image_file"))


def constant(channels, name):
    prop = channels.get(name, {})
    return None if has_image(prop) else prop.get("value")


def number(value, low=0, high=1):
    return type(value) in (float, int) and math.isfinite(value) and low <= value <= high


def rgb(value):
    return isinstance(value, (tuple, list)) and len(value) == 3 and all(number(c) for c in value)


def enum_index(channels, name, labels):
    value = constant(channels, name)
    declared = channels.get(name, {}).get("enum_values")
    if type(value) is int and 0 <= value < len(labels) and (declared is None or tuple(declared) == labels):
        return value
    return None


def _solid_skin(source):
    ch = source.channels
    weight = constant(ch, "Translucency Weight")
    return (source.shader_type == IRAY_UBER and constant(ch, "Thin Walled") is False
            and number(weight) and weight > 0
            and number(constant(ch, "Refraction Weight"), 0, 0)
            and number(constant(ch, "Cutout Opacity"), 1, 1))


def native_pbr_target(target):
    return (target.shader_url == PBRSKIN_SHADER_URL
            or (target.shader_url is None and target.shader_type == "studio/material/daz_brick"
                and {"Translucency Enable", "Sub Surface Enable", "Transmission Enable"} <= target.channels.keys()))


def _fits(target, name, value):
    if name not in target.channels or has_image(target.channels[name]):
        return False
    limits = target.channels[name]
    return number(value, limits.get("min", -math.inf), limits.get("max", math.inf))


def volume_equivalence(source: SurfaceMaterial, target: SurfaceMaterial) -> dict[str, dict]:
    """Match supported coefficients, not the entire rendered shader."""
    if not (_solid_skin(source) and native_pbr_target(target)):
        return {}
    ch = source.channels
    patches = {}
    transmitted = constant(ch, "Transmitted Color")
    td = constant(ch, "Transmitted Measurement Distance")
    if ({"Transmission Enable", "Transmitted Color"} <= target.channels.keys()
            and not has_image(target.channels["Transmitted Color"])
            and number(td, 0, math.inf) and td > 0 and _fits(target, "Transmitted Measurement Distance", td)
            and rgb(transmitted) and min(transmitted) > 0):
        # Both authored distances are in centimeters; both colors feed logarithmic absorption.
        patches.update({"Transmission Enable": {"value": True}, "Transmitted Color": {"value": list(transmitted)},
                        "Transmitted Measurement Distance": {"value": td}})

    mode = enum_index(ch, "SSS Mode", ("Mono", "Chromatic"))
    sd = constant(ch, "Scattering Measurement Distance")
    direction = constant(ch, "SSS Direction")
    if not ({"Sub Surface Enable", "SSS Color"} <= target.channels.keys()
            and not has_image(target.channels["SSS Color"])
            and number(sd, 0, math.inf) and sd > 0 and _fits(target, "Scattering Measurement Distance", sd)
            and number(direction, -1, 1) and _fits(target, "SSS Direction", direction)):
        return patches
    if mode == 0:
        amount = constant(ch, "SSS Amount")
        if not number(amount, 0, math.inf):
            return patches
        # For equal distances, the linear target is exp(-amount). DSON stores an encoded swatch.
        color = [math.exp(-amount / DAZ_SWATCH_GAMMA)] * 3
    elif mode == 1:
        color = constant(ch, "SSS Color")
        if not rgb(color):
            return patches
    else:
        return patches
    # The native color property rounds to 8 bits on load. Do not write a swatch that becomes log(0).
    if min(color) <= 0.5 / 255:
        return patches
    patches.update({"Sub Surface Enable": {"value": min(color) < 1},
                    "SSS Color": {"value": list(color)}, "Scattering Measurement Distance": {"value": sd},
                    "SSS Direction": {"value": direction}})
    return patches


@dataclass(frozen=True)
class DiffusePlan:
    mode: int
    weight: float
    base_tint: tuple[float, float, float]
    reflectance_tint: tuple[float, float, float]


def diffuse_plan(source: SurfaceMaterial) -> DiffusePlan | None:
    """Choose the diffuse split for standard solid, non-metallic Uber skin."""
    if not _solid_skin(source):
        return None
    ch = source.channels
    if (enum_index(ch, "Base Mixing", ("PBR Metallicity/Roughness", "PBR Specular/Glossiness", "Weighted")) != 0
            or any(not number(constant(ch, key), baseline, baseline) for key, baseline in (
                ("Metallic Weight", 0), ("Diffuse Overlay Weight", 0),
                ("Diffuse Strength", 1), ("Diffuse Weight", 1),
            ))):
        return None
    effect = enum_index(ch, "Base Color Effect", COLOR_EFFECT)
    if effect is None:
        return None
    if effect == 0:
        return DiffusePlan(effect, constant(ch, "Translucency Weight"), (1, 1, 1), (1, 1, 1))
    base = ch.get("diffuse", {})
    base_tint = base.get("value")
    reflectance = constant(ch, "SSS Reflectance Tint")
    if not (rgb(base_tint) and rgb(reflectance)):
        return None
    if (base.get("default_image_gamma", 0) != 0
            or any(_IDENTITY_IMAGE_MODIFIERS.get(k, object()) != v
                   for k, v in (base.get("image_modification") or {}).items())):
        return None
    for key, value in (("Horizontal Tiles", 1), ("Vertical Tiles", 1),
                       ("Horizontal Offset", 0), ("Vertical Offset", 0)):
        if key in ch and constant(ch, key) != value:
            return None
    return DiffusePlan(effect, constant(ch, "Translucency Weight"), tuple(base_tint), tuple(reflectance))


def bake_diffuse_split(plan: DiffusePlan, base_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the paired PBRSkin diffuse RGB and scalar transmission weight in linear space."""
    pixels = np.asarray(base_rgb, dtype=np.float32)
    if (plan.mode not in (1, 2) or not pixels.ndim or pixels.shape[-1] != 3
            or not np.isfinite(pixels).all() or np.any((pixels < 0) | (pixels > 1))):
        raise ValueError("Expected a Scatter & Transmit plan and normalized linear RGB texels")
    tint = (np.asarray(plan.base_tint, dtype=np.float32)
            * np.asarray(plan.reflectance_tint, dtype=np.float32)) ** DAZ_SWATCH_GAMMA
    effective = pixels * tint
    peak = effective.max(axis=-1, keepdims=True)
    diffuse = np.divide(effective, peak, out=np.ones_like(effective), where=peak > 0)
    mono = effective.mean(axis=-1) if plan.mode == 1 else peak[..., 0]
    return diffuse, 1 - (1 - plan.weight) * mono


def diffuse_equivalence(
    source: SurfaceMaterial, target: SurfaceMaterial, *, baked_pair: tuple[str, str] | None = None,
) -> dict[str, dict]:
    """Bind the matching scalar or a caller-baked (diffuse, weight) map pair."""
    plan = diffuse_plan(source)
    if (plan is None or not native_pbr_target(target) or "Translucency Enable" not in target.channels
            or constant(target.channels, "Diffuse Enable") is False
            or constant(target.channels, "Makeup Enable") is True
            or ("Metallic Weight" in target.channels and constant(target.channels, "Metallic Weight") != 0)):
        return {}
    ch = source.channels
    if not _fits(target, "Translucency Weight", plan.weight if plan.mode == 0 else 1):
        return {}
    patches = {"Translucency Enable": {"value": True}}
    if plan.mode == 0:
        patches["Translucency Weight"] = {"value": plan.weight}
    elif baked_pair is not None and "diffuse" in target.channels:
        color, weight = baked_pair
        if not color or not weight or color == weight:
            return {}
        patches.update({"diffuse": {"value": [1, 1, 1], "image": None, "image_file": color,
                                    "default_image_gamma": 0},
                        "Translucency Weight": {"value": 1, "image": None, "image_file": weight,
                                                "default_image_gamma": 1}})
    else:
        return {}
    rough = constant(ch, "Diffuse Roughness")
    if number(rough) and _fits(target, "Diffuse Roughness", rough):
        patches["Diffuse Roughness"] = {"value": rough}
    invert = constant(ch, "Invert Transmission Normal")
    if type(invert) is bool and "Invert Transmission Normal" in target.channels:
        patches["Invert Transmission Normal"] = {"value": invert}
    return patches
