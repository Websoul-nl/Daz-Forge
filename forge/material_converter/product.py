"""Discover character presets declared by one installed DAZ product."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from forge.analyzer.support import parse_support_metadata
from .character import SkinSource, UV_NAMES, inspect_skin
from .pbr_presets import read_dson


_SKIN_PRESETS = {"preset_material", "preset_hierarchical_material"}
_VARIANT_PRESETS = _SKIN_PRESETS | {"preset_layered_image", "preset_shader", "preset_properties"}


@dataclass(frozen=True)
class SkinCandidate:
    path: Path
    label: str
    source: SkinSource | None


@dataclass(frozen=True)
class CharacterProduct:
    manifest: Path
    root: Path
    name: str
    skins: tuple[SkinCandidate, ...]
    variants: tuple[Path, ...]
    missing: tuple[str, ...]


def load_character_product(path: Path) -> CharacterProduct:
    dsx = path.resolve()
    if (dsx.suffix.casefold() != ".dsx" or dsx.parent.name.casefold() != "support"
            or dsx.parent.parent.name.casefold() != "runtime"):
        raise ValueError("Select an installed product DSX from its library's Runtime/Support folder")
    root = dsx.parent.parent.parent
    metadata = parse_support_metadata(dsx.read_bytes())
    skins, variants, missing = [], [], []
    seen = set()
    for asset in metadata.assets:
        rel = unquote(asset.path.strip()).replace("\\", "/")
        if rel.startswith("/") and not rel.startswith("//"):
            rel = rel[1:]
        path_parts = PurePosixPath(rel).parts
        if (PurePosixPath(rel).suffix.casefold() != ".duf"
                or not path_parts or path_parts[0].casefold() not in {"people", "presets"}
                or any(p in {"", ".", ".."} or ":" in p or "\x00" in p for p in rel.split("/"))):
            continue
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            missing.append(rel)
            continue
        try:
            document = read_dson(path)
        except (ValueError, KeyError, OSError):
            if "material" in asset.content_type.casefold() or "layered" in asset.content_type.casefold():
                variants.append(path)
            continue
        kind = document.get("asset_info", {}).get("type")
        if kind not in _VARIANT_PRESETS:
            continue
        if kind not in _SKIN_PRESETS:
            variants.append(path)
            continue
        try:
            source = inspect_skin(document)
        except (ValueError, KeyError):
            for uv in UV_NAMES:
                try:
                    inspect_skin(document, uv)
                except (ValueError, KeyError):
                    continue
                skins.append(SkinCandidate(path, rel, None))
                break
            else:
                variants.append(path)
        else:
            skins.append(SkinCandidate(path, rel, source))
    return CharacterProduct(dsx, root, metadata.product_name or dsx.stem, tuple(skins), tuple(variants), tuple(missing))
