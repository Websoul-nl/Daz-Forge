import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from forge.analyzer.source import scan_source
from forge.packager.dim import build_dim_package
from forge.ui.main_window import analyze_source


def write_file(path: Path, content: bytes | str = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)


def dson(asset_type: str, author: str = "Websoul") -> bytes:
    return json.dumps(
        {
            "file_version": "0.6.1.0",
            "asset_info": {
                "id": "/Props/Websoul/Hero%20Prop.duf",
                "type": asset_type,
                "contributor": {"author": author, "email": "", "website": ""},
            },
        }
    ).encode("utf-8")


def test_build_dim_package_writes_only_zip_manifest_and_support(tmp_path: Path) -> None:
    source = tmp_path / "Hero Product"
    output = tmp_path / "out"
    write_file(source / "Props" / "Websoul" / "Hero Prop.duf", dson("scene_subset"))
    write_file(source / "Props" / "Websoul" / "Hero Prop.duf.png", b"png")
    write_file(source / "Runtime" / "Textures" / "Websoul" / "Hero.jpg", b"texture")
    write_file(source / "Runtime" / "Support" / "OLD_1_Old.dsx", "<old/>")
    write_file(source / "Runtime" / "Support" / "OLD_1_Old.dsa", "// old")
    write_file(source / "Runtime" / "Support" / "OLD_1_Old.jpg", b"old image")

    contract = analyze_source(source)
    contract["product"].update(
        {
            "product_name": "Hero Product",
            "store_display_name": "Websoul",
            "store_id": "WEBSOUL",
            "store_prefix": "WEB",
            "store_code": "",
            "product_token": "90000000",
            "global_id": "11111111-2222-4333-8444-555555555555",
            "artists": ["Websoul"],
            "primary_artist": "Websoul",
            "product_image": "Runtime/Support/OLD_1_Old.jpg",
        }
    )

    result = build_dim_package(scan_source(source), contract, output)

    assert result.zip_path.name == "WEB90000000-01_HeroProduct.zip"
    assert sorted(path.name for path in output.iterdir()) == [result.zip_path.name]
    with ZipFile(result.zip_path) as archive:
        names = set(archive.namelist())
        assert "Manifest.dsx" in names
        assert "Supplement.dsx" in names
        assert "Content/Props/Websoul/Hero Prop.duf" in names
        assert "Content/Props/Websoul/Hero Prop.duf.png" in names
        assert "Content/Runtime/Textures/Websoul/Hero.jpg" in names
        assert "Content/Runtime/Support/WEBSOUL_90000000_Hero_Product.dsx" in names
        assert "Content/Runtime/Support/WEBSOUL_90000000_Hero_Product.dsa" in names
        assert "Content/Runtime/Support/WEBSOUL_90000000_Hero_Product.jpg" in names
        assert "Content/Runtime/Support/OLD_1_Old.dsx" not in names
        assert "Content/Runtime/Support/OLD_1_Old.dsa" not in names
        assert "Content/Runtime/Support/OLD_1_Old.jpg" not in names
        assert archive.read("Content/Runtime/Support/WEBSOUL_90000000_Hero_Product.jpg") == b"old image"
        support_script = archive.read("Content/Runtime/Support/WEBSOUL_90000000_Hero_Product.dsa").decode("utf-8")
        assert 'createStore("WEBSOUL", "", "")' in support_script
        assert "queueDBMetaFile" in support_script

        manifest = archive.read("Manifest.dsx").decode("utf-8")
        assert 'GlobalID VALUE="11111111-2222-4333-8444-555555555555"' in manifest
        assert 'VALUE="Content/Runtime/Support/WEBSOUL_90000000_Hero_Product.dsx"' in manifest
        assert 'VALUE="Content/Runtime/Support/WEBSOUL_90000000_Hero_Product.dsa"' in manifest

        supplement = archive.read("Supplement.dsx").decode("utf-8")
        assert 'ProductName VALUE="Hero Product"' in supplement

        support = archive.read("Content/Runtime/Support/WEBSOUL_90000000_Hero_Product.dsx").decode("utf-8")
        assert '<Product VALUE="Hero Product">' in support
        assert '<StoreID VALUE="WEBSOUL"/>' in support
        assert '<ProductToken VALUE="90000000"/>' in support
        assert '<Artist VALUE="Websoul"/>' in support
        assert '<Asset VALUE="/Props/Websoul/Hero Prop.duf">' in support
        assert '<ContentType VALUE="Set"/>' in support
        assert '<Category VALUE="/Default/Props"/>' in support
        assert '<SupportAssets VALUE="/Runtime/Support/WEBSOUL_90000000_Hero_Product.dsx">' in support
        assert '<SupportAsset VALUE="/Props/Websoul/Hero Prop.duf"/>' in support
        assert '<SupportAsset VALUE="/Props/Websoul/Hero Prop.duf.png"/>' in support
        assert '<SupportAsset VALUE="/Runtime/Support/WEBSOUL_90000000_Hero_Product.jpg"/>' in support
        assert '<SupportAsset VALUE="/Runtime/Textures/Websoul/Hero.jpg"/>' in support


def test_build_dim_package_combines_store_prefix_and_creator_code_with_six_character_cap(tmp_path: Path) -> None:
    source = tmp_path / "Sade Product"
    output = tmp_path / "out"
    write_file(source / "Props" / "Sade" / "Hero Prop.duf", dson("scene_subset", author="Sade"))
    contract = analyze_source(source)
    contract["product"].update(
        {
            "product_name": "Sade Product",
            "store_display_name": "3D SHARDS",
            "store_id": "3D SHARDS",
            "store_prefix": "SHA",
            "store_code": "SADE",
            "product_token": "42",
            "global_id": "11111111-2222-4333-8444-555555555555",
            "artists": ["Sade"],
            "primary_artist": "Sade",
        }
    )

    result = build_dim_package(scan_source(source), contract, output)

    assert result.zip_path.name == "SHASAD00000042-01_SadeProduct.zip"
    assert result.support_path == "Runtime/Support/3D_SHARDS_42_Sade_Product.dsx"
    with ZipFile(result.zip_path) as archive:
        support = archive.read("Content/Runtime/Support/3D_SHARDS_42_Sade_Product.dsx").decode("utf-8")
        assert '<StoreID VALUE="3D SHARDS"/>' in support
        assert '<SupportAssets VALUE="/Runtime/Support/3D_SHARDS_42_Sade_Product.dsx">' in support


def test_rebuild_removes_legacy_json_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "Product"
    write_file(source / "Props" / "Hero.duf", dson("scene_subset"))
    contract = analyze_source(source)
    output = tmp_path / "out"
    original = build_dim_package(scan_source(source), contract, output)
    old_report = original.zip_path.with_suffix(".report.json")
    old_report.write_text('{"old":true}', encoding="utf-8")

    result = build_dim_package(scan_source(source), contract, output)

    assert result.zip_path == original.zip_path
    assert not old_report.exists()
    assert list(output.glob("*.json")) == []
    assert [path.name for path in output.iterdir()] == [result.zip_path.name]


def test_atomic_build_preserves_existing_zip_on_source_read_failure(tmp_path: Path) -> None:
    source = tmp_path / "Product"
    asset = source / "Props" / "Hero.duf"
    write_file(asset, dson("scene_subset"))
    scan = scan_source(source)
    contract = analyze_source(source)
    output = tmp_path / "out"
    output.mkdir()
    previous = output / "LU90000000-01_Product.zip"
    previous.write_bytes(b"previous valid package")
    asset.unlink()

    with pytest.raises(OSError):
        build_dim_package(scan, contract, output)

    assert previous.read_bytes() == b"previous valid package"
    assert sorted(path.name for path in output.iterdir()) == [previous.name]


def test_packager_rejects_duplicate_paths_even_if_invoked_directly(tmp_path: Path) -> None:
    source = tmp_path / "Product"
    write_file(source / "Props" / "Hero.duf", dson("scene_subset"))
    write_file(source / "Props" / "hero.duf", dson("scene_subset"))
    scan = scan_source(source)

    assert scan.duplicates
    with pytest.raises(ValueError, match="Duplicate content paths"):
        build_dim_package(scan, {"product": {}}, tmp_path / "out")
