from app.ai_client_requests import resolve_mic_request_credentials


class _Cfg:
    def __init__(self, **kwargs):
        self._api_key = kwargs.pop("api_key", "sk-visual")
        self._mic_api_key = kwargs.pop("mic_api_key", "sk-mic")
        self._data = kwargs

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


def test_resolve_mic_request_credentials_linked_to_visual():
    cfg = _Cfg(
        mic_use_visual_model="1",
        api_endpoint="https://ark.cn-beijing.volces.com/api/v3",
        api_mode="doubao",
        model="doubao-seed-1-6-flash-250828",
        default_model_id="doubao-seed-1-6-flash-250828",
        custom_models=[
            {
                "name": "Test",
                "default_model_id": "doubao-seed-1-6-flash-250828",
                "modelId": "doubao-seed-1-6-flash-250828",
                "endpoint": "https://ark.cn-beijing.volces.com/api/v3",
                "apiKey": "sk-visual",
                "mode": "doubao",
            }
        ],
    )
    resolved = resolve_mic_request_credentials(cfg)
    assert resolved == (
        "https://ark.cn-beijing.volces.com/api/v3",
        "sk-visual",
        "doubao-seed-1-6-flash-250828",
        "doubao",
    )


def test_resolve_mic_request_credentials_independent():
    cfg = _Cfg(
        mic_use_visual_model="0",
        api_endpoint="https://ark.cn-beijing.volces.com/api/v3",
        api_mode="doubao",
        model="doubao-seed-1-6-flash-250828",
        mic_api_endpoint="https://api.xiaomimimo.com/v1",
        mic_api_mode="openai",
        mic_model="mimo-v2.5",
        mic_api_key="sk-mimo",
    )
    resolved = resolve_mic_request_credentials(cfg)
    assert resolved == (
        "https://api.xiaomimimo.com/v1",
        "sk-mimo",
        "mimo-v2.5",
        "openai-compatible",
    )


def test_resolve_mic_request_credentials_independent_incomplete_returns_none():
    cfg = _Cfg(
        mic_use_visual_model="0",
        mic_api_endpoint="https://api.xiaomimimo.com/v1",
        mic_api_mode="openai",
        mic_model="",
    )
    assert resolve_mic_request_credentials(cfg) is None
