from pathlib import Path
from zipfile import ZipFile

from forge.analyzer.inventory import classify_inventory
from forge.analyzer.source import scan_source


def write_file(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_zip(path: Path, names: list[str]) -> None:
    with ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, "x")


def classify_folder(tmp_path: Path):
    return classify_inventory(scan_source(tmp_path))


def test_clickable_assets_outside_data_and_runtime_are_smart_content(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf")
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa")
    write_file(tmp_path / "Scripts" / "Websoul" / "Encrypted.dse")
    write_file(tmp_path / "Props" / "Websoul" / "OddSupport.dsf")

    inventory = classify_folder(tmp_path)

    assert [item.content_path for item in inventory.smart_content] == [
        "People/Genesis 9/Characters/Hero.duf",
        "Props/Websoul/OddSupport.dsf",
        "Scripts/Websoul/Encrypted.dse",
        "Scripts/Websoul/Tool.dsa",
    ]
    assert all(item.include_in_smart_content for item in inventory.smart_content)


def test_data_and_runtime_files_are_shipped_but_not_smart_content(tmp_path: Path) -> None:
    write_file(tmp_path / "data" / "Websoul" / "Product" / "asset.dsf")
    write_file(tmp_path / "Runtime" / "Support" / "WEBS_1_Product.dsa")
    write_file(tmp_path / "Runtime" / "Support" / "WEBS_1_Product.dsx")
    write_file(tmp_path / "Runtime" / "Textures" / "Websoul" / "texture.jpg")
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf")

    inventory = classify_folder(tmp_path)

    assert [item.content_path for item in inventory.smart_content] == [
        "People/Genesis 9/Characters/Hero.duf",
    ]
    roles = {item.content_path: item.role for item in inventory.items}
    assert roles["data/Websoul/Product/asset.dsf"] == "data"
    assert roles["Runtime/Support/WEBS_1_Product.dsa"] == "runtime"
    assert roles["Runtime/Support/WEBS_1_Product.dsx"] == "runtime"
    assert roles["Runtime/Textures/Websoul/texture.jpg"] == "runtime"


def test_user_facing_dsf_gets_warning(tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Websoul" / "OddSupport.dsf")

    inventory = classify_folder(tmp_path)

    item = inventory.smart_content[0]
    assert item.content_path == "Props/Websoul/OddSupport.dsf"
    assert item.warnings == ("user-facing-dsf",)
    assert inventory.warnings == ("Props/Websoul/OddSupport.dsf: user-facing-dsf",)


def test_thumbnail_sidecars_are_detected_and_linked_to_asset(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf")
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf.jpg")
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.tip.png")
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Other.duf.png")

    inventory = classify_folder(tmp_path)

    assert [(item.content_path, item.related_asset_path) for item in inventory.thumbnails] == [
        ("People/Genesis 9/Characters/Hero.duf.jpg", "People/Genesis 9/Characters/Hero.duf"),
        ("People/Genesis 9/Characters/Hero.tip.png", "People/Genesis 9/Characters/Hero.duf"),
        ("People/Genesis 9/Characters/Other.duf.png", "People/Genesis 9/Characters/Other.duf"),
    ]


def test_documentation_readmes_and_licenses_are_detected(tmp_path: Path) -> None:
    write_file(tmp_path / "ReadMe.txt")
    write_file(tmp_path / "License.pdf")
    write_file(tmp_path / "Documentation" / "Product" / "Manual.htm")
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf")

    inventory = classify_folder(tmp_path)

    assert [item.content_path for item in inventory.documentation] == [
        "Documentation/Product/Manual.htm",
        "License.pdf",
        "ReadMe.txt",
    ]


def test_obvious_promo_and_template_junk_is_detected(tmp_path: Path) -> None:
    write_file(tmp_path / "Promo" / "popup_01.jpg")
    write_file(tmp_path / "Templates" / "uv_template.png")
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf")

    inventory = classify_folder(tmp_path)

    assert [item.content_path for item in inventory.ignored] == [
        "Promo/popup_01.jpg",
        "Templates/uv_template.png",
    ]


def test_inventory_classifies_zip_scan(tmp_path: Path) -> None:
    zip_path = tmp_path / "product.zip"
    write_zip(
        zip_path,
        [
            "Content/People/Genesis 9/Characters/Hero.duf",
            "Content/People/Genesis 9/Characters/Hero.duf.png",
            "Content/Runtime/Textures/Websoul/Hero.jpg",
        ],
    )

    inventory = classify_inventory(scan_source(zip_path))

    assert [item.content_path for item in inventory.smart_content] == [
        "People/Genesis 9/Characters/Hero.duf",
    ]
    assert inventory.thumbnails[0].related_asset_path == "People/Genesis 9/Characters/Hero.duf"