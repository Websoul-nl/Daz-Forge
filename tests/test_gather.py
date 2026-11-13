import json
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from forge.analyzer.gather import is_daz_base_file
from forge.analyzer.source import SourceScanError, scan_source
from forge.analyzer.support import parse_support_metadata
from forge.packager.dim import build_dim_package
from forge.ui.main_window import analyze_source


def write(path: Path, data: bytes | str = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    return path


def dsx_xml(assets: list[str], supporting: list[str], name: str = "Sporty Swimsuit") -> str:
    def node(tag: str, value: str) -> str:
        return f'<{tag} VALUE="{escape(value, {"\"": "&quot;"})}"/>'
    assets_xml = "".join(node("Asset", "/" + path) for path in assets)
    support_xml = "".join(node("SupportAsset", "/" + path) for path in supporting)
    return (
        '<ContentDBInstall VERSION="1.0"><Products>'
        f'<Product VALUE="{name}">'
        '<StoreID VALUE="LOCAL USER"/><ProductToken VALUE="424242"/>'
        '<Artists><Artist VALUE="Artist"/></Artists>'
        f'<Assets>{assets_xml}</Assets>'
        f'<SupportAssets VALUE="/Runtime/Support/Test.dsx">{support_xml}</SupportAssets>'
        '</Product></Products></ContentDBInstall>'
    )


def dson(path: str, references: list[str]) -> str:
    return json.dumps({
        "file_version": "0.6.1.0",
        "asset_info": {"id": "/" + path, "type": "wearable"},
        "scene": {
            "nodes": [{"url": reference} for reference in references],
        },
    })


SUIT = "People/Genesis 8 Female/Clothing/Artist/Sporty/Suit.duf"
EYES = "data/DAZ 3D/Genesis 8/Female/Genesis8FemaleEyes.dsf"
MORPH = "data/DAZ 3D/Genesis 8/Female/Morphs/Artist/Sporty/Fix.dsf"
TEXTURE = "Runtime/Textures/Artist/Sporty/Diffuse.jpg"
NORMAL = "Runtime/Textures/Artist/Sporty/Normal.jpg"
UNKNOWN = "Runtime/Textures/AnotherVendor/Shared.jpg"
FOREIGN = "Runtime/Textures/Artist/Sporty/OtherProduct.jpg"


def product(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "DAZ Library"
    references = ["/" + EYES + "#eyes", "/" + MORPH + "#fix", "/" + TEXTURE,
                  "/" + NORMAL, "/" + UNKNOWN, "/" + FOREIGN]
    write(root / SUIT, dson(SUIT, references))
    write(root / MORPH, dson(MORPH, []))
    write(root / TEXTURE)
    write(root / NORMAL)
    write(root / UNKNOWN)
    write(root / FOREIGN)
    write(root / EYES)
    dsx = write(root / "Runtime/Support/Test.dsx", dsx_xml([SUIT], [MORPH, TEXTURE]))
    write(root / "Runtime/Support/Test.jpg", b"product image")
    write(root / "Runtime/Support/Other.dsx", dsx_xml([], [FOREIGN], "Another product"))
    return root, dsx


def test_support_parser_collects_support_assets() -> None:
    metadata = parse_support_metadata(dsx_xml([SUIT], [MORPH, TEXTURE]).encode())
    assert metadata.support_assets == ("/" + MORPH, "/" + TEXTURE)


def test_base_eyes_are_excluded_even_if_declared(tmp_path: Path) -> None:
    root, dsx = product(tmp_path)
    # Explicitly claiming DAZ eyes must not circumvent the safety restriction.
    dsx.write_text(dsx_xml([SUIT], [MORPH, TEXTURE, EYES]), encoding="utf-8")
    scan = scan_source(dsx)
    statuses = {entry.content_path: entry.status for entry in scan.gathered_files}
    included = {entry.content_path for entry in scan.files}

    assert statuses[EYES] == "base"
    assert EYES not in included
    assert MORPH in included  # Product-specific morphs under DAZ 3D are allowed.
    assert TEXTURE in included
    assert NORMAL in included  # Recursively discovered texture in same namespace.
    assert SUIT in included
    assert "Runtime/Support/Test.jpg" in included
    assert statuses[UNKNOWN] == "unknown"
    assert UNKNOWN not in included
    assert statuses[FOREIGN] == "external"
    assert FOREIGN not in included
    assert not scan.hard_errors
    assert scan.source_kind == "dsx"


def test_protect_base_data_without_blocking_vendor_morphs() -> None:
    assert is_daz_base_file(EYES)
    assert is_daz_base_file("data/DAZ 3D/Genesis 9/Base/Genesis9.dsf")
    assert not is_daz_base_file(MORPH)
    assert not is_daz_base_file("data/DAZ 3D/Genesis 8/Female/UV Sets/Artist/Custom.dsf")
    assert not is_daz_base_file("data/Artist/Swimsuit/mesh.dsf")


def test_build_gathered_zip_has_no_external_or_base_dependencies(tmp_path: Path) -> None:
    root, dsx = product(tmp_path)
    contract = analyze_source(dsx)
    assert contract["gathered_files"]
    assert contract["product"]["product_name"] == "Sporty Swimsuit"
    assert contract["product"]["source_kind"] == "dsx"
    assert contract["rows"][0]["final"]["content_type"] == "Follower/Wardrobe" or contract["rows"][0]["final"]["content_type"]

    result = build_dim_package(scan_source(dsx), contract, tmp_path / "out")
    with ZipFile(result.zip_path) as archive:
        names = set(archive.namelist())
        assert "Content/" + SUIT in names
        assert "Content/" + MORPH in names
        assert "Content/" + TEXTURE in names
        assert "Content/" + NORMAL in names
        assert "Content/" + EYES not in names
        assert "Content/" + UNKNOWN not in names
        assert "Content/" + FOREIGN not in names
        assert "Manifest.dsx" in names
        assert "Supplement.dsx" in names
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert any(entry["status"] == "base" and entry["content_path"] == EYES
               for entry in report["gathered_files"])


def test_missing_declared_file_blocks_packaging(tmp_path: Path) -> None:
    root, dsx = product(tmp_path)
    (root / MORPH).unlink()
    scan = scan_source(dsx)
    assert any("Product file missing:" in error for error in scan.hard_errors)
    assert any(entry.content_path == MORPH and entry.status == "missing"
               for entry in scan.gathered_files)
    with pytest.raises(ValueError, match="incomplete gathered source"):
        build_dim_package(scan, analyze_source(dsx), tmp_path / "out")


def test_rejects_dsx_outside_runtime_support(tmp_path: Path) -> None:
    dsx = write(tmp_path / "Wrong.dsx", dsx_xml([SUIT], []))
    with pytest.raises(SourceScanError, match="Runtime/Support"):
        scan_source(dsx)


def test_cross_library_declared_dependency(tmp_path: Path) -> None:
    root, dsx = product(tmp_path)
    other_root = tmp_path / "Other Library"
    (root / TEXTURE).unlink()
    write(other_root / TEXTURE, b"second library")
    scan = scan_source(dsx, extra_libraries=(other_root,))
    assert TEXTURE in {entry.content_path for entry in scan.files}
