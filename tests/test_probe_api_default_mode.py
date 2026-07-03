"""Probe API connection default api_mode alignment."""

from unittest.mock import MagicMock, patch

from app.main_web_facade_mixin import DanmuAppWebFacadeMixin

from app.web_api.custom_models import MASKED_KEY

from tests.fakes import FakeConfig


class _ProbeHost(DanmuAppWebFacadeMixin):
    def __init__(self, config):
        self.config = config


def test_probe_api_connection_uses_custom_model_key():
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 无参数 probe 应使用 custom_models 档案 key，
    不再回退全局 api_key（路径 B 已移除）。"""
    model_id = "gpt-4o"
    cfg = FakeConfig(
        {
            "api_endpoint": "https://api.example.com/v1",
            "api_mode": "openai",
            "model": model_id,
            "default_model_id": model_id,
        },
    )
    cfg.set_custom_models(
        [
            {
                "name": "OpenAI",
                "default_model_id": model_id,
                "modelId": model_id,
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-profile-key",
                "mode": "openai",
            }
        ]
    )
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection()
    mock_probe.assert_called_once_with(
        "https://api.example.com/v1",
        "sk-profile-key",
        model_id,
        "openai-compatible",
    )


def test_probe_uses_custom_model_key_when_global_missing():
    model_id = "mimo-v2.5"
    cfg = FakeConfig(
        {
            "api_endpoint": "",
            "default_model_id": model_id,
        },
    )
    cfg.set_custom_models(
        [
            {
                "name": "MiMo",
                "default_model_id": model_id,
                "modelId": model_id,
                "endpoint": "https://api.xiaomimimo.com/v1",
                "apiKey": "sk-mimo-profile",
                "mode": "openai",
            }
        ]
    )
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection()
    mock_probe.assert_called_once_with(
        "https://api.xiaomimimo.com/v1",
        "sk-mimo-profile",
        model_id,
        "openai-compatible",
    )


def test_probe_with_masked_key_falls_back_to_profile_key():
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: MASKED_KEY 时应回退到 custom_models 档案 apiKey，
    不再回退全局 api_key（路径 B 已移除）。"""
    model_id = "mimo-v2.5"
    cfg = FakeConfig(
        {
            "api_endpoint": "https://api.example.com/v1",
            "default_model_id": model_id,
        },
    )
    cfg.set_custom_models(
        [
            {
                "name": "MiMo",
                "default_model_id": model_id,
                "modelId": model_id,
                "endpoint": "https://api.xiaomimimo.com/v1",
                "apiKey": "sk-mimo-profile",
                "mode": "openai",
            }
        ]
    )
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection(
            api_endpoint="https://api.example.com/v1",
            api_key=MASKED_KEY,
            model="gpt-4o",
            api_mode="openai",
        )
    mock_probe.assert_called_once_with(
        "https://api.example.com/v1",
        "sk-mimo-profile",
        "gpt-4o",
        "openai",
    )


def test_probe_with_masked_key_and_no_params_uses_custom_model_key():
    """无参数调用时，MASKED_KEY 仍应回退到默认自定义模型的 apiKey。"""
    model_id = "mimo-v2.5"
    cfg = FakeConfig(
        {
            "api_endpoint": "",
            "default_model_id": model_id,
        },
    )
    cfg.set_custom_models(
        [
            {
                "name": "MiMo",
                "default_model_id": model_id,
                "modelId": model_id,
                "endpoint": "https://api.xiaomimimo.com/v1",
                "apiKey": "sk-mimo-profile",
                "mode": "openai",
            }
        ]
    )
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection(api_key=MASKED_KEY)
    mock_probe.assert_called_once_with(
        "https://api.xiaomimimo.com/v1",
        "sk-mimo-profile",
        model_id,
        "openai-compatible",
    )


def test_probe_api_mode_only_does_not_override_custom_credentials():
    """仅 api_mode 非空（如旧 ProbePayload 默认 doubao）时仍用自定义模型凭证。"""
    model_id = "mimo-v2.5"
    cfg = FakeConfig(
        {
            "api_endpoint": "",
            "default_model_id": model_id,
        },
    )
    cfg.set_custom_models(
        [
            {
                "name": "MiMo",
                "default_model_id": model_id,
                "modelId": model_id,
                "endpoint": "https://api.xiaomimimo.com/v1",
                "apiKey": "sk-mimo-profile",
                "mode": "openai",
            }
        ]
    )
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection(api_mode="doubao")
    mock_probe.assert_called_once_with(
        "https://api.xiaomimimo.com/v1",
        "sk-mimo-profile",
        model_id,
        "openai-compatible",
    )


def test_probe_route_empty_body_uses_custom_model_credentials():
    """POST /api/probe {} 应解析默认自定义模型档案，而非 Pydantic 默认 api_mode。"""
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    model_id = "mimo-v2.5"
    cfg = FakeConfig(
        {
            "api_endpoint": "",
            "default_model_id": model_id,
        },
    )
    cfg.set_custom_models(
        [
            {
                "name": "MiMo",
                "default_model_id": model_id,
                "modelId": model_id,
                "endpoint": "https://api.xiaomimimo.com/v1",
                "apiKey": "sk-mimo-profile",
                "mode": "openai",
            }
        ]
    )
    host = _ProbeHost(cfg)

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app = host

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)

    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        client = TestClient(app)
        res = client.post("/api/probe", json={})
    assert res.status_code == 200
    mock_probe.assert_called_once_with(
        "https://api.xiaomimimo.com/v1",
        "sk-mimo-profile",
        model_id,
        "openai-compatible",
    )
