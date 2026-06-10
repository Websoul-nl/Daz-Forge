from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from forge.pose_converter.mapping import ChannelRef, RULES_BY_SOURCE


@dataclass(frozen=True)
class PoseConversionResult:
    pose: dict[str, Any]
    converted_channels: int
    skipped_channels: int
    unmapped_bones: tuple[str, ...]


def convert_g8f_pose_to_g9(pose: dict[str, Any]) -> PoseConversionResult:
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
        rules = RULES_BY_SOURCE.get(source_ref, ())
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
    _mark_as_genesis_9_pose(output)
    return PoseConversionResult(
        pose=output,
        converted_channels=converted_channels,
        skipped_channels=skipped_channels,
        unmapped_bones=tuple(sorted(unmapped_bones)),
    )


def parse_animation_url(url: str) -> tuple[str, str, str] | None:
    prefix = "name://@selection/"
    marker = ":?"
    suffix = "/value"

    if not url.startswith(prefix) or marker not in url or not url.endswith(suffix):
        return None

    bone, channel = url[len(prefix) : -len(suffix)].split(marker, 1)
    parts = channel.split("/")
    if len(parts) != 2:
        return None
    return bone, parts[0], parts[1]


def animation_url(ref: ChannelRef) -> str:
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
    asset_info = pose.setdefault("asset_info", {})
    asset_info["type"] = "preset_pose"
    asset_id = str(asset_info.get("id", ""))
    if asset_id:
        asset_id = asset_id.replace("Genesis%208%20Female", "Genesis%209")
        asset_id = asset_id.replace("Genesis 8 Female", "Genesis 9")
        asset_id = asset_id.replace("G8F", "G9")
        asset_info["id"] = asset_id
