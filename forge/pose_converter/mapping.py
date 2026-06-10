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
    direct_bone("hip", "hip")
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


RULES_BY_SOURCE: dict[ChannelRef, tuple[MappingRule, ...]] = {}
for mapping_rule in G8F_TO_G9_RULES:
    RULES_BY_SOURCE[mapping_rule.source] = RULES_BY_SOURCE.get(mapping_rule.source, ()) + (mapping_rule,)
