import gzip
import json
from pathlib import Path
from zipfile import ZipFile

from forge.analyzer.dson import parse_dson_asset_info
from forge.analyzer.source import read_source_file, scan_source


def dson_bytes(asset_type: str = "wearable", author: str = "Websoul") -> bytes:
    return json.dumps(
        {
            "file_version": "0.6.1.0",
            "asset_info": {
                "id": "/Props/Musical/Pan%20flute/Pan%20flute.duf",
                "type": asset_type,
                "contributor": {
                    "author": author,
                    "email": "",
                    "website": "Websoul.nl",
                },
                "revision": "1.0",
                "modified": "2023-01-11T19:40:48Z",
            },
        }
    ).encode("utf-8")


def test_read_source_file_from_folder_scan(tmp_path: Path) -> None:
    asset_path = tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(dson_bytes(asset_type="character"))
    scan = scan_source(tmp_path)

    data = read_source_file(scan, scan.files[0])

    assert json.loads(data)["asset_info"]["type"] == "character"


def test_read_source_file_from_zip_scan(tmp_path: Path) -> None:
    zip_path = tmp_path / "product.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("Content/People/Genesis 9/Characters/Hero.duf", dson_bytes())
    scan = scan_source(zip_path)

    data = read_source_file(scan, scan.files[0])

    assert json.loads(data)["asset_info"]["contributor"]["author"] == "Websoul"


def test_parse_plain_dson_asset_info() -> None:
    info = parse_dson_asset_info(dson_bytes(asset_type="preset_material"))

    assert info.file_version == "0.6.1.0"
    assert info.asset_id == "/Props/Musical/Pan%20flute/Pan%20flute.duf"
    assert info.asset_type == "preset_material"
    assert info.contributor.author == "Websoul"
    assert info.contributor.website == "Websoul.nl"
    assert info.revision == "1.0"
    assert info.modified == "2023-01-11T19:40:48Z"


def test_parse_gzip_compressed_dson_asset_info() -> None:
    compressed = gzip.compress(dson_bytes(asset_type="uv_set", author="Collective3d"))

    info = parse_dson_asset_info(compressed)

    assert info.asset_type == "uv_set"
    assert info.contributor.author == "Collective3d"


def test_parse_zip_wrapped_dson_asset_info(tmp_path: Path) -> None:
    zip_path = tmp_path / "wrapped.duf"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("payload.json", dson_bytes(asset_type="pose"))

    info = parse_dson_asset_info(zip_path.read_bytes())

    assert info.asset_type == "pose"