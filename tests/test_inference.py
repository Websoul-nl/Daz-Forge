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


def test_preset_shape_infers_shaping_metadata_and_agrees_with_support(tmp_path: Path) -> None:
    write_file(
        tmp_path / "People" / "Genesis 9" / "Characters" / "Websoul" / "Hero" / "Shaping" / "Hero Body Apply.duf",
        dson("preset_shape"),
    )
    write_file(
        tmp_path / "Runtime" / "Support" / "WEBS_1_Hero.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Hero">
              <Assets>
                <Asset VALUE="/People/Genesis 9/Characters/Websoul/Hero/Shaping/Hero Body Apply.duf">
                  <ContentType VALUE="Preset/Morph/Apply/Body"/>
                  <Categories><Category VALUE="/Default/Shaping/Apply/Body"/></Categories>
                </Asset>
              </Assets>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Preset/Morph"
    assert asset.categories == ("/Default/Shaping",)
    assert "unknown-content-type" not in asset.warnings
    assert "support-content-type-conflict" not in asset.warnings
    assert "support-category-conflict" not in asset.warnings


def test_layered_image_support_agrees_with_material_family(tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Pan flute" / "Decoration" / "Autumn.duf", dson("preset_layered_image"))
    write_file(
        tmp_path / "Runtime" / "Support" / "WEBS_1_Pan_Flute.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Pan Flute">
              <Assets>
                <Asset VALUE="/Props/Pan flute/Decoration/Autumn.duf">
                  <ContentType VALUE="Preset/Layered-Image"/>
                  <Categories><Category VALUE="/Default/Materials/Iray/Props"/></Categories>
                </Asset>
              </Assets>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Preset/Materials"
    assert "support-content-type-conflict" not in asset.warnings
    assert "support-category-conflict" not in asset.warnings


def test_script_categories_win_over_incidental_folder_roots(tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Musical" / "Pan flute" / "Setup" / "Setup Smart Content.dsa", "// script")

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Script/Utility"
    assert asset.categories == ("/Default/Utilities/Scripts",)


def test_prop_wearables_keep_prop_category_and_follower_support_agrees(tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Musical" / "Pan flute" / "Pan flute G9 Left Hand.duf", dson("wearable"))
    write_file(
        tmp_path / "Runtime" / "Support" / "WEBS_1_Pan_Flute.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Pan Flute">
              <Assets>
                <Asset VALUE="/Props/Musical/Pan flute/Pan flute G9 Left Hand.duf">
                  <ContentType VALUE="Follower/Attachment/Upper-Body/Arm/Left/Hand"/>
                  <Categories><Category VALUE="/Default/Props/Musical"/></Categories>
                </Asset>
              </Assets>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Follower/Wardrobe"
    assert asset.categories == ("/Default/Props",)
    assert "support-content-type-conflict" not in asset.warnings
    assert "support-category-conflict" not in asset.warnings


def test_generation_tokens_infer_compatibilities(tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Musical" / "Pan flute" / "Pan flute G8F Left Hand.duf", dson("wearable"))
    write_file(tmp_path / "Props" / "Musical" / "Pan flute" / "Poses" / "G9" / "G9 Sitting.duf", dson("preset_pose"))
    write_file(tmp_path / "People" / "Genesis 8" / "Poses" / "Lexana" / "Bad Boys" / "01 BB.duf", dson("preset_pose"))

    result = analyze(tmp_path)
    by_path = {asset.path: asset for asset in result.assets}

    assert by_path["Props/Musical/Pan flute/Pan flute G8F Left Hand.duf"].compatibilities == (
        "/Genesis 8/Female",
        "/Genesis 8.1/Female",
    )
    assert by_path["Props/Musical/Pan flute/Poses/G9/G9 Sitting.duf"].compatibilities == ("/Genesis 9/Base",)
    assert by_path["People/Genesis 8/Poses/Lexana/Bad Boys/01 BB.duf"].compatibilities == (
        "/Genesis 8/Female",
        "/Genesis 8/Male",
    )


def test_prop_helpers_under_pose_folder_keep_prop_category(tmp_path: Path) -> None:
    write_file(
        tmp_path / "People" / "Genesis 8" / "Poses" / "Lexana" / "Bad Boys" / "Probs" / "Chair.duf",
        dson("scene_subset"),
    )

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Set"
    assert asset.categories == ("/Default/Props",)


def test_scene_subset_under_props_infers_prop_and_agrees_with_prop_support(tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Musical" / "Pan flute" / "Pan flute.duf", dson("scene_subset"))
    write_file(
        tmp_path / "Runtime" / "Support" / "WEBS_1_Pan_Flute.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Pan Flute">
              <Assets>
                <Asset VALUE="/Props/Musical/Pan flute/Pan flute.duf">
                  <ContentType VALUE="Prop"/>
                  <Categories><Category VALUE="/Default/Props/Musical"/></Categories>
                </Asset>
              </Assets>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )

    result = analyze(tmp_path)

    asset = result.assets[0]
    assert asset.content_type == "Prop"
    assert asset.categories == ("/Default/Props",)
    assert "support-content-type-conflict" not in asset.warnings


def test_scene_subset_under_props_can_remain_set_when_support_says_set(tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Websoul" / "Deck" / "Deck Scene.duf", dson("scene_subset"))
    write_file(
        tmp_path / "Runtime" / "Support" / "WEBS_1_Deck.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Deck">
              <Assets>
                <Asset VALUE="/Props/Websoul/Deck/Deck Scene.duf">
                  <ContentType VALUE="Set"/>
                  <Categories><Category VALUE="/Default/Props/Architecture"/></Categories>
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
    assert asset.categories == ("/Default/Props",)
    assert "support-content-type-conflict" not in asset.warnings
