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
    default_code: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StoreSettings":
        return cls(
            display_name=str(raw.get("display_name", "")),
            store_id=str(raw.get("store_id", raw.get("display_name", ""))),
            dim_prefix=str(raw.get("dim_prefix", raw.get("prefix", ""))),
            default_code=str(raw.get("default_code", "")),
        )


@dataclass(frozen=True)
class AppSettings:
    default_store: StoreSettings = field(
        default_factory=lambda: StoreSettings(
            display_name="Websoul",
            store_id="Websoul",
            dim_prefix="WEB",
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


def default_store_catalog() -> tuple[StoreSettings, ...]:
    return (
        StoreSettings(display_name="DAZ 3D", store_id="DAZ 3D", dim_prefix="IM"),
        StoreSettings(display_name="LOCAL USER", store_id="LOCAL USER", dim_prefix="LU"),
        StoreSettings(display_name="Websoul", store_id="Websoul", dim_prefix="WEB"),
        StoreSettings(display_name="3D SHARDS", store_id="3D SHARDS", dim_prefix="SHA"),
    )


def load_store_catalog(path: Path) -> tuple[StoreSettings, ...]:
    if not path.exists():
        stores = default_store_catalog()
        save_store_catalog(path, stores)
        return stores
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw_stores = raw.get("stores", raw) if isinstance(raw, dict) else raw
    if not isinstance(raw_stores, list):
        raise ValueError(f"Store catalog must contain a list of stores: {path}")
    stores = tuple(StoreSettings.from_dict(item) for item in raw_stores if isinstance(item, dict))
    return stores or default_store_catalog()


def save_store_catalog(path: Path, stores: tuple[StoreSettings, ...] | list[StoreSettings]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"stores": [asdict(store) for store in stores]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def upsert_store(path: Path, store: StoreSettings) -> None:
    stores = list(load_store_catalog(path))
    store_key = _store_key(store.display_name)
    for index, existing in enumerate(stores):
        if _store_key(existing.display_name) == store_key or _store_key(existing.store_id) == _store_key(store.store_id):
            stores[index] = store
            break
    else:
        stores.append(store)
    save_store_catalog(path, stores)


def _store_key(value: str) -> str:
    return value.strip().lower()
