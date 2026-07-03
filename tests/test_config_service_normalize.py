"""ConfigService._normalize_items 分支测试（W-TEST-CONFIG-NORMALIZE-001）。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.application.config_service import MASKED_API_KEY, ConfigService
from app.config_store import ConfigStore

from tests.test_config_store import _CommitCountingConn


@pytest.fixture
def config_service(tmp_path):
    config = ConfigStore(db_path=tmp_path / "normalize.db")
    app = SimpleNamespace(
        config=config,
        personae=MagicMock(),
        config_changed=MagicMock(),
    )
    return ConfigService(app)


def test_normalize_font_size_clamped(config_service):
    items = {"font_size": "9999"}
    config_service._normalize_items(items)
    assert items["font_size"] == "72"


def test_normalize_danmu_render_mode_invalid_defaults_scrolling(config_service):
    items = {"danmu_render_mode": "invalid_mode"}
    config_service._normalize_items(items)
    assert items["danmu_render_mode"] == "scrolling"


def test_normalize_pet_scale_clamped(config_service):
    items = {"pet_scale": "9.9"}
    config_service._normalize_items(items)
    assert items["pet_scale"] == "2.0"


def test_normalize_danmu_speed_invalid_defaults(config_service):
    items = {"danmu_speed": "not-a-number"}
    config_service._normalize_items(items)
    assert items["danmu_speed"] == "2"


def test_normalize_floating_panel_speed_invalid_uses_default(config_service):
    items = {"floating_panel_speed": "bad"}
    config_service._normalize_items(items)
    from app.config_defaults import DEFAULT_FLOATING_PANEL_SPEED

    assert items["floating_panel_speed"] == DEFAULT_FLOATING_PANEL_SPEED


def test_apply_web_payload_ignores_visual_api_key(config_service):
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: apply_web_payload 不再接受视觉 api_key。"""
    config_service._config.set_api_key("real-secret-key")
    config_service.apply_web_payload({"api_key": "sk-attempt-write", "danmu_speed": "2.5"})
    assert config_service._config.get_api_key() == "real-secret-key"
    assert config_service._config.get("danmu_speed") == "2.5"


def test_apply_web_payload_masks_mic_api_key_unchanged(config_service):
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: mic_api_key 仍走加密路径，MASKED 时保留原值。"""
    config_service._config.set_mic_api_key("mic-real-secret")
    config_service.apply_web_payload({"mic_api_key": MASKED_API_KEY, "danmu_speed": "2.5"})
    assert config_service._config.get_mic_api_key() == "mic-real-secret"
    assert config_service._config.get("danmu_speed") == "2.5"


def _wrap_commit_counter(config_service):
    counting = _CommitCountingConn(config_service._config.conn)
    config_service._config.conn = counting
    return counting


def test_apply_web_payload_uses_single_commit_for_normal_save(config_service):
    counting = _wrap_commit_counter(config_service)
    config_service.apply_web_payload({"danmu_speed": "2.5", "font_size": "28"})
    assert counting.commit_call_count == 1
    assert config_service._config.get("danmu_speed") == "2.5"
    assert config_service._config.get("font_size") == "28"


def test_apply_web_payload_uses_single_commit_with_mic_api_key(config_service):
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 视觉 api_key 已下线，改用 mic_api_key 验证单次提交。"""
    counting = _wrap_commit_counter(config_service)
    config_service.apply_web_payload(
        {"mic_api_key": "sk-mic-new-key-1234567890", "danmu_speed": "3"}
    )
    assert counting.commit_call_count == 1
    assert config_service._config.get_mic_api_key() == "sk-mic-new-key-1234567890"
    assert config_service._config.get("danmu_speed") == "3"


def test_normalize_persona_name_prefix_enabled_bool(config_service):
    items = {"persona_name_prefix_enabled": "true"}
    config_service._normalize_items(items)
    assert items["persona_name_prefix_enabled"] == "1"

    items = {"persona_name_prefix_enabled": "off"}
    config_service._normalize_items(items)
    assert items["persona_name_prefix_enabled"] == "0"


def test_apply_web_payload_uses_single_commit_with_custom_models(config_service):
    counting = _wrap_commit_counter(config_service)
    config_service.apply_web_payload(
        {
            "custom_models": [
                {
                    "name": "Test",
                    "modelId": "test-model",
                    "mode": "openai",
                    "endpoint": "https://api.example.com/v1",
                    "apiKey": "sk-custom-key-1234567890",
                }
            ]
        }
    )
    assert counting.commit_call_count == 1
    models = config_service._config.get_custom_models()
    assert models[0]["apiKey"] == "sk-custom-key-1234567890"


def test_apply_web_payload_syncs_default_model_id_to_legacy_model(config_service):
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: default_model_id 写入需对应完整 custom_models 档案。"""
    new_model = "doubao-seed-1-6-flash-250828"
    # 预设 default_model_id 以通过 validate_web_config_patch；model 保留旧值以验证双写同步
    config_service._config.set_batch(
        {
            "model": "old-model",
            "default_model_id": new_model,
        }
    )
    config_service._config.set_custom_models(
        [
            {
                "name": "Doubao",
                "default_model_id": new_model,
                "modelId": new_model,
                "endpoint": "https://ark.cn-beijing.volces.com/api/v3",
                "apiKey": "sk-profile",
                "mode": "doubao",
            }
        ]
    )
    config_service.apply_web_payload({"default_model_id": new_model})
    assert config_service._config.get_default_model_id() == new_model
    assert config_service._config.get("model") == new_model
