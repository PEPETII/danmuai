"""Probe API connection default api_mode alignment."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.main_web_facade_mixin import DanmuAppWebFacadeMixin

from app.web_api.custom_models import MASKED_KEY

from tests.fakes import FakeConfig


class _ProbeHost(DanmuAppWebFacadeMixin):
    def __init__(self, config):
        self.config = config


def test_probe_api_connection_uses_config_default_openai_mode():
    host = _ProbeHost(SimpleNamespace(
        get_api_key=MagicMock(return_value="sk-test"),
        get_default_model_id=MagicMock(return_value=""),
        get_custom_models=MagicMock(return_value=[]),
        get=MagicMock(side_effect=lambda k, d="": {"api_endpoint": "https://api.example.com/v1", "api_mode": "openai", "model": "gpt-4o"}.get(k, d)),
    ))
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection()
    mock_probe.assert_called_once_with(
        "https://api.example.com/v1",
        "sk-test",
        "gpt-4o",
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


def test_probe_with_masked_key_and_explicit_endpoint_uses_global_key():
    """Regression: 【API 与模型】界面测试时，MASKED_KEY 应回退到全局 api_key，而非默认自定义模型的 apiKey。"""
    model_id = "mimo-v2.5"
    cfg = FakeConfig(
        {
            "api_endpoint": "https://api.example.com/v1",
            "api_key": "sk-global",
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
        "sk-global",
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
