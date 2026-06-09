import json
from urllib.error import URLError

from forge.analyzer.inference import AssetSuggestion, InferenceResult, ProductSuggestion
from forge.analyzer.model_provider import (
    LMStudioProvider,
    ModelProviderError,
    ModelUnavailableError,
    OllamaProvider,
    build_model_packet,
    request_model_suggestions,
)


def inference_result() -> InferenceResult:
    return InferenceResult(
        product=ProductSuggestion(
            product_type="clothing/outfit",
            primary_artist="Websoul",
            artist_state="single",
            artists=("Websoul",),
        ),
        assets=(
            AssetSuggestion(
                path="People/Genesis 9/Clothing/Websoul/Dress.duf",
                content_type="Follower/Wardrobe",
                categories=("/Default/Wardrobe",),
                asset_type="wearable",
                author="Websoul",
                confidence=0.8,
                warnings=("support-category-conflict",),
            ),
        ),
        warnings=("People/Genesis 9/Clothing/Websoul/Dress.duf: support-category-conflict",),
    )


def test_build_model_packet_uses_structured_summary_without_raw_file_data() -> None:
    packet = build_model_packet(inference_result())

    assert packet["product"]["product_type"] == "clothing/outfit"
    assert packet["product"]["artists"] == ["Websoul"]
    assert packet["assets"][0]["path"] == "People/Genesis 9/Clothing/Websoul/Dress.duf"
    assert packet["assets"][0]["content_type"] == "Follower/Wardrobe"
    serialized = json.dumps(packet)
    assert "raw" not in serialized.lower()
    assert "file_bytes" not in serialized.lower()


class UnavailableProvider:
    name = "fake-unavailable"

    def suggest(self, packet):
        raise ModelUnavailableError("not running")


class ErrorProvider:
    name = "fake-error"

    def suggest(self, packet):
        raise ModelProviderError("bad json")


class StaticProvider:
    name = "fake-static"

    def suggest(self, packet):
        return {
            "suggestions": [
                {
                    "path": "People/Genesis 9/Clothing/Websoul/Dress.duf",
                    "content_type": "Follower/Wardrobe",
                    "categories": ["/Default/Wardrobe/Dresses"],
                    "compatibility_base": "/Websoul Dress/Dress",
                    "compatibilities": ["/Genesis 9/Base"],
                    "confidence": 0.72,
                    "reason": "Dress wearable under Genesis 9 clothing.",
                }
            ]
        }


def test_unavailable_provider_returns_warning_result() -> None:
    result = request_model_suggestions(UnavailableProvider(), {"assets": []})

    assert result.provider == "fake-unavailable"
    assert result.available is False
    assert result.suggestions == ()
    assert result.warnings == ("model-unavailable: not running",)


def test_provider_error_returns_warning_result() -> None:
    result = request_model_suggestions(ErrorProvider(), {"assets": []})

    assert result.available is False
    assert result.warnings == ("model-error: bad json",)


def test_valid_provider_json_becomes_structured_suggestions() -> None:
    result = request_model_suggestions(StaticProvider(), {"assets": []})

    assert result.available is True
    assert len(result.suggestions) == 1
    suggestion = result.suggestions[0]
    assert suggestion.path == "People/Genesis 9/Clothing/Websoul/Dress.duf"
    assert suggestion.categories == ("/Default/Wardrobe/Dresses",)
    assert suggestion.compatibilities == ("/Genesis 9/Base",)
    assert suggestion.confidence == 0.72


def test_lm_studio_provider_sends_openai_compatible_request(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "suggestions": [
                                            {
                                                "path": "Asset.duf",
                                                "categories": ["/Default/Props"],
                                                "confidence": 0.5,
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = LMStudioProvider(base_url="http://127.0.0.1:1234/v1", model="local-test", timeout_seconds=7)
    response = provider.suggest({"assets": [{"path": "Asset.duf"}]})

    assert captured["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert captured["timeout"] == 7
    assert captured["payload"]["model"] == "local-test"
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert captured["payload"]["response_format"]["json_schema"]["name"] == "daz_forge_metadata_suggestions"
    assert "Return strict JSON" in captured["payload"]["messages"][0]["content"]
    assert "DAZ-style slash paths" in captured["payload"]["messages"][0]["content"]
    assert response["suggestions"][0]["path"] == "Asset.duf"


def test_ollama_provider_sends_openai_compatible_request(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "suggestions": [
                                            {
                                                "path": "Asset.duf",
                                                "categories": ["/Default/Props"],
                                                "confidence": 0.5,
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="qwen3:4b", timeout_seconds=11)
    response = provider.suggest({"assets": [{"path": "Asset.duf"}]})

    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["timeout"] == 11
    assert captured["payload"]["model"] == "qwen3:4b"
    assert captured["payload"]["think"] is False
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert response["suggestions"][0]["path"] == "Asset.duf"


def test_provider_extracts_json_after_qwen_thinking_text(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "Thinking...\n"
                                    "The user wants JSON, so I should comply.\n"
                                    "...done thinking.\n"
                                    '{"suggestions":[{"path":"Asset.duf","categories":["/Default/Props"],"confidence":0.5}]}'
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = OllamaProvider()
    response = provider.suggest({"assets": [{"path": "Asset.duf"}]})

    assert response["suggestions"][0]["path"] == "Asset.duf"


def test_lm_studio_provider_wraps_connection_errors(monkeypatch) -> None:
    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = LMStudioProvider(base_url="http://127.0.0.1:1234/v1")

    result = request_model_suggestions(provider, {"assets": []})

    assert result.available is False
    assert result.warnings == ("model-unavailable: connection refused",)
