"""Tiny synthetic material libraries; never package the live content library."""

import gzip
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile
import zlib

import pytest

from forge.material_converter import SurfaceMaterial, build_g9_skin_preset
from forge.material_converter import package
from forge.material_converter.package import build_dim_material_package, build_material_package


PRODUCT = "People/Genesis 9/Characters/Daz Forge/Robyn 8 G9 PBR Skin"
NAME = "PRIVATE Robyn G9 PBR Skin & Maps"
SHARED = "Runtime/Textures/Shared/face color.jpg"
NORMAL = "Runtime/Textures/Private/normal.png"
ANIMATED = "Runtime/Textures/Private/animated.png"
SHADER = "data/DAZ 3D/Built-in Content/PBRSkin.dsf"
NATIVE_BODY = "Runtime/Textures/Daz/Characters/Genesis9/Base/Skin_Details/Genesis9_BodyF_NM_1002.jpg"


def write(root: Path, relative: str, payload: bytes = b"tiny fixture") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def dson(root: Path, relative: str, document: dict, compressed: bool = False) -> Path:
    payload = json.dumps(document).encode("utf-8")
    return write(root, relative, gzip.compress(payload) if compressed else payload)


@pytest.fixture
def library(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "library"
    dson(root, PRODUCT + "/Apply.duf", {
        "asset_info": {"id": "/" + PRODUCT + "/Apply.duf", "type": "preset_material"},
        "scene": {"materials": [{
            "url": "/data/DAZ%203D/Built-in%20Content/PBRSkin.dsf#PBRSkin",
            "diffuse": {"channel": {"image_file": "/Runtime/Textures/Shared/face%20color.jpg"}},
            "extra": [{"image_library": [{
                "id": "nested", "map": [{"url": "/" + NORMAL}],
            }]}],
        }]},
        "image_library": [{
            "id": "color", "map": [{"url": "/" + SHARED}],
        }],
    }, compressed=True)
    dson(root, PRODUCT + "/Options/Tone.duf", {
        "asset_info": {"type": "preset_material"},
        "scene": {"animations": [{
            "url": "name://@selection#materials/Head:?diffuse/image_file",
            "keys": [[0, "/" + ANIMATED], [1, "/" + SHARED], [2, None]],
        }]},
    })
    write(root, PRODUCT + "/Apply.duf.png", b"icon")
    write(root, PRODUCT + "/Apply.duf.tip.png", b"large icon")
    write(root, PRODUCT + "/Options/Tone.duf.png", b"option icon")
    write(root, PRODUCT + "/Reset.dsa", b"// opaque DAZ script fixture")
    write(root, PRODUCT + "/Reset.dsa.png", b"script icon")
    for texture in (SHARED, NORMAL, ANIMATED):
        write(root, texture, (texture + " payload").encode())
    write(root, "Runtime/Textures/Shared/unreferenced.jpg")
    write(root, SHADER, b"purchased shader must not be copied")
    dson(root, "People/Genesis 9/Characters/Daz Forge/DazForgeDazFile.duf", {
        "asset_info": {"type": "scene"}, "scene": {"nodes": [{"id": "unrelated"}]},
    })
    write(root, "Blender/anatomy.blend", b"unrelated scene")
    write(root, "People/Genesis 9/Characters/Other/Product.duf", b"unrelated")
    return root, tmp_path / "output" / "private.zip"


def build(library: tuple[Path, Path], **kwargs) -> package.MaterialPackageResult:
    root, output = library
    return build_material_package(root, PRODUCT, output, product_name=NAME, **kwargs)


def snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def test_streamed_package_closure_icons_manifest_and_hash(library) -> None:
    root, output = library
    original = snapshot(root)
    result = build(library)
    assert snapshot(root) == original
    assert result.zip_path == output
    assert result.content_root == root.resolve()
    assert result.product_relative_folder == PRODUCT
    assert result.product_name == NAME
    assert result.resources == tuple(sorted((SHARED, NORMAL, ANIMATED)))
    assert result.dependency_files == (SHADER,)
    assert result.resource_file_count == 3
    assert len(result.product_files) == 7
    assert result.extra_files == ()
    assert result.content_file_count == 10
    assert result.archive_file_count == 12
    assert result.content_bytes == sum((root / p.removeprefix("Content/")).stat().st_size
                                       for p in result.installed_files)
    assert result.zip_bytes == output.stat().st_size
    assert result.sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert not output.with_name(output.name + ".partial").exists()
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == result.archive_file_count
        assert set(archive.namelist()) == {"Manifest.dsx", "Supplement.dsx", *result.installed_files}
        assert archive.namelist().count("Content/" + SHARED) == 1
        assert archive.read("Content/" + PRODUCT + "/Apply.duf.png") == b"icon"
        for path in result.installed_files:
            assert archive.read(path) == original[path.removeprefix("Content/")][0]
            member = archive.getinfo(path)
            archive.fp.seek(member.header_offset + 4)
            version, _, _, _, _, _, compressed, expanded = struct.unpack("<HHHHHIII", archive.fp.read(22))
            assert version < 45
            assert (compressed, expanded) == (member.compress_size, member.file_size)
        assert not any("Blender" in n or "DazForgeDazFile" in n or "unreferenced" in n
                       or n.startswith("Content/data/") or "/Other/" in n for n in archive.namelist())
        manifest = ET.fromstring(archive.read("Manifest.dsx"))
        assert manifest.tag == "DAZInstallManifest"
        assert tuple(e.get("VALUE") for e in manifest.findall("File")) == result.installed_files
        assert all(e.get("TARGET") == "Content" and e.get("ACTION") == "Install"
                   for e in manifest.findall("File"))
        assert manifest.find("GlobalID").get("VALUE") == ""
        supplement = ET.fromstring(archive.read("Supplement.dsx"))
        assert supplement.find("ProductName").get("VALUE") == NAME


def test_explicit_extras_and_subtree_overlap_deduplicate(library) -> None:
    root, _ = library
    write(root, "Documentation/Private Readme.txt", b"private usage")
    write(root, "Documentation/unrequested.txt")
    result = build(library, extra_relative_files=[
        "Documentation/Private%20Readme.txt", "Documentation/Private Readme.txt",
        PRODUCT + "/Apply.duf.png", SHARED,
    ])
    assert result.content_file_count == 11
    assert len(result.extra_files) == 3
    assert "Content/Documentation/Private Readme.txt" in result.installed_files
    assert "Content/Documentation/unrequested.txt" not in result.installed_files


def test_explicit_dson_extra_also_resolves_texture_dependencies(library) -> None:
    root, _ = library
    extra = "Presets/Private/Extra.duf"
    texture = "Runtime/Textures/Extra/additional.png"
    dson(root, extra, {"channel": {"image_file": "/" + texture}})
    write(root, texture)
    result = build(library, extra_relative_files=[extra])
    assert texture in result.resources
    assert result.content_file_count == 12


@pytest.mark.parametrize("installed_locally", [True, False])
def test_native_detail_package_references_but_does_not_bundle_daz_assets(library, installed_locally):
    root, output = library
    preset = build_g9_skin_preset(
        {"Torso": SurfaceMaterial(channels={
            "Normal Map": {"value": 1, "image_file": "/Runtime/Textures/Converted/Old Normal.png"},
        })},
        {"Body": "Torso"}, asset_id="/" + PRODUCT + "/Native.duf",
    )
    dson(root, PRODUCT + "/Native.duf", preset)
    if installed_locally:
        write(root, NATIVE_BODY)

    result = build(library)
    assert NATIVE_BODY in result.dependency_files
    assert NATIVE_BODY not in result.resources
    with ZipFile(output) as archive:
        assert "Content/" + NATIVE_BODY not in archive.namelist()
        assert NATIVE_BODY in archive.read("Content/" + PRODUCT + "/Native.duf").decode()


def test_dim_material_package_uses_same_identity_and_support_triplet(library):
    root, output = library
    image = output.parent.parent / "promo.jpg"
    image.write_bytes(b"fixture product image")
    guid = "11111111-2222-4333-8444-555555555555"
    contract = {
        "product": {
            "product_name": "Skin for G9", "store_prefix": "SHA", "store_code": "UNCV",
            "product_token": "7", "package_version": 2, "global_id": guid,
            "artists": ["Original Artist"],
        },
        "rows": [{
            "path": PRODUCT + "/Apply.duf",
            "final": {"content_type": "Preset/Materials/MDL", "categories": ["/Default/Materials"]},
        }],
    }

    result = build_dim_material_package(root, PRODUCT, output.parent, contract=contract, product_image=image)
    assert result.zip_path.name == "SHAUNCV00000007-02_SkinforG9.zip"
    support = "Content/Runtime/Support/3D_SHARDS_7_Skin_for_G9"
    expected_support = {support + suffix for suffix in (".dsx", ".dsa", ".jpg")}
    assert expected_support <= set(result.installed_files)
    assert result.archive_file_count == result.content_file_count + 2
    assert not (root / "Runtime/Support").exists()
    with ZipFile(result.zip_path) as archive:
        manifest = ET.fromstring(archive.read("Manifest.dsx"))
        supplement = ET.fromstring(archive.read("Supplement.dsx"))
        product = ET.fromstring(archive.read(support + ".dsx")).find("Products/Product")
        assert manifest.find("GlobalID").get("VALUE") == product.find("GlobalID").get("VALUE") == guid
        assert supplement.find("ProductName").get("VALUE") == product.get("VALUE") == "Skin for G9"
        assert product.find("StoreID").get("VALUE") == "3D SHARDS"
        assert product.find("ProductToken").get("VALUE") == "7"
        assert product.find("Artists/Artist").get("VALUE") == "Original Artist"
        assert "queueDBMetaFile" in archive.read(support + ".dsa").decode()
        assert archive.read(support + ".jpg") == image.read_bytes()


def test_explicit_extras_cannot_bundle_native_detail_maps(library):
    root, output = library
    write(root, NATIVE_BODY)
    with pytest.raises(ValueError, match="native G9 detail"):
        build(library, extra_relative_files=[NATIVE_BODY])
    assert not output.exists()


def test_local_image_refs_and_layered_library_maps(library) -> None:
    root, _ = library
    dson(root, PRODUCT + "/Layered.duf", {
        "scene": {"materials": [{"channel": {"image": "#layered%20map"}}],
                  "animations": [{
                      "url": "name://@selection#materials/Head:?diffuse/image",
                      "keys": [[0, "#layered%20map"], [1, None]],
                  }]},
        "image_library": [{"id": "layered map", "map": [
            {"url": "/" + SHARED, "layers": [{"url": "/" + NORMAL}]},
        ]}],
    })
    result = build(library)
    assert result.resources == tuple(sorted((SHARED, NORMAL, ANIMATED)))


@pytest.mark.parametrize("animated", [False, True])
def test_dangling_local_image_ref_is_rejected(library, animated) -> None:
    root, output = library
    document = {"channel": {"image": "#missing"}}
    if animated:
        document = {"scene": {"animations": [{
            "url": "name://@selection#materials/Head:?diffuse/image", "keys": [[0, "#missing"]],
        }]}}
    dson(root, PRODUCT + "/Dangling.duf", document)
    with pytest.raises(ValueError, match="Missing local image definitions"):
        build(library)
    assert not output.exists()


def test_subtree_read_failure_is_not_silently_skipped(library, monkeypatch) -> None:
    _, output = library

    def denied_walk(folder, *, followlinks, onerror):
        assert not followlinks
        onerror(PermissionError("cannot read a product subdirectory"))
        return iter(())

    monkeypatch.setattr(package.os, "walk", denied_walk)
    with pytest.raises(PermissionError, match="cannot read"):
        build(library)
    assert not output.exists()


@pytest.mark.parametrize("uri", [
    "/Runtime/Textures/../secret.png", "/Runtime/Textures/%2e%2e/secret.png",
    "/Runtime/Textures/%252e%252e/secret.png", "/Runtime/Textures/%2Fsecret.png",
    "/Runtime/Textures/%5csecret.png", "//server/share/map.png", "C:/maps/face.jpg",
    "file:///C:/maps/face.jpg", "https://example.com/map.png", "\\Runtime\\Textures\\face.jpg",
    "/Runtime/Textures/face.jpg?query", "/Runtime/Textures/face.jpg#fragment",
    "/Runtime/Textures/map%00.png", "/Runtime/Textures/bad%ZZ.png",
    "/Runtime/Textures/%ff.png", "/Runtime/Textures/CON.jpg", "/Runtime/Textures/map. ",
    "/data/Purchased/map.jpg", "/Runtime/Textures//map.png", "/tmp/map.png",
])
def test_unsafe_texture_uri_fails_closed(library, uri) -> None:
    root, output = library
    dson(root, PRODUCT + "/Unsafe.duf", {"nested": {"image_file": uri}})
    with pytest.raises(ValueError):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


@pytest.mark.parametrize("location", ["channel", "nested_library", "animation"])
def test_missing_map_fails_closed(library, location) -> None:
    root, output = library
    missing = "/Runtime/Textures/Missing/map.jpg"
    document = {
        "channel": {"image_file": missing},
        "nested_library": {"extra": [{"image_library": [{"map": [{"url": missing}]}]}]},
        "animation": {"scene": {"animations": [{
            "url": "name://@selection#materials/Head:?diffuse/image_file", "keys": [[0, missing]],
        }]}},
    }[location]
    dson(root, PRODUCT + "/Missing.duf", document)
    with pytest.raises(FileNotFoundError, match="Missing content resource"):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


@pytest.mark.parametrize("relative", ["../outside", "/People/Private", "People/../Private",
                                        "Blender", "Runtime/Textures", "data/Private"])
def test_rejects_unsafe_product_folders(library, relative) -> None:
    root, output = library
    with pytest.raises(ValueError):
        build_material_package(root, relative, output, product_name=NAME)


@pytest.mark.parametrize("relative", ["../outside.txt", "/outside.txt", "*.png",
                                        "Documentation/%252e%252e/outside.txt"])
def test_rejects_unsafe_explicit_extras(library, relative) -> None:
    with pytest.raises(ValueError):
        build(library, extra_relative_files=[relative])


@pytest.mark.parametrize("relative", ["Blender/anatomy.blend", "data/Purchased/mesh.dsf",
                                        PRODUCT + "/accidental.blend1",
                                        "People/Genesis 9/Characters/Daz Forge/DazForgeDazFile.duf"])
def test_refuses_explicit_scene_mesh_or_blender_payloads(library, relative) -> None:
    root, _ = library
    if relative.endswith("blend1"):
        write(root, relative)
    with pytest.raises(ValueError, match="Scene/mesh"):
        build(library, extra_relative_files=[relative])


@pytest.mark.parametrize("extra", [False, True])
@pytest.mark.parametrize("suffix", [
    ".obj", ".FBX", ".dae", ".stl", ".ply", ".glb", ".daz", ".pz3",
    ".bin", ".exe", ".zip", ".dsb", ".dse", ".gif", "",
])
def test_unsupported_payloads_fail_before_output(library, extra, suffix) -> None:
    root, output = library
    relative = ("Documentation" if extra else PRODUCT) + "/unsupported" + suffix
    write(root, relative)
    original = snapshot(root)
    with pytest.raises(ValueError, match="payload"):
        build(library, extra_relative_files=[relative] if extra else [])
    assert snapshot(root) == original
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


@pytest.mark.parametrize("relative", [
    "Runtime/Geometries/Private/mesh.png",
    "rUnTiMe/gEoMeTrIeS/Private/mesh.json",
    "Runtime/Geometries/Private/mesh.duf",
])
def test_geometry_tree_is_rejected_even_with_supported_suffix(library, relative) -> None:
    root, output = library
    write(root, relative, b"{}")
    with pytest.raises(ValueError, match="Scene/mesh"):
        build(library, extra_relative_files=[relative])
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


def test_dson_referenced_resource_must_have_supported_suffix(library) -> None:
    root, output = library
    resource = "Runtime/Textures/Private/mesh.obj"
    write(root, resource)
    dson(root, PRODUCT + "/UnsupportedResource.duf", {"channel": {"image_file": "/" + resource}})
    with pytest.raises(ValueError, match="payload"):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


@pytest.mark.parametrize("extra", [False, True])
def test_supported_payload_suffixes_remain_installable(library, extra) -> None:
    root, _ = library
    relatives = []
    for suffix in (".duf", ".dsf", ".dsa", ".png", ".jpg", ".jpeg", ".tif",
                   ".tiff", ".exr", ".hdr", ".bmp", ".webp", ".txt", ".md", ".json"):
        relative = ("Documentation" if extra else PRODUCT) + "/supported" + suffix.upper()
        write(root, relative, b"{}")
        relatives.append(relative)
    result = build(library, extra_relative_files=relatives if extra else [])
    assert all("Content/" + p in result.installed_files for p in relatives)


@pytest.mark.parametrize("extra", [False, True])
@pytest.mark.parametrize("document", [
    {"modifier_library": [{"id": "morph", "morph": {
        "vertex_count": 4, "deltas": {"count": 1, "values": [[0, 1.0, 2.0, 3.0]]},
    }}]},
    {"uv_set_library": [{"id": "uv", "uvs": {"count": 1, "values": [[0.0, 0.0]]}}]},
    {"node_library": [{"id": "node"}]},
    {"geometry_library": [{"id": "mesh"}]},
    {"unknown_library": [{"id": "unsupported"}]},
    {"extra": [{"modifier_library": [{"id": "nested"}]}]},
    {"scene": {"modifiers": [{"id": "morph", "url": "/data/Private/Morph.dsf#morph"}]}},
])
def test_non_material_dson_payloads_fail_closed(library, extra, document) -> None:
    root, output = library
    relative = ("Presets/Private" if extra else PRODUCT) + "/NonMaterial.dsf"
    dson(root, relative, document)
    with pytest.raises(ValueError, match="Scene/mesh"):
        build(library, extra_relative_files=[relative] if extra else [])
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


@pytest.mark.parametrize("asset_type", [
    "scene", "modifier", "uv_set", "geometry", "node", "preset_pose", "unknown", "", None,
])
def test_unsupported_dson_asset_type_is_rejected(library, asset_type) -> None:
    root, output = library
    dson(root, PRODUCT + "/WrongType.duf", {"asset_info": {"type": asset_type}})
    with pytest.raises(ValueError, match="DSON"):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


@pytest.mark.parametrize("asset_type", ["preset_material", "preset_shader", "material", "image", None])
def test_material_partial_dson_documents_remain_installable(library, asset_type) -> None:
    root, _ = library
    document = {
        "scene": {"materials": [{"channel": {"image_file": "/" + NORMAL}}]},
        "node_library": [], "geometry_library": [], "modifier_library": [], "uv_set_library": [],
    }
    if asset_type is not None:
        document["asset_info"] = {"type": asset_type}
    relative = PRODUCT + "/Partial.duf"
    dson(root, relative, document)
    result = build(library)
    assert "Content/" + relative in result.installed_files
    assert NORMAL in result.resources


@pytest.mark.parametrize("partial", [False, True])
def test_existing_archive_or_partial_is_never_overwritten(library, partial) -> None:
    _, output = library
    target = output.with_name(output.name + ".partial") if partial else output
    target.parent.mkdir(parents=True)
    target.write_bytes(b"keep exactly")
    with pytest.raises(FileExistsError):
        build(library)
    assert target.read_bytes() == b"keep exactly"
    if partial:
        assert not output.exists()


def test_existing_zip_is_not_modified_on_second_build(library) -> None:
    result = build(library)
    payload = result.zip_path.read_bytes()
    with pytest.raises(FileExistsError):
        build(library)
    assert result.zip_path.read_bytes() == payload


@pytest.mark.parametrize("broken", [b"not JSON", b"\x1f\x8bbroken", b"[]"])
def test_malformed_dson_fails_before_creating_partial(library, broken) -> None:
    root, output = library
    write(root, PRODUCT + "/Broken.duf", broken)
    with pytest.raises(ValueError):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


def test_zip_payload_copy_is_chunked_not_read_bytes(library, monkeypatch) -> None:
    root, _ = library
    texture = root / NORMAL
    texture.write_bytes(b"a" * (package._CHUNK * 2 + 3))
    read_bytes = Path.read_bytes

    def no_texture_read_bytes(path):
        assert path != texture, "texture payload must be streamed"
        return read_bytes(path)

    calls = []
    copyfileobj = package.shutil.copyfileobj

    def bounded_copy(source, target, length):
        calls.append(length)
        return copyfileobj(source, target, length)

    monkeypatch.setattr(Path, "read_bytes", no_texture_read_bytes)
    monkeypatch.setattr(package.shutil, "copyfileobj", bounded_copy)
    result = build(library)
    assert calls == [package._CHUNK] * result.content_file_count
    with ZipFile(result.zip_path) as archive:
        assert len(archive.read("Content/" + NORMAL)) == package._CHUNK * 2 + 3


def test_crc_corruption_is_detected_before_publish(library, monkeypatch) -> None:
    _, output = library
    verify = package._verify_archive

    def corrupt_then_verify(path, installed, name):
        with ZipFile(path) as archive:
            info = archive.getinfo("Content/" + NORMAL)
        with path.open("r+b") as stream:
            stream.seek(info.header_offset + 26)
            lengths = stream.read(4)
            name_len = int.from_bytes(lengths[:2], "little")
            extra_len = int.from_bytes(lengths[2:], "little")
            stream.seek(info.header_offset + 30 + name_len + extra_len)
            value = stream.read(1)
            stream.seek(-1, 1)
            stream.write(bytes([value[0] ^ 0xFF]))
        verify(path, installed, name)

    monkeypatch.setattr(package, "_verify_archive", corrupt_then_verify)
    with pytest.raises((ValueError, BadZipFile, zlib.error)):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


def test_manifest_mismatch_is_detected(library, tmp_path) -> None:
    result = build(library)
    tampered = tmp_path / "tampered.zip"
    with ZipFile(result.zip_path) as source, ZipFile(tampered, "w") as target:
        for name in source.namelist():
            payload = source.read(name)
            if name == "Manifest.dsx":
                payload = payload.replace(b"Content/People/", b"Content/../People/", 1)
            target.writestr(name, payload)
    with pytest.raises(ValueError, match="manifest paths"):
        package._verify_archive(tampered, result.installed_files, NAME)


def test_output_created_during_build_is_not_overwritten(library, monkeypatch) -> None:
    _, output = library
    verify = package._verify_archive

    def raced_output(path, installed, name):
        verify(path, installed, name)
        output.write_bytes(b"other build")

    monkeypatch.setattr(package, "_verify_archive", raced_output)
    with pytest.raises(FileExistsError):
        build(library)
    assert output.read_bytes() == b"other build"
    assert not output.with_name(output.name + ".partial").exists()


def test_copy_error_cleans_partial(library, monkeypatch) -> None:
    _, output = library

    def fail_copy(source, target, length):
        raise OSError("simulated read failure")

    monkeypatch.setattr(package.shutil, "copyfileobj", fail_copy)
    with pytest.raises(OSError, match="simulated read failure"):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


def test_source_changed_after_dson_parse_is_rejected(library, monkeypatch) -> None:
    root, output = library
    reader = package.read_dson

    def change_after_parse(path):
        doc = reader(path)
        with path.open("ab") as stream:
            stream.write(b" ")
        return doc

    monkeypatch.setattr(package, "read_dson", change_after_parse)
    with pytest.raises(ValueError, match="Source changed"):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


def test_source_changed_after_zip_verification_is_rejected(library, monkeypatch) -> None:
    root, output = library
    verify = package._verify_archive

    def changed_source(path, installed, name):
        verify(path, installed, name)
        with (root / NORMAL).open("ab") as stream:
            stream.write(b"source changed after it was copied")

    monkeypatch.setattr(package, "_verify_archive", changed_source)
    with pytest.raises(ValueError, match="Source changed"):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


def test_publication_failure_cleans_partial(library, monkeypatch) -> None:
    _, output = library

    def no_hard_links(source, target):
        raise OSError("filesystem does not support hard links")

    monkeypatch.setattr(package.os, "link", no_hard_links)
    with pytest.raises(OSError, match="does not support hard links"):
        build(library)
    assert not output.exists()
    assert not output.with_name(output.name + ".partial").exists()


def test_missing_explicit_extra_fails_closed(library) -> None:
    _, output = library
    with pytest.raises(FileNotFoundError):
        build(library, extra_relative_files=["Documentation/Missing.txt"])
    assert not output.exists()


@pytest.mark.parametrize("relative, error", [
    (PRODUCT, ValueError), (PRODUCT + "/Directory.txt", FileNotFoundError),
])
def test_directories_cannot_be_explicit_extra_files(library, relative, error) -> None:
    root, _ = library
    (root / relative).mkdir(exist_ok=True)
    with pytest.raises(error):
        build(library, extra_relative_files=[relative])


def test_empty_product_folder_is_rejected(tmp_path) -> None:
    root = tmp_path / "library"
    (root / PRODUCT).mkdir(parents=True)
    with pytest.raises(ValueError, match="contains no files"):
        build_material_package(root, PRODUCT, tmp_path / "empty.zip", product_name=NAME)


def test_output_inside_source_library_is_refused(library) -> None:
    root, _ = library
    with pytest.raises(ValueError, match="outside"):
        build_material_package(root, PRODUCT, root / PRODUCT / "private.zip", product_name=NAME)


def test_symlink_texture_is_rejected(library, tmp_path) -> None:
    root, _ = library
    outside = write(tmp_path, "outside.png")
    link = root / NORMAL
    link.unlink()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit creating symlinks")
    with pytest.raises(ValueError, match="Linked content"):
        build(library)


def test_linked_product_directory_is_rejected(library, tmp_path) -> None:
    root, _ = library
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / PRODUCT / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit creating symlinks")
    with pytest.raises(ValueError, match="Linked content"):
        build(library)


@pytest.mark.parametrize("name", ["", " ", "broken\x00name", "bad\ud800name"])
def test_invalid_product_name_is_rejected(library, name) -> None:
    root, output = library
    with pytest.raises(ValueError):
        build_material_package(root, PRODUCT, output, product_name=name)
