"""Tests for model/provider selection validation and status projection."""

from __future__ import annotations

import pytest
from app.model_providers import is_model_config_complete, resolve_active_model_id
from app.model_selection import (
    infer_provider_id,
    resolve_model_status,
    validate_web_config_patch,
    visual_api_endpoint_issue,
)
from app.web_console import apply_config_patch


class _Cfg:
    def __init__(self, data=None, *, custom_models=None):
        self._data = dict(data or {})
        if custom_models is not None:
            self._data["custom_models"] = custom_models

    def get(self, key, default=""):
        return self._data.get(key, default)

    def get_custom_models(self):
        return list(self._data.get("custom_models", []))


def test_infer_provider_id_from_dashscope_endpoint():
    endpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert infer_provider_id(endpoint, "openai") == "dashscope"


def test_validate_web_config_ignores_retired_global_model_fields():
    """旧客户端提交 model/api 字段时，不再触发全局模型校验。"""
    cfg = _Cfg(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "model": "qwen-plus",
        }
    )
    validate_web_config_patch(
        cfg,
        {
            "api_endpoint": "not-used-by-visual-selection",
            "api_mode": "doubao",
            "model": "not-a-global-model",
            "default_model_id": "not-a-global-model",
        },
    )


def test_validate_web_config_patch_validates_independent_mic_endpoint():
    cfg = _Cfg({"mic_use_visual_model": "0"})
    with pytest.raises(ValueError, match="API Endpoint|endpoint"):
        validate_web_config_patch(cfg, {"mic_use_visual_model": "0", "mic_api_endpoint": ""})


def test_visual_api_endpoint_issue_flags_missing_first_profile():
    cfg = _Cfg(
        {
            "api_endpoint": "",
            "api_mode": "doubao",
            "model": "doubao-seed-1-6-flash-250828",
            "_api_key": "sk-test",
        }
    )
    assert visual_api_endpoint_issue(cfg) is not None


def test_validate_web_config_patch_allows_active_custom_model_save():
    model_id = "my-custom-vision"
    cfg = _Cfg(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": model_id,
            "custom_models": [
                {
                    "name": "Custom Vision",
                    "modelId": model_id,
                    "model_ids": [model_id],
                    "default_model_id": model_id,
                    "endpoint": "https://custom.example/v1",
                    "apiKey": "sk-test",
                    "mode": "openai",
                }
            ],
        }
    )
    validate_web_config_patch(
        cfg,
        {"model": model_id, "default_model_id": model_id},
    )


def test_resolve_model_status_without_profiles_has_no_active_model():
    cfg = _Cfg(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "stale-global-model",
        }
    )
    status = resolve_model_status(cfg)
    assert status["active_model_id"] == ""
    assert status["model_source"] == "unknown"
    assert status["uses_custom_credentials"] is False


def test_resolve_model_status_custom_credentials():
    model_id = "my-custom-vision"
    cfg = _Cfg(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "custom_models": [
                {
                        "name": "Custom Vision",
                        "modelId": model_id,
                        "model_ids": [model_id],
                        "default_model_id": model_id,
                    "endpoint": "https://custom.example/v1",
                    "apiKey": "sk-x",
                    "mode": "openai",
                }
            ],
        }
    )
    status = resolve_model_status(cfg)
    assert status["uses_custom_credentials"] is True
    assert status["model_source"] == "custom"
    assert status["model_display_name"] == "Custom Vision"
    assert resolve_active_model_id(cfg) == model_id
    assert is_model_config_complete(cfg.get_custom_models()[0])


def test_apply_config_patch_ignores_retired_global_model_payload():
    from unittest.mock import MagicMock

    from tests.fakes import FakeConfig

    config = FakeConfig(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "model": "doubao-seed-1-6-flash-250828",
        }
    )
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "model": "doubao-seed-1-6-flash-250828",
        },
    )

    assert config.get("model") == "doubao-seed-1-6-flash-250828"
