# Product Token Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add shared product-token assignment for the DIM Packager and Pose Converter, preferring source Smart Content tokens and using a local registry only for generated tokens, manual overrides, and same-store collision warnings.

**Architecture:** Create a focused `forge.product_tokens` service that owns registry JSON parsing, source identity, assignment, recording, counter updates, and collision checks. Keep UI code responsible only for asking the service for an assignment, displaying the token, and recording a successful build. Store-scoped uniqueness uses `output_store_id + assigned_token`, while source/workflow identity uses `source identity + output_store_id + workflow`.

**Tech Stack:** Python dataclasses, JSON files under `config/`, existing `forge.analyzer.support.parse_support_metadata`, existing PySide6 UI fields, pytest.

---

## File Structure

- Create `forge/product_tokens.py`: registry dataclasses, JSON load/save, source identity extraction, token assignment, collision checks, successful-build recording.
- Modify `forge/ui/main_window.py`: inject a registry path, call token assignment for both tabs, refresh token on source/store/preset changes, record successful builds, show same-store collision messages.
- Modify `forge/settings.py` only if a tiny helper for incrementing `next_product_number` keeps UI code cleaner; otherwise keep settings writes in `main_window.py`.
- Modify `.gitignore`: add `config/product-tokens.json`.
- Modify `docs/user-manual.md`: explain source-token reuse and local registry behavior.
- Add `tests/test_product_tokens.py`: pure unit coverage for registry behavior.
- Modify `tests/test_ui_review.py`: integration coverage for DIM Packager and Pose Converter token autofill/build recording.

## Task 1: Product Token Registry Core

**Files:**
- Create: `forge/product_tokens.py`
- Test: `tests/test_product_tokens.py`

- [ ] **Step 1: Write failing registry tests**

Add `tests/test_product_tokens.py`:

```python
import json
from pathlib import Path

import pytest

from forge.product_tokens import (
    ProductTokenRegistryError,
    SourceProductIdentity,
    TokenAssignment,
    TokenCollision,
    load_product_token_registry,
    resolve_product_token,
    record_product_token_build,
)


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
        source_identity=identity("Second"),
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_product_tokens.py -q
```

Expected: FAIL during import because `forge.product_tokens` does not exist.

- [ ] **Step 3: Implement registry service**

Create `forge/product_tokens.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


class ProductTokenRegistryError(ValueError):
    """Raised when the product token registry cannot be read or written."""


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
    output_store_id: str
    workflow_label: str
    generated_product_name: str
    assigned_token: str
    token_source: str
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ProductTokenEntry":
        return cls(
            source_key=str(raw.get("source_key", "")),
            source_store_id=str(raw.get("source_store_id", "")),
            source_product_token=str(raw.get("source_product_token", "")),
            source_product_name=str(raw.get("source_product_name", "")),
            output_store_id=str(raw.get("output_store_id", "")),
            workflow_label=str(raw.get("workflow_label", "")),
            generated_product_name=str(raw.get("generated_product_name", "")),
            assigned_token=str(raw.get("assigned_token", "")),
            token_source=str(raw.get("token_source", "")),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "assigned_token": self.assigned_token,
            "created_at": self.created_at,
            "generated_product_name": self.generated_product_name,
            "output_store_id": self.output_store_id,
            "source_key": self.source_key,
            "source_product_name": self.source_product_name,
            "source_product_token": self.source_product_token,
            "source_store_id": self.source_store_id,
            "token_source": self.token_source,
            "updated_at": self.updated_at,
            "workflow_label": self.workflow_label,
        }


class ProductTokenRegistry:
    def __init__(self, entries: tuple[ProductTokenEntry, ...] = ()) -> None:
        self.entries = entries

    def find(self, source_identity: SourceProductIdentity, output_store_id: str, workflow_label: str) -> ProductTokenEntry | None:
        key = _entry_key(source_identity, output_store_id, workflow_label)
        for entry in self.entries:
            if (entry.source_key, _store_key(entry.output_store_id), entry.workflow_label) == key:
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
        current_key = _entry_key(source_identity, output_store_id, workflow_label)
        collisions: list[TokenCollision] = []
        for entry in self.entries:
            if _store_key(entry.output_store_id) != _store_key(output_store_id):
                continue
            if _token_key(entry.assigned_token) != _token_key(assigned_token):
                continue
            entry_key = (entry.source_key, _store_key(entry.output_store_id), entry.workflow_label)
            if entry_key == current_key:
                continue
            collisions.append(
                TokenCollision(
                    output_store_id=entry.output_store_id,
                    assigned_token=entry.assigned_token,
                    product_name=entry.generated_product_name or entry.source_product_name,
                )
            )
        return tuple(collisions)

    def upsert(
        self,
        *,
        source_identity: SourceProductIdentity,
        workflow_label: str,
        output_store_id: str,
        generated_product_name: str,
        assigned_token: str,
        token_source: str,
    ) -> "ProductTokenRegistry":
        now = _utc_now()
        replacement = ProductTokenEntry(
            source_key=source_identity.source_key,
            source_store_id=source_identity.source_store_id,
            source_product_token=source_identity.source_product_token,
            source_product_name=source_identity.source_product_name,
            output_store_id=output_store_id,
            workflow_label=workflow_label,
            generated_product_name=generated_product_name,
            assigned_token=assigned_token,
            token_source=token_source,
            created_at=now,
            updated_at=now,
        )
        key = _entry_key(source_identity, output_store_id, workflow_label)
        entries = []
        replaced = False
        for entry in self.entries:
            if (entry.source_key, _store_key(entry.output_store_id), entry.workflow_label) == key:
                replacement = ProductTokenEntry(**{**replacement.to_dict(), "created_at": entry.created_at, "updated_at": now})
                entries.append(replacement)
                replaced = True
            else:
                entries.append(entry)
        if not replaced:
            entries.append(replacement)
        return ProductTokenRegistry(tuple(entries))

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [entry.to_dict() for entry in self.entries]}


def load_product_token_registry(path: Path) -> ProductTokenRegistry:
    if not path.exists():
        return ProductTokenRegistry()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProductTokenRegistryError(f"Invalid product token registry JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise ProductTokenRegistryError(f"Product token registry must contain a JSON object: {path}")
    raw_entries = raw.get("entries", [])
    if not isinstance(raw_entries, list):
        raise ProductTokenRegistryError(f"Product token registry entries must be a list: {path}")
    return ProductTokenRegistry(tuple(ProductTokenEntry.from_dict(item) for item in raw_entries if isinstance(item, dict)))


def save_product_token_registry(path: Path, registry: ProductTokenRegistry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_product_token(
    registry_path: Path,
    *,
    source_identity: SourceProductIdentity,
    workflow_label: str,
    output_store_id: str,
    generated_product_name: str,
    next_product_number: int,
) -> TokenAssignment:
    registry = load_product_token_registry(registry_path)
    entry = registry.find(source_identity, output_store_id, workflow_label)
    if entry is not None and entry.token_source == "manual":
        return TokenAssignment(entry.assigned_token, "manual", False)
    if source_identity.source_product_token:
        return TokenAssignment(source_identity.source_product_token, "source", False)
    if entry is not None and entry.assigned_token:
        return TokenAssignment(entry.assigned_token, entry.token_source or "generated", False)
    return TokenAssignment(str(next_product_number), "generated", True)


def record_product_token_build(
    registry_path: Path,
    *,
    source_identity: SourceProductIdentity,
    workflow_label: str,
    output_store_id: str,
    generated_product_name: str,
    assigned_token: str,
    token_source: str,
) -> None:
    registry = load_product_token_registry(registry_path)
    registry = registry.upsert(
        source_identity=source_identity,
        workflow_label=workflow_label,
        output_store_id=output_store_id,
        generated_product_name=generated_product_name,
        assigned_token=assigned_token,
        token_source=token_source,
    )
    save_product_token_registry(registry_path, registry)


def _entry_key(source_identity: SourceProductIdentity, output_store_id: str, workflow_label: str) -> tuple[str, str, str]:
    return (source_identity.source_key, _store_key(output_store_id), workflow_label)


def _store_key(value: str) -> str:
    return value.strip().lower()


def _token_key(value: str) -> str:
    digits = "".join(character for character in str(value) if character.isdigit())
    return digits.lstrip("0") or digits


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
```

- [ ] **Step 4: Run registry tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_product_tokens.py -q
```

Expected: PASS.

## Task 2: Source Identity Extraction And Ignore Rule

**Files:**
- Modify: `forge/product_tokens.py`
- Modify: `.gitignore`
- Test: `tests/test_product_tokens.py`

- [ ] **Step 1: Add failing source identity tests**

Append to `tests/test_product_tokens.py`:

```python
from zipfile import ZipFile

from forge.product_tokens import source_identity_from_path


def test_source_identity_reads_support_metadata_from_zip(tmp_path: Path) -> None:
    zip_path = tmp_path / "IM00083577-01_HeroProduct.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "Content/Runtime/Support/DAZ_3D_83577_Hero_Product.dsx",
            b'''<?xml version="1.0" encoding="utf-8"?>
<ContentDBInstall VERSION="1.0">
  <Products>
    <Product VALUE="Hero Product">
      <StoreID VALUE="DAZ 3D"/>
      <ProductToken VALUE="83577"/>
    </Product>
  </Products>
</ContentDBInstall>''',
        )

    result = source_identity_from_path(zip_path)

    assert result.source_key == "support:daz 3d:83577:hero product"
    assert result.source_store_id == "DAZ 3D"
    assert result.source_product_token == "83577"
    assert result.source_product_name == "Hero Product"


def test_source_identity_falls_back_to_normalized_path_name(tmp_path: Path) -> None:
    source = tmp_path / "Loose Product"
    source.mkdir()

    result = source_identity_from_path(source)

    assert result.source_key == "path:loose product"
    assert result.source_product_name == "Loose Product"
    assert result.source_product_token == ""
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_product_tokens.py::test_source_identity_reads_support_metadata_from_zip tests\test_product_tokens.py::test_source_identity_falls_back_to_normalized_path_name -q
```

Expected: FAIL because `source_identity_from_path` is missing.

- [ ] **Step 3: Implement source identity extraction and ignore file**

Add imports and function to `forge/product_tokens.py`:

```python
from pathlib import PurePosixPath

from forge.analyzer.source import read_source_file, scan_source
from forge.analyzer.support import SupportParseError, parse_support_metadata


def source_identity_from_path(source: Path) -> SourceProductIdentity:
    try:
        scan = scan_source(source)
    except Exception:
        return _fallback_source_identity(source)
    for source_file in sorted(scan.files, key=lambda item: item.content_path.lower()):
        path = PurePosixPath(source_file.content_path)
        if len(path.parts) < 3 or path.parts[0].lower() != "runtime" or path.parts[1].lower() != "support":
            continue
        if path.suffix.lower() != ".dsx":
            continue
        try:
            metadata = parse_support_metadata(read_source_file(scan, source_file))
        except (OSError, SupportParseError):
            continue
        if metadata.product_name or metadata.product_token or metadata.store_id:
            return SourceProductIdentity(
                source_key=f"support:{_store_key(metadata.store_id)}:{_token_key(metadata.product_token)}:{_name_key(metadata.product_name)}",
                source_store_id=metadata.store_id,
                source_product_token=_token_key(metadata.product_token),
                source_product_name=metadata.product_name,
            )
    return _fallback_source_identity(source)


def _fallback_source_identity(source: Path) -> SourceProductIdentity:
    name = source.stem if source.suffix.lower() == ".zip" else source.name
    return SourceProductIdentity(source_key=f"path:{_name_key(name)}", source_product_name=name)


def _name_key(value: str) -> str:
    return " ".join(str(value).replace("_", " ").split()).strip().lower()
```

Add to `.gitignore`:

```text
config/product-tokens.json
```

- [ ] **Step 4: Run registry tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_product_tokens.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit core registry**

Run:

```powershell
git add .gitignore forge/product_tokens.py tests/test_product_tokens.py
git commit -m "feat: add product token registry"
```

Expected: Commit contains only the registry service, tests, and ignore rule.

## Task 3: DIM Packager Integration

**Files:**
- Modify: `forge/ui/main_window.py`
- Test: `tests/test_ui_review.py`

- [ ] **Step 1: Add failing DIM Packager UI tests**

Append to `tests/test_ui_review.py`:

```python
def test_dim_packager_reuses_source_token_and_logs_build(qapp, tmp_path: Path) -> None:
    source = tmp_path / "IM00083577-01_HeroProduct.zip"
    _write_zip(
        source,
        {
            "Content/Runtime/Support/DAZ_3D_83577_Hero_Product.dsx": b'''<?xml version="1.0" encoding="utf-8"?>
<ContentDBInstall VERSION="1.0">
  <Products>
    <Product VALUE="Hero Product">
      <StoreID VALUE="DAZ 3D"/>
      <ProductToken VALUE="83577"/>
    </Product>
  </Products>
</ContentDBInstall>''',
            "Content/Props/Hero.duf": b"{}",
        },
    )
    settings_path = tmp_path / "settings.json"
    registry_path = tmp_path / "product-tokens.json"
    window = MainWindow(
        app_settings=AppSettings(next_product_number=90000000),
        settings_path=settings_path,
        token_registry_path=registry_path,
        run_analysis_synchronously=True,
    )

    window.set_source_path(source)
    window.analyze_current_source()
    window.store_combo.setCurrentText("LOCAL USER")
    window.build_current_package()

    assert window.token_edit.text() == "83577"
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    assert raw["entries"][0]["output_store_id"] == "LOCAL USER"
    assert raw["entries"][0]["assigned_token"] == "83577"
    assert raw["entries"][0]["token_source"] == "source"


def test_dim_packager_warns_for_same_store_token_collision(qapp, tmp_path: Path) -> None:
    registry_path = tmp_path / "product-tokens.json"
    record_product_token_build(
        registry_path,
        source_identity=SourceProductIdentity("path:first", source_product_name="First"),
        workflow_label="DIM Packager",
        output_store_id="LOCAL USER",
        generated_product_name="First",
        assigned_token="90000000",
        token_source="generated",
    )
    source = tmp_path / "Second"
    source.mkdir()
    write_file(source / "Props" / "Second.duf")
    window = MainWindow(
        app_settings=AppSettings(next_product_number=90000000),
        token_registry_path=registry_path,
        run_analysis_synchronously=True,
    )

    window.set_source_path(source)
    window.analyze_current_source()
    window.store_combo.setCurrentText("LOCAL USER")
    window.build_current_package()

    assert "Product token already used in LOCAL USER by First" in window.issue_text()
```

Add imports near the top of `tests/test_ui_review.py`:

```python
import json
from forge.product_tokens import SourceProductIdentity, record_product_token_build
```

- [ ] **Step 2: Run focused UI tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_review.py::test_dim_packager_reuses_source_token_and_logs_build tests\test_ui_review.py::test_dim_packager_warns_for_same_store_token_collision -q
```

Expected: FAIL because `MainWindow` does not accept `token_registry_path` and does not resolve tokens through the registry.

- [ ] **Step 3: Wire DIM Packager token assignment**

In `forge/ui/main_window.py`, import:

```python
from forge.product_tokens import (
    ProductTokenRegistryError,
    load_product_token_registry,
    record_product_token_build,
    resolve_product_token,
    source_identity_from_path,
)
```

Update `MainWindow.__init__` signature:

```python
token_registry_path: Path | None = None,
```

Set:

```python
self.token_registry_path = token_registry_path or _default_token_registry_path()
```

Add helper methods:

```python
def _dim_workflow_label(self) -> str:
    return "DIM Packager"


def _refresh_dim_token_assignment(self) -> None:
    product = self.current_contract.get("product", {})
    source_path = str(product.get("source_path") or self.source_edit.text().strip())
    if not source_path:
        return
    output_store_id = str(product.get("store_id") or self.store_combo.currentText().strip())
    try:
        assignment = resolve_product_token(
            self.token_registry_path,
            source_identity=source_identity_from_path(Path(source_path)),
            workflow_label=self._dim_workflow_label(),
            output_store_id=output_store_id,
            generated_product_name=str(product.get("product_name") or self.product_name_edit.text().strip()),
            next_product_number=self.app_settings.next_product_number,
        )
    except ProductTokenRegistryError as exc:
        self._set_issue_lines([str(exc)])
        return
    product["product_token"] = assignment.token
    product["_token_source"] = assignment.token_source
    product["_token_is_new_generated"] = assignment.is_new_generated
```

Call `_refresh_dim_token_assignment()` at the end of `_ensure_product_metadata()` after store fields are known, replacing the old unconditional fallback:

```python
if not product.get("product_token"):
    product["product_token"] = str(self.app_settings.next_product_number)
self._refresh_dim_token_assignment()
```

In `_store_changed`, call `_refresh_dim_token_assignment()` before `_product_metadata_changed()` or update `_product_metadata_changed()` to call it after store changes when the token was not manually edited.

Add helpers:

```python
def _dim_token_collisions(self, source: Path) -> tuple[str, ...]:
    product = self.current_contract.get("product", {})
    token = self.token_edit.text().strip()
    if not token:
        return ()
    registry = load_product_token_registry(self.token_registry_path)
    collisions = registry.collisions_for(
        output_store_id=str(product.get("store_id") or self.store_combo.currentText().strip()),
        assigned_token=token,
        source_identity=source_identity_from_path(source),
        workflow_label=self._dim_workflow_label(),
    )
    return tuple(f"Product token already used in {collision.output_store_id} by {collision.product_name}" for collision in collisions)


def _record_dim_token_build(self, source: Path) -> None:
    product = self.current_contract.get("product", {})
    source_token = source_identity_from_path(source).source_product_token
    token = self.token_edit.text().strip()
    token_source = "manual"
    if token == source_token and source_token:
        token_source = "source"
    elif product.get("_token_source") == "generated":
        token_source = "generated"
    record_product_token_build(
        self.token_registry_path,
        source_identity=source_identity_from_path(source),
        workflow_label=self._dim_workflow_label(),
        output_store_id=str(product.get("store_id") or self.store_combo.currentText().strip()),
        generated_product_name=self.product_name_edit.text().strip(),
        assigned_token=token,
        token_source=token_source,
    )
    if product.get("_token_is_new_generated") and token == str(self.app_settings.next_product_number):
        self._save_next_product_number(self.app_settings.next_product_number + 1)
```

In `build_current_package`, before `build_dim_package`, check collisions:

```python
collisions = self._dim_token_collisions(Path(source_text))
if collisions:
    self._set_issue_lines(list(collisions))
    return
```

After successful `build_dim_package`, call:

```python
self._record_dim_token_build(Path(source_text))
```

Add:

```python
def _save_next_product_number(self, value: int) -> None:
    self.app_settings = AppSettings(
        default_store=self.app_settings.default_store,
        next_product_number=value,
        lm_studio_base_url=self.app_settings.lm_studio_base_url,
        ollama_base_url=self.app_settings.ollama_base_url,
        default_output_folder=self.app_settings.default_output_folder,
        default_staging_folder=self.app_settings.default_staging_folder,
        default_daz_library=self.app_settings.default_daz_library,
        dim_downloads_folder=self.app_settings.dim_downloads_folder,
        preserve_staging=self.app_settings.preserve_staging,
    )
    save_settings(self.settings_path, self.app_settings)
```

Add module helper:

```python
def _default_token_registry_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "product-tokens.json"
```

- [ ] **Step 4: Run focused DIM tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_review.py::test_dim_packager_reuses_source_token_and_logs_build tests\test_ui_review.py::test_dim_packager_warns_for_same_store_token_collision -q
```

Expected: PASS.

## Task 4: Pose Converter Integration

**Files:**
- Modify: `forge/ui/main_window.py`
- Test: `tests/test_ui_review.py`

- [ ] **Step 1: Add failing Pose Converter registry tests**

Append to `tests/test_ui_review.py`:

```python
def test_pose_converter_reuses_source_token_for_selected_store(qapp, tmp_path: Path) -> None:
    source = tmp_path / "IM00112833-01_FNTitanMkActionPoseforGenesis9.zip"
    _write_zip(
        source,
        {
            "Content/Runtime/Support/DAZ_3D_112833_FN_Titan.dsx": b'''<?xml version="1.0" encoding="utf-8"?>
<ContentDBInstall VERSION="1.0">
  <Products>
    <Product VALUE="FN Titan Mk Action Pose for Genesis 9">
      <StoreID VALUE="DAZ 3D"/>
      <ProductToken VALUE="112833"/>
    </Product>
  </Products>
</ContentDBInstall>''',
            "Content/People/Genesis 9/Poses/FN Titan/Pose.duf": b"{}",
        },
    )
    window = MainWindow(app_settings=AppSettings(next_product_number=90000000), token_registry_path=tmp_path / "tokens.json")

    window.set_pose_source_path(source)
    window.pose_store_combo.setCurrentText("LOCAL USER")

    assert window.pose_token_edit.text() == "112833"


def test_pose_converter_generates_separate_tokens_for_presets_without_source_token(qapp, tmp_path: Path) -> None:
    source = tmp_path / "Loose Poses"
    source.mkdir()
    write_file(source / "People" / "Genesis 9" / "Poses" / "Loose" / "Pose.duf", "{}")
    registry_path = tmp_path / "tokens.json"
    window = MainWindow(app_settings=AppSettings(next_product_number=90000000), settings_path=tmp_path / "settings.json", token_registry_path=registry_path)

    window.set_pose_source_path(source)
    window.pose_preset_combo.setCurrentText("Genesis 9 -> Genesis 8 Female")
    female_token = window.pose_token_edit.text()
    record_product_token_build(
        registry_path,
        source_identity=source_identity_from_path(source),
        workflow_label="Genesis 9 -> Genesis 8 Female",
        output_store_id="LOCAL USER",
        generated_product_name=window.pose_product_name_edit.text(),
        assigned_token=female_token,
        token_source="generated",
    )
    window.app_settings = AppSettings(next_product_number=90000001)

    window.pose_preset_combo.setCurrentText("Genesis 9 -> Genesis 8 Male")

    assert female_token == "90000000"
    assert window.pose_token_edit.text() == "90000001"
```

Add import:

```python
from forge.product_tokens import source_identity_from_path
```

- [ ] **Step 2: Run focused tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_review.py::test_pose_converter_reuses_source_token_for_selected_store tests\test_ui_review.py::test_pose_converter_generates_separate_tokens_for_presets_without_source_token -q
```

Expected: FAIL because pose source/preset changes do not resolve through registry.

- [ ] **Step 3: Wire Pose Converter token assignment and recording**

In `forge/ui/main_window.py`, update `set_pose_source_path` to call `_refresh_pose_token_assignment()` after setting product name.

Add:

```python
def _pose_workflow_label(self) -> str:
    return self._selected_pose_preset().label


def _refresh_pose_token_assignment(self) -> None:
    source_text = self.pose_source_edit.text().strip()
    if not source_text:
        return
    output_store_id = self._pose_package_metadata()["store_id"]
    try:
        assignment = resolve_product_token(
            self.token_registry_path,
            source_identity=source_identity_from_path(Path(source_text)),
            workflow_label=self._pose_workflow_label(),
            output_store_id=output_store_id,
            generated_product_name=self.pose_product_name_edit.text().strip(),
            next_product_number=self.app_settings.next_product_number,
        )
    except ProductTokenRegistryError as exc:
        self._set_pose_status(str(exc))
        return
    self.pose_token_edit.setText(assignment.token)
    self._pose_token_source = assignment.token_source
    self._pose_token_is_new_generated = assignment.is_new_generated
```

Connect:

```python
self.pose_preset_combo.currentTextChanged.connect(lambda _value: self._refresh_pose_token_assignment())
self.pose_store_combo.currentTextChanged.connect(lambda _value: self._refresh_pose_token_assignment())
```

Add:

```python
def _pose_token_collisions(self, source: Path) -> tuple[str, ...]:
    token = self.pose_token_edit.text().strip()
    if not token:
        return ()
    metadata = self._pose_package_metadata()
    registry = load_product_token_registry(self.token_registry_path)
    collisions = registry.collisions_for(
        output_store_id=str(metadata.get("store_id") or ""),
        assigned_token=token,
        source_identity=source_identity_from_path(source),
        workflow_label=self._pose_workflow_label(),
    )
    return tuple(f"Product token already used in {collision.output_store_id} by {collision.product_name}" for collision in collisions)


def _record_pose_token_build(self, source: Path) -> None:
    identity = source_identity_from_path(source)
    token = self.pose_token_edit.text().strip()
    token_source = "manual"
    if token == identity.source_product_token and identity.source_product_token:
        token_source = "source"
    elif getattr(self, "_pose_token_source", "") == "generated":
        token_source = "generated"
    record_product_token_build(
        self.token_registry_path,
        source_identity=identity,
        workflow_label=self._pose_workflow_label(),
        output_store_id=self._pose_package_metadata()["store_id"],
        generated_product_name=self.pose_product_name_edit.text().strip(),
        assigned_token=token,
        token_source=token_source,
    )
    if getattr(self, "_pose_token_is_new_generated", False) and token == str(self.app_settings.next_product_number):
        self._save_next_product_number(self.app_settings.next_product_number + 1)
```

In `build_pose_converter_package`, check collisions before the builder and record after successful build:

```python
collisions = self._pose_token_collisions(source)
if collisions:
    self._set_pose_status("\n".join(collisions))
    return
```

After success:

```python
self._record_pose_token_build(source)
```

- [ ] **Step 4: Run focused Pose Converter tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_review.py::test_pose_converter_reuses_source_token_for_selected_store tests\test_ui_review.py::test_pose_converter_generates_separate_tokens_for_presets_without_source_token -q
```

Expected: PASS.

## Task 5: Settings Counter And Regression Coverage

**Files:**
- Modify: `tests/test_ui_review.py`
- Modify: `forge/ui/main_window.py`

- [ ] **Step 1: Add failing counter regression test**

Append to `tests/test_ui_review.py`:

```python
def test_pose_converter_increments_next_number_only_for_new_generated_token(qapp, tmp_path: Path) -> None:
    source = tmp_path / "Loose Poses"
    source.mkdir()
    write_file(source / "People" / "Genesis 9" / "Poses" / "Loose" / "Pose.duf", "{}")
    settings_path = tmp_path / "settings.json"
    registry_path = tmp_path / "tokens.json"
    calls = {}

    def builder(source_path, output_path, metadata, preset):
        calls["metadata"] = metadata
        return _pose_builder_result(output_path / "package.zip")

    window = MainWindow(
        app_settings=AppSettings(next_product_number=90000000),
        settings_path=settings_path,
        token_registry_path=registry_path,
        pose_package_builder=builder,
    )

    window.set_pose_source_path(source)
    window.build_pose_converter_package()

    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert calls["metadata"]["product_token"] == "90000000"
    assert saved["next_product_number"] == 90000001
```

- [ ] **Step 2: Run counter test to verify failure or pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_ui_review.py::test_pose_converter_increments_next_number_only_for_new_generated_token -q
```

Expected before Task 4 implementation: FAIL. Expected after Task 4 implementation: PASS. If it fails after Task 4, fix `_save_next_product_number` or token-source tracking.

- [ ] **Step 3: Run all affected tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_product_tokens.py tests\test_ui_review.py tests\test_pose_converter.py tests\test_settings.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit UI integration**

Run:

```powershell
git add forge/ui/main_window.py tests/test_ui_review.py
git commit -m "feat: apply product token registry in UI"
```

Expected: Commit contains UI integration and UI tests.

## Task 6: Documentation And Final Verification

**Files:**
- Modify: `docs/user-manual.md`

- [ ] **Step 1: Update user manual**

In `docs/user-manual.md`, add a short subsection under `Settings And Defaults`:

```markdown
## Product Tokens

Daz Forge treats product identity as `Store ID + Product token`. The same token can be reused under a different store.

When source Smart Content contains a product token, Daz Forge reuses that token by default. If no source token is available, Daz Forge assigns `next_product_number`, remembers it in local `config/product-tokens.json`, and increments the next number after a successful build.

`config/product-tokens.json` is local machine state and is ignored by git, like `config/settings.json`.
```

- [ ] **Step 2: Run full test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Inspect git status**

Run:

```powershell
git status --short --ignored config/settings.json config/product-tokens.json
```

Expected:

```text
!! config/settings.json
```

If `config/product-tokens.json` exists after tests, expected also includes:

```text
!! config/product-tokens.json
```

- [ ] **Step 4: Commit documentation**

Run:

```powershell
git add docs/user-manual.md
git commit -m "docs: explain product token reuse"
```

Expected: Commit contains only the user manual change.

## Self-Review Notes

- Spec coverage: The tasks cover source Smart Content token reuse, store-scoped identity, generated local tokens, manual overrides, registry logging, same-store warnings, both UI tabs, ignored registry file, docs, and tests.
- Placeholder scan: The plan contains no placeholder tasks; every code step names concrete functions, files, commands, and expected outcomes.
- Type consistency: `SourceProductIdentity`, `TokenAssignment`, `TokenCollision`, `ProductTokenRegistry`, `resolve_product_token`, `record_product_token_build`, and `source_identity_from_path` are introduced before later tasks use them.
