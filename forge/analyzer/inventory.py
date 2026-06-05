from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from forge.analyzer.source import SourceScan


CLICKABLE_EXTENSIONS = frozenset({".duf", ".dsf", ".dsa", ".dse"})
DOCUMENT_EXTENSIONS = frozenset({".txt", ".pdf", ".htm", ".html", ".rtf", ".md"})
THUMBNAIL_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
IGNORED_ROOTS = frozenset({"promo", "promos", "templates", "template"})


@dataclass(frozen=True)
class InventoryItem:
    content_path: str
    extension: str
    role: str
    include_in_smart_content: bool = False
    warnings: tuple[str, ...] = ()
    related_asset_path: str | None = None


@dataclass(frozen=True)
class InventoryResult:
    items: tuple[InventoryItem, ...]
    smart_content: tuple[InventoryItem, ...]
    documentation: tuple[InventoryItem, ...]
    thumbnails: tuple[InventoryItem, ...]
    ignored: tuple[InventoryItem, ...]
    warnings: tuple[str, ...]


def classify_inventory(scan: SourceScan) -> InventoryResult:
    items = tuple(_classify_path(file.content_path) for file in scan.files)
    smart_content = tuple(item for item in items if item.include_in_smart_content)
    documentation = tuple(item for item in items if item.role == "documentation")
    thumbnails = tuple(item for item in items if item.role == "thumbnail")
    ignored = tuple(item for item in items if item.role == "ignored")
    warnings = tuple(
        f"{item.content_path}: {warning}"
        for item in items
        for warning in item.warnings
    )
    return InventoryResult(
        items=items,
        smart_content=smart_content,
        documentation=documentation,
        thumbnails=thumbnails,
        ignored=ignored,
        warnings=warnings,
    )


def _classify_path(content_path: str) -> InventoryItem:
    parts = PurePosixPath(content_path).parts
    extension = _extension(content_path)

    if _is_under_root(parts, "data"):
        return InventoryItem(content_path=content_path, extension=extension, role="data")

    if _is_under_root(parts, "runtime"):
        return InventoryItem(content_path=content_path, extension=extension, role="runtime")

    thumbnail_asset = _thumbnail_asset_path(content_path)
    if thumbnail_asset is not None:
        return InventoryItem(
            content_path=content_path,
            extension=extension,
            role="thumbnail",
            related_asset_path=thumbnail_asset,
        )

    if _is_documentation(content_path, parts, extension):
        return InventoryItem(content_path=content_path, extension=extension, role="documentation")

    if parts and parts[0].lower() in IGNORED_ROOTS:
        return InventoryItem(content_path=content_path, extension=extension, role="ignored")

    if extension in CLICKABLE_EXTENSIONS:
        warnings = ("user-facing-dsf",) if extension == ".dsf" else ()
        return InventoryItem(
            content_path=content_path,
            extension=extension,
            role="asset",
            include_in_smart_content=True,
            warnings=warnings,
        )

    return InventoryItem(content_path=content_path, extension=extension, role="shipped")


def _is_under_root(parts: tuple[str, ...], root: str) -> bool:
    return bool(parts) and parts[0].lower() == root


def _is_documentation(content_path: str, parts: tuple[str, ...], extension: str) -> bool:
    if parts and parts[0].lower() == "documentation":
        return True
    name = PurePosixPath(content_path).name.lower()
    if extension in DOCUMENT_EXTENSIONS and (
        "readme" in name or "read me" in name or "license" in name or "licence" in name
    ):
        return True
    return False


def _thumbnail_asset_path(content_path: str) -> str | None:
    lower = content_path.lower()
    if not any(lower.endswith(ext) for ext in THUMBNAIL_EXTENSIONS):
        return None

    for marker in (".duf", ".dsf", ".dsa", ".dse"):
        for suffix in THUMBNAIL_EXTENSIONS:
            full_suffix = f"{marker}{suffix}"
            if lower.endswith(full_suffix):
                return content_path[: -len(suffix)]

    for suffix in THUMBNAIL_EXTENSIONS:
        tip_suffix = f".tip{suffix}"
        if lower.endswith(tip_suffix):
            return content_path[: -len(tip_suffix)] + ".duf"

    return None


def _extension(content_path: str) -> str:
    return PurePosixPath(content_path).suffix.lower()