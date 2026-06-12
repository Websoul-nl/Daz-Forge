import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from forge.product_tokens import (
    ProductTokenRegistryError,
    SourceProductIdentity,
    TokenAssignment,
    TokenCollision,
    load_product_token_registry,
    resolve_product_token,
    record_product_token_build,
    source_identity_from_path,
)


def test_source_identity_defaults_optional_metadata() -> None:
    source = SourceProductIdentity("path:first", source_product_name="First")

    assert source.source_key == "path:first"
    assert source.source_store_id == ""
    assert source.source_product_token == ""
    assert source.source_product_name == "First"


def test_source_identity_reads_support_metadata_from_zip(tmp_path: Path) -> None:
    zip_path = tmp_path / "IM00083577-01_HeroProduct.zip"
    write_support_zip(zip_path, product_name="Hero Product", store_id="DAZ 3D", token="83577")

    result = source_identity_from_path(zip_path)

    assert result.source_key == "support:daz 3d:83577"
    assert result.source_store_id == "DAZ 3D"
    assert result.source_product_token == "83577"
    assert result.source_product_name == "Hero Product"


def test_source_identity_accepts_store_token_support_metadata_without_product_name(tmp_path: Path) -> None:
    zip_path = tmp_path / "IM00083577-01_HeroProduct.zip"
    write_support_zip(zip_path, product_name="", store_id="DAZ 3D", token="83577")

    result = source_identity_from_path(zip_path)

    assert result.source_key == "support:daz 3d:83577"
    assert result.source_store_id == "DAZ 3D"
    assert result.source_product_token == "83577"
    assert result.source_product_name == ""


def test_source_identity_skips_bad_support_metadata_and_uses_next_readable_zip_entry(tmp_path: Path) -> None:
    zip_path = tmp_path / "IM00083577-01_HeroProduct.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("Content/Runtime/Support/Bad.dsx", b"<ContentDBInstall>")
        archive.writestr(
            "Content/Runtime/Support/Good.dsx",
            support_metadata(product_name="Hero Product", store_id="DAZ 3D", token="83577"),
        )

    result = source_identity_from_path(zip_path)

    assert result.source_key == "support:daz 3d:83577"
    assert result.source_store_id == "DAZ 3D"
    assert result.source_product_token == "83577"
    assert result.source_product_name == "Hero Product"


def test_source_identity_store_token_key_reuses_manual_override_across_product_name_changes(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    first_zip = tmp_path / "HeroProduct.zip"
    renamed_zip = tmp_path / "HeroProductRenamed.zip"
    write_support_zip(first_zip, product_name="Hero Product", store_id="DAZ 3D", token="83577")
    write_support_zip(renamed_zip, product_name="Hero Product Renamed", store_id="DAZ 3D", token="83577")

    first = source_identity_from_path(first_zip)
    renamed = source_identity_from_path(renamed_zip)
    record_product_token_build(
        registry_path,
        source_identity=first,
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product",
        assigned_token="12345678",
        token_source="manual",
    )

    assignment = resolve_product_token(
        registry_path,
        source_identity=renamed,
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product Renamed",
        next_product_number=90000000,
    )

    assert first.source_key == renamed.source_key
    assert first.source_key == "support:daz 3d:83577"
    assert assignment == TokenAssignment(token="12345678", token_source="manual", is_new_generated=False)


def test_source_identity_reuses_manual_override_across_store_spacing_and_case_changes(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    first_zip = tmp_path / "HeroProduct.zip"
    respaced_zip = tmp_path / "HeroProductRespaced.zip"
    write_support_zip(first_zip, product_name="Hero Product", store_id="DAZ 3D", token="83577")
    write_support_zip(respaced_zip, product_name="Hero Product", store_id="daz  3d", token="83577")

    first = source_identity_from_path(first_zip)
    respaced = source_identity_from_path(respaced_zip)
    record_product_token_build(
        registry_path,
        source_identity=first,
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product",
        assigned_token="12345678",
        token_source="manual",
    )

    assignment = resolve_product_token(
        registry_path,
        source_identity=respaced,
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product",
        next_product_number=90000000,
    )

    assert first.source_key == respaced.source_key
    assert assignment == TokenAssignment(token="12345678", token_source="manual", is_new_generated=False)


def test_source_identity_falls_back_to_normalized_path_name(tmp_path: Path) -> None:
    source = tmp_path / "Loose Product"
    source.mkdir()

    result = source_identity_from_path(source)

    assert result.source_key == "path:loose product"
    assert result.source_product_name == "Loose Product"
    assert result.source_product_token == ""


def test_gitignore_ignores_product_token_registry() -> None:
    assert "config/product-tokens.json" in Path(".gitignore").read_text(encoding="utf-8").splitlines()


def write_support_zip(zip_path: Path, *, product_name: str, store_id: str, token: str) -> None:
    with ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "Content/Runtime/Support/Product.dsx",
            support_metadata(product_name=product_name, store_id=store_id, token=token),
        )


def support_metadata(*, product_name: str, store_id: str, token: str) -> bytes:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<ContentDBInstall VERSION="1.0">
  <Products>
    <Product VALUE="{product_name}">
      <StoreID VALUE="{store_id}"/>
      <ProductToken VALUE="{token}"/>
    </Product>
  </Products>
</ContentDBInstall>'''.encode("utf-8")


def identity(name: str = "Hero Product", token: str = "", store: str = "") -> SourceProductIdentity:
    return SourceProductIdentity(
        source_key="zip:HeroProduct.zip",
        source_store_id=store,
        source_product_token=token,
        source_product_name=name,
    )


def test_source_token_wins_without_existing_registry_entry(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"

    assignment = resolve_product_token(
        registry_path,
        source_identity=identity(token="83577", store="DAZ 3D"),
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product",
        next_product_number=90000000,
    )

    assert assignment == TokenAssignment(token="83577", token_source="source", is_new_generated=False)
    assert not registry_path.exists()


def test_missing_source_token_uses_next_number_and_reuses_registry(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"

    first = resolve_product_token(
        registry_path,
        source_identity=identity(),
        workflow_label="Genesis 9 -> Genesis 8 Female",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product G8F",
        next_product_number=90000000,
    )
    record_product_token_build(
        registry_path,
        source_identity=identity(),
        workflow_label="Genesis 9 -> Genesis 8 Female",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product G8F",
        assigned_token=first.token,
        token_source=first.token_source,
    )

    second = resolve_product_token(
        registry_path,
        source_identity=identity(),
        workflow_label="Genesis 9 -> Genesis 8 Female",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product G8F",
        next_product_number=90000001,
    )

    assert first == TokenAssignment(token="90000000", token_source="generated", is_new_generated=True)
    assert second == TokenAssignment(token="90000000", token_source="generated", is_new_generated=False)


def test_same_source_different_pose_preset_gets_different_generated_token(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    source = identity()

    female = resolve_product_token(
        registry_path,
        source_identity=source,
        workflow_label="Genesis 9 -> Genesis 8 Female",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product G8F",
        next_product_number=90000000,
    )
    record_product_token_build(
        registry_path,
        source_identity=source,
        workflow_label="Genesis 9 -> Genesis 8 Female",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product G8F",
        assigned_token=female.token,
        token_source=female.token_source,
    )

    male = resolve_product_token(
        registry_path,
        source_identity=source,
        workflow_label="Genesis 9 -> Genesis 8 Male",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product G8M",
        next_product_number=90000001,
    )

    assert male == TokenAssignment(token="90000001", token_source="generated", is_new_generated=True)


def test_manual_override_is_preferred_over_source_token(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    source = identity(token="83577", store="DAZ 3D")
    record_product_token_build(
        registry_path,
        source_identity=source,
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product",
        assigned_token="12345678",
        token_source="manual",
    )

    assignment = resolve_product_token(
        registry_path,
        source_identity=source,
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product",
        next_product_number=90000000,
    )

    assert assignment == TokenAssignment(token="12345678", token_source="manual", is_new_generated=False)


def test_source_product_name_change_still_reuses_registry_entry(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    original = identity(name="Hero Product")
    renamed = identity(name="Hero Product Renamed")
    record_product_token_build(
        registry_path,
        source_identity=original,
        workflow_label="Genesis 9 -> Genesis 8 Female",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product G8F",
        assigned_token="90000000",
        token_source="generated",
    )

    assignment = resolve_product_token(
        registry_path,
        source_identity=renamed,
        workflow_label="Genesis 9 -> Genesis 8 Female",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product G8F",
        next_product_number=90000001,
    )

    assert assignment == TokenAssignment(token="90000000", token_source="generated", is_new_generated=False)


def test_record_build_preserves_created_at_and_refreshes_updated_at(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    source = identity()
    record_product_token_build(
        registry_path,
        source_identity=source,
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product",
        assigned_token="83577",
        token_source="source",
    )
    first = load_product_token_registry(registry_path).entries[0]

    record_product_token_build(
        registry_path,
        source_identity=source,
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="Hero Product Renamed",
        assigned_token="12345678",
        token_source="manual",
    )
    registry = load_product_token_registry(registry_path)

    assert len(registry.entries) == 1
    assert registry.entries[0].created_at == first.created_at
    assert registry.entries[0].updated_at
    assert registry.entries[0].updated_at != first.updated_at
    assert registry.entries[0].assigned_token == "12345678"
    assert registry.entries[0].generated_product_name == "Hero Product Renamed"


def test_same_token_is_allowed_for_different_output_stores(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    record_product_token_build(
        registry_path,
        source_identity=identity("First"),
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="First",
        assigned_token="83577",
        token_source="source",
    )

    collisions = load_product_token_registry(registry_path).collisions_for(
        output_store_id="3D SHARDS",
        assigned_token="83577",
        source_identity=identity("Second"),
        workflow_label="DIM Packager",
    )

    assert collisions == ()


def test_same_token_warns_for_different_source_in_same_store(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    record_product_token_build(
        registry_path,
        source_identity=identity("First"),
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="First",
        assigned_token="83577",
        token_source="source",
    )

    collisions = load_product_token_registry(registry_path).collisions_for(
        output_store_id="LOCAL USER",
        assigned_token="83577",
        source_identity=SourceProductIdentity(source_key="zip:Second.zip", source_product_name="Second"),
        workflow_label="DIM Packager",
    )

    assert collisions == (
        TokenCollision(output_store_id="LOCAL USER", assigned_token="83577", product_name="First"),
    )


def test_invalid_registry_json_has_clear_error(tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    registry_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ProductTokenRegistryError, match="Invalid product token registry JSON"):
        load_product_token_registry(registry_path)


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '{"entries": {}}',
        '{"entries": ["bad"]}',
        '{"entries": [{"source_key": "zip:HeroProduct.zip", "extra": "field"}]}',
    ],
)
def test_invalid_registry_shape_has_clear_error(tmp_path: Path, content: str) -> None:
    registry_path = tmp_path / "product-tokens.json"
    registry_path.write_text(content, encoding="utf-8")

    with pytest.raises(ProductTokenRegistryError, match="Invalid product token registry shape"):
        load_product_token_registry(registry_path)


@pytest.mark.parametrize("field_name", ["source_product_token", "assigned_token"])
def test_invalid_registry_entry_string_field_types_have_clear_error(
    tmp_path: Path,
    field_name: str,
) -> None:
    registry_path = tmp_path / "product-tokens.json"
    entry = {
        "assigned_token": "83577",
        "created_at": "2026-06-12T18:00:00+00:00",
        "generated_product_name": "Hero Product",
        "output_store_id": "LOCAL USER",
        "source_key": "zip:HeroProduct.zip",
        "source_product_name": "Hero Product",
        "source_product_token": "83577",
        "source_store_id": "DAZ 3D",
        "token_source": "source",
        "updated_at": "2026-06-12T18:00:00+00:00",
        "workflow_label": "DIM Packager",
    }
    entry[field_name] = None
    registry_path.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")

    with pytest.raises(ProductTokenRegistryError, match="Invalid product token registry shape"):
        load_product_token_registry(registry_path)
