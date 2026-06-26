from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
import re

from forge.analyzer.dson import DsonAssetInfo, DsonParseError, parse_dson_asset_info
from forge.analyzer.inventory import InventoryItem, InventoryResult
from forge.analyzer.source import SourceFile, SourceScan, read_source_file
from forge.analyzer.support import SupportAssetHint, SupportParseError, parse_support_metadata


CONTENT_TYPE_BY_DSON_TYPE = {
    "character": "Actor/Character",
    "figure": "Actor",
    "wearable": "Follower/Wardrobe",
    "preset_hierarchical_material": "Preset/Materials",
    "preset_material": "Preset/Materials",
    "preset_layered_image": "Preset/Materials",
    "preset_shape": "Preset/Morph",
    "preset_properties": "Preset/Properties",
    "preset_pose": "Preset/Pose",
    "preset_hierarchical_pose": "Preset/Pose",
    "pose": "Preset/Pose",
    "preset_shader": "Preset/Shader",
    "scene_subset": "Set",
    "scene": "Scene",
    "uv_set": "Support/UV Set",
}


@dataclass(frozen=True)
class AssetSuggestion:
    path: str
    content_type: str
    categories: tuple[str, ...]
    compatibility_base: str = ""
    compatibilities: tuple[str, ...] = ()
    asset_type: str = ""
    author: str = ""
    confidence: float = 0.6
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductSuggestion:
    product_type: str
    primary_artist: str
    artist_state: str
    artists: tuple[str, ...]


@dataclass(frozen=True)
class InferenceResult:
    product: ProductSuggestion
    assets: tuple[AssetSuggestion, ...]
    warnings: tuple[str, ...]


def infer_metadata(scan: SourceScan, inventory: InventoryResult) -> InferenceResult:
    file_by_content_path = {file.content_path: file for file in scan.files}
    support_hints = _load_support_hints(scan)
    assets = tuple(
        _infer_asset(scan, item, file_by_content_path[item.content_path], support_hints.get(item.content_path, ()))
        for item in inventory.smart_content
    )
    product = _infer_product(assets)
    warnings = _collect_warnings(product, assets)
    return InferenceResult(product=product, assets=assets, warnings=warnings)


def _infer_asset(
    scan: SourceScan,
    item: InventoryItem,
    source_file: SourceFile,
    support_hints: tuple[SupportAssetHint, ...],
) -> AssetSuggestion:
    dson_info = _parse_dson_for_item(scan, item, source_file)
    content_type = _infer_content_type(item, dson_info)
    support_content_types = {hint.content_type for hint in support_hints if hint.content_type}
    content_type = _adjust_content_type_with_support(item, content_type, support_content_types)
    categories = _infer_categories(item.content_path, content_type)
    compatibilities = _infer_compatibilities(item.content_path)
    author = dson_info.contributor.author if dson_info is not None else ""
    asset_type = dson_info.asset_type if dson_info is not None else ""
    warnings = list(item.warnings)
    confidence = 0.6

    if not content_type:
        warnings.append("unknown-content-type")
        confidence = 0.3

    if dson_info is None and item.extension in {".duf", ".dsf"}:
        warnings.append("dson-parse-failed")
        confidence = min(confidence, 0.4)

    support_categories = {category for hint in support_hints for category in hint.categories}

    if support_content_types:
        if any(_metadata_family_agrees(content_type, support_type) for support_type in support_content_types):
            confidence = max(confidence, 0.8)
        else:
            warnings.append("support-content-type-conflict")
            confidence = min(confidence, 0.45)

    if support_categories:
        if any(_metadata_family_agrees(category, support_category) for category in categories for support_category in support_categories):
            confidence = max(confidence, 0.9)
        else:
            warnings.append("support-category-conflict")
            confidence = min(confidence, 0.45)

    return AssetSuggestion(
        path=item.content_path,
        content_type=content_type,
        categories=categories,
        compatibilities=compatibilities,
        asset_type=asset_type,
        author=author,
        confidence=confidence,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _parse_dson_for_item(scan: SourceScan, item: InventoryItem, source_file: SourceFile) -> DsonAssetInfo | None:
    if item.extension not in {".duf", ".dsf"}:
        return None
    try:
        return parse_dson_asset_info(read_source_file(scan, source_file))
    except (DsonParseError, OSError):
        return None


def _infer_content_type(item: InventoryItem, dson_info: DsonAssetInfo | None) -> str:
    parts = tuple(part.lower() for part in PurePosixPath(item.content_path).parts)
    if item.extension in {".dsa", ".dse"}:
        return "Script/Utility"
    if dson_info is None:
        return ""
    if dson_info.asset_type == "wearable" and "hair" in parts:
        return "Follower/Hair"
    if dson_info.asset_type == "wearable" and "accessories" in parts:
        return "Follower/Accessory"
    return CONTENT_TYPE_BY_DSON_TYPE.get(dson_info.asset_type, "")


def _adjust_content_type_with_support(
    item: InventoryItem,
    content_type: str,
    support_content_types: set[str],
) -> str:
    parts = tuple(part.lower() for part in PurePosixPath(item.content_path).parts)
    if content_type == "Set" and parts and parts[0] == "props":
        if any(_metadata_family(support_type) == "prop" for support_type in support_content_types):
            return "Prop"
    return content_type


def _infer_categories(content_path: str, content_type: str) -> tuple[str, ...]:
    parts = tuple(part.lower() for part in PurePosixPath(content_path).parts)
    joined = "/".join(parts)

    if content_type.startswith("Script/"):
        return ("/Default/Utilities/Scripts",)
    if parts and parts[0] == "vehicles":
        return ("/Default/Transportation/Land",)
    if parts and parts[0] == "scripts":
        return ("/Default/Utilities/Scripts",)
    if "materials" in parts or content_type == "Preset/Materials":
        return ("/Default/Materials",)
    if content_type in {"Prop", "Set"} and ("props" in parts or "probs" in parts):
        return ("/Default/Props",)
    if "poses" in parts or content_type == "Preset/Pose":
        return ("/Default/Poses",)
    if "shaping" in parts or content_type == "Preset/Morph":
        return ("/Default/Shaping",)
    if "hair" in parts or content_type == "Follower/Hair":
        return ("/Default/Hair",)
    if "characters" in parts or content_type == "Actor/Character":
        return ("/Default/Figures/People",)
    if "accessories" in parts or content_type == "Follower/Accessory":
        return ("/Default/Accessories",)
    if parts and parts[0] in {"props", "figures"}:
        return ("/Default/Props",)
    if "clothing" in parts or "wardrobe" in joined or content_type == "Follower/Wardrobe":
        return ("/Default/Wardrobe",)
    if parts and parts[0] in {"environments", "scenes"}:
        return ("/Default/Environments",)
    return ()



def _metadata_family_agrees(left: str, right: str) -> bool:
    if not left or not right:
        return False
    left_clean = _metadata_family(left)
    right_clean = _metadata_family(right)
    return (
        left_clean == right_clean
        or left_clean.startswith(f"{right_clean}/")
        or right_clean.startswith(f"{left_clean}/")
    )


def _metadata_family(value: str) -> str:
    clean = value.rstrip("/").lower()
    if clean.startswith("follower/"):
        return "follower"
    if clean.startswith("preset/layered-image"):
        return "preset/materials"
    if clean.startswith("preset/material"):
        return "preset/materials"
    if clean.startswith("preset/morph"):
        return "preset/morph"
    if clean.startswith("script/"):
        return "script"
    return clean


def _infer_compatibilities(content_path: str) -> tuple[str, ...]:
    path_lower = content_path.lower()
    compact = re.sub(r"[^a-z0-9]+", "", content_path.lower())
    if "g3f" in compact or "genesis3female" in compact:
        return ("/Genesis 3/Female",)
    if "g3m" in compact or "genesis3male" in compact:
        return ("/Genesis 3/Male",)
    if "g8f" in compact or "genesis8female" in compact:
        return ("/Genesis 8/Female", "/Genesis 8.1/Female")
    if "g8m" in compact or "genesis8male" in compact:
        return ("/Genesis 8/Male", "/Genesis 8.1/Male")
    if "genesis8" in compact or re.search(r"(^|[^a-z0-9])g8([^a-z0-9]|$)", path_lower):
        return ("/Genesis 8/Female", "/Genesis 8/Male")
    if "g9" in compact or "genesis9" in compact:
        return ("/Genesis 9/Base",)
    return ()

def _infer_product(assets: tuple[AssetSuggestion, ...]) -> ProductSuggestion:
    content_counts = Counter(asset.content_type for asset in assets)
    authors = tuple(sorted({asset.author for asset in assets if asset.author}))

    if len(authors) == 1:
        artist_state = "single"
        primary_artist = authors[0]
    elif len(authors) > 1:
        artist_state = "ambiguous"
        primary_artist = ""
    else:
        artist_state = "missing"
        primary_artist = ""

    product_type = _infer_product_type(content_counts)
    return ProductSuggestion(
        product_type=product_type,
        primary_artist=primary_artist,
        artist_state=artist_state,
        artists=authors,
    )


def _infer_product_type(content_counts: Counter[str]) -> str:
    if not content_counts:
        return "unknown"
    if content_counts["Actor/Character"]:
        return "character"
    if content_counts["Follower/Hair"]:
        return "hair"
    if content_counts["Follower/Wardrobe"] or content_counts["Follower/Accessory"]:
        return "clothing/outfit"
    if content_counts["Preset/Pose"] and content_counts["Preset/Pose"] >= sum(content_counts.values()) / 2:
        return "pose pack"
    if content_counts["Script/Utility"] and content_counts["Script/Utility"] >= sum(content_counts.values()) / 2:
        return "script/tool"
    if len([key for key, value in content_counts.items() if key and value]) > 2:
        return "mixed product"
    if content_counts["Set"] or content_counts["Prop"]:
        return "prop/environment"
    return "mixed product"


def _load_support_hints(scan: SourceScan) -> dict[str, tuple[SupportAssetHint, ...]]:
    grouped: dict[str, list[SupportAssetHint]] = {}
    for source_file in scan.files:
        lower = source_file.content_path.lower()
        if not lower.startswith("runtime/support/") or not lower.endswith(".dsx"):
            continue
        try:
            metadata = parse_support_metadata(read_source_file(scan, source_file))
        except (SupportParseError, OSError):
            continue
        for asset in metadata.assets:
            key = _normalize_support_asset_path(asset.path)
            grouped.setdefault(key, []).append(asset)
    return {key: tuple(value) for key, value in grouped.items()}


def _normalize_support_asset_path(path: str) -> str:
    return path.lstrip("/")


def _collect_warnings(product: ProductSuggestion, assets: tuple[AssetSuggestion, ...]) -> tuple[str, ...]:
    warnings: list[str] = []
    if product.artist_state == "ambiguous":
        warnings.append("product: ambiguous-authors")
    if product.artist_state == "missing":
        warnings.append("product: missing-author")
    for asset in assets:
        warnings.extend(f"{asset.path}: {warning}" for warning in asset.warnings)
    return tuple(dict.fromkeys(warnings))
