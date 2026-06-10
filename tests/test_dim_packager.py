import json
from pathlib import Path
from zipfile import ZipFile

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


def test_build_dim_package_writes_zip_manifest_support_and_report(tmp_path: Path) -> None:
    source = tmp_path / "Hero Product"
    output = tmp_path / "out"
    write_file(source / "Props" / "Websoul" / "Hero Prop.duf", dson("scene_subset"))
    write_file(source / "Props" / "Websoul" / "Hero Prop.duf.png", b"png")
    write_file(source / "Runtime" / "Textures" / "Websoul" / "Hero.jpg", b"texture")
    write_file(source / "Runtime" / "Support" / "OLD_1_Old.dsx", "<old/>")
    write_file(source / "Runtime" / "Support" / "OLD_1_Old.jpg", b"old image")

    contract = analyze_source(source)
    contract["product"].update(
        {
            "product_name": "Hero Product",
            "store_display_name": "Websoul",
            "store_id": "Websoul",
            "store_prefix": "WEB",
            "store_code": "",
            "product_token": "24156030",
            "global_id": "11111111-2222-4333-8444-555555555555",
            "artists": ["Websoul"],
            "primary_artist": "Websoul",
            "product_image": "Runtime/Support/OLD_1_Old.jpg",
        }
    )

    result = build_dim_package(scan_source(source), contract, output)

    assert result.zip_path.name == "WEB24156030-01_HeroProduct.zip"
    assert result.report_path.name == "WEB24156030-01_HeroProduct.report.json"
    with ZipFile(result.zip_path) as archive:
        names = set(archive.namelist())
        assert "Manifest.dsx" in names
        assert "Supplement.dsx" in names
        assert "Content/Props/Websoul/Hero Prop.duf" in names
        assert "Content/Props/Websoul/Hero Prop.duf.png" in names
        assert "Content/Runtime/Textures/Websoul/Hero.jpg" in names
        assert "Content/Runtime/Support/WEB_24156030_Hero_Product.dsx" in names
        assert "Content/Runtime/Support/WEB_24156030_Hero_Product.jpg" in names
        assert "Content/Runtime/Support/OLD_1_Old.dsx" not in names
        assert "Content/Runtime/Support/OLD_1_Old.jpg" not in names
        assert archive.read("Content/Runtime/Support/WEB_24156030_Hero_Product.jpg") == b"old image"

        manifest = archive.read("Manifest.dsx").decode("utf-8")
        assert 'GlobalID VALUE="11111111-2222-4333-8444-555555555555"' in manifest
        assert 'VALUE="Content/Runtime/Support/WEB_24156030_Hero_Product.dsx"' in manifest

        supplement = archive.read("Supplement.dsx").decode("utf-8")
        assert 'ProductName VALUE="Hero Product"' in supplement

        support = archive.read("Content/Runtime/Support/WEB_24156030_Hero_Product.dsx").decode("utf-8")
        assert '<Product VALUE="Hero Product">' in support
        assert '<StoreID VALUE="Websoul"/>' in support
        assert '<ProductToken VALUE="24156030"/>' in support
        assert '<Artist VALUE="Websoul"/>' in support
        assert '<Asset VALUE="/Props/Websoul/Hero Prop.duf">' in support
        assert '<ContentType VALUE="Set"/>' in support
        assert '<Category VALUE="/Default/Props"/>' in support

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["zip_name"] == "WEB24156030-01_HeroProduct.zip"
    assert report["package_code"] == "WEB"
    assert report["product_image_path"] == "Runtime/Support/WEB_24156030_Hero_Product.jpg"
    assert report["skipped_existing_support_files"] == ["Runtime/Support/OLD_1_Old.dsx", "Runtime/Support/OLD_1_Old.jpg"]


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
    assert result.support_path == "Runtime/Support/SHASAD_42_Sade_Product.dsx"
    with ZipFile(result.zip_path) as archive:
        support = archive.read("Content/Runtime/Support/SHASAD_42_Sade_Product.dsx").decode("utf-8")
        assert '<StoreID VALUE="3D SHARDS"/>' in support
