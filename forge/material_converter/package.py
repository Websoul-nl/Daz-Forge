"""Private, content-only DIM ZIPs; never discover assets by scanning a library.

Only the chosen product subtree, explicit extra files, and DSON texture
references are installed. External /data references and known native G9 detail
atlases are reported, not copied.
Texture payloads, ZIP verification, and hashing are streamed; memory is bounded
by path metadata and the largest DSON document (read_dson loads one at a time).
The DIM entry point takes an explicit product identity and generates Smart
Content support. The private content-only entry point does neither.
Source files must remain unchanged during the build. Publication requires hard-link
support on the output filesystem, to guarantee an atomic no-overwrite publish.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from forge.material_converter.g9_presets import G9_MALE_ANATOMY, G9_UNCIRCUMCISED_CONTROL, G9_UNCIRCUMCISED_MORPH
from forge.material_converter.pbr_presets import read_dson
from forge.material_converter.skin_detail import NATIVE_DETAIL_DEPENDENCIES
from forge.packager.dim import _manifest_xml, _supplement_xml, _support_script, _support_xml
from forge.packager.identity import DimPackageIdentity, dim_package_identity


_CHUNK = 1024 * 1024
_DSON_SUFFIXES = {".duf", ".dsf"}
_PAYLOAD_SUFFIXES = {
    ".duf", ".dsf", ".dsa", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
    ".exr", ".hdr", ".bmp", ".webp", ".txt", ".md", ".json",
}
_MATERIAL_ASSET_TYPES = {
    "preset_material", "preset_shader", "material", "image",
    "preset_hierarchical_material", "preset_properties", "preset_layered_image",
}
_MATERIAL_LIBRARIES = {"material_library", "image_library"}
_EXTERNAL_TEXTURES = frozenset(path.casefold() for path in NATIVE_DETAIL_DEPENDENCIES)


@dataclass(frozen=True)
class MaterialPackageResult:
    zip_path: Path
    content_root: Path
    product_relative_folder: str
    product_name: str
    product_files: tuple[str, ...]
    extra_files: tuple[str, ...]
    resources: tuple[str, ...]
    dependency_files: tuple[str, ...]
    installed_files: tuple[str, ...]
    content_file_count: int
    resource_file_count: int
    archive_file_count: int
    content_bytes: int
    zip_bytes: int
    sha256: str
    dim_identity: DimPackageIdentity | None = None


def _relative_path(value: str, *, uri: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty content-relative path")
    if re.search(r"%(?![0-9a-fA-F]{2})|%2[fF]|%5[cC]", value):
        raise ValueError(f"Unsafe escaped content path: {value!r}")
    decoded = unquote(value, encoding="utf-8", errors="strict")
    if uri and decoded.startswith("/") and not decoded.startswith("//"):
        decoded = decoded[1:]
    parts = decoded.split("/")
    if (
        any(c in decoded for c in '\\:%?#*"<>|')
        or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
        or any(not p or p in {".", ".."} or p.endswith((".", " ")) for p in parts)
        or any(re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p) for p in parts)
    ):
        raise ValueError(f"Unsafe content path: {value!r}")
    return "/".join(parts)


def _source_path(root: Path, relative: str, *, directory: bool = False) -> Path:
    path = root
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"Linked content is not allowed: {relative}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Content escapes library: {relative}")
    if not (path.is_dir() if directory else path.is_file()):
        raise FileNotFoundError(f"Missing content resource: {relative}")
    return path


def _allowed_payload(relative: str) -> None:
    if relative.casefold() in _EXTERNAL_TEXTURES:
        raise ValueError(f"Installed native G9 detail cannot be bundled: {relative}")
    parts = relative.split("/")
    if (
        parts[0].casefold() == "data"
        or relative.casefold().startswith("runtime/geometries/")
        or any(p.casefold() == "blender" for p in parts)
        or Path(relative).suffix.casefold() not in _PAYLOAD_SUFFIXES
    ):
        raise ValueError(f"Scene/mesh or unsupported payload is not allowed: {relative}")


def _hierarchical_material_urls(scene: dict) -> set[str]:
    """Admit selection bindings only, never nodes that load or modify geometry."""
    nodes = scene.get("nodes")
    animations = scene.get("animations")
    if set(scene) - {"nodes", "animations", "materials"} or not all(
        isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows)
        for rows in (nodes, animations)
    ):
        raise ValueError("Expected a selection-bound hierarchical material preset")
    declared = set()
    geometries = set()
    for node in nodes:
        name = node.get("id")
        allowed_keys = {"id", "url", "parent"} if declared else {"id", "url"}
        if (
            set(node) - {"geometries"} != allowed_keys or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]+", name)
            or name in declared or node.get("url") != f"name://@selection/{name}:"
            or (declared and node["parent"] not in {f"#{parent}" for parent in declared})
        ):
            raise ValueError("Hierarchical material nodes must bind to the existing selection hierarchy")
        declared.add(name)
        if "geometries" in node:
            geom_id = f"{name}-1"
            if node["geometries"] != [{"id": geom_id, "url": f"name://@selection#geometries/{name}:"}]:
                raise ValueError("Hierarchical material geometry must bind to the existing node")
            geometries.add("#" + geom_id)
    if "materials" in scene and (
        not isinstance(scene["materials"], list)
        or not all(isinstance(m, dict) and isinstance(m.get("geometry"), str) and m["geometry"] in geometries
                   for m in scene["materials"])
    ):
        raise ValueError("Hierarchical material declarations must use a bound geometry")
    urls = set()
    for animation in animations:
        url = animation.get("url")
        if G9_MALE_ANATOMY in declared:
            keys = animation.get("keys")
            if url == f"{G9_MALE_ANATOMY}#{G9_UNCIRCUMCISED_MORPH}:?value/value" and keys == [[0, 0]]:
                urls.add(url)
                continue
            if url == f"{G9_MALE_ANATOMY}#{G9_UNCIRCUMCISED_CONTROL}:?value/value" and (
                keys == [[0, True]] or keys == [[0, False]]
            ) and type(keys[0][1]) is bool:
                urls.add(url)
                continue
        match = re.fullmatch(r"([A-Za-z0-9_]+)#materials/[^#?/]+:\?[^#?]+", url) if isinstance(url, str) else None
        if not match or match[1] not in declared:
            raise ValueError("Hierarchical material animation targets an undeclared node or property")
        urls.add(url)
    return urls


def _references(document: dict) -> tuple[set[str], set[str]]:
    textures: set[str] = set()
    dependencies: set[str] = set()
    image_ids: set[str] = set()
    image_refs: set[str] = set()
    info = document.get("asset_info", {})
    scene = document.get("scene", {})
    asset_type = info.get("type")
    hierarchical = asset_type == "preset_hierarchical_material"
    local_urls = _hierarchical_material_urls(scene) if hierarchical else set()

    def texture(value: object) -> None:
        if value is None or value == "":
            return
        relative = _relative_path(value, uri=True)
        if not relative.casefold().startswith("runtime/textures/"):
            raise ValueError(f"Image must reference Runtime/Textures: {value!r}")
        textures.add(relative)

    def image_reference(value: object) -> None:
        if value is None or value == "":
            return
        if not isinstance(value, str):
            raise ValueError("Invalid local image reference")
        image_refs.add(unquote(value.removeprefix("#"), errors="strict"))

    def dependency(value: object) -> None:
        if not isinstance(value, str) or not value or value.startswith(("#", "name:")) or value in local_urls:
            return
        path = value.partition("#")[0]
        relative = _relative_path(path, uri=True)
        if relative.casefold().startswith("data/"):
            dependencies.add(relative)
        elif relative.casefold().startswith("runtime/textures/"):
            textures.add(relative)
        else:
            raise ValueError(f"Unsupported external DSON reference: {value!r}")

    def walk(value: object, *, image_library: bool = False) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_library") and key not in _MATERIAL_LIBRARIES and item:
                    raise ValueError(f"Scene/mesh DSON library is not allowed: {key}")
                if key == "image_library":
                    if not isinstance(item, list):
                        raise ValueError("image_library must be a list")
                    for definition in item:
                        if not isinstance(definition, dict):
                            raise ValueError("Image definitions must be objects")
                        if isinstance(definition.get("id"), str):
                            image_ids.add(unquote(definition["id"], errors="strict"))
                if key == "image_file" or (image_library and key == "url"):
                    texture(item)
                elif key == "image":
                    image_reference(item)
                elif key in {"url", "uv_set", "geometry"}:
                    dependency(item)
                walk(item, image_library=image_library or key == "image_library")
            # Animation values are positional, not named image_file properties.
            url = value.get("url")
            if isinstance(url, str) and "keys" in value and "?" in url:
                prop = unquote(url.rsplit("?", 1)[1], errors="strict").split("/")[-1]
                if prop in {"image_file", "image"}:
                    for key in value["keys"]:
                        if not isinstance(key, list) or len(key) < 2:
                            raise ValueError("Invalid image animation key")
                        (texture if prop == "image_file" else image_reference)(key[1])
        elif isinstance(value, list):
            for item in value:
                walk(item, image_library=image_library)

    # Partial material presets may omit asset_info, but declared types are checked.
    if "type" in info and (
        not isinstance(asset_type, str) or asset_type not in _MATERIAL_ASSET_TYPES
    ):
        raise ValueError(f"Scene/mesh or unsupported DSON asset type: {asset_type!r}")
    if (scene.get("nodes") and not hierarchical) or scene.get("geometries") or scene.get("modifiers"):
        raise ValueError("Scene/mesh DSON assets are not material product payloads")
    if asset_type == "preset_properties" and not scene.get("materials"):
        raise ValueError("A properties preset in a material product must include materials")
    if asset_type == "preset_layered_image" and (set(scene) != {"animations"} or document.get("material_library")):
        raise ValueError("A layered image preset cannot contain scene or material declarations")
    walk(document)
    missing = image_refs - image_ids
    if missing:
        raise ValueError(f"Missing local image definitions: {sorted(missing)}")
    return textures, dependencies


def _fingerprint(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _walk_error(error: OSError) -> None:
    raise error


def _verify_archive(
    path: Path, installed: tuple[str, ...], product_name: str, *,
    global_id: str = "", support: dict[str, bytes] | None = None,
) -> None:
    with ZipFile(path) as archive:
        names = archive.namelist()
        expected = {"Manifest.dsx", "Supplement.dsx", *installed}
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError("ZIP members do not match the planned content")
        manifest = ET.fromstring(archive.read("Manifest.dsx"))
        entries = manifest.findall("File")
        paths = tuple(entry.attrib.get("VALUE", "") for entry in entries)
        if (
            manifest.tag != "DAZInstallManifest" or paths != installed
            or manifest.find("GlobalID") is None or manifest.find("GlobalID").get("VALUE") != global_id
            or any(e.get("TARGET") != "Content" or e.get("ACTION") != "Install" for e in entries)
            or any(not p.startswith("Content/") or _relative_path(p) != p for p in paths)
        ):
            raise ValueError("ZIP manifest paths do not match installed files")
        supplement = ET.fromstring(archive.read("Supplement.dsx"))
        if supplement.find("ProductName").get("VALUE") != product_name:
            raise ValueError("ZIP supplement product name mismatch")
        if support and any(archive.read("Content/" + p) != payload for p, payload in support.items()):
            raise ValueError("ZIP Smart Content payloads do not match the planned support files")
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"ZIP CRC verification failed: {bad}")


def build_material_package(
    content_root: str | Path,
    product_relative_folder: str,
    output_zip: str | Path,
    *,
    extra_relative_files: Iterable[str] = (),
    product_name: str,
) -> MaterialPackageResult:
    """Build a private Content/ ZIP for manual installation, not DIM."""
    return _build_material_package(
        content_root, product_relative_folder, output_zip,
        extra_relative_files=extra_relative_files, product_name=product_name,
    )


def build_dim_material_package(
    content_root: str | Path,
    product_relative_folder: str,
    output_folder: str | Path,
    *,
    contract: dict,
    product_image: str | Path,
    extra_relative_files: Iterable[str] = (),
) -> MaterialPackageResult:
    """Stream a DIM material product with the standard name and support triplet."""
    product = contract.get("product", {})
    identity = dim_package_identity(product, str(product.get("product_name") or ""))
    image = Path(product_image)
    if image.suffix.casefold() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("Choose a JPEG or PNG DIM product image.")
    payload = image.read_bytes()
    if not payload:
        raise ValueError("The DIM product image is empty.")
    return _build_material_package(
        content_root, product_relative_folder, Path(output_folder) / (identity.package_stem + ".zip"),
        extra_relative_files=extra_relative_files, product_name=identity.product_name,
        identity=identity, contract={**contract, "product": identity.metadata(product)},
        image=(image.suffix.casefold(), payload),
    )


def _build_material_package(
    content_root: str | Path,
    product_relative_folder: str,
    output_zip: str | Path,
    *,
    extra_relative_files: Iterable[str],
    product_name: str,
    identity: DimPackageIdentity | None = None,
    contract: dict | None = None,
    image: tuple[str, bytes] | None = None,
) -> MaterialPackageResult:
    """Build and verify a streamed Content/ ZIP without source writes.

    Relative paths use forward slashes and may percent-encode UTF-8 names.
    Textures use content-root DSON URLs, optionally starting with a single '/'.
    Extra files are explicit files, not directories or globs. Resources and
    dependency_files are decoded content-relative paths; dependency fragments
    are omitted. Native detail atlases, like external shaders, are not resolved
    in the source library or included in the ZIP. Counts include deduplicated
    Content files, not XML metadata.
    Existing output or '<output_zip>.partial' always raises FileExistsError.
    A failed build removes only the partial file created by this invocation.
    DSA scripts/icons are opaque payloads, not parsed for dynamic dependencies.
    """
    root = Path(content_root).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    product = _relative_path(product_relative_folder)
    if product.split("/")[0].casefold() in {"runtime", "data", "blender"}:
        raise ValueError("Choose a product folder, not a shared resource tree")
    folder = _source_path(root, product, directory=True)
    if not isinstance(product_name, str) or not product_name.strip() or any(
        ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in {0xFFFE, 0xFFFF}
        for c in product_name
    ):
        raise ValueError("Expected a nonempty XML-safe product name")
    output = Path(output_zip).absolute()
    partial = output.with_name(output.name + ".partial")
    if output.suffix.casefold() != ".zip":
        raise ValueError("Output must have a .zip extension")
    if output.parent.resolve().is_relative_to(root):
        raise ValueError("Output must be outside the source content library")
    for target in (output, partial):
        if os.path.lexists(target):
            raise FileExistsError(target)
    if isinstance(extra_relative_files, (str, bytes)):
        raise ValueError("extra_relative_files must be an iterable of paths")

    products: set[str] = set()
    for directory, directories, files in os.walk(folder, followlinks=False, onerror=_walk_error):
        for name in directories:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            _source_path(root, _relative_path(relative), directory=True)
        for name in files:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if _relative_path(relative) != relative:
                raise ValueError(f"Ambiguous escaped filename: {relative}")
            products.add(relative)
    if not products:
        raise ValueError("Product folder contains no files")
    extras = {_relative_path(p) for p in extra_relative_files}
    files: dict[str, tuple[Path, tuple[int, int, int, int]]] = {}
    case_names: dict[str, str] = {}

    def add(relative: str) -> Path:
        _allowed_payload(relative)
        previous = case_names.setdefault(relative.casefold(), relative)
        if previous != relative:
            raise ValueError(f"Case-colliding content paths: {previous}, {relative}")
        path = _source_path(root, relative)
        if relative not in files:
            files[relative] = (path, _fingerprint(path))
        return path

    resources: set[str] = set()
    dependencies: set[str] = set()
    for relative in sorted(products | extras):
        path = add(relative)
        if path.suffix.casefold() in _DSON_SUFFIXES:
            maps, refs = _references(read_dson(path))
            resources.update(maps)
            dependencies.update(refs)
    external_textures = {path for path in resources if path.casefold() in _EXTERNAL_TEXTURES}
    dependencies.update(external_textures)
    resources.difference_update(external_textures)
    for relative in sorted(resources):
        add(relative)
    support: dict[str, bytes] = {}
    if identity is not None:
        assert contract is not None and image is not None
        if any(path.casefold().startswith("runtime/support/") for path in files):
            raise ValueError("Do not include existing Runtime/Support files in the DIM material source.")
        if any(_relative_path(row.get("path", "")) not in files for row in contract.get("rows", [])):
            raise ValueError("Smart Content metadata must reference included product files.")
        stem = identity.support_path.removesuffix(".dsx")
        image_path = _relative_path(stem + image[0])
        support = {
            identity.support_path: _support_xml(
                contract, identity.support_path, tuple(sorted((*files, image_path))),
            ).encode("utf-8"),
            stem + ".dsa": _support_script(contract["product"]).encode("utf-8"),
            image_path: image[1],
        }
    installed = tuple("Content/" + p for p in sorted(files.keys() | support.keys()))
    content_bytes = sum(stat[2] for _, stat in files.values()) + sum(map(len, support.values()))
    global_id = identity.global_id if identity else ""

    def check_source(relative: str, path: Path, fingerprint: tuple[int, int, int, int]) -> None:
        if _source_path(root, relative) != path or _fingerprint(path) != fingerprint:
            raise ValueError(f"Source changed during packaging: {relative}")

    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation reserves this build's partial; never clean up another's.
    with partial.open("x+b") as stream:
        try:
            with ZipFile(stream, "w", ZIP_DEFLATED, allowZip64=True) as archive:
                archive.writestr("Manifest.dsx", _manifest_xml(global_id, installed))
                archive.writestr("Supplement.dsx", _supplement_xml(product_name))
                for relative, (path, fingerprint) in sorted(files.items()):
                    check_source(relative, path, fingerprint)
                    # Supplying the size lets zipfile use ZIP64 only when needed.
                    member = ZipInfo.from_file(path, "Content/" + relative, strict_timestamps=False)
                    member.file_size = fingerprint[2]
                    member.compress_type = ZIP_DEFLATED
                    with path.open("rb") as source, archive.open(member, "w") as target:
                        shutil.copyfileobj(source, target, length=_CHUNK)
                    check_source(relative, path, fingerprint)
                for relative, payload in sorted(support.items()):
                    archive.writestr("Content/" + relative, payload)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            partial.unlink()
            raise
    try:
        if identity:
            _verify_archive(partial, installed, product_name, global_id=global_id, support=support)
        else:
            _verify_archive(partial, installed, product_name)
        digest = hashlib.sha256()
        with partial.open("rb") as stream:
            while chunk := stream.read(_CHUNK):
                digest.update(chunk)
        zip_bytes = partial.stat().st_size
        for relative, (path, fingerprint) in files.items():
            check_source(relative, path, fingerprint)
        # Unlike replace()/POSIX rename(), link() cannot overwrite a raced output.
        os.link(partial, output)
    finally:
        partial.unlink()
    return MaterialPackageResult(
        zip_path=output, content_root=root, product_relative_folder=product,
        product_name=product_name, product_files=tuple(sorted(products)),
        extra_files=tuple(sorted(extras)), resources=tuple(sorted(resources)),
        dependency_files=tuple(sorted(dependencies)), installed_files=installed,
        content_file_count=len(installed), resource_file_count=len(resources),
        archive_file_count=len(installed) + 2, content_bytes=content_bytes,
        zip_bytes=zip_bytes, sha256=digest.hexdigest(), dim_identity=identity,
    )
