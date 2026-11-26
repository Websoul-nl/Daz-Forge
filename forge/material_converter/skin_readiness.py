"""Check PBRSkin continuity and make full skin presets replace stale map bindings."""

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
from urllib.parse import quote, unquote

from .pbr_presets import PBRSKIN_SHADER_URL, extract_surfaces, read_dson


SKIN_ZONES = ("Body", "Head", "Arms", "Legs")
LIP_ROUGHNESS = "Specular Lobe 1 Roughness"
CHANNELS_PATH = "extra/studio_material_channels/channels/"
MAP_CHANNELS = frozenset({
    "diffuse", "Metallic Weight", "Diffuse Roughness", "Translucency Weight", "Translucency Color",
    "Dual Lobe Specular Weight", "Dual Lobe Specular Reflectivity", LIP_ROUGHNESS,
    "Specular Lobe 2 Roughness Mult", "Dual Lobe Specular Ratio", "Bump Strength", "Normal Map",
    "Makeup Weight", "Makeup Base Color", "Makeup Roughness Mult", "Ambient Occlusion Weight",
    "Detail Weight", "Detail Normal Map", "Detail Specular Roughness Mult", "Top Coat Weight",
    "Top Coat Color", "Top Coat Reflectivity", "Top Coat Roughness", "Metallic Flakes Weight",
    "Metallic Flakes Color", "Metallic Flakes Roughness", "Displacement Strength",
})
PREFIX_GATES = (
    ("Dual Lobe Specular ", "Dual Lobe Specular Enable"),
    ("Specular Lobe ", "Dual Lobe Specular Enable"),
    ("Top Coat ", "Top Coat Enable"), ("Metallic Flakes ", "Metallic Flakes Enable"),
    ("Detail ", "Detail Enable"), ("Makeup ", "Makeup Enable"),
    ("Specular Occlu", "Specular Occlusion Enable"), ("Translucency ", "Translucency Enable"),
    ("Transmitted ", "Transmission Enable"), ("SSS ", "Sub Surface Enable"),
)
GATES = {
    "diffuse":"Diffuse Enable","Diffuse Roughness":"Diffuse Enable",
    "Metallic Weight":"Metallicity Enable","Invert Transmission Normal":"Translucency Enable",
    "Bump Strength":"Bump Enable","Normal Map":"Bump Enable",
    "Ambient Occlusion Weight":"Specular Occlusion Enable",
    "Scattering Measurement Distance":"Sub Surface Enable",
}
NON_SHADING = {
    "Tags","OutlineColorID","Line Preview Color","Line Start Width","Line End Width","Line UV Width",
    "Render Priority","Propagate Priority","DrawStyle Override",
}
IMAGE_DEFAULTS = {
    "scale":1,"offset":0,"invert":False,"horizontal_tiles":1,"vertical_tiles":1,
    "horizontal_tiling_offset":0,"vertical_tiling_offset":0,"grayscale_mode":"average",
}


@dataclass(frozen=True)
class SkinIssue:
    channel: str
    kind: str
    surfaces: dict


@dataclass(frozen=True)
class SkinReadiness:
    applicable: bool
    issues: tuple[SkinIssue, ...]

    @property
    def ready(self):
        return self.applicable and not self.issues


def _full_skins(document):
    scene = document.get("scene", {})
    if not scene.get("materials"):
        return {}, ""
    hierarchical = document.get("asset_info", {}).get("type") == "preset_hierarchical_material"
    owner = "Genesis9" if hierarchical else None
    if hierarchical and not any(node.get("id") == owner for node in scene.get("nodes", ())):
        return {}, ""
    surfaces = extract_surfaces(document, owner=owner)
    if not all(z in surfaces for z in SKIN_ZONES):
        return {}, ""
    return {z: surfaces[z] for z in SKIN_ZONES}, owner or "name://@selection"


def _is_pbr(surface):
    return unquote(surface.shader_url or "").casefold()==unquote(PBRSKIN_SHADER_URL).casefold()


def _gate(channel):
    if channel in GATES:
        return GATES[channel]
    return next((gate for prefix,gate in PREFIX_GATES if channel.startswith(prefix) and channel!=gate),None)


def _same(a,b):
    if isinstance(a,(tuple,list)) and isinstance(b,(tuple,list)):
        return len(a)==len(b) and all(_same(x,y) for x,y in zip(a,b,strict=True))
    if type(a) in (float,int) and type(b) in (float,int):
        return math.isclose(a,b,rel_tol=0,abs_tol=1e-6)
    return type(a) is type(b) and a==b


def _mapped(prop):
    return bool(prop.get("image_file") or prop.get("image"))


def _map_settings(surface, key, prop):
    colour = key=="diffuse" or prop.get("type") in ("color","float_color")
    gamma = prop.get("default_image_gamma",0 if colour else 1)
    if prop.get("image"):
        ref = unquote(prop["image"].removeprefix("#"))
        gamma = surface.images.get(ref,{}).get("map_gamma",gamma)
    mods = {k:v for k,v in (prop.get("image_modification") or {}).items() if IMAGE_DEFAULTS.get(k,object())!=v}
    return {"gamma":gamma,"image_modification":mods}


def _clears(document):
    return {unquote(row["url"]) for row in document["scene"].get("animations", ())
            if row.get("keys")==[[0,None]] and row["url"].endswith(("/image","/image_file"))}


def _map_url(owner, zone, key, slot=None):
    attr = slot or (key if key == "diffuse" else CHANNELS_PATH + quote(key, safe=""))
    return f"{owner}#materials/{zone}:?{attr}/image"


def check_skin_readiness(document, *, allow_head_lip_map=False, require_map_clears=True):
    """Compare active values, map roles and clear coverage, not per-tile filenames."""
    skins, owner = _full_skins(document)
    if not skins or not any(map(_is_pbr, skins.values())):
        return SkinReadiness(False, ())
    if not all(map(_is_pbr,skins.values())):
        return SkinReadiness(True, (SkinIssue("Shader","different_shaders",
                                               {z:s.shader_url for z,s in skins.items()}),))
    issues = []
    cleared = _clears(document)
    keys = sorted(MAP_CHANNELS.union(*(s.channels for s in skins.values())))
    for key in keys:
        if key in NON_SHADING:
            continue
        gate = _gate(key)
        if gate and all(s.channels.get(gate,{}).get("value") is False for s in skins.values()):
            continue
        props = {z:s.channels.get(key,{}) for z,s in skins.items()}
        vals = {z:p.get("value") for z,p in props.items()}
        if not all(_same(v,vals["Body"]) for v in vals.values()):
            issues.append(SkinIssue(key,"mixed_values",vals))
        present = {z:_mapped(p) for z,p in props.items()}
        lip_only = key==LIP_ROUGHNESS and allow_head_lip_map and present=={
            "Head":True,"Body":False,"Arms":False,"Legs":False,
        }
        if any(present.values()) and not all(present.values()) and not lip_only:
            issues.append(SkinIssue(key,"mixed_map_bindings",present))
        mapped = {z:_map_settings(skins[z],key,props[z]) for z in SKIN_ZONES if present[z]}
        settings = list(mapped.values())
        if settings and any(value != settings[0] for value in settings[1:]):
            issues.append(SkinIssue(key,"mixed_map_settings",mapped))
        if require_map_clears and (key in MAP_CHANNELS or any(present.values())):
            missing = {}
            for z in SKIN_ZONES:
                url = unquote(_map_url(owner,z,key,skins[z].slots.get(key)))
                if not present[z] and url not in cleared and url+"_file" not in cleared:
                    missing[z] = "no explicit map clear"
            if missing:
                issues.append(SkinIssue(key,"stale_map_risk",missing))
    return SkinReadiness(True, tuple(issues))


def with_skin_map_clears(document):
    """Write null image animations for unused slots on a complete G9 PBRSkin preset."""
    skins, owner = _full_skins(document)
    if not skins or not all(map(_is_pbr,skins.values())):
        return document
    result = deepcopy(document)
    animations = result["scene"].setdefault("animations", [])
    cleared = _clears(document)
    for zone,surface in skins.items():
        for key in sorted(MAP_CHANNELS):
            if _mapped(surface.channels.get(key,{})):
                continue
            url = _map_url(owner,zone,key,surface.slots.get(key))
            if unquote(url) not in cleared and unquote(url)+"_file" not in cleared:
                animations.append({"url": url, "keys": [[0, None]]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("preset")
    parser.add_argument("--allow-head-lip-map", action="store_true")
    args = parser.parse_args()
    result = check_skin_readiness(read_dson(args.preset), allow_head_lip_map=args.allow_head_lip_map)
    print(json.dumps({"ready":result.ready,**asdict(result)},indent=2))
    return 0 if result.ready else 1


if __name__=="__main__":
    raise SystemExit(main())
