from __future__ import annotations

import pytest
from app.tts import (
    AuthDescriptor,
    AuthFieldDescriptor,
    BaseTtsProvider,
    InMemoryCredentialStore,
    ModelDescriptor,
    ProviderDescriptor,
    ProviderRegistry,
    TtsCapabilities,
    TtsCatalog,
    TtsManager,
    TtsResult,
    VoiceDescriptor,
)
from app.virtual_host.model_config import (
    VISION_MODEL_KEY,
    apply_virtual_host_model_config,
    custom_profile_supports_vision,
    encode_tts_option_id,
    export_virtual_host_model_config,
    list_vision_model_options,
    purge_virtual_host_model_refs,
    resolve_virtual_host_tts_binding,
    resolve_virtual_host_vision_credentials,
    sanitize_virtual_host_model_config,
    virtual_host_tts_enabled,
    virtual_host_vision_enabled,
)


class _FakeConfig:
    def __init__(self, data: dict | None = None, *, custom_models: list | None = None) -> None:
        self._data = dict(data or {})
        self._custom_models = list(custom_models or [])

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def set_batch(self, items: dict[str, str]) -> None:
        self._data.update(items)

    def get_custom_models(self):
        return list(self._custom_models)


def _vision_profile(model_id: str = "vision-model") -> dict:
    return {
        "name": "Vision profile",
        "default_model_id": model_id,
        "model_ids": [model_id],
        "endpoint": "https://ark.cn-beijing.volces.com/api/v3",
        "apiKey": "secret",
        "mode": "doubao",
        "max_tokens": 512,
    }


def _text_only_profile(model_id: str = "gpt-4.1-mini") -> dict:
    return {
        "name": "Text profile",
        "default_model_id": model_id,
        "model_ids": [model_id],
        "endpoint": "https://api.openai.com/v1",
        "apiKey": "secret",
        "mode": "openai-compatible",
        "max_tokens": 512,
    }


def _catalog_vision_profile(model_id: str = "qwen3-vl-flash") -> dict:
    return {
        "name": "Catalog vision profile",
        "default_model_id": model_id,
        "model_ids": [model_id],
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "apiKey": "secret",
        "mode": "openai-compatible",
        "max_tokens": 512,
    }


def test_custom_profile_supports_vision_uses_capability_resolver():
    assert custom_profile_supports_vision(_vision_profile("doubao-seed-1-6-vision-32k-250115"))
    assert custom_profile_supports_vision(_catalog_vision_profile("qwen3-vl-flash"))
    assert not custom_profile_supports_vision(_text_only_profile("gpt-4.1-mini"))


def test_list_vision_model_options_only_includes_complete_vision_profiles():
    config = _FakeConfig(
        custom_models=[
            _vision_profile("doubao-seed-1-6-vision-32k-250115"),
            _catalog_vision_profile("qwen3-vl-flash"),
            _text_only_profile("gpt-4.1-mini"),
            {**_vision_profile("broken"), "apiKey": ""},
        ]
    )
    options = list_vision_model_options(config)
    assert {item["id"] for item in options} == {
        "doubao-seed-1-6-vision-32k-250115",
        "qwen3-vl-flash",
    }


def test_sanitize_virtual_host_model_config_clears_stale_ids():
    config = _FakeConfig(
        {
            VISION_MODEL_KEY: "missing-vision",
            "virtual_host_tts_provider": "mimo",
            "virtual_host_tts_model_id": "missing-tts",
        },
        custom_models=[_catalog_vision_profile("qwen3-vl-flash")],
    )
    normalized = sanitize_virtual_host_model_config(config, persist=True)
    assert normalized[VISION_MODEL_KEY] == ""
    assert normalized["virtual_host_tts_provider"] == ""
    assert normalized["virtual_host_tts_model_id"] == ""
    assert virtual_host_vision_enabled(config) is False
    assert virtual_host_tts_enabled(config) is False


def test_apply_virtual_host_model_config_persists_valid_selection():
    config = _FakeConfig(custom_models=[_catalog_vision_profile("qwen3-vl-flash")])
    result = apply_virtual_host_model_config(
        config,
        {"vision_model_id": "qwen3-vl-flash"},
    )
    assert result["vision_model_id"] == "qwen3-vl-flash"
    assert virtual_host_vision_enabled(config) is True
    assert resolve_virtual_host_vision_credentials(config) is not None


def test_apply_virtual_host_model_config_rejects_unknown_vision_model():
    config = _FakeConfig(custom_models=[_catalog_vision_profile("qwen3-vl-flash")])
    with pytest.raises(ValueError, match="virtual_host_vision_model_unavailable"):
        apply_virtual_host_model_config(config, {"vision_model_id": "unknown-model"})


def test_purge_virtual_host_model_refs_clears_deleted_vision_model():
    config = _FakeConfig({VISION_MODEL_KEY: "vision-model"})
    purge_virtual_host_model_refs(config, "vision-model")
    assert config.get(VISION_MODEL_KEY) == ""


class FakeProvider(BaseTtsProvider):
    def synthesize(self, credentials, request, *, timeout_sec=60.0):
        del credentials, timeout_sec
        return TtsResult(request.text.encode(), "wav")


def _tts_manager():
    voice = VoiceDescriptor("voice-1", "Voice 1")
    model = ModelDescriptor(
        id="tts-model",
        label="TTS model",
        capabilities=TtsCapabilities(),
        voices=(voice,),
    )
    descriptor = ProviderDescriptor(
        id="tts-provider",
        label="TTS provider",
        auth=AuthDescriptor((AuthFieldDescriptor("api_key", "API key"),)),
        models=(model,),
    )
    provider = FakeProvider(descriptor)
    manager = TtsManager(ProviderRegistry([provider]), TtsCatalog([descriptor]))
    store = InMemoryCredentialStore()
    store.set("tts-provider", {"api_key": "secret"})
    manager.credentials = manager.credentials.__class__(store)
    return manager


def test_resolve_virtual_host_tts_binding_uses_virtual_host_source(monkeypatch):
    manager = _tts_manager()
    option_id = encode_tts_option_id("tts-provider", "tts-model")
    config = _FakeConfig(
        {
            "virtual_host_tts_provider": "tts-provider",
            "virtual_host_tts_model_id": "tts-model",
        }
    )

    monkeypatch.setattr(
        "app.virtual_host.model_config.list_tts_model_options",
        lambda _config: [{"id": option_id, "label": "TTS", "provider_id": "tts-provider", "model_id": "tts-model"}],
    )
    monkeypatch.setattr(
        "app.tts.config_credentials.stored_tts_credentials",
        lambda _config, _provider: {"api_key": "secret"},
    )
    binding = resolve_virtual_host_tts_binding(config, manager)
    assert binding is not None
    assert binding.source == "virtual_host"
    assert binding.provider_id == "tts-provider"
    assert binding.model_id == "tts-model"


def test_export_virtual_host_model_config_includes_option_lists(monkeypatch):
    config = _FakeConfig(custom_models=[_catalog_vision_profile("qwen3-vl-flash")])
    monkeypatch.setattr(
        "app.virtual_host.model_config.list_tts_model_options",
        lambda _config: [],
    )
    payload = export_virtual_host_model_config(config)
    assert payload["vision_options"]
    assert payload["tts_options"] == []
    assert payload["vision_enabled"] is False
