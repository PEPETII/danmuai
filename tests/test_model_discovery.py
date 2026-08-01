from dataclasses import dataclass

from app.providers.model_discovery import clear_discovery_cache, discover_models


@dataclass
class Response:
    payload: object
    status_code: int = 200

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, *, headers):
        self.calls.append((url, headers))
        return self.response


def test_openrouter_path_and_ids_are_account_discovered_without_vision_inference():
    clear_discovery_cache()
    client = FakeClient(Response({"data": [{"id": "author/model", "name": "Model"}]}))
    result = discover_models("openrouter", "secret", http_client=client, now=lambda: 100.0)
    assert result.discovery_kind == "account_discovery"
    assert result.models[0].id == "author/model"
    assert result.models[0].supports_vision is None
    assert result.models[0].price.input is None
    assert result.models[0].price.output is None
    assert result.verified_at == result.fetched_at == result.models[0].verified_at
    assert result.models[0].source.verified_at == result.fetched_at
    assert result.source_url == "https://openrouter.ai/docs/quick-start"
    assert result.request_url == "https://openrouter.ai/api/v1/models"
    assert client.calls[0][0] == "https://openrouter.ai/api/v1/models"
    assert "secret" not in repr(result)


def test_cache_hits_and_expires_by_endpoint_and_key_fingerprint():
    clear_discovery_cache()
    clock = [100.0]
    client = FakeClient(Response({"data": [{"id": "one"}]}))
    first = discover_models("openai", "key-a", http_client=client, now=lambda: clock[0], ttl_seconds=10)
    second = discover_models("openai", "key-a", http_client=client, now=lambda: clock[0], ttl_seconds=10)
    assert first is second
    assert len(client.calls) == 1
    clock[0] = 111.0
    discover_models("openai", "key-a", http_client=client, now=lambda: clock[0], ttl_seconds=10)
    assert len(client.calls) == 2


def test_invalid_payload_and_network_failure_return_curated_fallback_without_caching_failure():
    clear_discovery_cache()
    bad = FakeClient(Response({"unexpected": []}))
    result = discover_models("openai", "key", http_client=bad, now=lambda: 1.0)
    assert result.discovery_kind == "curated_fallback"
    assert result.status == "fallback_invalid_payload"
    class Broken:
        def get(self, *_args, **_kwargs):
            raise TimeoutError("key must not leak")
    failed = discover_models("openai", "key", http_client=Broken(), now=lambda: 2.0)
    assert failed.status == "fallback_request_error"
    assert "key" not in repr(failed)


def test_unknown_provider_is_structured_unknown():
    result = discover_models("not-a-provider", "key", now=lambda: 1.0)
    assert result.status == "unknown"
    assert result.discovery_kind == "curated_fallback"
