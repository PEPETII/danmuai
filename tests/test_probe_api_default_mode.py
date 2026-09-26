"""Probe API connection default api_mode alignment.

W-AUDIT-PROBE-SECRET-001：通用 ``/api/probe`` 没有不可变档案身份，因此在
回落"首档案/已存 key"时，禁止与调用方显式提供的 endpoint/model/mode 组合；
越界一律拒绝（路由层 400），且不调用 probe_connection（不发任何 HTTP 请求）。
"""

from unittest.mock import MagicMock, patch

import pytest
from app.api_probe import ProbeScopeViolation
from app.main_web_facade_mixin import DanmuAppWebFacadeMixin
from app.web_api.custom_models import MASKED_KEY

from tests.fakes import FakeConfig


def _mimo_profile_config():
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
    return cfg, model_id


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


def test_probe_api_connection_passes_explicit_stage():
    host = _ProbeHost(FakeConfig({}))
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection(
            api_endpoint="https://api.example.com/v1",
            model="gpt-4o",
            api_mode="openai",
            stage="audio",
        )
    mock_probe.assert_called_once_with(
        "https://api.example.com/v1", "", "gpt-4o", "openai", stage="audio"
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


def test_probe_with_masked_key_and_changed_endpoint_is_rejected():
    """W-AUDIT-PROBE-SECRET-001：掩码 key + 替换 endpoint 必须拒绝，且不发请求。

    旧行为（W-GLOBAL-VISUAL-APIKEY-REMOVE-001）是回退档案 key 后发往调用方
    指定的 endpoint，会构成受鉴权的凭据外带原语；现改为拒绝。
    """
    cfg, _model_id = _mimo_profile_config()
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        with pytest.raises(ProbeScopeViolation) as exc:
            host.probe_api_connection(
                api_endpoint="https://api.example.com/v1",
                api_key=MASKED_KEY,
                model="gpt-4o",
                api_mode="openai",
            )
    assert exc.value.error_code == "probe_scope_violation"
    mock_probe.assert_not_called()


def test_probe_with_empty_key_and_changed_endpoint_is_rejected():
    """空 key（同样回落档案 key）+ 替换 endpoint → 拒绝，且不发请求。"""
    cfg, _model_id = _mimo_profile_config()
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        with pytest.raises(ProbeScopeViolation):
            host.probe_api_connection(
                api_endpoint="https://attacker.example.com/v1",
                model="gpt-4o",
            )
    mock_probe.assert_not_called()


def test_probe_with_masked_key_and_changed_model_is_rejected():
    """掩码 key + 档案外 model → 拒绝，且不发请求。"""
    cfg, _model_id = _mimo_profile_config()
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        with pytest.raises(ProbeScopeViolation):
            host.probe_api_connection(api_key=MASKED_KEY, model="gpt-4o")
    mock_probe.assert_not_called()


def test_probe_with_explicit_new_key_allows_changed_endpoint():
    """调用方显式提供新 key 时才允许测试新 endpoint（新配置必须自带新 key）。"""
    cfg, _model_id = _mimo_profile_config()
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection(
            api_endpoint="https://api.example.com/v1",
            api_key="sk-brand-new-caller-key",
            model="gpt-4o",
            api_mode="openai",
        )
    mock_probe.assert_called_once_with(
        "https://api.example.com/v1",
        "sk-brand-new-caller-key",
        "gpt-4o",
        "openai",
    )


def test_probe_with_masked_key_same_scope_reuses_profile_key():
    """同一档案、未修改作用域时仍可复用已存 key（不削弱合法复用路径）。"""
    cfg, model_id = _mimo_profile_config()
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection(
            api_endpoint="https://api.xiaomimimo.com/v1",
            api_key=MASKED_KEY,
            model=model_id,
            api_mode="openai-compatible",
        )
    mock_probe.assert_called_once_with(
        "https://api.xiaomimimo.com/v1",
        "sk-mimo-profile",
        model_id,
        "openai-compatible",
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


def test_probe_api_mode_only_override_is_rejected():
    """W-AUDIT-PROBE-SECRET-001（新语义）：api_mode 属于凭据作用域。

    旧行为是"非空 api_mode 被静默忽略"，等于把已存 key 与调用方显式 mode
    组合；现要求显式提供新 key，否则拒绝且不发请求。
    """
    cfg, _model_id = _mimo_profile_config()
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        with pytest.raises(ProbeScopeViolation):
            host.probe_api_connection(api_mode="doubao")
    mock_probe.assert_not_called()


def test_probe_same_mode_spelling_is_not_a_violation():
    """同一 mode 的等价写法（openai == openai-compatible）不算越界。"""
    cfg, model_id = _mimo_profile_config()
    host = _ProbeHost(cfg)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        host.probe_api_connection(api_mode="openai")
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


def _probe_http_client(host):
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app = host

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    return TestClient(app, raise_server_exceptions=False)


def test_probe_route_rejects_masked_key_with_changed_endpoint():
    """W-AUDIT-PROBE-SECRET-001：POST /api/probe 掩码 key + 替换 endpoint → 400。

    通用 /api/probe 不再从首档案恢复 key 后发往调用方指定目标；响应也不含
    已存密钥值。
    """
    cfg, _model_id = _mimo_profile_config()
    host = _ProbeHost(cfg)
    client = _probe_http_client(host)
    with patch("app.main_web_facade_mixin.probe_connection") as mock_probe:
        mock_probe.return_value = MagicMock(ok=True, message="ok", status_code=200)
        res = client.post(
            "/api/probe",
            json={
                "api_endpoint": "https://attacker.example.com/v1",
                "api_key": MASKED_KEY,
                "model": "gpt-4o",
                "api_mode": "openai",
            },
        )
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["ok"] is False
    assert detail["error"] == "probe_scope_violation"
    assert "sk-mimo-profile" not in res.text
    mock_probe.assert_not_called()
