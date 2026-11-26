"""Forge's deterministic G8/G8.1 material conversion entry points."""

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote

import numpy as np
from PySide6.QtGui import QImageReader

from .atlas import TransferGrid, project, read_pixels, read_transfer, sample, texel_centers, write_pixels
from .eye_lookup import pad_eye_roles
from .g81_skin import resolve_g81_skin_layout
from .g9_presets import G9_FIGURE, bind_g9_material_hierarchy
from .iray_optics import bake_diffuse_split, diffuse_plan
from .iray_translation import Transfer, audit_iray_skin_channels, translated_iray_skin_values
from .layered_color import LIE_COLOR_SLOTS, LIE_PRESET_TYPE, as_native_lie_preset, rebase_color_stack
from .naming import g9_character_name, g9_texture_filename
from .normals import apply_transform
from .package import _references, build_material_package
from .pbr_presets import PBRSKIN_SHADER_URL, SurfaceMaterial, build_g9_material_preset, extract_surfaces, read_dson
from .preset_icons import write_preset_icons
from .skin_detail import NATIVE_DETAIL_CHANNELS, NATIVE_DETAIL_DEPENDENCIES, build_g9_skin_preset
from .skin_joins import reconcile_head_weight, reconcile_roughness
from .skin_readiness import LIP_ROUGHNESS, SKIN_ZONES, check_skin_readiness
from .source_iray import IRAY_UBER, build_g9_iray_uber_preset, rebind_iray_uber
from .source_pbr import Preservation, has_texture, pbr_preservation_map, rebind_pbr_skin
from .uv_seams import paired_edges


UBER = "Iray Uber"
PBR = "PBRSkin"
UV_NAMES = ("Base Female", "Base Male", "Base 8.1 Female", "Base 8.1 Male")
TILES = {"Head": 1001, "Body": 1002, "Arms": 1004, "Legs": 1003, "Fingernails": 1005, "Toenails": 1005}
ATTACHMENTS = {
    "Eyes": (1006, "Genesis9Eyes", {"Eye Left": "Irises", "Eye Right": "Irises"}, ("diffuse",)),
    "Mouth": (1007, "Genesis9Mouth", {"Mouth": "Mouth", "Teeth": "Teeth"}, ("diffuse", "Translucency Color")),
    "MouthCavity": (1001, G9_FIGURE, {"Mouth Cavity": "Mouth"}, ("diffuse", "Translucency Color")),
    "Lashes": (1008, "Genesis9Eyelashes", {"Eyelashes Upper": "Eyelashes", "Eyelashes Lower": "Eyelashes"},
               ("Cutout Opacity",)),
    "Tear": (1009, "Genesis9Tear", {"Tear": "Tear"}, ("Cutout Opacity",)),
}
SHADER_FILE = "data/DAZ 3D/Built-in Content/Daz Iray PBRSkin/PBRSkin.dsf"
G9_DATA = "data/Daz 3D/Genesis 9/Base"
BUNDLED_TRANSFERS = Path(__file__).with_name("uv_transfers")
MAX_OUTPUT_SIZE = 4096
IMAGE_DEFAULTS = dict(scale=1, offset=0, invert=False, horizontal_tiles=1, vertical_tiles=1,
                      horizontal_tiling_offset=0, vertical_tiling_offset=0, grayscale_mode="average")
LAYER_DEFAULTS = dict(invert=False, rotation=0, xmirror=False, ymirror=False, xscale=1, yscale=1, xoffset=0, yoffset=0)
SURFACE_UV_DEFAULTS = {"Horizontal Tiles": 1, "Vertical Tiles": 1, "Horizontal Offset": 0, "Vertical Offset": 0}


@dataclass(frozen=True)
class SkinSource:
    generation: str
    uv: str
    shader: str
    owner: str | None
    hierarchical: bool

    @property
    def routes(self) -> tuple[str, ...]:
        return (PBR,) if self.shader == PBR else (UBER, PBR)


@dataclass(frozen=True)
class ConversionResult:
    folder: Path
    archive: Path
    report: Path
    presets: tuple[str, ...]
    review_count: int


def _shader(surface):
    if unquote(surface.shader_url or "").casefold() == unquote(PBRSKIN_SHADER_URL).casefold():
        return PBR
    return UBER if surface.shader_type == IRAY_UBER else None


def inspect_skin(document: dict, confirmed_uv: str | None = None) -> SkinSource:
    scene = document.get("scene", {})
    roots = [(unquote(n["id"]), n) for n in scene.get("nodes", ())
             if re.fullmatch(r"Genesis8(?:_1)?(?:Male|Female)(?:-\d+)?", unquote(n.get("id", "")))]
    if len(roots) > 1:
        raise ValueError("Choose a preset with one source figure")
    owner, root = roots[0] if roots else (None, {})
    if not owner and scene.get("nodes"):
        raise ValueError("No compatible Genesis 8 or 8.1 figure was found")
    surfaces = extract_surfaces(document, owner=owner)
    if owner and "_1" in owner:
        layout = resolve_g81_skin_layout(document)
        generation, uv = "G8.1", layout.uv_name
    else:
        has_split = {"Head", "Body"} <= surfaces.keys() and "Torso" not in surfaces
        generation = "G8.1" if has_split else "G8"
        geometry = {"#" + unquote(g["id"]) for g in root.get("geometries", ())}
        main = {"Face", "Arms", "Legs"} | ({"Head", "Body"} if has_split else {"Torso"})
        group_paths = [row.get("uv_set") for row in scene.get("materials", ())
                       if main.intersection(row.get("groups", ()))
                       and (not owner or unquote(row.get("geometry", "")) in geometry)]
        if any(group_paths) and not all(group_paths):
            raise ValueError("The skin has a mix of declared and undeclared UVs")
        paths = {unquote(path) for path in group_paths if path}
        if len({p.casefold() for p in paths}) > 1:
            raise ValueError("The skin uses mixed UVs; one transfer cannot represent them")
        authored = next(iter(paths), "")
        uv = next((name for name in UV_NAMES if authored.partition("#")[2].casefold() == name.casefold()), "")
        if authored and (not uv or not authored.casefold().startswith("/data/daz 3d/genesis 8/")):
            raise ValueError("This UV set does not have a verified Base transfer")
        if not uv:
            if confirmed_uv not in UV_NAMES:
                raise ValueError("The preset does not state its UVs. Select the known source UV.")
            uv = confirmed_uv
        if generation == "G8" and uv.startswith("Base 8.1"):
            raise ValueError("A Torso-based skin requires legacy Base Male or Base Female UVs")
    if confirmed_uv and confirmed_uv != uv:
        raise ValueError(f"The selected UV does not match the authored {uv} UV")
    if owner and not owner.split("-")[0].endswith(uv.rsplit(" ", 1)[1]):
        raise ValueError("The source UV does not match the figure")
    if document.get("asset_info", {}).get("type") == "preset_hierarchical_material" and not owner:
        raise ValueError("The hierarchical material does not identify a supported figure")
    required = {"Face", "Arms", "Legs"} | ({"Head", "Body"} if generation == "G8.1" else {"Torso"})
    if not required <= surfaces.keys():
        raise ValueError("Choose a complete Genesis 8 or 8.1 skin preset")
    shaders = {_shader(surfaces[z]) for z in required}
    if len(shaders) != 1 or None in shaders:
        raise ValueError("The main skin mixes shaders or uses an unsupported shader")
    return SkinSource(generation, uv, shaders.pop(), owner,
                      document.get("asset_info", {}).get("type") == "preset_hierarchical_material")


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path leaves the selected folder: {relative}")
    return path


TRANSFER_MANIFEST = "manifest.json"
_TRANSFER_SCHEMA = "daz-forge-uv-transfer/1"
_TARGET_UV = "Base Multi UDIM"
_REQUIRED_TRANSFER_PARTS = {"Head", "Body", "Arms", "Legs"}


def transfer_bundle_name(generation: str, uv: str) -> str:
    """Keep the figure generation and its authored UV layout independent."""
    gender = uv.rsplit(" ", 1)[-1].lower()
    if generation == "G8.1":
        layout = "native" if uv.startswith("Base 8.1 ") else "legacy"
        return f"g8-1-{layout}-{gender}-to-g9"
    return f"g8-base-{gender}-to-g9"


def find_transfer_manifest(path: Path, source: SkinSource) -> Path | None:
    if path.is_file():
        return path.resolve()
    name = transfer_bundle_name(source.generation, source.uv)
    first = None
    for relative in (
        f"{name}/{TRANSFER_MANIFEST}", TRANSFER_MANIFEST,
        f"{source.generation} {source.uv}.json",
    ):
        candidate = path / relative
        if candidate.is_file():
            candidate = _inside(path, relative)
            if first is None:
                first = candidate
            if _has_transfer_payload(candidate, source):
                return candidate
    return first


def _read_transfer_manifest(manifest: Path, source: SkinSource | None = None) -> dict:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or (data.get("schema"), data.get("target_uv")) != (_TRANSFER_SCHEMA, _TARGET_UV):
        raise ValueError("Invalid Genesis 9 UV transfer manifest")
    if source and (data.get("generation"), data.get("source_uv")) != (source.generation, source.uv):
        raise ValueError("The UV transfer bundle does not match this source and Genesis 9")
    parts = data.get("parts")
    if not isinstance(parts, dict) or not _REQUIRED_TRANSFER_PARTS <= parts.keys():
        raise ValueError("The transfer bundle needs Head, Body, Arms and Legs")
    for zone, part in parts.items():
        if (not isinstance(part, dict) or not isinstance(part.get("slots"), dict)
                or not isinstance(part.get("file"), str) or not part["file"]
                or ("normal_transform" in part
                    and (not isinstance(part["normal_transform"], str) or not part["normal_transform"]))):
            raise ValueError(f"{zone}: invalid UV transfer part")
    return parts


def _has_transfer_payload(manifest: Path, source: SkinSource | None = None) -> bool:
    try:
        parts = _read_transfer_manifest(manifest, source)
        files = {part[key] for part in parts.values() for key in ("file", "normal_transform") if key in part}
        return all(_inside(manifest.parent, relative).is_file() for relative in files)
    except (OSError, ValueError):
        return False


def has_bundled_transfers(path: Path, source: SkinSource | None = None) -> bool:
    if source:
        try:
            manifest = find_transfer_manifest(path, source)
        except (OSError, ValueError):
            return False
        return manifest is not None and _has_transfer_payload(manifest, source)
    root = path.resolve()
    manifests = (path / TRANSFER_MANIFEST, *path.glob(f"*/{TRANSFER_MANIFEST}"), *path.glob("G8*.json"))
    for manifest in manifests:
        resolved = manifest.resolve()
        if resolved.is_relative_to(root) and _has_transfer_payload(resolved):
            return True
    return False


class TransferBundle:
    def __init__(self, path: Path, source: SkinSource):
        manifest = find_transfer_manifest(path, source)
        if manifest is None:
            raise ValueError(f"No transfer bundle for {source.generation} / {source.uv} in {path}")
        self.manifest = manifest
        self.root, self.parts = manifest.parent, _read_transfer_manifest(manifest, source)

    def load(self, zone):
        part = self.parts[zone]
        labels = part.get("labels", "source_id")
        if labels not in {"source_id", "roles"} or (labels == "roles" and zone != "Eyes"):
            raise ValueError(f"{zone}: unsupported donor label field")
        uv, ids = read_transfer(_inside(self.root, part["file"]), labels=labels)
        if labels == "roles":
            ids = pad_eye_roles(ids)
        present = set(np.unique(ids)) - {0}
        slots = {int(i): z for i, z in part["slots"].items()}
        if not present or present - slots.keys():
            raise ValueError(f"{zone}: missing UV donor regions")
        return uv, ids, {i: slots[i] for i in sorted(present)}

    def transform_normals(self, zone, pixels, ids, *, native_shape=None):
        relative = self.parts[zone].get("normal_transform")
        if not relative:
            raise ValueError("This UV bundle has no verified tangent calibration for the source normal")
        with np.load(_inside(self.root, relative), allow_pickle=False) as data:
            cs, sign, valid = data["cos_sin"], data["handedness"], data["valid"]
        native_shape = ids.shape if native_shape is None else native_shape
        if (cs.shape != (*native_shape, 2) or sign.shape != native_shape or valid.shape != native_shape
                or valid.dtype != np.bool_):
            raise ValueError("Tangent calibration dimensions do not match the UV bundle")
        # Sample the same nearest donor texel used by the resized lookup.
        yn = (texel_centers(native_shape[0], ids.shape[0]) + .5).astype(np.intp)
        xn = (texel_centers(native_shape[1], ids.shape[1]) + .5).astype(np.intp)
        covered = (ids != 0) & (pixels[..., 3] > .995)
        usable = covered & valid[yn[:, None], xn]
        if usable.sum() / max(np.count_nonzero(ids), 1) < .98:
            raise ValueError("Tangent calibration does not cover 98% of the projected normal")
        pixels[~usable, :3] = [.5, .5, 1]
        pixels[..., 3] = 1
        for start in range(0, len(ids), 64):
            y, x = np.nonzero(usable[start:start+64])
            y += start
            pixels[y, x, :3] = apply_transform(pixels[y, x, :3], cs[yn[y], xn[x]], sign[yn[y], xn[x]])
        return pixels


def _source_library(preset: Path) -> Path | None:
    return next((parent.parent for parent in preset.parents if parent.name.casefold() == "people"), None)


def _gamma_ok(prop, color):
    return (prop.get("default_image_gamma", 0 if color else 1) == (0 if color else 1)
            and all(IMAGE_DEFAULTS.get(k, object()) == v for k, v in (prop.get("image_modification") or {}).items()))


def _color(key, prop):
    return key == "diffuse" or prop.get("type") in ("color", "float_color")


def _scale(value, color):
    if color and isinstance(value, (list, tuple)) and len(value) == 3 and all(
        type(n) in (float, int) and 0 <= n <= 1 for n in value
    ):
        return tuple(float(n) ** 2.2 for n in value)
    if not color and type(value) in (float, int) and 0 <= value <= 1:
        return value
    raise ValueError("Regional multiplier cannot be baked into a normalized atlas")


class _Export:
    def __init__(self, source, document, preset, bundle, daz_library, content, title, source_library=None):
        self.source, self.document, self.preset, self.bundle = source, document, preset, bundle
        self.skin = extract_surfaces(document, owner=source.owner)
        self.content, self.title = content, title
        self.libraries = tuple(dict.fromkeys(filter(None, (source_library, _source_library(preset), daz_library))))
        self.daz_library = daz_library
        self.product = content / "People/Genesis 9/Materials/Daz Forge" / title
        self.textures = content / "Runtime/Textures/DazForge" / title
        self.product.mkdir(parents=True)
        self.textures.mkdir(parents=True)
        self.report = {
            "source": str(preset), "detected": asdict(source), "uv_transfer": str(bundle.manifest),
            "presets": [], "review": [], "dependencies": [], "texture_sizes": {},
        }
        self.base = None
        self.has_lip_bake = False
        self.saved_pixels = {}
        self.image_sizes = {}

    def review(self, route, target, reason, channel=None):
        item = {"route": route, "target": target, "reason": reason}
        if channel is not None:
            item["channel"] = channel
        if item not in self.report["review"]:
            self.report["review"].append(item)

    def path(self, url):
        relative = unquote(url).lstrip("/")
        if "\\" in relative or [
            p.casefold() for p in Path(relative).parts[:2]
        ] != ["runtime", "textures"]:
            raise ValueError(f"Not a Runtime texture reference: {url}")
        for root in self.libraries:
            candidate = _inside(root, relative)
            if candidate.is_file():
                return candidate
        raise ValueError(f"Source texture not found: {relative}")

    def image(self, surface, key, color):
        prop = surface.channels.get(key, {})
        if not has_texture(prop):
            return None
        if not _gamma_ok(prop, color) or any(
            name in surface.channels and (surface.channels[name].get("value", default) != default
                                          or has_texture(surface.channels[name]))
            for name, default in SURFACE_UV_DEFAULTS.items()
        ):
            raise ValueError("Source image has nonstandard gamma or texture modifiers")
        url = prop.get("image_file")
        if prop.get("image"):
            image = surface.images[unquote(prop["image"].removeprefix("#"))]
            layers = image.get("map", ())
            if len(layers) != 1 or image.get("map_gamma", 0 if color else 1) != (0 if color else 1):
                raise ValueError("Source map needs layered or nonstandard gamma handling")
            layer = layers[0]
            if (layer.get("operation", "alpha_blend") != "alpha_blend" or layer.get("transparency", 1) != 1
                    or layer.get("mask") or layer.get("layers") or any(layer.get(k, v) != v for k, v in LAYER_DEFAULTS.items())):
                raise ValueError("Source image layer has an unsupported transform, mask, or blend")
            url = layer["url"]
        return self.path(url)

    def put(self, route, zone, key, pixels, color):
        digest = hashlib.blake2b(np.ascontiguousarray(pixels), digest_size=16).digest()
        identity = (zone, color, pixels.shape, digest)
        if identity in self.saved_pixels:
            return self.saved_pixels[identity]
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", key)
        tile = TILES[zone] if zone in TILES else ATTACHMENTS[zone][0]
        name = g9_texture_filename(f"{zone}_{safe}_{tile}.png", character_name=self.title)
        folder = self.textures / route
        folder.mkdir(exist_ok=True)
        path = folder / name
        if path.exists():
            raise ValueError(f"Duplicate output map: {name}")
        write_pixels(path, pixels, color)
        url = "/" + path.relative_to(self.content).as_posix()
        self.saved_pixels[identity] = url
        self.report["texture_sizes"][url] = [pixels.shape[1], pixels.shape[0]]
        return url

    def map_size(self, paths, default, route, zone, key):
        sizes = []
        for path in set(paths) - {None}:
            if path not in self.image_sizes:
                size = QImageReader(str(path)).size()
                self.image_sizes[path] = max(size.width(), size.height()) if not size.isEmpty() else max(
                    read_pixels(path, False).shape[:2]
                )
            sizes.append(self.image_sizes[path])
        requested = max(sizes, default=default)
        if requested > MAX_OUTPUT_SIZE:
            self.review(route, zone, f"Source exceeds the {MAX_OUTPUT_SIZE}px export limit.", key)
        return min(requested, MAX_OUTPUT_SIZE)

    def emit(self, relative, doc, source=None):
        path = self.product / relative
        maps, deps = _references(doc)
        for ref in maps:
            if not (self.content / ref).is_file() and ref not in NATIVE_DETAIL_DEPENDENCIES:
                raise ValueError(f"Missing exported texture: {ref}")
        dependencies = sorted(deps | (maps & NATIVE_DETAIL_DEPENDENCIES))
        self.report["dependencies"] = sorted(set(self.report["dependencies"]) | set(dependencies))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as file:
            json.dump(doc, file, indent=2)
            file.write("\n")
        write_preset_icons(path, path.stem, "G8 to G9", accent="#a9d8d1", source_preset=source)
        self.report["presets"].append(path.relative_to(self.content).as_posix())

    def asset(self, relative):
        return "/" + (self.product / relative).relative_to(self.content).as_posix()

    def _skin_donors(self, zone, names, primary):
        donors = {}
        for i, name in names.items():
            s = self.skin.get(name)
            if s is None and name not in ("Lips", "Ears", "EyeSocket", "Fingernails", "Toenails"):
                raise ValueError(f"{zone}: source has no {name} UV donor")
            if s is None or _shader(s) != self.source.shader or (zone == "Head" and name == "EyeSocket"):
                if name != "EyeSocket":
                    self.review(self.source.shader, zone, f"Used {primary} instead of missing or incompatible {name}.")
                name, s = primary, self.skin[primary]
            if zone in ("Arms", "Legs") and name in ("Fingernails", "Toenails"):
                name = "Arms" if name == "Fingernails" else "Legs"
                s = self.skin[name]
            donors[i] = name, s
        return donors

    def _project_channel(self, route, zone, key, primary, donors, grid, *, bake, rule=None):
        primary_prop = primary.channels.get(key, {})
        color = _color(key, primary_prop)
        initial = primary_prop.get("value", [1, 1, 1] if color else 1)
        inputs, values = {}, []
        for i, (name, donor) in donors.items():
            prop = donor.channels.get(key, {})
            value = prop.get("value", initial)
            values.append(value)
            inputs[i] = self.image(donor, key, color), value
        if not any(path for path, _ in inputs.values()) and not (
            rule or bake and any(v != initial for v in values)
        ):
            return None, initial, None
        mixed = any(value != initial for value in values)
        if mixed and not bake:
            self.review(route, zone, "Regional slider values differ; kept the primary value.", key)
        if rule is not None:
            inputs = {i: (None, rule.texels[donors[i][0]]) for i in inputs}
            slider = rule.slider
        elif mixed and bake:
            inputs = {i: (path, _scale(value, color)) for i, (path, value) in inputs.items()}
            slider = [1, 1, 1] if color else 1
        else:
            inputs = {i: (path, 1) for i, (path, _) in inputs.items()}
            slider = initial
        size = self.map_size((path for path, _ in inputs.values()), min(max(grid.ids.shape), 2048), route, zone, key)
        uv, ids = grid.at_size(size)
        return project(uv, ids, inputs, color=color), slider, ids

    def _surface(self, route, zone, primary, donors, grid, schema):
        authored = self.skin[primary]
        mapped = {k for k, p in authored.channels.items() if has_texture(p)}
        preserved = route == PBR and self.source.shader == PBR
        pbr_rules = {}
        if preserved:
            regions = {primary: authored} | {name: s for name, s in donors.values()}
            pbr_rules = pbr_preservation_map(regions, schema, native_detail=True, target_surface=zone)
            keys = {k for k, r in pbr_rules.items() if r.action in (Preservation.REMAP, Preservation.BAKE)
                    or k in schema.channels and any(has_texture(s.channels.get(k, {})) for s in regions.values())
                    and k not in NATIVE_DETAIL_CHANNELS and r.action != Preservation.INACTIVE}
        elif route == UBER:
            keys = mapped | {k for _, s in donors.values() for k, p in s.channels.items()
                             if k in authored.channels and has_texture(p)}
        else:
            keys = {"diffuse", "Translucency Color", "Dual Lobe Specular Reflectivity"}
        maps, sliders = {}, {}
        base_pixels = None
        for key in sorted(keys):
            if (key == "Normal Map" and route != UBER) or key in ("Detail Normal Map", "Detail Specular Roughness Mult"):
                self.review(route, zone, "Source detail needs a verified tangent-space transfer; not copied.", key)
                continue
            if key == "Normal Map" and not self.bundle.parts[zone].get("normal_transform"):
                self.review(route, zone, "This UV bundle has no verified tangent calibration; source normal was not copied.", key)
                continue
            if route == UBER and key.startswith("Top Coat ") and authored.channels.get("Top Coat Weight", {}).get("value") == 0:
                continue
            try:
                rule = pbr_rules.get(key)
                pixels, value, ids = self._project_channel(
                    route, zone, key, authored, donors, grid, bake=preserved,
                    rule=rule.bake if rule else None,
                )
                if pixels is None:
                    continue
                if key == LIP_ROUGHNESS and zone == "Head" and rule and rule.bake:
                    self.has_lip_bake = rule.bake.texels.get("Lips") not in (None, 1) and all(
                        scale == 1 for region, scale in rule.bake.texels.items() if region != "Lips"
                    )
                if key == "Normal Map":
                    if any(self.image(s, key, False) is None for _, s in donors.values()):
                        raise ValueError("Some donor regions have no source normal; review the mixed normal binding")
                    pixels = self.bundle.transform_normals(zone, pixels, ids, native_shape=grid.ids.shape)
                if key == "diffuse" and route == PBR and not preserved:
                    base_pixels = pixels
                maps[key] = self.put(route, zone, key, pixels, _color(key, authored.channels.get(key, {})))
                sliders[key] = value
            except ValueError as exc:
                self.review(route, zone, str(exc), key)
        if has_texture(authored.channels.get("diffuse", {})) and "diffuse" not in maps:
            raise ValueError(f"{zone}: cannot export without the source Base Color map")
        if route == UBER:
            result = rebind_iray_uber(authored, {k:v for k,v in maps.items() if k in mapped},
                                     omit_maps=frozenset(mapped - maps.keys()))
            for key, url in maps.items():
                result.channels[key].update(value=sliders[key], image_file=url)
            return result
        if preserved:
            for key, rule in pbr_rules.items():
                if rule.action == Preservation.REVIEW and key not in maps:
                    self.review(route, zone, rule.reason, key)
            result = rebind_pbr_skin(authored, {k:v for k,v in maps.items() if k in authored.channels}, native_detail=True)
            for key in authored.channels.keys() - schema.channels.keys():
                result.channels.pop(key, None)
            for key, url in maps.items():
                result.channels.setdefault(key, deepcopy(schema.channels[key])).update(value=sliders[key], image_file=url)
            return result
        result = deepcopy(schema)
        result.slots["diffuse"] = "diffuse"
        for key in ("diffuse", "Translucency Color", "Dual Lobe Specular Reflectivity",
                    "Dual Lobe Specular Ratio", "Translucency Weight"):
            if key in result.channels and key in authored.channels and "value" in authored.channels[key]:
                result.channels[key]["value"] = deepcopy(authored.channels[key]["value"])
        for key, url in maps.items():
            result.channels[key].update(image_file=url, default_image_gamma=0 if _color(key, result.channels[key]) else 1)
        plan = diffuse_plan(authored)
        pair = None
        if base_pixels is not None and plan and plan.mode in (1, 2) and all(diffuse_plan(s) == plan for _, s in donors.values()):
            alpha = base_pixels[..., 3:4]
            rgb = np.divide(base_pixels[..., :3], alpha, out=np.zeros_like(base_pixels[..., :3]), where=alpha > 0)
            diffuse, weight = bake_diffuse_split(plan, np.clip(rgb, 0, 1))
            c = self.put(route, zone, "SplitColor", np.concatenate((diffuse*alpha, alpha), -1), True)
            w = base_pixels.copy()
            w[..., :3], w[..., 3] = weight[..., None], 1
            pair = c, self.put(route, zone, "SplitWeight", w, False)
        for key, patch in translated_iray_skin_values(authored, result, baked_pair=pair).items():
            result.channels[key].update(patch)
        for key, rule in audit_iray_skin_channels(authored, result, baked_pair=pair).items():
            if rule.transfer in (Transfer.REVIEW, Transfer.UNMAPPED):
                self.review(route, zone, rule.note, key)
        return result

    def skin_preset(self, route, progress):
        schema = None
        if route == PBR:
            schema = extract_surfaces(read_dson(self.daz_library / SHADER_FILE))["PBRSkin"]
        target = {}
        for zone in TILES:
            primary = "Face" if zone == "Head" else "Torso" if zone == "Body" and self.source.generation == "G8" else zone
            if zone not in self.bundle.parts or primary not in self.skin or _shader(self.skin[primary]) != self.source.shader:
                self.review(route, zone, "No verified adapter or matching authored shader; keep the loaded G9 material.")
                continue
            uv, ids, names = self.bundle.load(zone)
            progress(f"Converting {route}: {zone}")
            donors = self._skin_donors(zone, names, primary)
            target[zone] = self._surface(route, zone, primary, donors, TransferGrid(uv, ids), schema)
        name = f"01 Skin - {route}.duf"
        asset = self.asset(name)
        if route == PBR:
            if self.source.shader == PBR:
                self.align_pbr_gloss(target, progress)
            doc = build_g9_skin_preset(target, {z:z for z in target}, asset_id=asset,
                                      skin_profile="feminine" if self.source.uv.endswith("Female") else "masculine")
        else:
            doc = build_g9_iray_uber_preset(target, asset_id=asset)
        if self.source.hierarchical:
            doc = bind_g9_material_hierarchy({G9_FIGURE: doc}, asset_id=asset)
        if route == PBR:
            readiness = check_skin_readiness(doc, allow_head_lip_map=self.has_lip_bake)
            for issue in readiness.issues:
                self.review(route, ", ".join(issue.surfaces), issue.kind.replace("_", " "), issue.channel)
            self.report["skin_readiness"] = {"ready": readiness.ready, **asdict(readiness)}
        self.emit(name, doc, self.preset)
        surfaces = extract_surfaces(doc, owner=G9_FIGURE if self.source.hierarchical else None)
        try:
            self.audit_joins(route, surfaces)
        except (ValueError, KeyError, OSError) as exc:
            self.review(route, "Skin joins", f"Could not check the UV edges: {exc}")
        if self.base is None:
            self.base = surfaces

    def align_pbr_gloss(self, surfaces, progress):
        weight = "Dual Lobe Specular Weight"
        channels = {z: surfaces[z].channels.get(weight, {}) for z in SKIN_ZONES}
        mapped = {z for z,p in channels.items() if has_texture(p)}
        same_weight = len({p.get("value") for p in channels.values()}) == 1
        if mapped and same_weight:
            for zone, prop in channels.items():
                if not has_texture(prop) and type(prop.get("value")) in (float, int):
                    prop.update(image_file=self.put(PBR, zone, "SpecularWeightNeutral", np.ones((4,4,4), np.float32), False),
                                default_image_gamma=1)
        head = channels["Head"]
        if mapped == {"Head"} and same_weight and head.get("image_file") and _gamma_ok(head, False):
            try:
                geometry, uv_set = self._target_geometry()
                path = self.content / unquote(head["image_file"]).lstrip("/")
                corrected = reconcile_head_weight(read_pixels(path, False), geometry, uv_set)
                head["image_file"] = self.put(PBR, "Head", "SpecularWeightJoin", corrected, False)
            except (OSError, ValueError, KeyError) as exc:
                self.review(PBR, "Head", f"Kept projected specular weight: {exc}", weight)
        props = {z: surfaces[z].channels.get(LIP_ROUGHNESS, {}) for z in SKIN_ZONES}
        if not all(p.get("image_file") and _gamma_ok(p, False) for p in props.values()) or len(
            {p.get("value") for p in props.values()}
        ) != 1:
            return
        paths = {z: self.content / unquote(p["image_file"]).lstrip("/") for z,p in props.items()}
        dimensions = {zone: QImageReader(str(path)).size() for zone, path in paths.items()}
        if any(size.isEmpty() or size.width() != size.height() for size in dimensions.values()):
            return
        progress("Checking and aligning PBRSkin roughness joins")
        replacements = {}
        try:
            geometry, uv_set = self._target_geometry()
            reconcile_roughness(geometry, uv_set, lambda z: read_pixels(paths[z], False),
                                lambda z, pixels: replacements.update({z: self.put(PBR, z, "RoughnessJoin", pixels, False)}),
                                {zone: size.width() for zone, size in dimensions.items()})
        except (ValueError, KeyError, OSError) as exc:
            self.review(PBR, "Skin joins", f"Kept original projected roughness maps: {exc}")
        else:
            for zone, url in replacements.items():
                props[zone]["image_file"] = url

    def _target_geometry(self):
        root = self.daz_library / G9_DATA
        geometry = read_dson(root / "Genesis9.dsf")["geometry_library"][0]
        uv_set = read_dson(root / "UV Sets/Daz 3D/Base/Base Multi UDIM.dsf")["uv_set_library"][0]
        return geometry, uv_set

    def audit_joins(self, route, surfaces):
        geometry, uv_set = self._target_geometry()
        stats = self.report.setdefault("gloss_joins", {}).setdefault(route, {})
        for zone in ("Head", "Arms", "Legs"):
            pairs = paired_edges(geometry, uv_set, "Body", zone)
            if not pairs:
                raise ValueError(f"No shared edges for Body / {zone}")
            edges = []
            for idx in (0, 1):
                points = []
                for pair in pairs:
                    edge, center = pair[idx]
                    pos = edge[0] + np.array([[.25], [.5], [.75]]) * (edge[1] - edge[0])
                    shift = center-pos
                    points.append((pos, shift))
                edges.append(tuple(np.concatenate(columns) for columns in zip(*points, strict=True)))
            for key in ("Specular Lobe 1 Roughness", "Dual Lobe Specular Reflectivity", "Dual Lobe Specular Weight"):
                values = []
                for surface, (pos, shift) in zip((surfaces["Body"], surfaces[zone]), edges, strict=True):
                    prop = surface.channels.get(key, {})
                    value = prop.get("value")
                    if type(value) not in (int, float):
                        break
                    url = prop.get("image_file")
                    if prop.get("image"):
                        definition = surface.images[unquote(prop["image"].removeprefix("#"))]
                        [layer] = definition["map"]
                        url = layer["url"]
                    samples = 1
                    if url:
                        image = read_pixels(self.content / unquote(url).lstrip("/"), False)
                        length = np.maximum(np.linalg.norm(shift, axis=1, keepdims=True), 1e-8)
                        points = pos + shift * np.minimum(1, .5 / max(image.shape[:2]) / length)
                        samples = sample(image, points)[:,0]
                    values.append(samples * value)
                if len(values) == 2:
                    delta = np.abs(values[0]-values[1])
                    p95, worst = float(np.percentile(delta, 95)), float(np.max(delta))
                    stats.setdefault(zone, {})[key] = {"p95": p95, "max": worst}
                    if p95 > .025 or worst > .075:
                        self.review(route, f"Body / {zone}", f"Map × slider differs at the UV join (95th percentile {p95:.3f}, max {worst:.3f}).", key)

    def layered(self, source, document, index, source_label):
        edits = extract_surfaces(document)
        if not edits or any(set(s.channels) - set(LIE_COLOR_SLOTS) for s in edits.values()):
            raise ValueError("This overlay edits channels other than Base Color/Translucency Color")
        planned = {}
        matched = set()
        for zone in ("Head", "Body", "Arms", "Legs"):
            uv, ids, names = self.bundle.load(zone)
            grid = TransferGrid(uv, ids)
            for key in LIE_COLOR_SLOTS:
                stacks = {}
                for i, name in names.items():
                    donor = edits.get(name)
                    prop = donor.channels.get(key, {}) if donor else {}
                    if not prop:
                        continue
                    if not prop.get("image") or not _gamma_ok(prop, True) or "value" in prop:
                        raise ValueError(f"{name}/{key}: unsupported image binding")
                    definition = donor.images[unquote(prop["image"].removeprefix("#"))]
                    layers = definition.get("map", ())
                    if (len(layers) < 2 or definition.get("map_gamma", 0) != 0
                            or any(layer.get("mask") or layer.get("layers") or set(layer) - (
                                LAYER_DEFAULTS.keys() | {"label", "url", "operation", "transparency", "color"}
                            ) or any(layer.get(k, v) != v for k, v in LAYER_DEFAULTS.items()) for layer in layers)):
                        raise ValueError(f"{name}/{key}: unsupported LIE masks or transforms")
                    stacks[i] = layers
                    matched.add((name, key))
                if not stacks:
                    continue
                template = next(iter(stacks.values()))
                signature = lambda layers: [(p.get("operation"), p.get("transparency")) for p in layers]
                if any(signature(layers) != signature(template) for layers in stacks.values()) or any(
                    p.get("operation") not in {"alpha_blend", "multiply"} for p in template
                ):
                    raise ValueError(f"{zone}/{key}: incompatible layer order, blend mode or opacity")
                base = self.base[zone]
                prop = deepcopy(base.channels.get(key, {}))
                if prop.get("image"):
                    image = base.images[unquote(prop.pop("image").removeprefix("#"))]
                    [layer] = image["map"]
                    prop["image_file"] = layer["url"]
                stack = rebase_color_stack({"map_gamma": 0, "map": template}, prop)
                layers_by_donor = [{i: (self.path(layers[n]["url"]), 1) for i, layers in stacks.items()}
                                   for n in range(1, len(template))]
                base_path = self.content / unquote(prop["image_file"]).lstrip("/")
                paths = [base_path, *(path for inputs in layers_by_donor for path, _ in inputs.values())]
                size = self.map_size(paths, max(ids.shape), "Overlays", zone, key)
                stack["map_size"] = [size, size]
                layer_uv, layer_ids = grid.at_size(size)
                for n, (layer, inputs) in enumerate(zip(stack["map"][1:], layers_by_donor, strict=True), 1):
                    pixels = project(layer_uv, layer_ids, inputs, color=True)
                    name = f"Overlay{index}_{key}_{n}"
                    layer["url"] = self.put("Overlays", zone, name, pixels, True)
                planned.setdefault(zone, {})[key] = stack
        missing = {(z,k) for z,s in edits.items() for k in s.channels} - matched
        if missing:
            raise ValueError("No UV coverage for " + ", ".join(f"{z}/{k}" for z,k in sorted(missing)))
        surfaces = {
            z: SurfaceMaterial(channels={k: {"image": "#"+k} for k in stacks},
                               images=stacks, slots={"diffuse":"diffuse"})
            for z, stacks in planned.items()
        }
        name = (Path("Overlays") / Path(source_label).parent / source.name).as_posix()
        material = build_g9_material_preset(surfaces, {z:z for z in surfaces}, asset_id=self.asset(name), shader_url=None)
        self.emit(name, as_native_lie_preset(material), source)

    def accessory(self, part, materials, file, name, index):
        if part not in self.bundle.parts:
            raise ValueError(f"No verified {part} UV transfer in this bundle")
        _, owner, targets, channels = ATTACHMENTS[part]
        uv, ids, names = self.bundle.load(part)
        grid = TransferGrid(uv, ids)
        if part == "Eyes" and not {"Pupils", "Irises", "Sclera"} <= set(names.values()):
            raise ValueError("Eyes need a surface-aware pupil, iris and sclera transfer")
        missing = set(names.values()) - materials.keys()
        if missing:
            raise ValueError("Missing source surfaces: " + ", ".join(sorted(missing)))
        output = {}
        saved = {}
        for zone, primary in targets.items():
            subset = names if part != "Mouth" else {i:n for i,n in names.items() if n == primary}
            donors = {i: (n, materials[n]) for i, n in subset.items()}
            props = {}
            for key in channels:
                token = primary, key
                if token not in saved:
                    pixels, value, _ = self._project_channel(
                        "Accessories", part, key, materials[primary], donors, grid, bake=True,
                    )
                    saved[token] = (
                        self.put("Accessories", part, f"{index}_{primary}_{key}", pixels,
                                 _color(key, materials[primary].channels.get(key, {}))),
                        value,
                    ) if pixels is not None else (None, value)
                path, value = saved[token]
                if path:
                    props[key] = {"image_file": path, "value": value,
                                  "type": "color" if key != "Cutout Opacity" else "float"}
            if props:
                output[zone] = SurfaceMaterial(channels=props, slots={"diffuse":"diffuse"})
        if not output:
            raise ValueError("No compatible authored texture bindings")
        asset = self.asset(name)
        doc = build_g9_material_preset(output, {z:z for z in output}, asset_id=asset, shader_url=None)
        self.emit(name, bind_g9_material_hierarchy({owner:doc}, asset_id=asset), file)

    def default_accessories(self):
        materials = dict(self.skin)
        for node in self.document["scene"].get("nodes", ()):
            name = unquote(node.get("id", ""))
            if name != self.source.owner and (
                "eyelash" in name.casefold() or "tear" in name.casefold()
            ):
                try:
                    materials.update(extract_surfaces(self.document, owner=name))
                except (ValueError, KeyError) as exc:
                    self.review("Accessories", name, str(exc))
        for part, (_, _, zones, _) in ATTACHMENTS.items():
            if not set(zones.values()) <= materials.keys():
                continue
            try:
                self.accessory(part, materials, None, f"Accessories/{part} - Default.duf", 0)
            except (ValueError, KeyError, OSError) as exc:
                self.review("Accessories", part, str(exc))

    def _variant_materials(self, doc):
        if doc.get("asset_info", {}).get("type") == "preset_hierarchical_material":
            for node in doc["scene"].get("nodes", ()):
                if node.get("geometries"):
                    yield extract_surfaces(doc, owner=unquote(node["id"]))
        else:
            yield extract_surfaces(doc)

    def variants(self, variants_folder, product=None):
        if product is not None:
            entries = ((p.relative_to(product.root).as_posix(), p) for p in product.variants)
        elif variants_folder is not None:
            entries = ((p.relative_to(variants_folder).as_posix(), p) for p in sorted(variants_folder.rglob("*.duf")))
        else:
            self.review("Accessories", "Variants", "No variant folder selected. Separate presets were not converted.")
            return
        for index, (label, file) in enumerate(entries, 1):
            if file.resolve() == self.preset:
                continue
            try:
                doc = read_dson(file)
                if doc.get("asset_info", {}).get("type") == LIE_PRESET_TYPE:
                    self.layered(file, doc, index, label)
                    continue
                converted = False
                for group in self._variant_materials(doc):
                    for part, allowed in (
                        ("Eyes", {"Irises", "Pupils", "Sclera", "Cornea", "EyeMoisture"}),
                        ("Lashes", {"Eyelashes"}), ("Tear", {"Tear"}),
                    ):
                        if set(group) <= allowed and set(ATTACHMENTS[part][2].values()) <= group.keys():
                            materials = dict(self.skin)
                            for key, patch in group.items():
                                donor = deepcopy(materials.get(key, SurfaceMaterial()))
                                donor.images.update(patch.images)
                                for ch, prop in patch.channels.items():
                                    combined = donor.channels.setdefault(ch, {})
                                    if "image" in prop or "image_file" in prop:
                                        combined.pop("image", None)
                                        combined.pop("image_file", None)
                                    combined.update(prop)
                                materials[key] = donor
                            parent = Path(label).parent
                            self.accessory(part, materials, file, (Path("Accessories") / parent / file.name).as_posix(), index)
                            converted = True
                if not converted:
                    self.review("Accessories", label, "Needs a separate material pass (e.g. shell, graft, volume, brow, or shader makeup).")
            except (ValueError, KeyError, OSError) as exc:
                self.review("Accessories", label, str(exc))


def convert_character(
    preset: Path, daz_library: Path, transfer_folder: Path | None, output: Path, *,
    character_name: str, include_pbr: bool = False, confirmed_uv: str | None = None,
    variants_folder: Path | None = None, product_dsx: Path | None = None, progress=lambda message: None,
) -> ConversionResult:
    """Write a private archive and editable review report; never write into a source library."""
    preset, daz_library, output = preset.resolve(), daz_library.resolve(), output.resolve()
    if preset.suffix.casefold() != ".duf" or not preset.is_file():
        raise ValueError("Select an existing .duf skin preset")
    if not daz_library.is_dir() or not output.is_dir() or (variants_folder and not variants_folder.is_dir()):
        raise ValueError("Select existing DAZ, variant (if supplied), and export folders")
    product = None
    if product_dsx is not None:
        from .product import load_character_product

        product = load_character_product(product_dsx)
        if variants_folder is not None or not any(c.path == preset for c in product.skins):
            raise ValueError("Select a full-skin preset from this DSX product")
    source_root = product.root if product else _source_library(preset)
    if any(output.is_relative_to(root) for root in (source_root, daz_library) if root is not None):
        raise ValueError("Choose an export folder outside the source and DAZ libraries")
    if variants_folder and output.is_relative_to(variants_folder.resolve()):
        raise ValueError("Choose an export folder outside the variant folder")
    title = g9_character_name(character_name)
    if (re.search(r'[\\/:*?"<>|\x00-\x1f]', title) or title in {".", ".."} or
            title.rstrip(" .") != title or len(title) > 85):
        raise ValueError("The character name cannot be used as an export folder name")
    doc = read_dson(preset)
    source = inspect_skin(doc, confirmed_uv)
    bundle = TransferBundle(transfer_folder or BUNDLED_TRANSFERS, source)
    dest = output / f"{title} - Character Conversion"
    if dest.exists():
        raise FileExistsError(f"Export already exists: {dest}")
    routes = source.routes if source.shader == PBR or include_pbr else (UBER,)
    with tempfile.TemporaryDirectory(prefix=".daz-forge-", dir=output) as temp:
        stage = Path(temp) / "publish"
        exporter = _Export(source, doc, preset, bundle, daz_library, stage / "Content", title, source_root)
        exporter.report["requested_routes"] = list(routes)
        if product is not None:
            exporter.report["product_dsx"] = str(product.manifest)
            for missing in product.missing:
                exporter.review("Product", missing, "Listed in the selected DSX but not found in its library")
            for candidate in product.skins:
                if candidate.path != preset:
                    exporter.review("Product", candidate.label, "Alternate full skin; not applied to the selected skin")
        for index, route in enumerate(routes):
            progress(f"Converting {route} skin")
            try:
                exporter.skin_preset(route, progress)
            except (OSError, ValueError, KeyError) as exc:
                if index == 0:
                    raise ValueError(f"{route} export could not be built: {exc}") from exc
                exporter.review(route, "Optional skin", f"Not exported: {exc}")
        extra_groups = sorted(set(exporter.skin) - {
            "Face", "Head", "Lips", "Ears", "EyeSocket", "Body", "Torso", "Arms", "Legs", "Fingernails", "Toenails",
        })
        if extra_groups or source.hierarchical:
            exporter.review("Accessories", "Figure and fittings",
                            "Shape, shell and graft geometry are not transferred. Fit native G9 accessories before applying their presets.")
        exporter.default_accessories()
        progress("Checking material variants")
        exporter.variants(variants_folder, product)
        report = stage / "Review.json"
        report.write_text(json.dumps(exporter.report, indent=2) + "\n", encoding="utf-8")
        progress("Validating private content archive")
        archive = stage / f"{title} Materials.zip"
        build_material_package(exporter.content, exporter.product.relative_to(exporter.content).as_posix(),
                               archive, product_name=title)
        if dest.exists():
            raise FileExistsError(f"Export already exists: {dest}")
        stage.rename(dest)
    return ConversionResult(dest, dest/archive.name, dest/report.name, tuple(exporter.report["presets"]),
                            len(exporter.report["review"]))
