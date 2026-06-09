from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
import urllib.request

from forge.analyzer.inference import InferenceResult


class ModelProviderError(ValueError):
    """Raised when a model provider returns unusable data."""


class ModelUnavailableError(ModelProviderError):
    """Raised when a model provider cannot be reached."""


class MetadataSuggestionProvider(Protocol):
    name: str

    def suggest(self, packet: dict[str, Any]) -> dict[str, Any]:
        """Return raw provider suggestions for a structured analyzer packet."""


@dataclass(frozen=True)
class ModelAssetSuggestion:
    path: str
    content_type: str = ""
    categories: tuple[str, ...] = ()
    compatibility_base: str = ""
    compatibilities: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class ModelSuggestionResult:
    provider: str
    available: bool
    suggestions: tuple[ModelAssetSuggestion, ...]
    warnings: tuple[str, ...] = ()


def build_model_packet(inference: InferenceResult) -> dict[str, Any]:
    return {
        "product": {
            "product_type": inference.product.product_type,
            "primary_artist": inference.product.primary_artist,
            "artist_state": inference.product.artist_state,
            "artists": list(inference.product.artists),
        },
        "assets": [
            {
                "path": asset.path,
                "content_type": asset.content_type,
                "categories": list(asset.categories),
                "compatibility_base": asset.compatibility_base,
                "compatibilities": list(asset.compatibilities),
                "asset_type": asset.asset_type,
                "author": asset.author,
                "confidence": asset.confidence,
                "warnings": list(asset.warnings),
            }
            for asset in inference.assets
        ],
        "warnings": list(inference.warnings),
    }


def request_model_suggestions(
    provider: MetadataSuggestionProvider,
    packet: dict[str, Any],
) -> ModelSuggestionResult:
    try:
        raw = provider.suggest(packet)
        suggestions = _parse_model_suggestions(raw)
    except ModelUnavailableError as exc:
        return ModelSuggestionResult(
            provider=provider.name,
            available=False,
            suggestions=(),
            warnings=(f"model-unavailable: {exc}",),
        )
    except ModelProviderError as exc:
        return ModelSuggestionResult(
            provider=provider.name,
            available=False,
            suggestions=(),
            warnings=(f"model-error: {exc}",),
        )
    return ModelSuggestionResult(provider=provider.name, available=True, suggestions=suggestions)


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        model: str = "local-model",
        timeout_seconds: int = 30,
    ) -> None:
        self.base_url = _normalize_openai_base_url(base_url)
        self.model = model
        self.timeout_seconds = timeout_seconds

    def suggest(self, packet: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "daz_forge_metadata_suggestions",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "suggestions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "path": {"type": "string"},
                                        "content_type": {"type": "string"},
                                        "categories": {"type": "array", "items": {"type": "string"}},
                                        "compatibility_base": {"type": "string"},
                                        "compatibilities": {"type": "array", "items": {"type": "string"}},
                                        "confidence": {"type": "number"},
                                        "reason": {"type": "string"},
                                    },
                                    "required": [
                                        "path",
                                        "content_type",
                                        "categories",
                                        "compatibility_base",
                                        "compatibilities",
                                        "confidence",
                                        "reason",
                                    ],
                                },
                            }
                        },
                        "required": ["suggestions"],
                    },
                },
            },
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return strict JSON only. Suggest DAZ Smart Content metadata corrections. "
                        "Return only the JSON object, without thinking text, markdown, or commentary. "
                        "Do not invent assets. Use the provided paths exactly. "
                        "Use DAZ-style slash paths: categories start with /Default/, and "
                        "compatibility_base and compatibilities start with / when a known base is provided. "
                        "For Genesis figures, prefer bases like /Genesis 9/Base, /Genesis 8/Female, "
                        "or /Genesis 8/Male instead of plain display names."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(packet, ensure_ascii=False, sort_keys=True),
                },
            ],
        }
        payload.update(self._extra_payload())
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise ModelUnavailableError(str(reason)) from exc
        except OSError as exc:
            raise ModelUnavailableError(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ModelProviderError(f"LM Studio returned invalid JSON: {exc}") from exc

        return _extract_openai_json_content(response_payload)

    def _extra_payload(self) -> dict[str, Any]:
        return {}


class LMStudioProvider(OpenAICompatibleProvider):
    name = "lm-studio"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:1234/v1",
        model: str = "local-model",
        timeout_seconds: int = 30,
    ) -> None:
        super().__init__(base_url=base_url, model=model, timeout_seconds=timeout_seconds)


class OllamaProvider(OpenAICompatibleProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3:4b",
        timeout_seconds: int = 30,
    ) -> None:
        super().__init__(base_url=base_url, model=model, timeout_seconds=timeout_seconds)

    def _extra_payload(self) -> dict[str, Any]:
        return {"think": False}


def _normalize_openai_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def _extract_openai_json_content(response_payload: dict[str, Any]) -> dict[str, Any]:
    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelProviderError("LM Studio response does not contain choices[0].message.content") from exc

    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ModelProviderError("LM Studio message content is not a JSON string")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        parsed = _extract_first_json_object(content)
        if parsed is None:
            raise ModelProviderError(f"LM Studio message content is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ModelProviderError("LM Studio message JSON must be an object")
    return parsed


def _extract_first_json_object(content: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(content):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _parse_model_suggestions(raw: dict[str, Any]) -> tuple[ModelAssetSuggestion, ...]:
    if not isinstance(raw, dict):
        raise ModelProviderError("Model response must be a JSON object")
    raw_suggestions = raw.get("suggestions", [])
    if not isinstance(raw_suggestions, list):
        raise ModelProviderError("Model response 'suggestions' must be a list")

    return tuple(_parse_asset_suggestion(item) for item in raw_suggestions)


def _parse_asset_suggestion(item: Any) -> ModelAssetSuggestion:
    if not isinstance(item, dict):
        raise ModelProviderError("Each model suggestion must be an object")
    path = str(item.get("path", ""))
    if not path:
        raise ModelProviderError("Each model suggestion must include a path")
    return ModelAssetSuggestion(
        path=path,
        content_type=str(item.get("content_type", "")),
        categories=tuple(str(value) for value in _list_value(item.get("categories", []))),
        compatibility_base=str(item.get("compatibility_base", "")),
        compatibilities=tuple(str(value) for value in _list_value(item.get("compatibilities", []))),
        confidence=float(item.get("confidence", 0.0)),
        reason=str(item.get("reason", "")),
    )


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise ModelProviderError("Suggestion list fields must be arrays")
