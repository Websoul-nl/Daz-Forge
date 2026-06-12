from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, LargeZipFile

from forge.analyzer.source import SourceScanError, read_source_file, scan_source
from forge.analyzer.support import SupportParseError, parse_support_metadata


class ProductTokenRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class SourceProductIdentity:
    source_key: str
    source_store_id: str = ""
    source_product_token: str = ""
    source_product_name: str = ""


@dataclass(frozen=True)
class TokenAssignment:
    token: str
    token_source: str
    is_new_generated: bool


@dataclass(frozen=True)
class TokenCollision:
    output_store_id: str
    assigned_token: str
    product_name: str


@dataclass(frozen=True)
class ProductTokenEntry:
    source_key: str
    source_store_id: str
    source_product_token: str
    source_product_name: str
    workflow_label: str
    output_store_id: str
    generated_product_name: str
    assigned_token: str
    token_source: str
    created_at: str
    updated_at: str

    @classmethod
    def from_identity(
        cls,
        source_identity: SourceProductIdentity,
        *,
        workflow_label: str,
        output_store_id: str,
        generated_product_name: str,
        assigned_token: str,
        token_source: str,
    ) -> ProductTokenEntry:
        timestamp = _utc_timestamp()
        return cls(
            source_key=source_identity.source_key,
            source_store_id=source_identity.source_store_id,
            source_product_token=source_identity.source_product_token,
            source_product_name=source_identity.source_product_name,
            workflow_label=workflow_label,
            output_store_id=output_store_id,
            generated_product_name=generated_product_name,
            assigned_token=assigned_token,
            token_source=token_source,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def matches(
        self,
        *,
        source_identity: SourceProductIdentity,
        output_store_id: str,
        workflow_label: str,
    ) -> bool:
        return (
            self.source_key == source_identity.source_key
            and _normalize_identity_part(self.source_store_id) == _normalize_identity_part(source_identity.source_store_id)
            and _normalize_token(self.source_product_token) == _normalize_token(source_identity.source_product_token)
            and self.output_store_id == output_store_id
            and self.workflow_label == workflow_label
        )


@dataclass(frozen=True)
class ProductTokenRegistry:
    entries: tuple[ProductTokenEntry, ...] = ()

    def find(
        self,
        *,
        source_identity: SourceProductIdentity,
        output_store_id: str,
        workflow_label: str,
    ) -> ProductTokenEntry | None:
        for entry in self.entries:
            if entry.matches(
                source_identity=source_identity,
                output_store_id=output_store_id,
                workflow_label=workflow_label,
            ):
                return entry
        return None

    def collisions_for(
        self,
        *,
        output_store_id: str,
        assigned_token: str,
        source_identity: SourceProductIdentity,
        workflow_label: str,
    ) -> tuple[TokenCollision, ...]:
        normalized_token = _normalize_token(assigned_token)
        collisions = []
        for entry in self.entries:
            if entry.output_store_id != output_store_id:
                continue
            if _normalize_token(entry.assigned_token) != normalized_token:
                continue
            if entry.matches(
                source_identity=source_identity,
                output_store_id=output_store_id,
                workflow_label=workflow_label,
            ):
                continue
            collisions.append(
                TokenCollision(
                    output_store_id=entry.output_store_id,
                    assigned_token=entry.assigned_token,
                    product_name=entry.generated_product_name,
                )
            )
        return tuple(collisions)

    def upsert(self, entry: ProductTokenEntry) -> ProductTokenRegistry:
        updated_entries = []
        replaced = False
        identity = SourceProductIdentity(
            source_key=entry.source_key,
            source_store_id=entry.source_store_id,
            source_product_token=entry.source_product_token,
            source_product_name=entry.source_product_name,
        )
        for existing in self.entries:
            if existing.matches(
                source_identity=identity,
                output_store_id=entry.output_store_id,
                workflow_label=entry.workflow_label,
            ):
                updated_entries.append(
                    ProductTokenEntry(
                        source_key=entry.source_key,
                        source_store_id=entry.source_store_id,
                        source_product_token=entry.source_product_token,
                        source_product_name=entry.source_product_name,
                        workflow_label=entry.workflow_label,
                        output_store_id=entry.output_store_id,
                        generated_product_name=entry.generated_product_name,
                        assigned_token=entry.assigned_token,
                        token_source=entry.token_source,
                        created_at=existing.created_at,
                        updated_at=_refreshed_timestamp(existing.updated_at),
                    )
                )
                replaced = True
            else:
                updated_entries.append(existing)
        if not replaced:
            updated_entries.append(entry)
        return ProductTokenRegistry(entries=tuple(updated_entries))

    def to_dict(self) -> dict[str, Any]:
        entries = sorted(
            (asdict(entry) for entry in self.entries),
            key=lambda item: (
                item["output_store_id"],
                _normalize_token(item["assigned_token"]),
                item["source_key"],
                item["workflow_label"],
            ),
        )
        return {"entries": entries}


def load_product_token_registry(registry_path: str | Path) -> ProductTokenRegistry:
    path = Path(registry_path)
    if not path.exists():
        return ProductTokenRegistry()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProductTokenRegistryError(f"Invalid product token registry JSON: {path}") from exc

    if not isinstance(data, dict):
        raise ProductTokenRegistryError(f"Invalid product token registry shape: {path}")

    raw_entries = data.get("entries", [])
    if not isinstance(raw_entries, list):
        raise ProductTokenRegistryError(f"Invalid product token registry shape: {path}")

    entries = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            raise ProductTokenRegistryError(f"Invalid product token registry shape: {path}")
        try:
            loaded_entry = ProductTokenEntry(**entry)
            _validate_entry_field_types(loaded_entry)
            entries.append(loaded_entry)
        except (TypeError, ValueError) as exc:
            raise ProductTokenRegistryError(f"Invalid product token registry shape: {path}") from exc
    return ProductTokenRegistry(entries=tuple(entries))


def save_product_token_registry(registry_path: str | Path, registry: ProductTokenRegistry) -> None:
    path = Path(registry_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(registry.to_dict(), indent=2, sort_keys=True)
    path.write_text(f"{content}\n", encoding="utf-8")


def resolve_product_token(
    registry_path: str | Path,
    *,
    source_identity: SourceProductIdentity,
    workflow_label: str,
    output_store_id: str,
    generated_product_name: str,
    next_product_number: int,
) -> TokenAssignment:
    registry = load_product_token_registry(registry_path)
    existing = registry.find(
        source_identity=source_identity,
        output_store_id=output_store_id,
        workflow_label=workflow_label,
    )

    if existing is not None and existing.token_source == "manual":
        return TokenAssignment(token=existing.assigned_token, token_source="manual", is_new_generated=False)

    if source_identity.source_product_token:
        return TokenAssignment(
            token=source_identity.source_product_token,
            token_source="source",
            is_new_generated=False,
        )

    if existing is not None:
        return TokenAssignment(
            token=existing.assigned_token,
            token_source=existing.token_source,
            is_new_generated=False,
        )

    return TokenAssignment(
        token=str(next_product_number),
        token_source="generated",
        is_new_generated=True,
    )


def source_identity_from_path(source: Path) -> SourceProductIdentity:
    path = Path(source)
    try:
        scan = scan_source(path)
    except (SourceScanError, OSError, BadZipFile, LargeZipFile):
        scan = None

    if scan is not None:
        for source_file in scan.files:
            content_path = source_file.content_path.replace("\\", "/")
            if not _is_support_metadata_path(content_path):
                continue
            try:
                metadata = parse_support_metadata(read_source_file(scan, source_file))
            except (OSError, BadZipFile, LargeZipFile, SupportParseError):
                continue
            normalized_token = _normalize_token(metadata.product_token)
            normalized_store = _normalize_identity_part(metadata.store_id)
            normalized_name = _normalize_identity_part(metadata.product_name)
            if (normalized_store and normalized_token) or normalized_name:
                return SourceProductIdentity(
                    source_key=_support_source_key(
                        normalized_store=normalized_store,
                        normalized_token=normalized_token,
                        normalized_name=normalized_name,
                    ),
                    source_store_id=metadata.store_id,
                    source_product_token=normalized_token,
                    source_product_name=metadata.product_name,
                )

    fallback_name = path.stem if path.is_file() and path.suffix.lower() == ".zip" else path.name
    return SourceProductIdentity(
        source_key=f"path:{_normalize_identity_part(fallback_name)}",
        source_product_name=fallback_name,
    )


def record_product_token_build(
    registry_path: str | Path,
    *,
    source_identity: SourceProductIdentity,
    workflow_label: str,
    output_store_id: str,
    generated_product_name: str,
    assigned_token: str,
    token_source: str,
) -> None:
    registry = load_product_token_registry(registry_path)
    entry = ProductTokenEntry.from_identity(
        source_identity,
        workflow_label=workflow_label,
        output_store_id=output_store_id,
        generated_product_name=generated_product_name,
        assigned_token=assigned_token,
        token_source=token_source,
    )
    save_product_token_registry(registry_path, registry.upsert(entry))


def _normalize_token(token: str) -> str:
    digits = re.sub(r"\D", "", token)
    return digits.lstrip("0") or ("0" if digits else "")


def _normalize_identity_part(value: str) -> str:
    normalized = value.replace("_", " ")
    return re.sub(r"\s+", " ", normalized).strip().lower()


def _is_support_metadata_path(content_path: str) -> bool:
    parts = content_path.split("/")
    return (
        len(parts) == 3
        and parts[0].lower() == "runtime"
        and parts[1].lower() == "support"
        and parts[2].lower().endswith(".dsx")
    )


def _support_source_key(*, normalized_store: str, normalized_token: str, normalized_name: str) -> str:
    if normalized_store and normalized_token:
        return f"support:{normalized_store}:{normalized_token}"
    return f"support:{normalized_store}:{normalized_token}:{normalized_name}"


def _validate_entry_field_types(entry: ProductTokenEntry) -> None:
    for field_name in ProductTokenEntry.__dataclass_fields__:
        if not isinstance(getattr(entry, field_name), str):
            raise ValueError(f"{field_name} must be a string")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _refreshed_timestamp(previous: str) -> str:
    timestamp = _utc_timestamp()
    while timestamp == previous:
        timestamp = _utc_timestamp()
    return timestamp
