"""Gather an installed DAZ product from its Runtime/Support DSX without repackaging DAZ base assets.

Only declared product files and dependencies with positive ownership evidence are
included. Referenced base, third-party and unresolved files stay in the report.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import json
import posixpath
import re
from typing import Iterable
from urllib.parse import unquote, urlsplit

from forge.analyzer.dson import DsonParseError, _decode_dson_bytes
from forge.analyzer.source import (
    DAZ_ROOTS, DuplicateContentPath, GatheredFile, SourceFile, SourceScan,
    SourceScanError, _find_duplicates,
)
from forge.analyzer.support import SupportParseError, parse_support_metadata

DSON_EXTENSIONS = frozenset({".duf", ".dsf", ".dse"})
REFERENCE_EXTENSIONS = frozenset({
    ".duf", ".dsf", ".dsa", ".dse", ".jpg", ".jpeg", ".png", ".tif",
    ".tiff", ".bmp", ".exr", ".hdr", ".tx", ".obj", ".mtl", ".dae",
    ".svg", ".webp",
})
THUMBNAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".tip.png", ".tip.jpg")
# Intentionally narrow. Never blacklist the entire DAZ 3D vendor directory:
# third-party products can legitimately have their own data there.
BASE_DATA = re.compile(
    r"^data/daz 3d/(?:genesis(?:[ /_-]|$)|victoria 4(?:/|$)|michael 4(?:/|$))",
    flags=re.IGNORECASE,
)
BASE_TEXTURES = re.compile(
    r"^runtime/textures/(?:daz(?: 3d)?/(?:characters/)?genesis(?:[ /_-]|$)"
    r"|daz/characters/(?:genesis(?:[ /_-]|$)|genesis\d))",
    flags=re.IGNORECASE,
)


def is_daz_base_file(content_path: str) -> bool:
    """Conservative built-in blacklist; installed base ownership is also checked."""
    normalized = content_path.replace("\\", "/").lstrip("/")
    lower = normalized.casefold()
    # Morphs/UV Sets are extensibility points beneath the Genesis base folder.
    # A vendor's morph or UV set is not itself Genesis base data.
    if BASE_DATA.search(normalized):
        if "/morphs/" in lower:
            return bool(re.search(r"/morphs/daz 3d/(?:base/|genesis(?:[ /_-]|$))", lower))
        if "/uv sets/" in lower:
            return bool(re.search(r"/uv sets/daz 3d/(?:base/|genesis(?:[ /_-]|$))", lower))
        return True
    return bool(BASE_TEXTURES.search(normalized))


def _normalized_path(raw: str, *, parent: str = "") -> str:
    """Convert DAZ URL paths to safe content-root-relative paths."""
    value = unquote(raw.strip().replace("\\", "/")).split("#", 1)[0].split("?", 1)[0]
    if not value or value.startswith(("//", "http:", "https:", "file:")):
        return ""
    if re.match(r"^[a-zA-Z]:", value) or "\x00" in value:
        return ""
    if value.startswith("/"):
        value = value.lstrip("/")
    elif value.split("/", 1)[0].lower() not in DAZ_ROOTS and parent:
        value = posixpath.join(posixpath.dirname(parent), value)
    normalized = posixpath.normpath(value)
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"..", "."} or ":" in part for part in parts):
        return ""
    if parts[0].lower() not in DAZ_ROOTS:
        return ""
    return "/".join(parts)


def _references(data: bytes, content_path: str) -> tuple[str, ...]:
    """Walk DSON JSON strings, including gzip/ZIP-compressed DAZ assets."""
    try:
        document = json.loads(_decode_dson_bytes(data))
    except (DsonParseError, ValueError, OSError, EOFError, ImportError) as exc:
        raise ValueError(f"Cannot inspect DSON {content_path}: {exc}") from exc
    result: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
        elif isinstance(node, str):
            normalized = _normalized_path(node, parent=content_path)
            if normalized and PurePosixPath(normalized).suffix.lower() in REFERENCE_EXTENSIONS:
                result.add(normalized)

    visit(document)
    result.discard(content_path)
    return tuple(sorted(result, key=str.lower))


def _library_root(dsx: Path) -> Path:
    if (dsx.parent.name.lower() != "support"
            or dsx.parent.parent.name.lower() != "runtime"):
        raise SourceScanError("DSX must be inside a DAZ library's Runtime/Support folder.")
    return dsx.parent.parent.parent.resolve()


def _find_path(roots: tuple[Path, ...], content_path: str) -> Path | None:
    for root in roots:
        candidate = root.joinpath(*PurePosixPath(content_path).parts)
        if not candidate.is_file():
            continue
        # Do not permit a symlink to smuggle a file from outside a library.
        try:
            candidate.resolve().relative_to(root)
        except ValueError:
            continue
        return candidate
    return None


def _other_product_owners(roots: tuple[Path, ...], selected: Path) -> dict[str, str]:
    """Index DSX-declared ownership across configured libraries, not file proximity."""
    owners: dict[str, str] = {}
    for root in roots:
        support_dir = root / "Runtime" / "Support"
        if not support_dir.is_dir():
            continue
        for path in support_dir.glob("*.dsx"):
            if path.resolve() == selected.resolve():
                continue
            try:
                metadata = parse_support_metadata(path.read_bytes())
            except (OSError, SupportParseError):
                continue
            owner = metadata.product_name or path.stem
            for raw in (*[asset.path for asset in metadata.assets], *metadata.support_assets):
                normalized = _normalized_path(raw)
                if normalized:
                    owners.setdefault(normalized.casefold(), owner)
    return owners


def _product_prefixes(declared: set[str]) -> set[str]:
    prefixes: set[str] = set()
    for content_path in declared:
        parts = content_path.split("/")
        lower = [part.casefold() for part in parts]
        if lower[0] == "data" and len(parts) >= 4:
            prefixes.add("/".join(lower[:3]) + "/")
        elif lower[:2] == ["runtime", "textures"] and len(parts) >= 5:
            prefixes.add("/".join(lower[:4]) + "/")
    return prefixes


def _product_related(content_path: str, prefixes: set[str]) -> bool:
    key = content_path.casefold()
    return any(key.startswith(prefix) for prefix in prefixes)


def gather_dsx(dsx: Path, extra_libraries: Iterable[Path] = ()) -> SourceScan:
    selected = Path(dsx).resolve()
    if not selected.is_file() or selected.suffix.lower() != ".dsx":
        raise SourceScanError(f"Not a DSX file: {selected}")
    root = _library_root(selected)
    roots = tuple(dict.fromkeys(
        [root, *(Path(path).resolve() for path in extra_libraries if Path(path).is_dir())]
    ))
    try:
        metadata = parse_support_metadata(selected.read_bytes())
    except (OSError, SupportParseError) as exc:
        raise SourceScanError(f"Cannot read product DSX: {exc}") from exc

    own_dsx = selected.relative_to(root).as_posix()
    declared = {
        normalized for raw in (
            *(asset.path for asset in metadata.assets),
            *metadata.support_assets,
            "/" + own_dsx,
        )
        if (normalized := _normalized_path(raw))
    }
    if not metadata.assets and not metadata.support_assets:
        raise SourceScanError("DSX contains no Assets or SupportAssets to gather.")

    # Product image and asset thumbnails are often omitted from SupportAssets.
    for suffix in (".jpg", ".jpeg", ".png"):
        image = selected.with_suffix(suffix)
        if image.is_file():
            declared.add(image.relative_to(root).as_posix())
    for path in tuple(declared):
        if PurePosixPath(path).suffix.lower() not in DSON_EXTENSIONS:
            continue
        for suffix in THUMBNAIL_SUFFIXES:
            thumbnail = _find_path(roots, path + suffix)
            if thumbnail:
                declared.add(path + suffix)

    prefixes = _product_prefixes(declared)
    owners: dict[str, str] | None = None
    found: dict[str, SourceFile] = {}
    records: dict[str, GatheredFile] = {}
    warnings: list[str] = []
    hard_errors: list[str] = []
    queue: deque[tuple[str, str]] = deque(
        (path, "Declared in product metadata") for path in sorted(declared, key=str.lower)
    )

    while queue:
        content_path, via = queue.popleft()
        key = content_path.casefold()
        if key in records:
            continue
        explicitly_owned = content_path in declared
        if is_daz_base_file(content_path):
            records[key] = GatheredFile(content_path, "base", "Protected DAZ base asset")
            continue

        location = _find_path(roots, content_path)
        if location is None:
            records[key] = GatheredFile(content_path, "missing", f"Referenced by {via}")
            if explicitly_owned:
                hard_errors.append(f"Product file missing: {content_path}")
            else:
                warnings.append(f"Unresolved dependency: {content_path} (from {via})")
            continue

        if not explicitly_owned:
            if owners is None:
                owners = _other_product_owners(roots, selected)
            if key in owners:
                records[key] = GatheredFile(
                    content_path, "external", f"Owned by installed product: {owners[key]}",
                    str(location),
                )
                continue
            if not _product_related(content_path, prefixes):
                records[key] = GatheredFile(
                    content_path, "unknown",
                    "No ownership evidence; excluded from package", str(location),
                )
                warnings.append(f"Review unknown dependency: {content_path} (from {via})")
                continue

        source_file = SourceFile(str(location), content_path)
        found[key] = source_file
        records[key] = GatheredFile(
            content_path, "included",
            "Declared by DSX" if explicitly_owned else f"Same product namespace; from {via}",
            str(location),
        )
        if not explicitly_owned:
            warnings.append(f"Inferred product dependency: {content_path} (from {via})")

        if PurePosixPath(content_path).suffix.lower() in DSON_EXTENSIONS:
            try:
                references = _references(location.read_bytes(), content_path)
            except ValueError as exc:
                warnings.append(str(exc))
                continue
            for reference in references:
                if reference.casefold() not in records:
                    queue.append((reference, content_path))
        elif PurePosixPath(content_path).suffix.lower() in {".dsa", ".dse"}:
            warnings.append(f"Dynamic script references cannot be fully inspected: {content_path}")

    files = tuple(sorted(found.values(), key=lambda item: item.content_path.casefold()))
    records_sorted = tuple(sorted(records.values(), key=lambda item: (item.status, item.content_path.casefold())))
    return SourceScan(
        source_kind="dsx",
        source_path=str(selected),
        content_root=str(root),
        files=files,
        duplicates=_find_duplicates(files),
        warnings=tuple(dict.fromkeys(warnings)),
        hard_errors=tuple(dict.fromkeys(hard_errors)),
        gathered_files=records_sorted,
    )
