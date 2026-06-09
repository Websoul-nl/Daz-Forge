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

    contract = analyze_source(source)
    contract["product"].update(
        {
            "product_name": "Hero Product",
            "store_display_name": "Websoul",
            "store_id": "WEBS",
            "store_code": "WEBS",
            "product_token": "24156030",
            "global_id": "11111111-2222-4333-8444-555555555555",
            "artists": ["Websoul"],
            "primary_artist": "Websoul",
        }
    )

    result = build_dim_package(scan_source(source), contract, output)

    assert result.zip_path.name == "WEBS24156030-01_HeroProduct.zip"
    assert result.report_path.name == "WEBS24156030-01_HeroProduct.report.json"
    with ZipFile(result.zip_path) as archive:
        names = set(archive.namelist())
        assert "Manifest.dsx" in names
        assert "Supplement.dsx" in names
        assert "Content/Props/Websoul/Hero Prop.duf" in names
        assert "Content/Props/Websoul/Hero Prop.duf.png" in names
        assert "Content/Runtime/Textures/Websoul/Hero.jpg" in names
        assert "Content/Runtime/Support/WEBS_24156030_Hero_Product.dsx" in names
        assert "Content/Runtime/Support/OLD_1_Old.dsx" not in names

        manifest = archive.read("Manifest.dsx").decode("utf-8")
        assert 'GlobalID VALUE="11111111-2222-4333-8444-555555555555"' in manifest
        assert 'VALUE="Content/Runtime/Support/WEBS_24156030_Hero_Product.dsx"' in manifest

        supplement = archive.read("Supplement.dsx").decode("utf-8")
        assert 'ProductName VALUE="Hero Product"' in supplement

        support = archive.read("Content/Runtime/Support/WEBS_24156030_Hero_Product.dsx").decode("utf-8")
        assert '<Product VALUE="Hero Product">' in support
        assert '<StoreID VALUE="WEBS"/>' in support
        assert '<ProductToken VALUE="24156030"/>' in support
        assert '<Artist VALUE="Websoul"/>' in support
        assert '<Asset VALUE="/Props/Websoul/Hero Prop.duf">' in support
        assert '<ContentType VALUE="Set"/>' in support
        assert '<Category VALUE="/Default/Props"/>' in support

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["zip_name"] == "WEBS24156030-01_HeroProduct.zip"
    assert report["skipped_existing_support_files"] == ["Runtime/Support/OLD_1_Old.dsx"]

