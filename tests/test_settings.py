from pathlib import Path

from forge.settings import AppSettings, StoreSettings, load_settings


def test_default_settings_match_robert_defaults() -> None:
    settings = AppSettings.defaults()

    assert settings.default_store == StoreSettings(
        display_name="Websoul",
        store_id="WEBS",
        dim_prefix="WEBS",
    )
    assert settings.next_product_number == 24156030
    assert settings.lm_studio_base_url == "http://127.0.0.1:1234/v1"
    assert settings.preserve_staging is False


def test_load_settings_creates_file_when_missing(tmp_path: Path) -> None:
    settings_path = tmp_path / "config" / "settings.json"

    settings = load_settings(settings_path)

    assert settings_path.exists()
    assert settings.default_store.store_id == "WEBS"
    assert settings.next_product_number == 24156030


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
          "default_output_folder": "D:/DIM Output",
          "default_staging_folder": "D:/DIM Staging",
          "default_daz_library": "E:/Libraries/Daz Libraries/Daz3D Library New",
          "dim_downloads_folder": "D:/DIM Downloads",
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
