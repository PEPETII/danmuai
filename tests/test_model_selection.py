"""Tests for model/provider selection validation and status projection."""

from __future__ import annotations

import pytest
from app.model_catalog import default_catalog_model_id
from app.model_providers import is_model_config_complete, resolve_active_model_id
from app.model_selection import (
    infer_provider_id,
    resolve_model_status,
    validate_global_model_selection,
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

    def get_default_model_id(self):
        mid = self._data.get("default_model_id", "")
        return mid or self._data.get("model", "")

    def get_custom_models(self):
        return list(self._data.get("custom_models", []))


def test_infer_provider_id_from_dashscope_endpoint():
    endpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert infer_provider_id(endpoint, "openai") == "dashscope"


def test_validate_rejects_known_catalog_model_on_wrong_provider():
    with pytest.raises(ValueError, match="平台与模型不匹配|Provider and model"):
        validate_global_model_selection(
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "openai",
            "doubao-seed-1-6-flash-250828",
            [],
        )


def test_validate_web_config_rejects_doubao_mode_with_openai_host():
    cfg = _Cfg(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "model": "qwen-plus",
        }
    )
    with pytest.raises(ValueError, match="不匹配|does not match"):
        validate_web_config_patch(
            cfg,
            {"api_mode": "doubao"},
        )


def test_validate_allows_dashscope_catalog_model():
    dash_model = default_catalog_model_id("dashscope")
    validate_global_model_selection(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "openai",
        dash_model,
        [],
    )


def test_validate_allows_freeform_model_for_catalog_provider():
    validate_global_model_selection(
        "https://ark.cn-beijing.volces.com/api/v3",
        "doubao",
        "ep-20260618-custom-vision",
        [],
    )


def test_validate_web_config_allows_freeform_model_for_catalog_provider():
    cfg = _Cfg(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": "doubao-seed-1-6-flash-250828",
        }
    )
    validate_web_config_patch(
        cfg,
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": "ep-20260618-custom-vision",
        },
    )


def test_validate_rejects_global_save_when_model_id_reserved_for_custom():
    custom = [
        {
            "name": "My Flash",
            "modelId": "doubao-seed-1-6-flash-250828",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-test",
            "mode": "openai",
        }
    ]
    with pytest.raises(ValueError, match="模型配置档案|Model Profiles"):
        validate_global_model_selection(
            "https://ark.cn-beijing.volces.com/api/v3",
            "doubao",
            "doubao-seed-1-6-flash-250828",
            custom,
        )


def test_validate_allows_zhipu_freeform_model_id():
    validate_global_model_selection(
        "https://open.bigmodel.cn/api/paas/v4",
        "openai",
        "glm-4v-flash",
        [],
    )


def test_validate_web_config_patch_rejects_invalid_endpoint():
    cfg = _Cfg(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": "doubao-seed-1-6-flash-250828",
        }
    )
    with pytest.raises(ValueError, match="http://|https://|Invalid API|格式无效"):
        validate_web_config_patch(cfg, {"api_endpoint": "ark.cn-beijing.volces.com/api/v3"})


def test_validate_web_config_patch_allows_valid_endpoint_change():
    cfg = _Cfg(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": "doubao-seed-1-6-flash-250828",
        }
    )
    validate_web_config_patch(
        cfg,
        {"api_endpoint": "https://ark.cn-beijing.volces.com/api/v3/"},
    )


def test_validate_web_config_patch_rejects_empty_endpoint():
    cfg = _Cfg(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": "doubao-seed-1-6-flash-250828",
        }
    )
    with pytest.raises(ValueError, match="API Endpoint|endpoint"):
        validate_web_config_patch(cfg, {"api_endpoint": ""})


def test_visual_api_endpoint_issue_flags_empty_global_endpoint():
    cfg = _Cfg(
        {
            "api_endpoint": "",
            "api_mode": "doubao",
            "model": "doubao-seed-1-6-flash-250828",
            "_api_key": "sk-test",
        }
    )
    assert visual_api_endpoint_issue(cfg) is not None


def test_validate_web_config_patch_merges_payload_with_existing_config():
    cfg = _Cfg(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "model": "doubao-seed-1-6-flash-250828",
            "default_model_id": "doubao-seed-1-6-flash-250828",
        }
    )
    with pytest.raises(ValueError):
        validate_web_config_patch(cfg, {"api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1"})


def test_validate_web_config_patch_allows_active_custom_model_save():
    model_id = "my-custom-vision"
    cfg = _Cfg(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": model_id,
            "default_model_id": model_id,
            "custom_models": [
                {
                    "name": "Custom Vision",
                    "modelId": model_id,
                    "endpoint": "https://custom.example/v1",
                    "apiKey": "sk-test",
                    "mode": "openai",
                }
            ],
        }
    )
    validate_web_config_patch(
        cfg,
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": model_id,
        },
    )


def test_resolve_model_status_catalog_display_name():
    dash_model = default_catalog_model_id("dashscope")
    cfg = _Cfg(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "default_model_id": dash_model,
            "model": dash_model,
        }
    )
    status = resolve_model_status(cfg)
    assert status["active_model_id"] == dash_model
    assert status["model_source"] == "catalog"
    assert status["uses_custom_credentials"] is False
    assert status["provider_model_mismatch"] is False
    assert status["model_display_name"]
    assert status["model_display_name"] != ""


def test_resolve_model_status_mismatch_flag():
    cfg = _Cfg(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "default_model_id": "doubao-seed-1-6-flash-250828",
            "model": "doubao-seed-1-6-flash-250828",
        }
    )
    status = resolve_model_status(cfg)
    assert status["provider_model_mismatch"] is True
    assert status["model_source"] == "freeform"


def test_resolve_model_status_custom_credentials():
    model_id = "my-custom-vision"
    cfg = _Cfg(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "default_model_id": model_id,
            "model": model_id,
            "custom_models": [
                {
                    "name": "Custom Vision",
                    "modelId": model_id,
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


def test_apply_config_patch_rejects_mismatched_model():
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

    with pytest.raises(ValueError):
        apply_config_patch(
            app,
            {
                "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_mode": "openai",
                "model": "doubao-seed-1-6-flash-250828",
            },
        )

    assert config.get("model") == "doubao-seed-1-6-flash-250828"
    assert config.get_default_model_id() != default_catalog_model_id("dashscope")
