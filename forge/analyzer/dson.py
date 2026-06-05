from __future__ import annotations

from dataclasses import dataclass
import gzip
import io
import json
from typing import Any
from zipfile import ZipFile, is_zipfile


class DsonParseError(ValueError):
    """Raised when DSON asset metadata cannot be parsed."""


@dataclass(frozen=True)
class DsonContributor:
    author: str = ""
    email: str = ""
    website: str = ""


@dataclass(frozen=True)
class DsonAssetInfo:
    file_version: str
    asset_id: str
    asset_type: str
    contributor: DsonContributor
    revision: str
    modified: str


def parse_dson_asset_info(data: bytes) -> DsonAssetInfo:
    raw = _decode_dson_bytes(data)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DsonParseError(f"Invalid DSON JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise DsonParseError("DSON root must be a JSON object.")

    asset_info = parsed.get("asset_info", {})
    if not isinstance(asset_info, dict):
        asset_info = {}
    contributor = asset_info.get("contributor", {})
    if not isinstance(contributor, dict):
        contributor = {}

    return DsonAssetInfo(
        file_version=str(parsed.get("file_version", "")),
        asset_id=str(asset_info.get("id", "")),
        asset_type=str(asset_info.get("type", "")),
        contributor=DsonContributor(
            author=str(contributor.get("author", "")),
            email=str(contributor.get("email", "")),
            website=str(contributor.get("website", "")),
        ),
        revision=str(asset_info.get("revision", "")),
        modified=str(asset_info.get("modified", "")),
    )


def _decode_dson_bytes(data: bytes) -> str:
    payload = _decompress_dson_bytes(data)
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DsonParseError(f"DSON data is not UTF-8: {exc}") from exc


def _decompress_dson_bytes(data: bytes) -> bytes:
    if data.startswith(b"\x1f\x8b"):
        return gzip.decompress(data)

    stream = io.BytesIO(data)
    if is_zipfile(stream):
        stream.seek(0)
        with ZipFile(stream) as archive:
            names = [info.filename for info in archive.infolist() if not info.is_dir()]
            if len(names) != 1:
                raise DsonParseError("Zip-wrapped DSON must contain exactly one file.")
            return archive.read(names[0])

    return data