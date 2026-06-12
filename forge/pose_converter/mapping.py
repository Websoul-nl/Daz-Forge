from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChannelRef:
    bone: str
    group: str
    axis: str


@dataclass(frozen=True)
class MappingRule:
    source: ChannelRef
    target: ChannelRef
    multiplier: float = 1.0
    offset: float = 0.0

    def convert_value(self, value: float) -> float:
        return value * self.multiplier + self.offset


def rule(
    source_bone: str,
    group: str,
    axis: str,
    target_bone: str,
    *,
    target_group: str | None = None,
    target_axis: str | None = None,
    multiplier: float = 1.0,
    offset: float = 0.0,
) -> MappingRule:
    return MappingRule(
        source=ChannelRef(source_bone, group, axis),
        target=ChannelRef(target_bone, target_group or group, target_axis or axis),
        multiplier=multiplier,
        offset=offset,
    )


def direct_bone(source_bone: str, target_bone: str) -> tuple[MappingRule, ...]:
    return tuple(
        rule(source_bone, group, axis, target_bone)
        for group, axes in (("rotation", "xyz"), ("translation", "xyz"), ("scale", ("general", "x", "y", "z")))
        for axis in axes
    )


G8F_TO_G9_RULES: tuple[MappingRule, ...] = (
    direct_bone("", "")
    + direct_bone("hip", "hip")
    + direct_bone("pelvis", "pelvis")
    + direct_bone("abdomenLower", "spine1")
    + direct_bone("abdomenUpper", "spine2")
    + direct_bone("neckLower", "neck1")
    + direct_bone("neckUpper", "neck2")
    + direct_bone("head", "head")
    + direct_bone("lCollar", "l_shoulder")
    + direct_bone("rCollar", "r_shoulder")
    + direct_bone("lShldrBend", "l_upperarm")
    + direct_bone("rShldrBend", "r_upperarm")
    + direct_bone("lShldrTwist", "l_upperarm")
    + direct_bone("rShldrTwist", "r_upperarm")
    + direct_bone("lForearmBend", "l_forearm")
    + direct_bone("rForearmBend", "r_forearm")
    + direct_bone("lForearmTwist", "l_forearm")
    + direct_bone("rForearmTwist", "r_forearm")
    + direct_bone("lHand", "l_hand")
    + direct_bone("rHand", "r_hand")
    + direct_bone("lThighTwist", "l_thigh")
    + direct_bone("rThighTwist", "r_thigh")
    + direct_bone("lShin", "l_shin")
    + direct_bone("rShin", "r_shin")
    + direct_bone("lFoot", "l_foot")
    + direct_bone("rFoot", "r_foot")
    + direct_bone("lToe", "l_toes")
    + direct_bone("rToe", "r_toes")
    + direct_bone("lThumb1", "l_thumb1")
    + direct_bone("lThumb2", "l_thumb2")
    + direct_bone("lThumb3", "l_thumb3")
    + direct_bone("rThumb1", "r_thumb1")
    + direct_bone("rThumb2", "r_thumb2")
    + direct_bone("rThumb3", "r_thumb3")
    + direct_bone("lIndex1", "l_index1")
    + direct_bone("lIndex2", "l_index2")
    + direct_bone("lIndex3", "l_index3")
    + direct_bone("rIndex1", "r_index1")
    + direct_bone("rIndex2", "r_index2")
    + direct_bone("rIndex3", "r_index3")
    + direct_bone("lMid1", "l_mid1")
    + direct_bone("lMid2", "l_mid2")
    + direct_bone("lMid3", "l_mid3")
    + direct_bone("rMid1", "r_mid1")
    + direct_bone("rMid2", "r_mid2")
    + direct_bone("rMid3", "r_mid3")
    + direct_bone("lRing1", "l_ring1")
    + direct_bone("lRing2", "l_ring2")
    + direct_bone("lRing3", "l_ring3")
    + direct_bone("rRing1", "r_ring1")
    + direct_bone("rRing2", "r_ring2")
    + direct_bone("rRing3", "r_ring3")
    + direct_bone("lPinky1", "l_pinky1")
    + direct_bone("lPinky2", "l_pinky2")
    + direct_bone("lPinky3", "l_pinky3")
    + direct_bone("rPinky1", "r_pinky1")
    + direct_bone("rPinky2", "r_pinky2")
    + direct_bone("rPinky3", "r_pinky3")
    + (
        rule("lThighBend", "rotation", "x", "l_thigh"),
        rule("lThighBend", "rotation", "y", "l_thigh"),
        rule("lThighBend", "rotation", "z", "l_thigh", offset=6.0),
        rule("rThighBend", "rotation", "x", "r_thigh"),
        rule("rThighBend", "rotation", "y", "r_thigh"),
        rule("rThighBend", "rotation", "z", "r_thigh", offset=-6.0),
        rule("lMetatarsals", "rotation", "x", "l_foot"),
        rule("rMetatarsals", "rotation", "x", "r_foot"),
        rule("lMetatarsals", "rotation", "z", "l_metatarsal"),
        rule("rMetatarsals", "rotation", "z", "r_metatarsal"),
    )
)


G9_TO_G8_RULES: tuple[MappingRule, ...] = (
    direct_bone("", "")
    + direct_bone("hip", "hip")
    + direct_bone("pelvis", "pelvis")
    + direct_bone("spine1", "abdomenLower")
    + direct_bone("spine2", "abdomenUpper")
    + direct_bone("neck1", "neckLower")
    + direct_bone("neck2", "neckUpper")
    + direct_bone("head", "head")
    + direct_bone("l_shoulder", "lCollar")
    + direct_bone("r_shoulder", "rCollar")
    + direct_bone("l_upperarm", "lShldrBend")
    + direct_bone("r_upperarm", "rShldrBend")
    + direct_bone("l_forearm", "lForearmBend")
    + direct_bone("r_forearm", "rForearmBend")
    + direct_bone("l_hand", "lHand")
    + direct_bone("r_hand", "rHand")
    + direct_bone("l_shin", "lShin")
    + direct_bone("r_shin", "rShin")
    + direct_bone("l_foot", "lFoot")
    + direct_bone("r_foot", "rFoot")
    + direct_bone("l_toes", "lToe")
    + direct_bone("r_toes", "rToe")
    + direct_bone("l_thumb1", "lThumb1")
    + direct_bone("l_thumb2", "lThumb2")
    + direct_bone("l_thumb3", "lThumb3")
    + direct_bone("r_thumb1", "rThumb1")
    + direct_bone("r_thumb2", "rThumb2")
    + direct_bone("r_thumb3", "rThumb3")
    + direct_bone("l_index1", "lIndex1")
    + direct_bone("l_index2", "lIndex2")
    + direct_bone("l_index3", "lIndex3")
    + direct_bone("r_index1", "rIndex1")
    + direct_bone("r_index2", "rIndex2")
    + direct_bone("r_index3", "rIndex3")
    + direct_bone("l_mid1", "lMid1")
    + direct_bone("l_mid2", "lMid2")
    + direct_bone("l_mid3", "lMid3")
    + direct_bone("r_mid1", "rMid1")
    + direct_bone("r_mid2", "rMid2")
    + direct_bone("r_mid3", "rMid3")
    + direct_bone("l_ring1", "lRing1")
    + direct_bone("l_ring2", "lRing2")
    + direct_bone("l_ring3", "lRing3")
    + direct_bone("r_ring1", "rRing1")
    + direct_bone("r_ring2", "rRing2")
    + direct_bone("r_ring3", "rRing3")
    + direct_bone("l_pinky1", "lPinky1")
    + direct_bone("l_pinky2", "lPinky2")
    + direct_bone("l_pinky3", "lPinky3")
    + direct_bone("r_pinky1", "rPinky1")
    + direct_bone("r_pinky2", "rPinky2")
    + direct_bone("r_pinky3", "rPinky3")
    + (
        rule("l_thigh", "rotation", "x", "lThighBend"),
        rule("l_thigh", "rotation", "y", "lThighBend"),
        rule("l_thigh", "rotation", "z", "lThighBend", offset=-6.0),
        rule("r_thigh", "rotation", "x", "rThighBend"),
        rule("r_thigh", "rotation", "y", "rThighBend"),
        rule("r_thigh", "rotation", "z", "rThighBend", offset=6.0),
        rule("l_metatarsal", "rotation", "z", "lMetatarsals"),
        rule("r_metatarsal", "rotation", "z", "rMetatarsals"),
    )
)


def rules_by_source(rules: tuple[MappingRule, ...]) -> dict[ChannelRef, tuple[MappingRule, ...]]:
    grouped: dict[ChannelRef, tuple[MappingRule, ...]] = {}
    for mapping_rule in rules:
        grouped[mapping_rule.source] = grouped.get(mapping_rule.source, ()) + (mapping_rule,)
    return grouped


RULES_BY_SOURCE: dict[ChannelRef, tuple[MappingRule, ...]] = rules_by_source(G8F_TO_G9_RULES)
G9_TO_G8_RULES_BY_SOURCE: dict[ChannelRef, tuple[MappingRule, ...]] = rules_by_source(G9_TO_G8_RULES)
