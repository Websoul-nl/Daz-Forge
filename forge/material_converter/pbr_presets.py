"""Read local DSON materials and build selection-targeted G9 material presets.

No application APIs, geometry conversion, shader-default lookup, or writes occur
here. External shader defaults remain unresolved: only locally supplied channel
properties are effective. Returned objects are independent deep copies.

Example::

    doc = read_dson("source.duf")
    surfaces = extract_surfaces(doc, owner="Genesis8Female")
    preset = build_g9_material_preset(
        surfaces, {"Head": ["Face", "Lips"], "Body": "Torso"},
        asset_id="/People/Genesis 9/Materials/Converted.duf",
        overrides={"Head": {"Normal Map": {"image_file": None}}},
        source_asset_info=doc.get("asset_info"),
    )

The caller serializes the result as JSON .duf and applies it to the selected
figure using DAZ's content manager, not by merging a scene or raw geometry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import gzip
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, unquote
import zlib


PBRSKIN_SHADER_URL = (
    "/data/DAZ%203D/Built-in%20Content/Daz%20Iray%20PBRSkin/PBRSkin.dsf#PBRSkin"
)
_CHANNELS = "extra/studio_material_channels/channels/"
_RUNTIME_PROPERTIES = ("value", "image", "image_file", "image_modification")
_RESERVED_SLOTS = {"url", "id", "groups", "geometry", "uv_set", "extra", "name"}


@dataclass
class SurfaceMaterial:
    """Locally effective channel dictionaries keyed by channel ID.

    ``slots`` maps built-in channel IDs (e.g. diffuse) to their DSON property
    slots; other channels use studio_material_channels. ``images`` contains
    referenced image-library definitions keyed by decoded ID, retaining layered
    maps and gamma. ``shader_url`` is an external reference when present;
    ``shader_type`` identifies embedded shader extras (e.g. uber_iray).
    An explicit null image is normalized to ``image_file=None``.
    """

    channels: dict[str, dict[str, Any]] = field(default_factory=dict)
    shader_url: str | None = None
    shader_type: str | None = None
    slots: dict[str, str] = field(default_factory=dict)
    images: dict[str, dict[str, Any]] = field(default_factory=dict)


def read_dson(source: str | Path | bytes) -> dict[str, Any]:
    """Read a local path or UTF-8 bytes, detecting gzip by magic, not suffix.

    Malformed JSON/compression/encoding raises ValueError; filesystem errors
    propagate. This function does not resolve or open any referenced URLs.
    """
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    try:
        if data.startswith(b"\x1f\x8b"):
            data = gzip.decompress(data)
        document = json.loads(data.decode("utf-8-sig"))
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError, zlib.error) as exc:
        raise ValueError(f"Invalid DSON document: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("DSON root must be an object")
    return document


def _decode(text: str) -> str:
    return unquote(text, encoding="utf-8", errors="strict")


def _content_path(path: str, *, root: str | None = None) -> str:
    if not isinstance(path, str) or not path:
        raise ValueError("Expected a nonempty content-relative path")
    decoded = _decode(path)
    # Reject nested escapes as well as decoded separators/traversal. No path is
    # resolved against the host filesystem, and absolute host paths are rejected.
    if (
        decoded.startswith("//")
        or "\\" in decoded
        or ":" in decoded
        or any(ord(c) < 32 for c in decoded)
        or re.search(r"%[0-9a-fA-F]{2}", decoded)
        or re.search(r"%2[fF]|%5[cC]", path)
    ):
        raise ValueError(f"Unsafe content path: {path!r}")
    parts = decoded.removeprefix("/").split("/")
    if any(p in {"", ".", ".."} for p in parts):
        raise ValueError(f"Unsafe content path: {path!r}")
    if root is not None and "/".join(parts[: len(root.split('/'))]).casefold() != root.casefold():
        raise ValueError(f"Content path must be inside /{root}: {path!r}")
    if root is None and parts[0].casefold() not in {
        "people", "materials", "presets", "shader presets", "runtime", "data",
    }:
        raise ValueError(f"Not a supported content-root path: {path!r}")
    return "/" + "/".join(quote(p, safe="") for p in parts)


def _shader_url(url: str) -> str:
    path, marker, fragment = url.partition("#")
    if not marker or not fragment or "#" in fragment or "?" in path:
        raise ValueError("Shader URL must reference an external /data asset and fragment")
    return _content_path(path, root="data") + "#" + quote(_decode(fragment), safe="")


def _merge(target: dict, patch: Mapping) -> None:
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = deepcopy(value)


def _update_channel(target: dict, patch: Mapping) -> None:
    patch = deepcopy(dict(patch))
    if "current_value" in patch:
        patch["value"] = patch.pop("current_value")
    if "image" in patch:
        target.pop("image_file", None)
        target.pop("image", None)
        if patch["image"] is None:
            patch.pop("image")
            patch.setdefault("image_file", None)
    if "image_file" in patch:
        target.pop("image", None)
        patch.pop("image", None)
    _merge(target, patch)


def _apply_material(result: SurfaceMaterial, material: Mapping) -> None:
    for slot, wrapper in material.items():
        if isinstance(wrapper, Mapping) and isinstance(wrapper.get("channel"), Mapping):
            channel = wrapper["channel"]
            channel_id = channel.get("id", slot)
            _update_channel(result.channels.setdefault(channel_id, {}), channel)
            result.slots[channel_id] = slot
    for extra in material.get("extra", []):
        kind = extra.get("type", "")
        if kind.startswith("studio/material/"):
            result.shader_type = kind
        if kind == "studio_material_channels":
            for wrapper in extra.get("channels", []):
                channel = wrapper["channel"]
                _update_channel(result.channels.setdefault(channel["id"], {}), channel)


def _sample(keys: Sequence, time: float) -> Any:
    if not keys:
        raise ValueError("Material animation has no keys")
    if any(
        not isinstance(key, (list, tuple)) or len(key) < 2
        or not isinstance(key[0], (int, float)) or not math.isfinite(key[0])
        for key in keys
    ):
        raise ValueError("Invalid material animation keys")
    ordered = sorted(keys, key=lambda key: key[0])
    return deepcopy(next((key[1] for key in reversed(ordered) if key[0] <= time), ordered[0][1]))


def extract_surfaces(
    document: Mapping[str, Any], *, owner: str | None = None, time: float = 0.0,
) -> dict[str, SurfaceMaterial]:
    """Resolve library definitions, scene instances, then material animations.

    ``owner`` is a scene node ID (e.g. Genesis8Female). Its geometries and
    animations are selected, avoiding attached figures with identical surface
    names. Ambiguous names without an owner raise ValueError. Animation URLs
    can address a surface group, instance ID, or local definition ID. Sampling
    holds the latest key at/before ``time`` (first key before its start); this is
    a preset snapshot, not an interpolating animation engine. Unknown nonmaterial
    animations and UV/geometry properties are intentionally ignored.

    External shader files are never loaded. Missing local references and cycles
    raise ValueError. When there are no scene instances, library IDs are used as
    surface names. Animation-only presets discover surface names from their
    material animation targets. Images remain local refs with definitions in
    ``images``; animation-only presets cannot supply channel declaration metadata.
    """
    if not math.isfinite(time):
        raise ValueError("Snapshot time must be finite")
    library = {_decode(m["id"]): m for m in document.get("material_library", [])}
    scene = document.get("scene", {})
    nodes = scene.get("nodes", [])
    geometries = None
    if owner is not None and nodes:
        node = next((n for n in nodes if _decode(n["id"]) == owner), None)
        if node is None:
            raise ValueError(f"Unknown material owner: {owner}")
        geometries = {_decode(g["id"]) for g in node.get("geometries", [])}

    def resolve(material: Mapping, active: frozenset = frozenset()) -> SurfaceMaterial:
        result = SurfaceMaterial()
        url = material.get("url")
        if url:
            if url.startswith("#"):
                ref = _decode(url[1:])
                if ref in active or ref not in library:
                    raise ValueError(f"Missing or cyclic local material reference: {url}")
                result = resolve(library[ref], active | {ref})
            else:
                result.shader_url = _shader_url(url)
        _apply_material(result, material)
        return result

    surfaces: dict[str, SurfaceMaterial] = {}
    aliases: dict[str, set[str]] = {}
    materials = scene.get("materials", [])
    animation_only = not materials and not library
    if materials and geometries is not None:
        materials = [m for m in materials if _decode(m.get("geometry", "").removeprefix("#")) in geometries]
        animation_only = not materials
    if not materials and not animation_only:
        materials = [dict(m, groups=[_decode(m["id"])]) for m in library.values()]
    if animation_only:
        targets: dict[str, None] = {}
        for animation in scene.get("animations", []):
            prefix, marker, address = animation.get("url", "").partition("#materials/")
            name, separator, _ = address.partition(":?")
            if marker and separator and (owner is None or _decode(prefix) in {"", owner, "name://@selection"}):
                targets[_decode(name)] = None
        materials = [{"groups": [name]} for name in targets]
    for material in materials:
        if not animation_only and geometries is not None and _decode(material.get("geometry", "").removeprefix("#")) not in geometries:
            continue
        names = material.get("groups") or [material.get("id")]
        if not all(isinstance(n, str) and n for n in names):
            raise ValueError("Material needs a surface group or ID")
        for name in names:
            if name in surfaces:
                raise ValueError(f"Ambiguous surface {name!r}; select a scene owner")
            surfaces[name] = resolve(material)
        refs = [material.get("id")]
        ancestor = material
        while ancestor.get("url", "").startswith("#"):
            ref = _decode(ancestor["url"][1:])
            refs.append(ref)
            ancestor = library[ref]
        for ref in refs:
            if ref:
                aliases.setdefault(_decode(ref), set()).update(names)
    for name in surfaces:
        aliases.setdefault(name, set()).add(name)

    animation_owners: dict[str, set[str]] = {}
    for animation in scene.get("animations", []):
        url = animation.get("url", "")
        prefix, marker, address = url.partition("#materials/")
        if marker:
            name, separator, prop = address.partition(":?")
        elif url.startswith("#"):
            prefix = ""
            name, separator, prop = url[1:].partition("?")
            name = name.removesuffix(":")
        else:
            continue
        prefix = _decode(prefix)
        if not separator or (owner is not None and prefix not in {"", owner, "name://@selection"}):
            continue
        name = _decode(name)
        names = {name} if marker and name in surfaces else aliases.get(name, set())
        if not names:
            continue
        parts = prop.split("/")
        if prop.startswith(_CHANNELS) and len(parts) >= 5:
            channel_id, tail = _decode(parts[3]), parts[4:]
            slot = None
        elif len(parts) >= 2 and parts[0] != "extra":
            channel_id, tail = _decode(parts[0]), parts[1:]
            slot = channel_id
        else:
            continue
        if tail[0] not in (*_RUNTIME_PROPERTIES, "current_value"):
            continue
        if len(tail) > 1 and tail[0] != "image_modification":
            raise ValueError(f"Unsupported channel animation property: {prop}")
        for name in names:
            if prefix not in {"", "name://@selection"}:
                owners = animation_owners.setdefault(name, set())
                owners.add(prefix)
                if owner is None and len(owners) > 1:
                    raise ValueError(f"Ambiguous animation owners for {name!r}; select an owner")
            patch: dict[str, Any] = {}
            cursor = patch
            for key in tail[:-1]:
                cursor = cursor.setdefault(_decode(key), {})
            cursor[_decode(tail[-1])] = _sample(animation.get("keys", []), time)
            surface = surfaces[name]
            _update_channel(surface.channels.setdefault(channel_id, {"id": channel_id}), patch)
            if slot is not None:
                surface.slots[channel_id] = slot

    images = {_decode(i["id"]): i for i in document.get("image_library", [])}
    for surface in surfaces.values():
        for channel in surface.channels.values():
            if channel.get("image") is not None:
                ref = _decode(channel["image"].removeprefix("#"))
                if ref not in images:
                    raise ValueError(f"Missing local image reference: {channel['image']}")
                surface.images[ref] = deepcopy(images[ref])
    return surfaces


def _reject_host_paths(value: Any) -> None:
    if isinstance(value, str) and re.search(
        r"(?i)(?<![a-z])[a-z]:[\\/]|\\\\|file://|/(?:users|home|mnt|volumes|tmp)/", _decode(value),
    ):
        raise ValueError("Generated preset cannot contain host-absolute paths")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_host_paths(key)
            _reject_host_paths(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_host_paths(item)


def _normalize_image_urls(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "url":
                value[key] = _content_path(item, root="Runtime/Textures")
            else:
                _normalize_image_urls(item)
    elif isinstance(value, list):
        for item in value:
            _normalize_image_urls(item)


def _image_content(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _image_content(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_image_content(item) for item in value]
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return value


def build_g9_material_preset(
    surfaces: Mapping[str, SurfaceMaterial],
    surface_groups: Mapping[str, str | Sequence[str]],
    *,
    asset_id: str,
    overrides: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    shader_url: str | None = PBRSKIN_SHADER_URL,
    source_asset_info: Mapping[str, Any] | None = None,
    embed_iray_uber: bool = False,
) -> dict[str, Any]:
    """Build a standalone selection-targeted material .duf document.

    ``surface_groups`` maps each target name to a source name or ordered source
    names. Later sources merge channel properties over earlier ones; this is
    explicit layering, not texture compositing. ``overrides[target][channel]``
    patches raw channel properties last. Omitted maps inherit; ``image=None``
    or ``image_file=None`` explicitly removes the map. New channels default to
    the extra-channel path unless listed in ``SurfaceMaterial.slots``.
    An ``image`` override may reference an input image-library ID; colliding IDs
    from multiple sources are rejected rather than choosing an arbitrary map.

    ``shader_url=None`` normally creates an animations-only partial preset: no scene
    materials, channel declarations, shader URLs, or shader-type markers are
    emitted. Even untyped scene material entries can replace native DAZ shaders.
    Non-null image_file properties become image-library refs animated via /image;
    gamma uses default_image_gamma when supplied, otherwise 0 for color channels
    (color/float_color or the diffuse slot), 1 for numeric/data channels.
    Existing image-library definitions retain their gamma and layered maps.
    Image definitions are deduplicated globally by normalized content excluding
    their ID; all matching channels share one reference. Different gamma, layer,
    or other definition metadata remains distinct.
    The default explicitly switches targeted surfaces to external PBRSkin and
    retains the original material declarations and image_file animations.
    With ``shader_url=None, embed_iray_uber=True``, declare Iray Uber inline as
    in a DAZ-authored selection-targeted Iray Uber material preset.

    ``asset_id`` is an install-relative .duf URL. Images must live under
    Runtime/Textures; shader references must be external /data URLs. Unsafe
    paths are rejected, never stripped or guessed. Only contributor and revision
    are inherited from source asset metadata, not its ID, timestamp, UVs, nodes,
    geometry, or shader extras. No inputs are mutated. The returned dictionary
    is JSON-serializable; serialization and installation belong to the caller.
    """
    if not surface_groups:
        raise ValueError("Choose at least one target surface")
    asset_id = _content_path(asset_id)
    if not asset_id.casefold().endswith(".duf"):
        raise ValueError("Material preset asset_id must end in .duf")
    if embed_iray_uber and shader_url is not None:
        raise ValueError("An embedded Iray Uber material cannot use an external shader URL")
    if shader_url is not None:
        shader_url = _shader_url(shader_url)
    full_preset = shader_url is not None or embed_iray_uber
    overrides = overrides or {}
    if set(overrides) - set(surface_groups):
        raise ValueError("Overrides reference an unselected target surface")
    info = {"id": asset_id, "type": "preset_material"}
    for key in ("contributor", "revision"):
        if source_asset_info and key in source_asset_info:
            info[key] = deepcopy(source_asset_info[key])
    result: dict[str, Any] = {
        "file_version": "0.6.0.0", "asset_info": info,
        "scene": {"materials": [], "animations": []},
    }
    if not full_preset:
        del result["scene"]["materials"]
    image_ids: dict[str, str] = {}
    for target, sources in surface_groups.items():
        if not isinstance(target, str) or not target or any(ord(c) < 32 for c in target):
            raise ValueError("Target surface must be a nonempty name")
        names = [sources] if isinstance(sources, str) else list(sources)
        if not names:
            raise ValueError(f"Target {target!r} has no source surfaces")
        merged = SurfaceMaterial()
        image_aliases: dict[str, set[str]] = {}
        for index, name in enumerate(names):
            if name not in surfaces:
                raise ValueError(f"Unknown source surface: {name}")
            source = surfaces[name]
            # Namespace source images before merging: two inputs may use the
            # same image ID for different maps, including within one target.
            image_refs = {ref: f"image-{len(result.get('image_library', []))}-{index}-{n}"
                          for n, ref in enumerate(source.images)}
            for ref, image in source.images.items():
                merged.images[image_refs[ref]] = deepcopy(image)
                image_aliases.setdefault(ref, set()).add(image_refs[ref])
            for channel_id, channel in source.channels.items():
                patch = deepcopy(channel)
                if patch.get("image") is not None:
                    ref = _decode(patch["image"].removeprefix("#"))
                    if ref not in image_refs:
                        raise ValueError(f"Missing source image: {ref}")
                    patch["image"] = "#" + image_refs[ref]
                _update_channel(merged.channels.setdefault(channel_id, {}), patch)
            merged.slots.update(source.slots)
        for channel_id, patch in overrides.get(target, {}).items():
            if not isinstance(patch, Mapping) or ("id" in patch and patch["id"] != channel_id):
                raise ValueError("Channel overrides must be property mappings with matching IDs")
            patch = deepcopy(dict(patch))
            if patch.get("image") is not None:
                ref = _decode(patch["image"].removeprefix("#"))
                refs = image_aliases.get(ref, set())
                if len(refs) != 1:
                    raise ValueError(f"Missing or ambiguous override image: {ref}")
                patch["image"] = "#" + next(iter(refs))
            _update_channel(merged.channels.setdefault(channel_id, {}), patch)
        channel_declarations = {"type": "studio_material_channels", "channels": []}
        material = {"groups": [target], "extra": [channel_declarations]}
        if shader_url is not None:
            material["url"] = shader_url
            material["extra"].insert(0, {"type": "studio/material/daz_brick"})
        elif embed_iray_uber:
            material["extra"].insert(0, {"type": "studio/material/uber_iray", "version": "1.1.0.0"})
            result["scene"]["materials"].append({
                "groups": [target], "url": "#" + quote(target, safe=""),
                "extra": [{"type": "studio/material/uber_iray", "version": "1.1.0.0"}],
            })
        if full_preset and not embed_iray_uber:
            result["scene"]["materials"].append(material)
        for channel_id, channel in merged.channels.items():
            channel["id"] = channel_id
            if "image_file" in channel and channel["image_file"] is not None:
                channel["image_file"] = _content_path(channel["image_file"], root="Runtime/Textures")
                if shader_url is None:
                    ref = f"file-map-{len(result.get('image_library', []))}"
                    color = channel.get("type") in {"color", "float_color"} or merged.slots.get(channel_id) == "diffuse"
                    merged.images[ref] = {
                        "id": ref,
                        "map_gamma": channel.get("default_image_gamma", 0 if color else 1),
                        "map": [{"url": channel.pop("image_file")}],
                    }
                    channel["image"] = "#" + ref
            if channel.get("image") is not None:
                ref = _decode(channel["image"].removeprefix("#"))
                if ref not in merged.images:
                    raise ValueError(f"Missing merged image: {ref}")
                image = deepcopy(merged.images[ref])
                image.pop("id", None)
                _normalize_image_urls(image)
                content = json.dumps(_image_content(image), sort_keys=True, allow_nan=False)
                canonical_id = image_ids.get(content)
                if canonical_id is None:
                    canonical_id = f"file-map-{len(image_ids)}"
                    image_ids[content] = canonical_id
                    result.setdefault("image_library", []).append({"id": canonical_id, **image})
                channel["image"] = "#" + canonical_id
            declaration = deepcopy(channel)
            if channel_id in merged.slots:
                slot = merged.slots[channel_id]
                if slot in _RESERVED_SLOTS or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", slot):
                    raise ValueError(f"Invalid built-in channel slot: {slot}")
                path = slot
                material[slot] = {"channel": declaration}
            else:
                path = _CHANNELS + quote(channel_id, safe="")
                channel_declarations["channels"].append({"channel": declaration})
            if channel.get("image_file", False) is None:
                declaration.pop("image_file", None)
                declaration["image"] = None
            for prop in _RUNTIME_PROPERTIES:
                if prop not in channel:
                    continue
                value = channel[prop]
                prop = "image" if prop == "image_file" and value is None else prop
                values = value.items() if prop == "image_modification" else [(None, value)]
                for subkey, item in values:
                    suffix = prop + ("/" + quote(subkey, safe="") if subkey is not None else "")
                    result["scene"]["animations"].append({
                        "url": f"name://@selection#materials/{quote(target, safe='')}:?{path}/{suffix}",
                        "keys": [[0, deepcopy(item)]],
                    })
        if embed_iray_uber:
            del material["groups"]
            material["id"] = target
            result.setdefault("material_library", []).append(material)
    _reject_host_paths(result)
    # Fail here rather than handing the caller a partly serializable preset.
    json.dumps(result, allow_nan=False)
    return result
