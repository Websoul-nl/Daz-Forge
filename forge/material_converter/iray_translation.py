"""Transfer policy for Iray Uber skin values going into PBR Skin."""

from dataclasses import dataclass
from enum import StrEnum

from forge.material_converter.iray_optics import IRAY_UBER, constant, diffuse_equivalence, volume_equivalence
from forge.material_converter.pbr_presets import SurfaceMaterial


class Transfer(StrEnum):
    TINT = "copy tint"
    REMAP = "existing UV remap"
    ZERO = "preserve explicit off"
    CALCULATE = "calculate equivalent term"
    REVIEW = "review in Iray"
    RETAIN = "keep PBR policy"
    UNMAPPED = "no direct mapping"


@dataclass(frozen=True)
class Rule:
    transfer: Transfer
    note: str


_ZERO_WEIGHTS = {
    "Top Coat Weight": "Top Coat Enable",
    "Translucency Weight": None,  # Leave the switch alone so weight-only presets can restore translucency.
}


RULES = {
    "Transmitted Color": Rule(Transfer.TINT, "Copy RGB, not the source map or transmission mode."),
    "Top Coat Color": Rule(Transfer.TINT, "Copy RGB; any coat texture needs a separate UV and gamma check."),
    "diffuse": Rule(Transfer.REMAP, "Base Color keeps its multiplier and uses a converted color map."),
    "Translucency Color": Rule(Transfer.REMAP, "Keep the color multiplier; remap the SSS texture separately."),
    "Dual Lobe Specular Reflectivity": Rule(Transfer.REMAP, "Uses a converted data map when supplied."),
    "Bump Strength": Rule(Transfer.RETAIN, "Converted bump in Original Detail mode, native policy otherwise."),
    "Normal Map": Rule(Transfer.RETAIN, "Transform the source normals or use the native Detail normals."),
    "Translucency Weight": Rule(Transfer.ZERO, "Keep explicit zero; active modes require a verified diffuse split."),
    "Transmitted Measurement Distance": Rule(Transfer.REVIEW, "Needs a compatible solid absorption volume."),
    "Scattering Measurement Distance": Rule(Transfer.REVIEW, "Evaluate together with the other volume controls."),
    "SSS Color": Rule(Transfer.REVIEW, "Color is representable, but this PBR profile already sets the volume tint."),
    "SSS Direction": Rule(Transfer.REVIEW, "Keep the PBR volume baseline until matched in a render."),
    "SSS Reflectance Tint": Rule(Transfer.REVIEW, "Requires the matched diffuse and weight maps in Scatter & Transmit."),
    "SSS Amount": Rule(Transfer.REVIEW, "Only active in Mono mode; needs a compatible scattering volume."),
    "Top Coat Weight": Rule(Transfer.ZERO, "Disable a zero-weight coat; positive weights need coat calibration."),
    "Top Coat Roughness": Rule(Transfer.REVIEW, "Evaluate together with coat weight and a remapped texture."),
    "Top Coat Layering Mode": Rule(Transfer.UNMAPPED, "PBR Skin does not use this Iray Uber selector."),
    "Top Coat Color Effect": Rule(Transfer.UNMAPPED, "Do not copy the Iray Uber enum index."),
    "Top Coat IOR": Rule(Transfer.UNMAPPED, "PBR Skin reflectivity is not a direct IOR copy."),
    "Specular Lobe 2 Roughness": Rule(Transfer.UNMAPPED, "The PBR Skin multiplier is not this absolute roughness."),
    "Dual Lobe Specular Ratio": Rule(Transfer.REVIEW, "Already carried over where supplied; verify the highlight."),
    "Base Color Effect": Rule(Transfer.REVIEW, "Match the diffuse split where supported; never copy the enum."),
    "Metallic Flakes Color": Rule(Transfer.RETAIN, "Do not enable a disabled flake layer to transfer its tint."),
    "Diffuse Overlay Color": Rule(Transfer.UNMAPPED, "A PBR Makeup overlay requires its own mapping and mask."),
    "Diffuse Overlay Weight": Rule(Transfer.UNMAPPED, "Do not treat Iray overlay weight as PBR Makeup weight."),
    "Refraction Weight": Rule(Transfer.UNMAPPED, "Preserve native eye optics; do not apply skin rules to eyes."),
}

_CHANNEL_GROUPS = (
    (Transfer.REVIEW, "Evaluate the active base/specular layer in Iray; same names are not proof of equivalence.", (
        "Base Mixing", "Diffuse Roughness", "Dual Lobe Specular Weight", "Glossy Roughness",
        "Glossy Anisotropy", "Glossy Anisotropy Rotations", "Glossy Color", "Glossy Color Effect",
        "Glossy Layered Weight", "Glossy Reflectivity", "Glossy Specular", "Glossy Weight",
        "Glossiness", "Glossiness Squared", "Reflectivity", "Roughness Squared", "Share Glossy Inputs",
        "Specular Lobe 1 Glossiness", "Specular Lobe 1 Roughness", "Specular Lobe 2 Glossiness",
    )),
    (Transfer.REVIEW, "Calibrate as part of the complete transmission/volume response.", (
        "Invert Transmission Normal", "SSS Mode", "Thin Walled",
    )),
    (Transfer.REVIEW, "Needs a separate UV/material pass; do not copy source texture references.", (
        "Cutout Opacity", "Horizontal Offset", "Horizontal Tiles", "Vertical Offset", "Vertical Tiles",
        "Displacement Strength", "Minimum Displacement", "Maximum Displacement", "SubD Displacement Level",
    )),
    (Transfer.UNMAPPED, "Uber base mode, film or backscatter behavior has no verified PBR skin equivalent.", (
        "BSDF Type", "Base Thin Film", "Base Thin Film IOR", "Diffuse Strength", "Diffuse Weight",
        "Backscattering Anisotropy", "Backscattering Color", "Backscattering Glossiness",
        "Backscattering Roughness", "Backscattering Weight",
    )),
    (Transfer.UNMAPPED, "Requires separate PBR Makeup layer and UV-mask conversion.", (
        "Diffuse Overlay Color Effect", "Diffuse Overlay Roughness", "Diffuse Overlay Weight Squared",
    )),
    (Transfer.UNMAPPED, "Keep native accessory optics; no skin refraction/emission transfer.", (
        "Abbe", "Refraction Color", "Refraction Glossiness", "Refraction Index", "Refraction Roughness",
        "Emission Color", "Emission Profile", "Emission Temperature", "Luminance", "Luminance Units",
        "Luminous Efficacy", "Two Sided Light",
    )),
    (Transfer.RETAIN, "Keep the PBR template's flake/metal policy; translate an active effect separately.", (
        "Metallic Flakes Color Effect", "Metallic Flakes Density", "Metallic Flakes Glossiness",
        "Metallic Flakes Roughness", "Metallic Flakes Size", "Metallic Flakes Strength",
        "Metallic Flakes Thin Film", "Metallic Flakes Thin Film IOR", "Metallic Flakes Weight", "Metallic Weight",
    )),
    (Transfer.REVIEW, "Coat layer modes differ; calibrate these together only for an active coat.", (
        "Top Coat Anisotropy", "Top Coat Bump", "Top Coat Bump Mode", "Top Coat Curve Exponent",
        "Top Coat Curve Grazing", "Top Coat Curve Normal", "Top Coat Glossiness", "Top Coat Rotations",
        "Top Coat Thin Film", "Top Coat Thin Film IOR",
    )),
    (Transfer.RETAIN, "Keep target smoothing, geometry and display settings outside skin shading.", (
        "Line End Width", "Line Preview Color", "Line Start Width", "Line UV Width", "OutlineColorID",
        "Propagate Priority", "Render Priority", "Round Corners Across Materials", "Round Corners Radius",
        "Round Corners Roundness", "Smooth Angle", "Smooth On", "Tags",
    )),
)
for _transfer, _note, _channels in _CHANNEL_GROUPS:
    RULES.update(dict.fromkeys(_channels, Rule(_transfer, _note)))


def _is_constant_zero(channel: dict) -> bool:
    value = channel.get("value")
    return type(value) in (int, float) and value == 0 and not (channel.get("image") or channel.get("image_file"))


def audit_iray_skin_channels(
    source: SurfaceMaterial, target: SurfaceMaterial, *, baked_pair: tuple[str, str] | None = None,
) -> dict[str, Rule]:
    """Classify every authored source channel, without trusting matching names."""
    volume = volume_equivalence(source, target)
    split = diffuse_equivalence(source, target, baked_pair=baked_pair)
    calculated = dict.fromkeys(volume, "Match the authored absorption or scattering coefficient.")
    if "SSS Color" in volume:
        calculated["SSS Mode"] = calculated["SSS Color"]
        if constant(source.channels, "SSS Mode") == 0:
            calculated["SSS Amount"] = calculated.pop("SSS Color")
    calculated.update(dict.fromkeys(split, "Match the supported diffuse/transmission split."))
    if split:
        calculated["Base Color Effect"] = calculated["Translucency Weight"]
    if "diffuse" in split:
        calculated["SSS Reflectance Tint"] = calculated["diffuse"]

    audit = {}
    for channel in sorted(source.channels):
        if channel in calculated:
            audit[channel] = Rule(Transfer.CALCULATE, calculated[channel])
        elif channel in _ZERO_WEIGHTS and (
            channel not in target.channels or not _is_constant_zero(source.channels[channel])
        ):
            audit[channel] = Rule(Transfer.REVIEW, RULES[channel].note)
        elif channel in RULES:
            audit[channel] = RULES[channel]
        elif channel in target.channels:
            audit[channel] = Rule(Transfer.REVIEW, "Present in PBR Skin; equivalence not validated.")
        else:
            audit[channel] = Rule(Transfer.UNMAPPED, "No same-name target and no verified translation.")
    return audit


def translated_iray_skin_tints(source: SurfaceMaterial, target: SurfaceMaterial) -> dict[str, dict]:
    """Return value-only patches for verified tints on a caller-selected PBR Skin surface."""
    if source.shader_type != IRAY_UBER:
        return {}
    patches = {}
    for channel, rule in RULES.items():
        if rule.transfer is not Transfer.TINT or channel not in target.channels:
            continue
        value = source.channels.get(channel, {}).get("value")
        if not isinstance(value, (list, tuple)) or len(value) != 3 or not all(
            type(component) in (float, int) and 0 <= component <= 1 for component in value
        ):
            continue
        patches[channel] = {"value": list(value)}
    return patches


def translated_iray_skin_values(
    source: SurfaceMaterial, target: SurfaceMaterial, *, baked_pair: tuple[str, str] | None = None,
) -> dict[str, dict]:
    """Transfer verified tints, off states and supported shader terms."""
    patches = translated_iray_skin_tints(source, target)
    if source.shader_type != IRAY_UBER:
        return patches
    for channel, enable in _ZERO_WEIGHTS.items():
        if channel not in target.channels or not _is_constant_zero(source.channels.get(channel, {})):
            continue
        patches[channel] = {"value": 0}
        if enable is not None and enable in target.channels:
            patches[enable] = {"value": False}
    patches.update(volume_equivalence(source, target))
    patches.update(diffuse_equivalence(source, target, baked_pair=baked_pair))
    return patches
