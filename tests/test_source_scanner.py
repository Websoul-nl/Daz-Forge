from pathlib import Path
from zipfile import ZipFile

import pytest

from forge.analyzer.source import UnsafeArchivePathError, scan_source


def write_file(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_zip(path: Path, names: list[str]) -> None:
    with ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "x")


def test_scan_folder_with_content_root_strips_content_prefix(tmp_path: Path) -> None:
    write_file(tmp_path / "Content" / "People" / "Genesis 9" / "Characters" / "Hero.duf")
    write_file(tmp_path / "Content" / "Runtime" / "Textures" / "Websoul" / "Hero.jpg")

    scan = scan_source(tmp_path)

    assert scan.source_kind == "folder"
    assert scan.content_root == "Content"
    assert [file.content_path for file in scan.files] == [
        "People/Genesis 9/Characters/Hero.duf",
        "Runtime/Textures/Websoul/Hero.jpg",
    ]
    assert scan.hard_errors == ()


def test_scan_folder_with_direct_daz_roots_uses_source_as_content_root(tmp_path: Path) -> None:
    write_file(tmp_path / "data" / "Websoul" / "Product" / "asset.dsf")
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf")

    scan = scan_source(tmp_path)

    assert scan.content_root == ""
    assert [file.content_path for file in scan.files] == [
        "People/Genesis 9/Characters/Hero.duf",
        "data/Websoul/Product/asset.dsf",
    ]


def test_scan_folder_with_product_wrapper_detects_inner_content_root(tmp_path: Path) -> None:
    write_file(tmp_path / "My Product" / "Content" / "Runtime" / "Support" / "WEBS_1_My_Product.dsx")
    write_file(tmp_path / "My Product" / "Content" / "Props" / "Websoul" / "Thing.duf")

    scan = scan_source(tmp_path)

    assert scan.content_root == "My Product/Content"
    assert [file.content_path for file in scan.files] == [
        "Props/Websoul/Thing.duf",
        "Runtime/Support/WEBS_1_My_Product.dsx",
    ]


def test_scan_zip_detects_content_root_without_extracting(tmp_path: Path) -> None:
    zip_path = tmp_path / "product.zip"
    write_zip(
        zip_path,
        [
            "Content/People/Genesis 9/Characters/Hero.duf",
            "Content/Runtime/Textures/Websoul/Hero.jpg",
        ],
    )

    scan = scan_source(zip_path)

    assert scan.source_kind == "zip"
    assert scan.content_root == "Content"
    assert [file.content_path for file in scan.files] == [
        "People/Genesis 9/Characters/Hero.duf",
        "Runtime/Textures/Websoul/Hero.jpg",
    ]


def test_scan_folder_with_single_zip_wrapper_scans_embedded_zip(tmp_path: Path) -> None:
    write_file(tmp_path / "Install instructions.txt")
    zip_path = tmp_path / "Product.zip"
    write_zip(
        zip_path,
        [
            "Content/People/Genesis 9/Characters/Hero.duf",
            "Content/Runtime/Support/WEBS_1_Hero.dsx",
        ],
    )

    scan = scan_source(tmp_path)

    assert scan.source_kind == "zip"
    assert scan.source_path == str(zip_path)
    assert scan.content_root == "Content"
    assert scan.warnings == ("folder-wrapper-single-zip",)
    assert [file.content_path for file in scan.files] == [
        "People/Genesis 9/Characters/Hero.duf",
        "Runtime/Support/WEBS_1_Hero.dsx",
    ]


@pytest.mark.parametrize(
    "bad_name",
    [
        "../evil.duf",
        "Content/../evil.duf",
        "/absolute/evil.duf",
        "C:/absolute/evil.duf",
        "Content/C:/evil.duf",
    ],
)
def test_scan_zip_rejects_unsafe_member_paths(tmp_path: Path, bad_name: str) -> None:
    zip_path = tmp_path / "bad.zip"
    write_zip(zip_path, [bad_name])

    with pytest.raises(UnsafeArchivePathError):
        scan_source(zip_path)


def test_duplicate_normalized_content_paths_are_reported(tmp_path: Path) -> None:
    zip_path = tmp_path / "duplicate.zip"
    write_zip(zip_path, ["Content/Props/Thing.duf", "Content/Props/thing.duf"])

    scan = scan_source(zip_path)

    assert len(scan.duplicates) == 1
    duplicate = scan.duplicates[0]
    assert duplicate.normalized_key == "props/thing.duf"
    assert duplicate.content_paths == ("Props/Thing.duf", "Props/thing.duf")
