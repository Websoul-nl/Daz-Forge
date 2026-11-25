"""Detail selection for converted Genesis 9 PBR Skin presets."""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from .pbr_presets import SurfaceMaterial, build_g9_material_preset


class SkinDetailMode(StrEnum):
    NATIVE = "native"
    ORIGINAL = "original"


class SkinProfile(StrEnum):
    FEMININE = "feminine"
    MASCULINE = "masculine"


_DETAIL_ROOT = "/Runtime/Textures/Daz/Characters/Genesis9/Base/Skin_Details/"
_SHARED_MAPS = {
    "Head": "Genesis9_Head_NM_1001.jpg",
    "Arms": "Genesis9_Arms_NM_1004.jpg",
    "Legs": "Genesis9_Legs_NM_1003.jpg",
    "Fingernails": "Genesis9_Nails_NM_1005.jpg",
    "Toenails": "Genesis9_Nails_NM_1005.jpg",
}
_NATIVE_MAPS = {
    SkinProfile.FEMININE: {
        **_SHARED_MAPS, "Body": "Genesis9_BodyF_NM_1002.jpg",
        "Genitalia": "Genesis9_GensF_NM_1001.jpg",
    },
    SkinProfile.MASCULINE: {**_SHARED_MAPS, "Body": "Genesis9_BodyM_NM_1002.jpg"},
}
NATIVE_DETAIL_DEPENDENCIES = frozenset(
    (_DETAIL_ROOT + filename).removeprefix("/")
    for maps in _NATIVE_MAPS.values() for filename in maps.values()
)


def _native_channels(filename: str) -> dict[str, dict[str, Any]]:
    return {
        "Bump Enable": {"type": "bool", "value": True},
        "Bump Strength": {"value": 0, "image_file": None},
        "Normal Map": {"value": 1, "image_file": None},
        "Detail Enable": {"type": "bool", "value": True},
        "Detail Weight": {"value": 1, "image_file": None},
        "Detail Normal Map Mode": {"value": 1},
        "Detail Normal Map": {
            "value": 1, "image_file": _DETAIL_ROOT + filename, "default_image_gamma": 1,
        },
        "Detail Horizontal Tiles": {"value": 1},
        "Detail Vertical Tiles": {"value": 1},
        "Detail Horizontal Offset": {"value": 0},
        "Detail Vertical Offset": {"value": 0},
        "Detail Specular Roughness Mult": {"value": 1, "image_file": None},
    }


NATIVE_DETAIL_CHANNELS = frozenset(_native_channels(""))


def build_g9_skin_preset(
    surfaces: Mapping[str, SurfaceMaterial],
    surface_groups: Mapping[str, str | Sequence[str]],
    *,
    asset_id: str,
    detail_mode: SkinDetailMode | str = SkinDetailMode.NATIVE,
    skin_profile: SkinProfile | str = SkinProfile.FEMININE,
    overrides: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    source_asset_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the selected Genesis 9 PBR Skin policy into a preset.

    The native mode replaces converted base bump/normal maps on selected skin
    and supported anatomy surfaces with installed G9 Detail normals. The
    masculine profile does not select an anatomy atlas automatically.
    Other surfaces and settings are unchanged. Original mode retains the converted
    channels as supplied, including their strengths. Use the low-level builder
    for animation-only variants and presets that retain a non-PBR Skin shader.
    """
    try:
        mode = SkinDetailMode(detail_mode)
    except ValueError as exc:
        raise ValueError(f"Unknown skin detail mode: {detail_mode!r}") from exc
    try:
        maps = _NATIVE_MAPS[SkinProfile(skin_profile)]
    except ValueError as exc:
        raise ValueError(f"Unknown skin profile: {skin_profile!r}") from exc

    if mode is SkinDetailMode.NATIVE:
        patches = dict(overrides or {})
        for target in surface_groups:
            if target not in maps:
                continue
            channels = dict(patches.get(target, {}))
            for name, patch in _native_channels(maps[target]).items():
                channel = dict(channels.get(name, {}))
                channel.pop("current_value", None)
                if "image_file" in patch:
                    channel.pop("image", None)
                channel.update(patch)
                channels[name] = channel
            patches[target] = channels
        overrides = patches

    from .skin_readiness import with_skin_map_clears

    return with_skin_map_clears(build_g9_material_preset(
        surfaces, surface_groups, asset_id=asset_id, overrides=overrides,
        source_asset_info=source_asset_info,
    ))
