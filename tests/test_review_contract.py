import json
from pathlib import Path
from zipfile import ZipFile

from forge.analyzer.inference import infer_metadata
from forge.analyzer.inventory import classify_inventory
from forge.analyzer.model_provider import ModelAssetSuggestion, ModelSuggestionResult
from forge.analyzer.review_contract import build_review_contract, contract_to_dict
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


def analyze(path: Path, model_result: ModelSuggestionResult | None = None):
    scan = scan_source(path)
    inventory = classify_inventory(scan)
    inference = infer_metadata(scan, inventory)
    return build_review_contract(scan, inventory, inference, model_result)


def test_product_summary_contains_source_counts_and_model_status(tmp_path: Path) -> None:
    product_root = tmp_path / "Hero Hair Product"
    write_file(product_root / "People" / "Genesis 9" / "Hair" / "Websoul" / "Hero Hair.duf", dson("wearable"))
    write_file(product_root / "People" / "Genesis 9" / "Hair" / "Websoul" / "Hero Hair.duf.jpg")
    write_file(product_root / "Documentation" / "Hero Hair" / "ReadMe.txt", "license-ish")
    model = ModelSuggestionResult(provider="fake", available=False, suggestions=(), warnings=("model-unavailable",))

    contract = analyze(product_root, model)

    assert contract.product.source_kind == "folder"
    assert contract.product.content_root == ""
    assert contract.product.product_name == "Hero Hair Product"
    assert contract.product.store_display_name == ""
    assert contract.product.store_id == ""
    assert contract.product.store_code == ""
    assert contract.product.product_token == ""
    assert contract.product.product_type == "hair"
    assert contract.product.primary_artist == "Websoul"
    assert contract.product.model_provider == "fake"
    assert contract.product.model_available is False
    assert contract.product.total_files == 3
    assert contract.product.smart_content_count == 1
    assert contract.product.documentation_count == 1
    assert contract.product.thumbnail_count == 1


def test_product_summary_uses_existing_support_product_fields(tmp_path: Path) -> None:
    write_file(tmp_path / "Props" / "Sadriel" / "Jewelry.duf", dson("scene_subset", author="Sadriel"))
    write_file(
        tmp_path / "Runtime" / "Support" / "LOCAL_USER_Celtic_Jewelry.dsx",
        """
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Celtic Jewelry for Genesis 8 and 9">
              <StoreID VALUE="LOCAL USER"/>
              <GlobalID VALUE="bf8660f0-d6be-4171-abdd-19a3315e4170"/>
              <ProductToken VALUE="884422"/>
              <Artists>
                <Artist VALUE="Sade"/>
                <Artist VALUE="Sadriel"/>
              </Artists>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )

    contract = analyze(tmp_path)

    assert contract.product.product_name == "Celtic Jewelry for Genesis 8 and 9"
    assert contract.product.store_id == "LOCAL USER"
    assert contract.product.global_id == "bf8660f0-d6be-4171-abdd-19a3315e4170"
    assert contract.product.product_token == "884422"
    assert contract.product.artists == ("Sade", "Sadriel")
    assert contract.product.primary_artist == "Sade"


def test_asset_rows_keep_deterministic_model_support_and_final_fields(tmp_path: Path) -> None:
    asset_path = "People/Genesis 9/Hair/Websoul/Hero Hair.duf"
    write_file(tmp_path / asset_path, dson("wearable"))
    write_file(
        tmp_path / "Runtime" / "Support" / "WEBS_1_Hair.dsx",
        f"""
        <ContentDBInstall VERSION="1.0">
          <Products>
            <Product VALUE="Hero Hair">
              <Assets>
                <Asset VALUE="/{asset_path}">
                  <ContentType VALUE="Follower/Hair"/>
                  <Categories><Category VALUE="/Default/Hair/Long"/></Categories>
                  <CompatibilityBase VALUE="/Genesis 9/Base"/>
                  <Compatibilities><Compatibility VALUE="/Genesis 9/Base"/></Compatibilities>
                </Asset>
              </Assets>
            </Product>
          </Products>
        </ContentDBInstall>
        """,
    )
    model = ModelSuggestionResult(
        provider="fake",
        available=True,
        suggestions=(
            ModelAssetSuggestion(
                path=asset_path,
                content_type="Follower/Hair",
                categories=("/Default/Hair/Long",),
                compatibility_base="/Genesis 9/Base",
                compatibilities=("/Genesis 9/Base",),
                confidence=0.92,
                reason="Hair wearable under Genesis 9.",
            ),
        ),
    )

    contract = analyze(tmp_path, model)

    row = contract.rows[0]
    assert row.path == asset_path
    assert row.deterministic.content_type == "Follower/Hair"
    assert row.deterministic.categories == ("/Default/Hair",)
    assert row.model is not None
    assert row.model.categories == ("/Default/Hair/Long",)
    assert row.support is not None
    assert row.support.categories == ("/Default/Hair/Long",)
    assert row.final.content_type == "Follower/Hair"
    assert row.final.categories == ("/Default/Hair",)
    assert row.final.editable is True


def test_duplicate_content_paths_become_hard_blockers(tmp_path: Path) -> None:
    source = tmp_path / "duplicate.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("Props/Car.duf", dson("scene_subset"))
        archive.writestr("props/car.duf", dson("scene_subset"))

    contract = analyze(source)

    assert contract.hard_blockers
    assert contract.hard_blockers[0].code == "duplicate-content-path"
    assert sorted(contract.hard_blockers[0].paths) == ["Props/Car.duf", "props/car.duf"]


def test_contract_serializes_to_json_friendly_stable_dict(tmp_path: Path) -> None:
    write_file(tmp_path / "Vehicles" / "Websoul" / "Car.duf", dson("scene_subset"))

    contract = analyze(tmp_path)
    payload = contract_to_dict(contract)

    assert payload["schema_version"] == 1
    assert payload["rows"][0]["path"] == "Vehicles/Websoul/Car.duf"
    assert payload["rows"][0]["final"]["editable"] is True
    assert payload["restructure_plan"]["enabled"] is False
    json.dumps(payload)


def test_debug_summary_output_is_readable(tmp_path: Path) -> None:
    from forge.analyzer.debug_summary import analyze_source_to_summary

    write_file(tmp_path / "Scripts" / "Websoul" / "Tool.dsa", "// script")

    summary = analyze_source_to_summary(tmp_path)

    assert "Daz Forge Analysis Summary" in summary
    assert "Smart Content rows: 1" in summary
    assert "Scripts/Websoul/Tool.dsa" in summary
