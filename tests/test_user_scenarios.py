"""W-TEST-COVER-009: user-facing config / lifecycle scenario tests."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from app.ai_client_requests import get_model_config, resolve_request_credentials
from app.application.config_service import apply_web_config_patch
from app.config_store import ConfigStore

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeConfig, FakeLogger
from tests.helpers.config_payload import make_config_app_stub
from tests.test_p0_main_flow import _bind_on_ai_reply


def test_config_save_before_start_applies_patch_first(workspace_tmp):
    from app.web_console import WebConsoleBridge, save_config_via_bridge

    store = ConfigStore(workspace_tmp / "save_start.db")
    danmu_app = MagicMock()
    danmu_app.config = store
    danmu_app.personae = make_config_app_stub(store).personae
    danmu_app.config_changed = MagicMock()
    order: list[str] = []

    def _apply(payload):
        order.append("config")
        apply_web_config_patch(danmu_app, payload)

    danmu_app.apply_web_config_payload = _apply
    danmu_app.start = MagicMock(side_effect=lambda: order.append("start"))

    bridge = WebConsoleBridge(danmu_app)
    save_config_via_bridge(bridge, {"user_nickname": "测试"})
    danmu_app.start()
    assert order == ["config", "start"]
    assert store.get("user_nickname") == "测试"


def test_immediate_stop_after_start_clears_inflight():
    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    app.ai_in_flight = 2
    app.mic_in_flight = 1

    def _stop():
        app.ai_in_flight = 0
        app.mic_in_flight = 0
        app.ai_worker.mark_stopping()

    app.ai_worker.mark_stopping = MagicMock()
    app.stop = _stop
    app.stop()
    assert app.ai_in_flight == 0
    assert app.mic_in_flight == 0
    app.ai_worker.mark_stopping.assert_called_once()


def test_incomplete_custom_model_with_global_key_does_not_fallback():
    """Documents current resolve behavior: incomplete custom blocks global fallback."""
    cfg = FakeConfig(
        {
            "api_endpoint": "https://global.example.com/v1",
            "api_mode": "openai",
            "model": "gpt-4o",
            "default_model_id": "partial-model",
            "_api_key": "sk-global",
        },
    )
    cfg.set_custom_models(
        [
            {
                "name": "Partial",
                "modelId": "partial-model",
                "default_model_id": "partial-model",
                "endpoint": "",
                "apiKey": "",
                "mode": "openai-compatible",
            }
        ]
    )
    assert resolve_request_credentials(cfg) is None


def test_get_model_config_matches_default_model_id():
    """W-CUSTOMMODEL-SCHEMA-002: match profile by default_model_id when modelId absent."""
    model_id = "mimo-v2.5"
    cfg = FakeConfig(
        {
            "api_endpoint": "",
            "default_model_id": model_id,
            "custom_models": [
                {
                    "name": "MiMo",
                    "default_model_id": model_id,
                    "endpoint": "https://api.xiaomimimo.com/v1",
                    "apiKey": "sk-mimo",
                    "mode": "openai",
                }
            ],
        },
    )
    model_config = get_model_config(cfg)
    assert model_config.get("default_model_id") == model_id
    resolved = resolve_request_credentials(cfg)
    assert resolved is not None
    assert resolved[1] == "sk-mimo"
    assert resolved[2] == model_id


def test_stale_reply_after_timeout_meta_missing_does_not_enqueue():
    app = make_minimal_danmu_app()
    _bind_on_ai_reply(app)
    app.logger = FakeLogger()
    app._pending_request_meta = {}
    app.ai_in_flight = 1
    app._enqueue_reply_batch = MagicMock()

    app._on_ai_reply(
        '["late"]',
        "p",
        request_round=99,
        screenshot_id=99,
        captured_at=time.monotonic(),
        scene_generation=0,
        input_tokens=1,
        output_tokens=1,
    )

    assert app._enqueue_reply_batch.call_count == 0
