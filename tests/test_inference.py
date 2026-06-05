import json
from pathlib import Path

from forge.analyzer.inference import infer_metadata
from forge.analyzer.inventory import classify_inventory
from forge.analyzer.source import scan_source


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
                "id": "/People/Genesis%209/Test.duf",
                "type": asset_type,
                "contributor": {"author": author, "email": "", "website": ""},
                "revision": "1.0",
                "modified": "2026-06-05T00:00:00Z",
            },
        }
    ).encode("utf-8")


def analyze(path: Path):
    scan = scan_source(path)
    inventory = classify_inventory(scan)
    return infer_metadata(scan, inventory)


def test_maps_dson_asset_types_and_script_extensions_to_content_types(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf", dson("character"))
    write_file(tmp_path / "People" / "Genesis 9" / "Clothing" / "Dress.duf", dson("wearable"))
    write_file(tmp_path / "People" / "Genesis 9" / "Clothing" / "Materials" / "Dress Red.duf", dson("preset_hierarchical_material"))
    write_file(tmp_path / "People" / "Genesis 9" / "Poses" / "Pose.duf", dson("preset_hierarchical_pose"))
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")

    result = analyze(tmp_path)

    by_path = {asset.path: asset for asset in result.assets}
    assert by_path["People/Genesis 9/Characters/Hero.duf"].content_type == "Actor/Character"
    assert by_path["People/Genesis 9/Clothing/Dress.duf"].content_type == "Follower/Wardrobe"
    assert by_path["People/Genesis 9/Clothing/Materials/Dress Red.duf"].content_type == "Preset/Materials"
    assert by_path["People/Genesis 9/Poses/Pose.duf"].content_type == "Preset/Pose"
    assert by_path["Scripts/Websoul/Tool.dsa"].content_type == "Script/Utility"


def test_suggests_default_categories_from_paths_and_types(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf", dson("character"))
    write_file(tmp_path / "People" / "Genesis 9" / "Clothing" / "Dress.duf", dson("wearable"))
    write_file(tmp_path / "People" / "Genesis 9" / "Clothing" / "Materials" / "Dress Red.duf", dson("preset_material"))
    write_file(tmp_path / "Vehicles" / "Websoul" / "Car.duf", dson("scene_subset"))
    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dse", "encrypted")

    result = analyze(tmp_path)

    by_path = {asset.path: asset for asset in result.assets}
    assert by_path["People/Genesis 9/Characters/Hero.duf"].categories == ("/Default/Figures/People",)
    assert by_path["People/Genesis 9/Clothing/Dress.duf"].categories == ("/Default/Wardrobe",)
    assert by_path["People/Genesis 9/Clothing/Materials/Dress Red.duf"].categories == ("/Default/Materials",)
    assert by_path["Vehicles/Websoul/Car.duf"].categories == ("/Default/Transportation/Land",)
    assert by_path["Scripts/Websoul/Tool.dse"].categories == ("/Default/Utilities/Scripts",)


def test_infers_product_type_from_asset_mix(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Clothing" / "Dress.duf", dson("wearable"))
    write_file(tmp_path / "People" / "Genesis 9" / "Clothing" / "Shoes.duf", dson("wearable"))
    write_file(tmp_path / "People" / "Genesis 9" / "Clothing" / "Materials" / "Dress Red.duf", dson("preset_material"))

    result = analyze(tmp_path)

    assert result.product.product_type == "clothing/outfit"
    assert result.product.primary_artist == "Websoul"
    assert result.product.artist_state == "single"


def test_marks_multiple_authors_as_ambiguous(tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "One.duf", dson("scene_subset", author="Sade"))
    write_file(tmp_path / "Props" / "Two.duf", dson("scene_subset", author="x"))

    result = analyze(tmp_path)

    assert result.product.artist_state == "ambiguous"
    assert result.product.primary_artist == ""
    assert result.product.artists == ("Sade", "x")
    assert "product: ambiguous-authors" in result.warnings


def test_support_metadata_agreement_raises_confidence(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Characters" / "Hero.duf", dson("character"))
    write_file(
        tmp_path / "Runtime" / "Support" / "WEBS_1_Hero.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Hero">
              <StoreID VALUE="WEBS"/>
              <ProductToken VALUE="1"/>
              <Artists><Artist VALUE="Websoul"/></Artists>
              <Assets>
                <Asset VALUE="/People/Genesis 9/Characters/Hero.duf">
                  <ContentType VALUE="Actor/Character"/>
                  <Categories><Category VALUE="/Default/Figures/People"/></Categories>
                </Asset>
              </Assets>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.confidence == 0.9
    assert asset.warnings == ()


def test_support_metadata_conflict_adds_warning(tmp_path: Path) -> None:
    write_file(tmp_path / "Vehicles" / "Car.duf", dson("scene_subset"))
    write_file(
        tmp_path / "Runtime" / "Support" / "WEBS_1_Car.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Car">
              <Assets>
                <Asset VALUE="/Vehicles/Car.duf">
                  <ContentType VALUE="Prop"/>
                  <Categories><Category VALUE="/Default/Props/Landscape/Ground"/></Categories>
                </Asset>
              </Assets>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Set"
    assert asset.categories == ("/Default/Transportation/Land",)
    assert "support-content-type-conflict" in asset.warnings
    assert "support-category-conflict" in asset.warnings
    assert "Vehicles/Car.duf: support-category-conflict" in result.warnings

def test_hair_path_infers_hair_content_type_and_category(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Hair" / "Websoul" / "Hero Hair.duf", dson("wearable"))

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Follower/Hair"
    assert asset.categories == ("/Default/Hair",)
    assert result.product.product_type == "hair"


def test_support_child_values_agree_with_broad_deterministic_values(tmp_path: Path) -> None:
    write_file(tmp_path / "People" / "Genesis 9" / "Hair" / "Websoul" / "Hero Hair.duf", dson("wearable"))
    write_file(
        tmp_path / "Runtime" / "Support" / "WEBS_1_Hair.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Hair">
              <Assets>
                <Asset VALUE="People/Genesis 9/Hair/Websoul/Hero Hair.duf">
                  <ContentType VALUE="Follower/Hair"/>
                  <Categories><Category VALUE="/Default/Hair/Long"/></Categories>
                </Asset>
              </Assets>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Follower/Hair"
    assert asset.categories == ("/Default/Hair",)
    assert asset.confidence == 0.9
    assert asset.warnings == ()

def test_hair_materials_keep_material_category(tmp_path: Path) -> None:
    write_file(
        tmp_path / "People" / "Genesis 9" / "Hair" / "Websoul" / "Hero Hair" / "Materials" / "Auburn.duf",
        dson("preset_hierarchical_material"),
    )

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Preset/Materials"
    assert asset.categories == ("/Default/Materials",)