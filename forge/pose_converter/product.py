from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import re
import shutil
from urllib.parse import quote
from uuid import uuid4
from zipfile import ZipFile, is_zipfile

from forge.analyzer.inference import infer_metadata
from forge.analyzer.inventory import classify_inventory
from forge.analyzer.review_contract import build_review_contract, contract_to_dict
from forge.analyzer.source import scan_source
from forge.packager.dim import DimPackageResult, build_dim_package
from forge.pose_converter.converter import convert_g8f_pose_to_g9
from forge.pose_converter.duf import loads_duf, save_duf


@dataclass(frozen=True)
class PoseProductOutput:
    source_path: str
    output_path: str
    converted_channels: int
    skipped_channels: int
    unmapped_bones: tuple[str, ...]


@dataclass(frozen=True)
class PoseProductReport:
    source: str
    output_dir: str
    converted_count: int
    skipped_count: int
    outputs: tuple[PoseProductOutput, ...]
    skipped_files: tuple[str, ...]
    copied_images: tuple[str, ...]


@dataclass(frozen=True)
class ConvertedPoseDimPackageResult:
    converted_folder: Path
    conversion_report: PoseProductReport
    package: DimPackageResult


@dataclass(frozen=True)
class _SourceFile:
    content_path: str
    data: bytes


def build_converted_pose_dim_package(
    source: Path,
    output_dir: Path,
    *,
    metadata: dict | None = None,
) -> ConvertedPoseDimPackageResult:
    source = Path(source)
    output_dir = Path(output_dir)
    converted_folder = _converted_staging_folder(source, output_dir)
    _reset_converted_folder(converted_folder, output_dir)

    conversion_report = convert_pose_product(source, converted_folder)
    scan = scan_source(converted_folder)
    inventory = classify_inventory(scan)
    inference = infer_metadata(scan, inventory)
    contract = contract_to_dict(build_review_contract(scan, inventory, inference))
    contract["product"].update(_package_metadata(source, conversion_report, metadata or {}))
    package = build_dim_package(scan, contract, output_dir)

    return ConvertedPoseDimPackageResult(
        converted_folder=converted_folder,
        conversion_report=conversion_report,
        package=package,
    )


def convert_pose_product(source: Path, output_dir: Path) -> PoseProductReport:
    source = Path(source)
    output_dir = Path(output_dir)
    source_files = _read_source_files(source)
    files_by_path = {item.content_path: item for item in source_files}

    outputs: list[PoseProductOutput] = []
    skipped_files: list[str] = []
    copied_images: list[str] = []

    for source_file in sorted(source_files, key=lambda item: item.content_path.lower()):
        if not _is_g8f_pose_path(source_file.content_path):
            continue

        try:
            pose = loads_duf(source_file.data)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            skipped_files.append(source_file.content_path)
            continue

        result = convert_g8f_pose_to_g9(pose)
        output_content_path = _to_g9_content_path(source_file.content_path)
        _set_asset_id(result.pose, output_content_path)
        output_file = output_dir / "Content" / Path(output_content_path)
        save_duf(result.pose, output_file, compressed=True)

        for image_source, image_output in _thumbnail_pairs(source_file.content_path, output_content_path):
            source_image = files_by_path.get(image_source)
            if source_image is None:
                continue
            image_file = output_dir / "Content" / Path(image_output)
            image_file.parent.mkdir(parents=True, exist_ok=True)
            image_file.write_bytes(source_image.data)
            copied_images.append(image_output)

        outputs.append(
            PoseProductOutput(
                source_path=source_file.content_path,
                output_path=output_content_path,
                converted_channels=result.converted_channels,
                skipped_channels=result.skipped_channels,
                unmapped_bones=result.unmapped_bones,
            )
        )

    report = PoseProductReport(
        source=str(source),
        output_dir=str(output_dir),
        converted_count=len(outputs),
        skipped_count=len(skipped_files),
        outputs=tuple(outputs),
        skipped_files=tuple(skipped_files),
        copied_images=tuple(copied_images),
    )
    _write_report(report, output_dir / "pose_conversion_report.json")
    return report


def _read_source_files(source: Path) -> list[_SourceFile]:
    if source.is_file() and is_zipfile(source):
        return _read_zip_source(source)
    if source.is_dir():
        return _read_folder_source(source)
    raise ValueError(f"Source must be a zip file or folder: {source}")


def _converted_staging_folder(source: Path, output_dir: Path) -> Path:
    return output_dir / "_pose_converter_staging" / _safe_stem(source)


def _reset_converted_folder(converted_folder: Path, output_dir: Path) -> None:
    staging_root = (output_dir / "_pose_converter_staging").resolve()
    resolved = converted_folder.resolve()
    if staging_root != resolved and staging_root not in resolved.parents:
        raise ValueError(f"Refusing to reset folder outside pose converter staging: {converted_folder}")
    if converted_folder.exists():
        shutil.rmtree(converted_folder)
    converted_folder.mkdir(parents=True, exist_ok=True)


def _package_metadata(
    source: Path,
    report: PoseProductReport,
    metadata: dict,
) -> dict:
    product_name = str(metadata.get("product_name") or _converted_product_name(source, report))
    artists = _metadata_list(metadata.get("artists"))
    primary_artist = str(metadata.get("primary_artist") or (artists[0] if artists else ""))
    store_display_name = str(metadata.get("store_display_name") or "")
    store_id = str(metadata.get("store_id") or store_display_name)
    return {
        "product_name": product_name,
        "store_display_name": store_display_name,
        "store_id": store_id,
        "store_prefix": str(metadata.get("store_prefix") or ""),
        "store_code": str(metadata.get("store_code") or ""),
        "product_token": str(metadata.get("product_token") or "1"),
        "global_id": str(metadata.get("global_id") or uuid4()),
        "artists": artists,
        "primary_artist": primary_artist,
        "product_image": str(metadata.get("product_image") or ""),
    }


def _converted_product_name(source: Path, report: PoseProductReport) -> str:
    if report.outputs:
        parts = PurePosixPath(report.outputs[0].output_path).parts
        lowered = tuple(part.lower() for part in parts)
        if "poses" in lowered:
            index = lowered.index("poses")
            if len(parts) > index + 1:
                return parts[index + 1]
    return _source_name_without_dim_prefix(source).replace("Genesis8Female", "Genesis9")


def _source_name_without_dim_prefix(source: Path) -> str:
    stem = source.stem
    return re.sub(r"^[A-Z]{0,6}\d{8}-\d{2}_", "", stem)


def _safe_stem(source: Path) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", source.stem).strip("._-")
    return cleaned or "pose-product"


def _metadata_list(value) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]
    if value is None:
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _read_zip_source(source: Path) -> list[_SourceFile]:
    files = []
    with ZipFile(source) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            files.append(_SourceFile(_content_path(info.filename), archive.read(info)))
    return files


def _read_folder_source(source: Path) -> list[_SourceFile]:
    files = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        files.append(_SourceFile(_content_path(path.relative_to(source).as_posix()), path.read_bytes()))
    return files


def _content_path(path: str) -> str:
    normalized = path.replace("\\", "/").lstrip("/")
    if normalized.lower().startswith("content/"):
        normalized = normalized[len("Content/") :]
    return normalized


def _is_g8f_pose_path(path: str) -> bool:
    lowered = path.lower()
    return (
        lowered.endswith(".duf")
        and "/people/genesis 8 female/poses/" in f"/{lowered}"
    )


def _to_g9_content_path(path: str) -> str:
    replacements = (
        ("Genesis 8 Female", "Genesis 9"),
        ("Genesis%208%20Female", "Genesis%209"),
        ("G8F", "G9"),
        ("G8 F", "G9"),
    )
    converted = path
    for old, new in replacements:
        converted = converted.replace(old, new)
    return converted


def _set_asset_id(pose: dict, output_content_path: str) -> None:
    asset_info = pose.setdefault("asset_info", {})
    asset_info["id"] = "/" + quote(output_content_path, safe="/._-!")


def _thumbnail_pairs(source_path: str, output_path: str) -> tuple[tuple[str, str], ...]:
    source = PurePosixPath(source_path)
    output = PurePosixPath(output_path)
    return (
        (f"{source_path}.png", f"{output_path}.png"),
        (source.with_suffix(".tip.png").as_posix(), output.with_suffix(".tip.png").as_posix()),
    )


def _write_report(report: PoseProductReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
