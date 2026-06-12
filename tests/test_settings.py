import json
from pathlib import Path

from forge.settings import (
    AppSettings,
    StoreSettings,
    default_store_catalog,
    load_settings,
    load_store_catalog,
    save_settings,
    upsert_store,
)


def test_default_settings_use_share_safe_local_user_defaults() -> None:
    settings = AppSettings.defaults()

    assert settings.default_store == StoreSettings(
        display_name="LOCAL USER",
        store_id="LOCAL USER",
        dim_prefix="LU",
    )
    assert settings.next_product_number == 90000000
    assert settings.lm_studio_base_url == "http://127.0.0.1:1234/v1"
    assert settings.preserve_staging is False


def test_load_settings_creates_file_when_missing(tmp_path: Path) -> None:
    settings_path = tmp_path / "config" / "settings.json"

    settings = load_settings(settings_path)

    assert settings_path.exists()
    assert settings.default_store.store_id == "LOCAL USER"
    assert settings.default_store.dim_prefix == "LU"
    assert settings.next_product_number == 90000000


def test_load_settings_preserves_existing_values(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        """
        {
          "default_store": {
            "display_name": "Renderosity",
            "store_id": "RENDEROSITY",
            "dim_prefix": "RND"
          },
          "next_product_number": 12345678,
          "lm_studio_base_url": "http://localhost:9999/v1",
          "ollama_base_url": "http://localhost:11434",
          "default_output_folder": "build/output",
          "default_staging_folder": "build/staging",
          "default_daz_library": "example/library",
          "dim_downloads_folder": "build/downloads",
          "preserve_staging": true
        }
        """,
        encoding="utf-8",
    )

    settings = load_settings(settings_path)

    assert settings.default_store.display_name == "Renderosity"
    assert settings.default_store.dim_prefix == "RND"
    assert settings.next_product_number == 12345678
    assert settings.preserve_staging is True


def test_save_settings_omits_store_code_from_global_default_store(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings = AppSettings(default_store=StoreSettings("Shards", "Shards", "SHA", default_code="WEB"))

    save_settings(settings_path, settings)

    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    assert raw["default_store"] == {
        "display_name": "Shards",
        "store_id": "Shards",
        "dim_prefix": "SHA",
    }


def test_default_store_catalog_contains_known_store_prefixes() -> None:
    stores = {store.display_name: store for store in default_store_catalog()}

    assert stores["DAZ 3D"].dim_prefix == "IM"
    assert stores["LOCAL USER"].dim_prefix == "LU"
    assert stores["Renderosity"].dim_prefix == "RND"
    assert stores["Renderhub"].dim_prefix == "RHB"
    assert stores["CGTrader"].dim_prefix == "CGT"
    assert stores["DeviantArt"].dim_prefix == "DA"


def test_load_store_catalog_creates_json_when_missing(tmp_path: Path) -> None:
    catalog_path = tmp_path / "stores.json"

    stores = load_store_catalog(catalog_path)

    assert catalog_path.exists()
    assert [store.display_name for store in stores] == [
        "DAZ 3D",
        "LOCAL USER",
        "Renderosity",
        "Renderhub",
        "CGTrader",
        "DeviantArt",
    ]


def test_upsert_store_adds_and_updates_store_catalog(tmp_path: Path) -> None:
    catalog_path = tmp_path / "stores.json"
    load_store_catalog(catalog_path)

    upsert_store(catalog_path, StoreSettings("3D SHARDS", "3D SHARDS", "SHX", default_code="SAD"))
    upsert_store(catalog_path, StoreSettings("Renderosity", "Renderosity", "RND", default_code=""))
    stores = {store.display_name: store for store in load_store_catalog(catalog_path)}

    assert stores["3D SHARDS"].dim_prefix == "SHX"
    assert stores["3D SHARDS"].default_code == "SAD"
    assert stores["Renderosity"].dim_prefix == "RND"
