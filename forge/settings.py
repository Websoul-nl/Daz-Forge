from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoreSettings:
    display_name: str
    store_id: str
    dim_prefix: str


@dataclass(frozen=True)
class AppSettings:
    default_store: StoreSettings = field(
        default_factory=lambda: StoreSettings(
            display_name="Websoul",
            store_id="WEBS",
            dim_prefix="WEBS",
        )
    )
    next_product_number: int = 24156030
    lm_studio_base_url: str = "http://127.0.0.1:1234/v1"
    ollama_base_url: str = "http://127.0.0.1:11434"
    default_output_folder: str = ""
    default_staging_folder: str = ""
    default_daz_library: str = "E:/Libraries/Daz Libraries/Daz3D Library New"
    dim_downloads_folder: str = ""
    preserve_staging: bool = False

    @classmethod
    def defaults(cls) -> "AppSettings":
        return cls()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppSettings":
        defaults = cls.defaults()
        store_raw = raw.get("default_store", {})
        default_store = StoreSettings(
            display_name=str(store_raw.get("display_name", defaults.default_store.display_name)),
            store_id=str(store_raw.get("store_id", defaults.default_store.store_id)),
            dim_prefix=str(store_raw.get("dim_prefix", defaults.default_store.dim_prefix)),
        )
        return cls(
            default_store=default_store,
            next_product_number=int(raw.get("next_product_number", defaults.next_product_number)),
            lm_studio_base_url=str(raw.get("lm_studio_base_url", defaults.lm_studio_base_url)),
            ollama_base_url=str(raw.get("ollama_base_url", defaults.ollama_base_url)),
            default_output_folder=str(raw.get("default_output_folder", defaults.default_output_folder)),
            default_staging_folder=str(raw.get("default_staging_folder", defaults.default_staging_folder)),
            default_daz_library=str(raw.get("default_daz_library", defaults.default_daz_library)),
            dim_downloads_folder=str(raw.get("dim_downloads_folder", defaults.dim_downloads_folder)),
            preserve_staging=bool(raw.get("preserve_staging", defaults.preserve_staging)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_settings(path: Path) -> AppSettings:
    if not path.exists():
        settings = AppSettings.defaults()
        save_settings(path, settings)
        return settings

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Settings file must contain a JSON object: {path}")
    return AppSettings.from_dict(raw)


def save_settings(path: Path, settings: AppSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )