from __future__ import annotations

import pytest
from app.config_store import ConfigStore
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
from app.tts.config_credentials import clear_stored_tts_credentials, stored_tts_credentials
from app.tts_providers import TTS_PROVIDER_MIMO, TTS_PROVIDER_MINIMAX
from app.virtual_host.model_config import (
    VISION_MODEL_KEY,
    apply_virtual_host_model_config,
    custom_profile_supports_vision,
    decode_tts_option_id,
    encode_tts_option_id,
    export_virtual_host_model_config,
    list_tts_model_options,
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
    # W-AUDIT-MODEL-IDENTITY-001：视觉引用按不可变 profile_id。本文件大部分用例只关心
    # 档案内容，故 fixture 让身份与上游模型名一致；"身份≠模型名 / 重复名" 的专门契约
    # 用例见本文件下方 *_profile_id_* / *_duplicate_* 测试。
    return {
        "name": "Vision profile",
        "profile_id": model_id,
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
        "profile_id": model_id,
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
        "profile_id": model_id,
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


# ---------------------------------------------------------------------------
# W-AUDIT-MODEL-IDENTITY-001：视觉引用使用不可变 profile_id（身份 ≠ 上游模型名）
# ---------------------------------------------------------------------------


def _vision_profile_with_identity(
    profile_id: str,
    model_id: str,
    *,
    api_key: str = "secret",
) -> dict:
    return {
        "name": f"Vision {profile_id}",
        "profile_id": profile_id,
        "default_model_id": model_id,
        "model_ids": [model_id],
        "endpoint": "https://ark.cn-beijing.volces.com/api/v3",
        "apiKey": api_key,
        "mode": "doubao",
        "max_tokens": 512,
    }


def test_vision_options_expose_profile_id_and_resolve_correct_duplicate():
    """两个档案共享同一上游模型名时，选项 id 是各自 profile_id，且各自命中正确档案。"""
    shared_model = "doubao-seed-1-6-vision-32k-250115"
    config = _FakeConfig(
        custom_models=[
            _vision_profile_with_identity("cmp_a", shared_model, api_key="key-a"),
            _vision_profile_with_identity("cmp_b", shared_model, api_key="key-b"),
        ]
    )
    options = list_vision_model_options(config)
    assert {item["id"] for item in options} == {"cmp_a", "cmp_b"}
    assert {item["model_id"] for item in options} == {shared_model}

    apply_virtual_host_model_config(config, {"vision_model_id": "cmp_b"})
    assert config.get(VISION_MODEL_KEY) == "cmp_b"
    resolved = resolve_virtual_host_vision_credentials(config)
    assert resolved is not None
    endpoint, api_key, model_id, _mode = resolved
    assert api_key == "key-b"
    assert model_id == shared_model


def test_apply_virtual_host_model_config_rejects_ambiguous_model_name():
    """按重复的上游模型名提交视觉选择 → 不猜测首项，直接拒绝。"""
    shared_model = "doubao-seed-1-6-vision-32k-250115"
    config = _FakeConfig(
        custom_models=[
            _vision_profile_with_identity("cmp_a", shared_model, api_key="key-a"),
            _vision_profile_with_identity("cmp_b", shared_model, api_key="key-b"),
        ]
    )
    with pytest.raises(ValueError, match="virtual_host_vision_model_unavailable"):
        apply_virtual_host_model_config(config, {"vision_model_id": shared_model})


def test_sanitize_migrates_unique_legacy_model_name_vision_ref():
    """唯一匹配的旧版按模型名记录 → 归一化为 profile_id 并持久化。"""
    legacy_model = "qwen3-vl-flash"
    profile = {
        **_catalog_vision_profile(legacy_model),
        "profile_id": "cmp_vision",
    }
    config = _FakeConfig({VISION_MODEL_KEY: legacy_model}, custom_models=[profile])
    normalized = sanitize_virtual_host_model_config(config, persist=True)
    assert normalized[VISION_MODEL_KEY] == "cmp_vision"
    assert config.get(VISION_MODEL_KEY) == "cmp_vision"


def test_sanitize_clears_ambiguous_legacy_model_name_vision_ref():
    """重复模型名的旧版视觉引用无法唯一确定 → 回落为空并写回（要求重新选择）。"""
    shared_model = "doubao-seed-1-6-vision-32k-250115"
    config = _FakeConfig(
        {VISION_MODEL_KEY: shared_model},
        custom_models=[
            _vision_profile_with_identity("cmp_a", shared_model),
            _vision_profile_with_identity("cmp_b", shared_model),
        ],
    )
    normalized = sanitize_virtual_host_model_config(config, persist=True)
    assert normalized[VISION_MODEL_KEY] == ""
    assert config.get(VISION_MODEL_KEY) == ""


def test_purge_virtual_host_model_refs_keeps_other_profile_with_same_model_name():
    """删除重复名之一时：只按被删档案 profile_id 清理，另一档案引用不受影响。"""
    shared_model = "doubao-seed-1-6-vision-32k-250115"
    remaining = [_vision_profile_with_identity("cmp_b", shared_model)]

    # 引用指向 A 的 profile_id → 清理
    config_a = _FakeConfig({VISION_MODEL_KEY: "cmp_a"}, custom_models=remaining)
    purge_virtual_host_model_refs(config_a, "cmp_a", shared_model)
    assert config_a.get(VISION_MODEL_KEY) == ""

    # 旧版按模型名记录，且剩余档案仍拥有该模型名 → 不清理
    config_legacy = _FakeConfig({VISION_MODEL_KEY: shared_model}, custom_models=remaining)
    purge_virtual_host_model_refs(config_legacy, "cmp_a", shared_model)
    assert config_legacy.get(VISION_MODEL_KEY) == shared_model

    # 旧版按模型名记录，且没有任何剩余档案拥有该模型名 → 清理
    config_orphan = _FakeConfig({VISION_MODEL_KEY: shared_model}, custom_models=[])
    purge_virtual_host_model_refs(config_orphan, "cmp_a", shared_model)
    assert config_orphan.get(VISION_MODEL_KEY) == ""


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


def test_list_tts_model_options_mimo_minimax_only_without_stale_dashscope(workspace_tmp):
    store = ConfigStore(workspace_tmp / "vh_tts_mimo_minimax.db")
    try:
        store.set_tts_secret(TTS_PROVIDER_MIMO, "api_key", "mimo-key")
        store.set_tts_secret(TTS_PROVIDER_MINIMAX, "api_key", "minimax-key")
        options = list_tts_model_options(store)
        providers = {item["provider_id"] for item in options}
        assert providers == {TTS_PROVIDER_MIMO, TTS_PROVIDER_MINIMAX}
        minimax_models = {item["model_id"] for item in options if item["provider_id"] == TTS_PROVIDER_MINIMAX}
        assert minimax_models == {"speech-2.8-turbo", "speech-2.8-hd"}
        option_ids = [item["id"] for item in options]
        assert len(option_ids) == len(set(option_ids))
        assert encode_tts_option_id(TTS_PROVIDER_MINIMAX, "speech-2.8-turbo") in option_ids
        store.set_batch(
            {
                "virtual_host_tts_provider": TTS_PROVIDER_MINIMAX,
                "virtual_host_tts_model_id": "speech-2.8-turbo",
            }
        )
        binding = resolve_virtual_host_tts_binding(store)
        assert binding is not None
        assert binding.provider_id == TTS_PROVIDER_MINIMAX
        assert binding.model_id == "speech-2.8-turbo"
    finally:
        store.close()


def test_list_tts_model_options_excludes_cleared_stale_dashscope_credentials(workspace_tmp):
    store = ConfigStore(workspace_tmp / "vh_tts_stale_dash.db")
    try:
        store.set_tts_secret(TTS_PROVIDER_MIMO, "api_key", "mimo-key")
        store.set_tts_secret(TTS_PROVIDER_MINIMAX, "api_key", "minimax-key")
        store.set_tts_secret("dashscope", "api_key", "stale-dashscope")
        assert {item["provider_id"] for item in list_tts_model_options(store)} == {
            TTS_PROVIDER_MIMO,
            TTS_PROVIDER_MINIMAX,
            "dashscope",
        }
        clear_stored_tts_credentials(store, "dashscope")
        providers = {item["provider_id"] for item in list_tts_model_options(store)}
        assert providers == {TTS_PROVIDER_MIMO, TTS_PROVIDER_MINIMAX}
        assert stored_tts_credentials(store, "dashscope") == {}
    finally:
        store.close()


def test_list_tts_model_options_dashscope_models_not_duplicated(workspace_tmp):
    store = ConfigStore(workspace_tmp / "vh_tts_dash_unique.db")
    try:
        store.set_tts_secret("dashscope", "api_key", "dash-key")
        options = [
            item
            for item in list_tts_model_options(store)
            if item["provider_id"] == "dashscope"
        ]
        model_ids = [item["model_id"] for item in options]
        assert model_ids
        assert len(model_ids) == len(set(model_ids))
        assert all(decode_tts_option_id(item["id"])[0] == "dashscope" for item in options)
    finally:
        store.close()


def test_list_and_binding_require_the_runtime_default_wav_format(monkeypatch):
    voice = VoiceDescriptor("voice-1", "Voice 1")
    model = ModelDescriptor(
        id="mp3-only-model",
        label="MP3 only",
        capabilities=TtsCapabilities(output_formats=frozenset({"mp3"})),
        voices=(voice,),
    )
    descriptor = ProviderDescriptor(
        id="mp3-only-provider",
        label="MP3 only provider",
        models=(model,),
    )
    manager = TtsManager(
        ProviderRegistry([FakeProvider(descriptor)]),
        TtsCatalog([descriptor]),
    )
    monkeypatch.setattr("app.virtual_host.model_config.get_tts_manager", lambda: manager)
    config = _FakeConfig(
        {
            "virtual_host_tts_provider": "mp3-only-provider",
            "virtual_host_tts_model_id": "mp3-only-model",
        }
    )

    assert list_tts_model_options(config) == []
    assert resolve_virtual_host_tts_binding(config, manager) is None


def test_virtual_host_tts_selection_persists_after_reload(workspace_tmp):
    store = ConfigStore(workspace_tmp / "vh_tts_persist.db")
    try:
        store.set_tts_secret(TTS_PROVIDER_MIMO, "api_key", "mimo-key")
        store.set_tts_secret(TTS_PROVIDER_MINIMAX, "api_key", "minimax-key")
        option_id = encode_tts_option_id(TTS_PROVIDER_MINIMAX, "speech-2.8-turbo")
        apply_virtual_host_model_config(store, {"tts_option_id": option_id})
        assert store.get("virtual_host_tts_provider") == TTS_PROVIDER_MINIMAX
        assert store.get("virtual_host_tts_model_id") == "speech-2.8-turbo"

        store.close()
        store = ConfigStore(workspace_tmp / "vh_tts_persist.db")
        exported = export_virtual_host_model_config(store)
        assert exported["tts_option_id"] == option_id
        assert exported["tts_enabled"] is True
        assert exported["tts_options"]
        assert option_id in {item["id"] for item in exported["tts_options"]}
    finally:
        store.close()
