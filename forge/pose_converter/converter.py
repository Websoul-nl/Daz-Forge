from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any

from forge.pose_converter.mapping import ChannelRef, G9_TO_G8_RULES_BY_SOURCE, RULES_BY_SOURCE


class PoseConversionPreset(Enum):
    G8_TO_G9 = "Genesis 8 -> Genesis 9"
    G9_TO_G8_FEMALE = "Genesis 9 -> Genesis 8 Female"
    G9_TO_G8_MALE = "Genesis 9 -> Genesis 8 Male"
    G9_TO_G8_BOTH = "Genesis 9 -> Genesis 8 Female + Male"
    G9_TO_G8_MERGED = "Genesis 9 -> Genesis 8 Merged"

    @property
    def label(self) -> str:
        return self.value

    @classmethod
    def from_label(cls, label: str) -> "PoseConversionPreset":
        for preset in cls:
            if preset.label == label:
                return preset
        raise ValueError(f"Unknown pose conversion preset: {label}")


@dataclass(frozen=True)
class PoseConversionResult:
    pose: dict[str, Any]
    converted_channels: int
    skipped_channels: int
    unmapped_bones: tuple[str, ...]


def convert_g8f_pose_to_g9(pose: dict[str, Any]) -> PoseConversionResult:
    return convert_pose(pose, PoseConversionPreset.G8_TO_G9)


def convert_pose(pose: dict[str, Any], preset: PoseConversionPreset) -> PoseConversionResult:
    rules_by_source = _rules_for_preset(preset)
    output = deepcopy(pose)
    scene = output.setdefault("scene", {})
    source_animations = pose.get("scene", {}).get("animations", [])
    contributions: dict[ChannelRef, dict[float, float]] = {}
    unmapped_bones: set[str] = set()
    converted_channels = 0
    skipped_channels = 0

    for animation in source_animations:
        parsed = parse_animation_url(str(animation.get("url", "")))
        if parsed is None:
            skipped_channels += 1
            continue

        source_ref = ChannelRef(*parsed)
        rules = rules_by_source.get(source_ref, ())
        if not rules:
            unmapped_bones.add(source_ref.bone)
            skipped_channels += 1
            continue

        keys = animation.get("keys", [])
        if not isinstance(keys, list) or not keys:
            skipped_channels += 1
            continue

        for mapping_rule in rules:
            target_keys = contributions.setdefault(mapping_rule.target, {})
            for key in keys:
                if not isinstance(key, list) or len(key) < 2:
                    continue
                time = float(key[0])
                value = mapping_rule.convert_value(float(key[1]))
                target_keys[time] = target_keys.get(time, 0.0) + value
            converted_channels += 1

    scene["animations"] = _build_animations(contributions)
    _mark_pose_for_preset(output, preset)
    return PoseConversionResult(
        pose=output,
        converted_channels=converted_channels,
        skipped_channels=skipped_channels,
        unmapped_bones=tuple(sorted(unmapped_bones)),
    )


def _rules_for_preset(preset: PoseConversionPreset) -> dict[ChannelRef, tuple]:
    if preset == PoseConversionPreset.G8_TO_G9:
        return RULES_BY_SOURCE
    return G9_TO_G8_RULES_BY_SOURCE


def parse_animation_url(url: str) -> tuple[str, str, str] | None:
    bone_prefix = "name://@selection/"
    root_prefix = "name://@selection"
    marker = ":?"
    suffix = "/value"

    if not url.endswith(suffix) or marker not in url:
        return None

    if url.startswith(bone_prefix):
        bone, channel = url[len(bone_prefix) : -len(suffix)].split(marker, 1)
    elif url.startswith(root_prefix + marker):
        bone = ""
        channel = url[len(root_prefix + marker) : -len(suffix)]
    else:
        return None
    parts = channel.split("/")
    if len(parts) != 2:
        return None
    return bone, parts[0], parts[1]


def animation_url(ref: ChannelRef) -> str:
    if not ref.bone:
        return f"name://@selection:?{ref.group}/{ref.axis}/value"
    return f"name://@selection/{ref.bone}:?{ref.group}/{ref.axis}/value"


def _build_animations(contributions: dict[ChannelRef, dict[float, float]]) -> list[dict[str, Any]]:
    animations = []
    for ref in sorted(contributions, key=lambda item: (item.bone, item.group, item.axis)):
        keys = []
        for time, value in sorted(contributions[ref].items()):
            if _is_default_value(ref, value):
                continue
            keys.append([_clean_number(time), _clean_number(value)])
        if keys:
            animations.append({"url": animation_url(ref), "keys": keys})
    return animations


def _is_default_value(ref: ChannelRef, value: float) -> bool:
    if ref.group == "scale":
        return abs(value - 1.0) < 0.000001
    return abs(value) < 0.000001


def _clean_number(value: float) -> float | int:
    if abs(value - round(value)) < 0.000001:
        return int(round(value))
    return round(value, 6)


def _mark_as_genesis_9_pose(pose: dict[str, Any]) -> None:
    _mark_pose_for_preset(pose, PoseConversionPreset.G8_TO_G9)


def _mark_pose_for_preset(pose: dict[str, Any], preset: PoseConversionPreset) -> None:
    asset_info = pose.setdefault("asset_info", {})
    asset_info["type"] = "preset_pose"
    asset_id = str(asset_info.get("id", ""))
    if asset_id:
        asset_id = _convert_asset_id_for_preset(asset_id, preset)
        asset_info["id"] = asset_id


def _convert_asset_id_for_preset(asset_id: str, preset: PoseConversionPreset) -> str:
    if preset == PoseConversionPreset.G8_TO_G9:
        replacements = (
            ("Genesis%208%20Female", "Genesis%209"),
            ("Genesis%208%20Male", "Genesis%209"),
            ("Genesis 8 Female", "Genesis 9"),
            ("Genesis 8 Male", "Genesis 9"),
            ("G8F", "G9"),
            ("G8M", "G9"),
        )
    elif preset == PoseConversionPreset.G9_TO_G8_MALE:
        replacements = (("Genesis%209", "Genesis%208%20Male"), ("Genesis 9", "Genesis 8 Male"), ("G9", "G8M"))
    elif preset == PoseConversionPreset.G9_TO_G8_MERGED:
        replacements = (("Genesis%209", "Genesis%208"), ("Genesis 9", "Genesis 8"), ("G9", "G8"))
    else:
        replacements = (("Genesis%209", "Genesis%208%20Female"), ("Genesis 9", "Genesis 8 Female"), ("G9", "G8F"))
    converted = asset_id
    for old, new in replacements:
        converted = converted.replace(old, new)
    return converted
