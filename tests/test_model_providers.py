from app.model_providers import (
    DEFAULT_PROVIDER_ID,
    apply_provider_to_form,
    get_openai_adapter_for_model,
    guess_provider_from_endpoint,
    is_doubao_mode,
    is_model_config_complete,
    is_valid_endpoint,
    mic_audio_supported_for_config,
    mic_audio_supported_for_mic_config,
    model_likely_supports_mic_audio,
    normalize_api_mode_for_select,
    normalize_endpoint,
    normalize_mode,
    provider_rules_for_api,
    resolve_active_model_id,
    resolve_api_transport,
    resolve_mic_model_id,
    resolve_openai_provider_id,
    resolve_provider_for_ui,
    validate_model_config,
)
from app.providers.registry import HOST_ENTRIES


def test_normalize_endpoint_strips_trailing_slash():
    assert normalize_endpoint("https://api.example.com/v1/") == "https://api.example.com/v1"


def test_normalize_endpoint_strips_chat_completions_suffix():
    assert (
        normalize_endpoint("https://openrouter.ai/api/v1/chat/completions")
        == "https://openrouter.ai/api/v1"
    )
    assert (
        normalize_endpoint("https://openrouter.ai/api/v1/chat/completions/")
        == "https://openrouter.ai/api/v1"
    )


def test_normalize_endpoint_strips_responses_suffix():
    assert (
        normalize_endpoint("https://ark.cn-beijing.volces.com/api/v3/responses")
        == "https://ark.cn-beijing.volces.com/api/v3"
    )


def test_normalize_endpoint_strips_only_one_api_path_suffix():
    # Must not produce double-strip bugs on already-normalized base URLs.
    assert normalize_endpoint("https://api.example.com/v1") == "https://api.example.com/v1"


def test_is_valid_endpoint_requires_https_or_http():
    assert is_valid_endpoint("https://ark.cn-beijing.volces.com/api/v3")
    assert not is_valid_endpoint("")
    assert not is_valid_endpoint("not-a-url")


def test_normalize_mode_maps_openai_aliases():
    assert normalize_mode("openai") == "openai-compatible"
    assert normalize_mode("openai-compatible") == "openai-compatible"
    assert normalize_mode("doubao") == "doubao"
    assert is_doubao_mode("doubao")


def test_validate_model_config_requires_all_fields():
    errors = validate_model_config({"name": "x", "modelId": "m", "endpoint": "", "apiKey": "k"})
    assert "custom_model.error_endpoint" in errors

    errors = validate_model_config(
        {
            "name": "x",
            "modelId": "m",
            "endpoint": "https://api.deepseek.com/v1",
            "apiKey": "",
        }
    )
    assert "custom_model.error_api_key" in errors

    assert is_model_config_complete(
        {
            "name": "DeepSeek",
            "modelId": "deepseek-chat",
            "endpoint": "https://api.deepseek.com/v1",
            "apiKey": "sk-test",
        }
    )


def test_apply_provider_to_form_doubao():
    form = apply_provider_to_form("doubao")
    assert "ark.cn-beijing.volces.com" in form["endpoint"]
    assert form["mode"] == "doubao"
    assert form["lock_mode"] is True


def test_validate_model_config_invalid_endpoint():
    errors = validate_model_config(
        {
            "name": "x",
            "modelId": "m",
            "endpoint": "ftp://bad",
            "apiKey": "k",
        }
    )
    assert "custom_model.error_endpoint_invalid" in errors


def test_validate_model_config_normalizes_stale_mode_on_known_host():
    errors = validate_model_config(
        {
            "name": "x",
            "modelId": "m",
            "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "apiKey": "k",
            "mode": "doubao",
        }
    )
    assert "config.error_endpoint_mode_mismatch" not in errors
    assert errors == []


def test_apply_provider_to_form_mimo():
    form = apply_provider_to_form("mimo")
    assert "api.xiaomimimo.com" in form["endpoint"]
    assert form["mode"] == "openai-compatible"
    assert form["lock_mode"] is True


def test_apply_provider_to_form_zai():
    form = apply_provider_to_form("zai")
    assert "api.z.ai" in form["endpoint"]
    assert form["mode"] == "openai-compatible"
    assert form["lock_mode"] is True


def test_guess_provider_from_endpoint():
    assert guess_provider_from_endpoint("https://api.deepseek.com/v1") == DEFAULT_PROVIDER_ID
    assert guess_provider_from_endpoint("https://unknown.example/v1", "doubao") == "custom_doubao"
    assert guess_provider_from_endpoint("") == DEFAULT_PROVIDER_ID
    assert guess_provider_from_endpoint("https://api.xiaomimimo.com/v1") == "mimo"
    assert guess_provider_from_endpoint("https://api.z.ai/api/paas/v4") == "zai"


def test_provider_rules_for_api_matches_host_entries():
    rules = provider_rules_for_api()
    assert rules["default_provider_id"] == DEFAULT_PROVIDER_ID
    assert rules["editable_api_mode_provider_ids"] == ["custom_openai", "custom_doubao"]
    assert len(rules["host_entries"]) == len(HOST_ENTRIES)
    for entry, api_entry in zip(HOST_ENTRIES, rules["host_entries"], strict=True):
        assert api_entry == {
            "fragment": entry.fragment,
            "provider_id": entry.provider_id,
            "transport": entry.transport,
        }


def test_normalize_api_mode_for_select_known_hosts():
    for entry in HOST_ENTRIES:
        ep = f"https://{entry.fragment}/v1"
        opposite_mode = "openai-compatible" if entry.transport == "doubao" else "doubao"
        assert normalize_api_mode_for_select(opposite_mode, ep) == (
            "doubao" if entry.transport == "doubao" else "openai"
        )


def test_normalize_api_mode_for_select_unknown_host_fallback():
    assert normalize_api_mode_for_select("doubao", "https://unknown.example/v1") == "doubao"
    assert normalize_api_mode_for_select("openai", "https://unknown.example/v1") == "openai"
    assert normalize_api_mode_for_select("openai-compatible", "https://unknown.example/v1") == "openai"


def test_resolve_provider_for_ui_matches_guess_and_transport():
    ep = "https://ark.cn-beijing.volces.com/api/v3"
    resolved = resolve_provider_for_ui(ep, "openai")
    assert resolved["provider_id"] == "doubao"
    assert resolved["transport"] == "doubao"
    assert resolved["api_mode_select"] == "doubao"

    unknown = resolve_provider_for_ui("https://unknown.example/v1", "doubao")
    assert unknown["provider_id"] == "custom_doubao"
    assert unknown["transport"] == "doubao"
    assert unknown["api_mode_select"] == "doubao"


def test_resolve_api_transport_ark_endpoint_uses_doubao_even_when_mode_openai():
    endpoint = "https://ark.cn-beijing.volces.com/api/v3"
    assert resolve_api_transport(endpoint, "openai") == "doubao"
    assert resolve_api_transport(endpoint, "openai-compatible") == "doubao"


def test_resolve_api_transport_siliconflow_uses_openai_even_when_mode_doubao():
    endpoint = "https://api.siliconflow.cn/v1"
    assert resolve_api_transport(endpoint, "doubao") == "openai"


class _Cfg:
    def __init__(self, **kwargs):
        self._data = kwargs
        self._api_key = kwargs.pop("api_key", "sk-visual")
        self._mic_api_key = kwargs.pop("mic_api_key", "sk-mic")

    def get(self, key, default=""):
        return self._data.get(key, default)

    def get_api_key(self):
        return self._api_key

    def get_mic_api_key(self):
        return self._mic_api_key

    def get_default_model_id(self):
        return self.get("default_model_id", self.get("model", ""))

    def get_custom_models(self):
        return self._data.get("custom_models", [])


def test_resolve_active_model_id_prefers_custom_default():
    cfg = _Cfg(
        model="doubao-seed-1-6-flash-250828",
        default_model_id="doubao-seed-2-0-mini-260428",
        custom_models=[
            {"modelId": "doubao-seed-2-0-mini-260428", "endpoint": "https://x/v3", "apiKey": "k"},
        ],
    )
    assert resolve_active_model_id(cfg) == "doubao-seed-2-0-mini-260428"


def test_model_likely_supports_mic_audio():
    assert not model_likely_supports_mic_audio("doubao-seed-1-6-flash-250828")
    assert model_likely_supports_mic_audio("doubao-seed-2-0-mini-260428")
    assert model_likely_supports_mic_audio("doubao-seed-1-6-vision-250615")
    assert not model_likely_supports_mic_audio("")


def test_model_supports_mic_audio_mimo_v25_only():
    from app.model_providers import model_supports_mic_audio

    ep = "https://api.xiaomimimo.com/v1"
    assert model_supports_mic_audio("mimo-v2.5", endpoint=ep, api_mode="openai-compatible")
    assert not model_supports_mic_audio("mimo-v2-omni", endpoint=ep, api_mode="openai-compatible")
    assert not model_supports_mic_audio(
        "doubao-seed-1-6-flash-250828", endpoint=ep, api_mode="openai-compatible"
    )


def test_model_supports_mic_audio_doubao_endpoint():
    from app.model_providers import model_supports_mic_audio

    ep = "https://ark.cn-beijing.volces.com/api/v3"
    assert model_supports_mic_audio("doubao-seed-2-0-mini-260428", endpoint=ep, api_mode="doubao")
    assert not model_supports_mic_audio("doubao-seed-1-6-flash-250828", endpoint=ep, api_mode="doubao")


def test_model_supports_mic_audio_mimo_v25_custom_proxy_endpoint():
    from app.model_providers import model_supports_mic_audio

    ep = "https://my-mimo-proxy.com/v1"
    assert model_supports_mic_audio("mimo-v2.5", endpoint=ep, api_mode="openai-compatible")
    assert not model_supports_mic_audio("mimo-v2-omni", endpoint=ep, api_mode="openai-compatible")


def test_model_supports_mic_audio_rejects_non_mimo_on_custom_openai():
    from app.model_providers import model_supports_mic_audio

    ep = "https://example.com/v1"
    assert not model_supports_mic_audio("gpt-4o", endpoint=ep, api_mode="openai")
    assert not model_supports_mic_audio("deepseek-chat", endpoint=ep, api_mode="openai-compatible")


def test_model_supports_mic_audio_honors_supports_mic_declared():
    from app.model_providers import model_supports_mic_audio

    ep = "https://openrouter.ai/api/v1"
    assert model_supports_mic_audio(
        "openai/gpt-4o-audio-preview",
        endpoint=ep,
        api_mode="openai-compatible",
        supports_mic_declared=True,
    )
    assert not model_supports_mic_audio(
        "openai/gpt-4o-audio-preview",
        endpoint=ep,
        api_mode="openai-compatible",
        supports_mic_declared=False,
    )


def test_model_supports_mic_audio_catalog_lookup():
    from app.model_providers import model_supports_mic_audio

    ep = "https://openrouter.ai/api/v1"
    assert model_supports_mic_audio(
        "doubao-seed-2-0-mini-260428",
        endpoint=ep,
        api_mode="openai-compatible",
    )


def test_resolve_openai_provider_id_mimo_v25_requires_mimo_host():
    ep = "https://my-mimo-proxy.com/v1"
    assert resolve_openai_provider_id("mimo-v2.5", ep, "openai-compatible") == DEFAULT_PROVIDER_ID
    assert resolve_openai_provider_id("gpt-4o", ep, "openai-compatible") == DEFAULT_PROVIDER_ID
    official = "https://api.xiaomimimo.com/v1"
    assert resolve_openai_provider_id("mimo-v2.5", official, "openai-compatible") == "mimo"


def test_mic_audio_supported_for_mic_config_falls_back_to_visual():
    cfg = _Cfg(
        mic_use_visual_model="1",
        model="doubao-seed-2-0-mini-260428",
        api_endpoint="https://ark.cn-beijing.volces.com/api/v3",
        api_mode="doubao",
    )
    assert mic_audio_supported_for_mic_config(cfg) is True


def test_mic_audio_supported_for_mic_config_uses_independent_credentials():
    cfg = _Cfg(
        mic_use_visual_model="0",
        model="doubao-seed-1-6-flash-250828",
        api_endpoint="https://ark.cn-beijing.volces.com/api/v3",
        api_mode="doubao",
        mic_model="doubao-seed-2-0-mini-260428",
        mic_api_endpoint="https://ark.cn-beijing.volces.com/api/v3",
        mic_api_mode="doubao",
    )
    assert mic_audio_supported_for_mic_config(cfg) is True


def test_resolve_mic_model_id_prefers_mic_model_when_unlinked():
    cfg = _Cfg(
        mic_use_visual_model="0",
        model="doubao-seed-1-6-flash-250828",
        mic_model="doubao-seed-2-0-mini-260428",
    )
    assert resolve_mic_model_id(cfg) == "doubao-seed-2-0-mini-260428"


def test_mic_audio_supported_for_config_custom_model_supports_mic_flag():
    cfg = _Cfg(
        default_model_id="or-audio",
        custom_models=[
            {
                "modelId": "or-audio",
                "endpoint": "https://openrouter.ai/api/v1",
                "mode": "openai-compatible",
                "apiKey": "sk",
                "supportsMic": True,
            }
        ],
    )
    assert mic_audio_supported_for_config(cfg) is True


def test_mic_audio_supported_for_config_custom_mimo_proxy():
    cfg = _Cfg(
        model="mimo-v2.5",
        api_endpoint="https://my-mimo-proxy.com/v1",
        api_mode="openai-compatible",
    )
    assert mic_audio_supported_for_config(cfg) is True

    cfg_unsupported = _Cfg(
        model="gpt-4o",
        api_endpoint="https://example.com/v1",
        api_mode="openai-compatible",
    )
    assert mic_audio_supported_for_config(cfg_unsupported) is False


def test_get_openai_adapter_for_model_mimo_v25_requires_official_host():
    from app.providers.adapters.default_openai import DefaultOpenAIAdapter
    from app.providers.adapters.mimo import MimoOpenAIAdapter

    proxy_adapter = get_openai_adapter_for_model(
        "mimo-v2.5",
        "https://my-mimo-proxy.com/v1",
        "openai-compatible",
    )
    assert isinstance(proxy_adapter, DefaultOpenAIAdapter)
    official_adapter = get_openai_adapter_for_model(
        "mimo-v2.5",
        "https://api.xiaomimimo.com/v1",
        "openai-compatible",
    )
    assert isinstance(official_adapter, MimoOpenAIAdapter)
