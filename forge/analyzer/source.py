from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


DAZ_ROOTS = frozenset(
    {
        "animals",
        "cameras",
        "camera presets",
        "data",
        "documentation",
        "environments",
        "figures",
        "general",
        "light presets",
        "lights",
        "people",
        "props",
        "render presets",
        "runtime",
        "scenes",
        "scripts",
        "shader presets",
        "shaders",
        "vehicles",
    }
)


class SourceScanError(ValueError):
    """Raised when a source cannot be scanned as a DAZ content source."""


class UnsafeArchivePathError(SourceScanError):
    """Raised when a zip member path could escape the intended source root."""


@dataclass(frozen=True)
class SourceFile:
    source_path: str
    content_path: str


@dataclass(frozen=True)
class DuplicateContentPath:
    normalized_key: str
    content_paths: tuple[str, ...]


@dataclass(frozen=True)
class SourceScan:
    source_kind: str
    source_path: str
    content_root: str
    files: tuple[SourceFile, ...]
    duplicates: tuple[DuplicateContentPath, ...]
    warnings: tuple[str, ...] = ()
    hard_errors: tuple[str, ...] = ()


def scan_source(path: Path) -> SourceScan:
    source = Path(path)
    if source.is_dir():
        return _scan_folder(source)
    if source.is_file() and source.suffix.lower() == ".zip":
        return _scan_zip(source)
    raise SourceScanError(f"Source must be a folder or zip file: {source}")


def _scan_folder(path: Path) -> SourceScan:
    names = sorted(
        _path_to_posix(file.relative_to(path))
        for file in path.rglob("*")
        if file.is_file()
    )
    return _build_scan("folder", str(path), names)


def _scan_zip(path: Path) -> SourceScan:
    with ZipFile(path) as archive:
        names = sorted(
            _validate_archive_member(info.filename)
            for info in archive.infolist()
            if not info.is_dir()
        )
    return _build_scan("zip", str(path), names)


def _build_scan(source_kind: str, source_path: str, source_names: list[str]) -> SourceScan:
    content_root = _detect_content_root(source_names)
    content_files = tuple(
        SourceFile(source_path=name, content_path=_strip_root(name, content_root))
        for name in source_names
        if _is_under_root(name, content_root)
    )
    duplicates = _find_duplicates(content_files)
    return SourceScan(
        source_kind=source_kind,
        source_path=source_path,
        content_root=content_root,
        files=content_files,
        duplicates=duplicates,
    )


def _detect_content_root(names: list[str]) -> str:
    if not names:
        raise SourceScanError("Source does not contain files.")

    if _has_daz_root_at_prefix(names, "Content"):
        return "Content"

    if _has_daz_root_at_prefix(names, ""):
        return ""

    top_levels = {name.split("/", 1)[0] for name in names}
    if len(top_levels) == 1:
        wrapper = next(iter(top_levels))
        wrapper_content = f"{wrapper}/Content"
        if _has_daz_root_at_prefix(names, wrapper_content):
            return wrapper_content
        if _has_daz_root_at_prefix(names, wrapper):
            return wrapper

    raise SourceScanError("Could not detect a DAZ content root.")


def _has_daz_root_at_prefix(names: list[str], prefix: str) -> bool:
    prefix_parts = _parts(prefix)
    root_index = len(prefix_parts)
    for name in names:
        parts = _parts(name)
        if len(parts) <= root_index:
            continue
        if prefix_parts and tuple(parts[: len(prefix_parts)]) != tuple(prefix_parts):
            continue
        if parts[root_index].lower() in DAZ_ROOTS:
            return True
    return False


def _strip_root(name: str, root: str) -> str:
    if root == "":
        return name
    prefix = f"{root}/"
    if not name.startswith(prefix):
        raise SourceScanError(f"Path is not under content root {root}: {name}")
    return name[len(prefix) :]


def _is_under_root(name: str, root: str) -> bool:
    if root == "":
        return True
    return name.startswith(f"{root}/")


def _find_duplicates(files: tuple[SourceFile, ...]) -> tuple[DuplicateContentPath, ...]:
    seen: dict[str, list[str]] = {}
    for file in files:
        key = file.content_path.lower()
        seen.setdefault(key, []).append(file.content_path)

    duplicates = [
        DuplicateContentPath(normalized_key=key, content_paths=tuple(paths))
        for key, paths in sorted(seen.items())
        if len(paths) > 1
    ]
    return tuple(duplicates)


def _validate_archive_member(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    parts = path.parts
    if not normalized or normalized.endswith("/"):
        return normalized
    if path.is_absolute():
        raise UnsafeArchivePathError(f"Archive member uses an absolute path: {name}")
    if any(part in {"", ".", ".."} for part in parts):
        raise UnsafeArchivePathError(f"Archive member contains an unsafe path segment: {name}")
    if any(_looks_like_drive(part) for part in parts):
        raise UnsafeArchivePathError(f"Archive member contains a drive-qualified path: {name}")
    return path.as_posix()


def _looks_like_drive(part: str) -> bool:
    return len(part) >= 2 and part[1] == ":" and part[0].isalpha()


def _parts(value: str) -> tuple[str, ...]:
    if value == "":
        return ()
    return tuple(PurePosixPath(value).parts)


def _path_to_posix(path: Path) -> str:
    return path.as_posix()