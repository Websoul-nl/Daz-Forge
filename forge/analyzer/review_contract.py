from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote

from forge.analyzer.inference import AssetSuggestion, InferenceResult
from forge.analyzer.inventory import InventoryResult
from forge.analyzer.model_provider import ModelAssetSuggestion, ModelSuggestionResult
from forge.analyzer.source import SourceScan, read_source_file
from forge.analyzer.support import SupportAssetHint, SupportParseError, parse_support_metadata


@dataclass(frozen=True)
class ProductReviewSummary:
    source_path: str
    source_kind: str
    content_root: str
    product_name: str
    product_type: str
    primary_artist: str
    artist_state: str
    artists: tuple[str, ...]
    total_files: int
    smart_content_count: int
    documentation_count: int
    thumbnail_count: int
    ignored_count: int
    model_provider: str = ""
    model_available: bool = False
    store_display_name: str = ""
    store_id: str = ""
    store_code: str = ""
    product_token: str = ""
    global_id: str = ""


@dataclass(frozen=True)
class MetadataFields:
    content_type: str = ""
    categories: tuple[str, ...] = ()
    compatibility_base: str = ""
    compatibilities: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class FinalMetadataFields:
    content_type: str
    categories: tuple[str, ...]
    compatibility_base: str = ""
    compatibilities: tuple[str, ...] = ()
    editable: bool = True


@dataclass(frozen=True)
class ReviewAssetRow:
    path: str
    file_name: str
    extension: str
    author: str
    asset_type: str
    deterministic: MetadataFields
    model: MetadataFields | None
    support: MetadataFields | None
    final: FinalMetadataFields
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewIssue:
    code: str
    message: str
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestructurePlan:
    enabled: bool = False
    moves: tuple[Any, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewGridContract:
    schema_version: int
    product: ProductReviewSummary
    rows: tuple[ReviewAssetRow, ...]
    warnings: tuple[ReviewIssue, ...]
    hard_blockers: tuple[ReviewIssue, ...]
    restructure_plan: RestructurePlan


def build_review_contract(
    scan: SourceScan,
    inventory: InventoryResult,
    inference: InferenceResult,
    model_result: ModelSuggestionResult | None = None,
) -> ReviewGridContract:
    model_by_path = _model_suggestions_by_path(model_result)
    support_by_path = _support_hints_by_path(scan)
    rows = tuple(
        _build_asset_row(asset, model_by_path.get(asset.path), support_by_path.get(asset.path))
        for asset in inference.assets
    )
    return ReviewGridContract(
        schema_version=1,
        product=_build_product_summary(scan, inventory, inference, model_result),
        rows=rows,
        warnings=_build_warnings(inventory, inference, model_result),
        hard_blockers=_build_hard_blockers(scan),
        restructure_plan=RestructurePlan(),
    )


def contract_to_dict(contract: ReviewGridContract) -> dict[str, Any]:
    return _json_value(asdict(contract))


def _build_product_summary(
    scan: SourceScan,
    inventory: InventoryResult,
    inference: InferenceResult,
    model_result: ModelSuggestionResult | None,
) -> ProductReviewSummary:
    support_product = _support_product_metadata(scan)
    artists = support_product.artists if support_product is not None and support_product.artists else inference.product.artists
    primary_artist = artists[0] if artists else inference.product.primary_artist
    return ProductReviewSummary(
        source_path=scan.source_path,
        source_kind=scan.source_kind,
        content_root=scan.content_root,
        product_name=support_product.product_name if support_product is not None and support_product.product_name else _source_product_name(scan),
        product_type=inference.product.product_type,
        primary_artist=primary_artist,
        artist_state=inference.product.artist_state,
        artists=artists,
        total_files=len(scan.files),
        smart_content_count=len(inventory.smart_content),
        documentation_count=len(inventory.documentation),
        thumbnail_count=len(inventory.thumbnails),
        ignored_count=len(inventory.ignored),
        model_provider=model_result.provider if model_result is not None else "",
        model_available=model_result.available if model_result is not None else False,
        store_id=support_product.store_id if support_product is not None else "",
        store_code=support_product.store_id if support_product is not None else "",
        product_token=support_product.product_token if support_product is not None else "",
        global_id=support_product.global_id if support_product is not None else "",
    )


def _source_product_name(scan: SourceScan) -> str:
    path = PurePosixPath(scan.source_path.replace("\\", "/"))
    return path.stem or path.name


def _support_product_metadata(scan: SourceScan):
    for source_file in scan.files:
        path = PurePosixPath(source_file.content_path)
        if len(path.parts) < 3 or path.parts[0].lower() != "runtime" or path.parts[1].lower() != "support":
            continue
        if path.suffix.lower() != ".dsx":
            continue
        try:
            return parse_support_metadata(read_source_file(scan, source_file))
        except SupportParseError:
            continue
    return None


def _build_asset_row(
    asset: AssetSuggestion,
    model: ModelAssetSuggestion | None,
    support: SupportAssetHint | None,
) -> ReviewAssetRow:
    deterministic = MetadataFields(
        content_type=asset.content_type,
        categories=asset.categories,
        compatibility_base=asset.compatibility_base,
        compatibilities=asset.compatibilities,
        confidence=asset.confidence,
        reason="deterministic analyzer",
    )
    final = FinalMetadataFields(
        content_type=asset.content_type,
        categories=asset.categories,
        compatibility_base=asset.compatibility_base,
        compatibilities=asset.compatibilities,
    )
    return ReviewAssetRow(
        path=asset.path,
        file_name=PurePosixPath(asset.path).name,
        extension=PurePosixPath(asset.path).suffix.lower(),
        author=asset.author,
        asset_type=asset.asset_type,
        deterministic=deterministic,
        model=_model_fields(model),
        support=_support_fields(support),
        final=final,
        warnings=asset.warnings,
    )


def _model_fields(model: ModelAssetSuggestion | None) -> MetadataFields | None:
    if model is None:
        return None
    return MetadataFields(
        content_type=model.content_type,
        categories=model.categories,
        compatibility_base=model.compatibility_base,
        compatibilities=model.compatibilities,
        confidence=model.confidence,
        reason=model.reason,
    )


def _support_fields(support: SupportAssetHint | None) -> MetadataFields | None:
    if support is None:
        return None
    return MetadataFields(
        content_type=support.content_type,
        categories=support.categories,
        compatibility_base=support.compatibility_base,
        compatibilities=support.compatibilities,
        confidence=1.0,
        reason="existing support file",
    )


def _build_warnings(
    inventory: InventoryResult,
    inference: InferenceResult,
    model_result: ModelSuggestionResult | None,
) -> tuple[ReviewIssue, ...]:
    issues = [
        ReviewIssue(code="inventory-warning", message=warning)
        for warning in inventory.warnings
    ]
    issues.extend(ReviewIssue(code="inference-warning", message=warning) for warning in inference.warnings)
    if model_result is not None:
        issues.extend(ReviewIssue(code="model-warning", message=warning) for warning in model_result.warnings)
    return tuple(issues)


def _build_hard_blockers(scan: SourceScan) -> tuple[ReviewIssue, ...]:
    issues = [
        ReviewIssue(
            code="duplicate-content-path",
            message=f"Duplicate normalized content path: {duplicate.normalized_key}",
            paths=duplicate.content_paths,
        )
        for duplicate in scan.duplicates
    ]
    issues.extend(ReviewIssue(code="source-hard-error", message=message) for message in scan.hard_errors)
    return tuple(issues)


def _model_suggestions_by_path(model_result: ModelSuggestionResult | None) -> dict[str, ModelAssetSuggestion]:
    if model_result is None:
        return {}
    return {suggestion.path: suggestion for suggestion in model_result.suggestions}


def _support_hints_by_path(scan: SourceScan) -> dict[str, SupportAssetHint]:
    hints: dict[str, SupportAssetHint] = {}
    for source_file in scan.files:
        path = PurePosixPath(source_file.content_path)
        if len(path.parts) < 3 or path.parts[0].lower() != "runtime" or path.parts[1].lower() != "support":
            continue
        if path.suffix.lower() != ".dsx":
            continue
        try:
            support = parse_support_metadata(read_source_file(scan, source_file))
        except SupportParseError:
            continue
        for hint in support.assets:
            normalized = _normalize_support_path(hint.path)
            if normalized:
                hints[normalized] = hint
    return hints


def _normalize_support_path(path: str) -> str:
    normalized = unquote(path.replace("\\", "/")).lstrip("/")
    if not normalized:
        return ""
    return PurePosixPath(normalized).as_posix()


def _json_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value
