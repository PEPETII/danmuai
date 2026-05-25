from app.model_providers import (
    DEFAULT_PROVIDER_ID,
    apply_provider_to_form,
    guess_provider_from_endpoint,
    is_doubao_mode,
    is_model_config_complete,
    is_valid_endpoint,
    model_likely_supports_mic_audio,
    normalize_endpoint,
    normalize_mode,
    resolve_active_model_id,
    validate_model_config,
)


def test_normalize_endpoint_strips_trailing_slash():
    assert normalize_endpoint("https://api.example.com/v1/") == "https://api.example.com/v1"


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


def test_guess_provider_from_endpoint():
    assert guess_provider_from_endpoint("https://api.deepseek.com/v1") == "deepseek"
    assert guess_provider_from_endpoint("https://unknown.example/v1", "doubao") == "custom_doubao"
    assert guess_provider_from_endpoint("") == DEFAULT_PROVIDER_ID


class _Cfg:
    def __init__(self, **kwargs):
        self._data = kwargs

    def get(self, key, default=""):
        return self._data.get(key, default)

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
