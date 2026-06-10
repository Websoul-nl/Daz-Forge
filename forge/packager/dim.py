from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

from forge.analyzer.source import SourceScan, read_source_file


@dataclass(frozen=True)
class DimPackageResult:
    zip_path: Path
    report_path: Path
    package_name: str
    support_path: str
    installed_files: tuple[str, ...]
    skipped_existing_support_files: tuple[str, ...]


def build_dim_package(
    scan: SourceScan,
    contract: dict,
    output_folder: Path,
) -> DimPackageResult:
    product = contract.get("product", {})
    product_name = str(product.get("product_name") or Path(scan.source_path).stem)
    package_code = _package_code(product)
    token = _digits(str(product.get("product_token") or "1")) or "1"
    token_padded = token.zfill(8)
    global_id = str(product.get("global_id") or "")
    package_stem = f"{package_code}{token_padded}-01_{_compact_product_name(product_name)}"
    output_folder.mkdir(parents=True, exist_ok=True)
    zip_path = output_folder / f"{package_stem}.zip"
    report_path = output_folder / f"{package_stem}.report.json"
    support_content_path = f"Runtime/Support/{package_code}_{token}_{_support_product_name(product_name)}.dsx"
    support_archive_path = f"Content/{support_content_path}"

    file_payloads: dict[str, bytes] = {}
    skipped_support_files: list[str] = []
    for source_file in scan.files:
        content_path = PurePosixPath(source_file.content_path).as_posix()
        if _is_existing_support_file(content_path):
            skipped_support_files.append(content_path)
            continue
        file_payloads[f"Content/{content_path}"] = read_source_file(scan, source_file)

    support_xml = _support_xml(contract)
    file_payloads[support_archive_path] = support_xml.encode("utf-8")
    installed_files = tuple(sorted(file_payloads))
    manifest_xml = _manifest_xml(global_id, installed_files)
    supplement_xml = _supplement_xml(product_name)

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Manifest.dsx", manifest_xml)
        archive.writestr("Supplement.dsx", supplement_xml)
        for archive_path in installed_files:
            archive.writestr(archive_path, file_payloads[archive_path])

    report = {
        "zip_name": zip_path.name,
        "product_name": product_name,
        "package_code": package_code,
        "store_prefix": str(product.get("store_prefix") or ""),
        "store_code": str(product.get("store_code") or ""),
        "product_token": token,
        "global_id": global_id,
        "support_path": support_content_path,
        "installed_files": list(installed_files),
        "skipped_existing_support_files": skipped_support_files,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return DimPackageResult(
        zip_path=zip_path,
        report_path=report_path,
        package_name=zip_path.name,
        support_path=support_content_path,
        installed_files=installed_files,
        skipped_existing_support_files=tuple(skipped_support_files),
    )


def _support_xml(contract: dict) -> str:
    product = contract.get("product", {})
    root = ET.Element("ContentDBInstall", {"VERSION": "1.0"})
    products = ET.SubElement(root, "Products")
    product_element = ET.SubElement(products, "Product", {"VALUE": str(product.get("product_name", ""))})
    _child(product_element, "StoreID", str(product.get("store_id") or product.get("store_display_name") or ""))
    _child(product_element, "GlobalID", str(product.get("global_id") or ""))
    _child(product_element, "ProductToken", str(product.get("product_token") or ""))
    artists_element = ET.SubElement(product_element, "Artists")
    for artist in product.get("artists", []):
        if str(artist):
            _child(artists_element, "Artist", str(artist))
    assets_element = ET.SubElement(product_element, "Assets")
    for row in contract.get("rows", []):
        final = row.get("final", {})
        if not final.get("editable", True):
            continue
        asset = ET.SubElement(assets_element, "Asset", {"VALUE": f"/{row.get('path', '')}"})
        _child(asset, "ContentType", str(final.get("content_type", "")))
        categories = ET.SubElement(asset, "Categories")
        for category in _values(final.get("categories", [])):
            _child(categories, "Category", category)
        if final.get("compatibility_base"):
            _child(asset, "CompatibilityBase", str(final.get("compatibility_base", "")))
        compatibilities = ET.SubElement(asset, "Compatibilities")
        for compatibility in _values(final.get("compatibilities", [])):
            _child(compatibilities, "Compatibility", compatibility)
    return _xml_string(root)


def _manifest_xml(global_id: str, installed_files: tuple[str, ...]) -> str:
    root = ET.Element("DAZInstallManifest", {"VERSION": "0.1"})
    _child(root, "GlobalID", global_id)
    for archive_path in installed_files:
        ET.SubElement(root, "File", {"TARGET": "Content", "ACTION": "Install", "VALUE": archive_path})
    return _xml_string(root)


def _supplement_xml(product_name: str) -> str:
    root = ET.Element("ProductSupplement", {"VERSION": "0.1"})
    _child(root, "ProductName", product_name)
    _child(root, "InstallTypes", "Content")
    _child(root, "ProductTags", "DAZStudio4_5")
    return _xml_string(root)


def _child(parent: ET.Element, tag: str, value: str) -> ET.Element:
    return ET.SubElement(parent, tag, {"VALUE": value})


def _xml_string(root: ET.Element) -> str:
    ET.indent(root, space=" ")
    return ET.tostring(root, encoding="unicode", short_empty_elements=True).replace(" />", "/>") + "\n"


def _is_existing_support_file(content_path: str) -> bool:
    lower = content_path.lower()
    return lower.startswith("runtime/support/") and lower.endswith((".dsx", ".dsa", ".jpg"))


def _values(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    return [str(item) for item in value if str(item)]


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _package_code(product: dict) -> str:
    prefix = str(product.get("store_prefix") or "")
    code = str(product.get("store_code") or "")
    combined = prefix + code
    if not combined:
        combined = str(product.get("store_id") or product.get("store_display_name") or "LOCAL")
    cleaned = re.sub(r"[^A-Za-z0-9]", "", combined).upper()
    return cleaned[:6] or "LOCAL"


def _compact_product_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value)
    return cleaned or "Product"


def _support_product_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return cleaned or "Product"
