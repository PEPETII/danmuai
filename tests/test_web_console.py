"""Tests for local web console helpers."""

import time
from unittest.mock import MagicMock

import pytest
from app.web_console import (
    WEB_CONFIG_KEYS,
    WebConsoleBridge,
    apply_config_patch,
    export_config,
    extract_config_payload,
)


class FakeConfig:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self._api_key = values.get("_api_key", "") if values else ""

    def get(self, key, default=""):
        return self.values.get(key, default)

    def get_int(self, key, default=0):
        val = self.get(key)
        return int(val) if val else default

    def get_float(self, key, default=0.0):
        val = self.get(key)
        return float(val) if val else default

    def get_api_key(self):
        return self._api_key

    def set_api_key(self, key):
        self._api_key = key
        self.values["api_key_encrypted"] = "enc"

    def set_batch(self, items):
        self.values.update(items)

    def set_default_model_id(self, model_id):
        self.values["default_model_id"] = model_id

    def set(self, key, value):
        self.values[key] = value

    def get_default_model_id(self):
        return self.values.get("default_model_id", self.values.get("model", ""))

    def get_custom_models(self):
        return self.values.get("custom_models", [])

    def set_custom_models(self, models):
        self.values["custom_models"] = models


def test_export_config_masks_api_key():
    cfg = FakeConfig({"api_endpoint": "https://example.com", "_api_key": "sk-secret"})
    data = export_config(cfg)
    assert data["api_endpoint"] == "https://example.com"
    assert data["api_key"] == "********"
    assert data["has_api_key"] is True


def test_export_config_fills_defaults_for_empty_store(tmp_path):
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "fresh.db")
    data = export_config(store)
    assert data["danmu_speed"] == "2"
    assert data["danmu_lines"] == "20"
    assert data["dedup_threshold"] == "0.5"
    assert data["freshness"] == "medium"
    assert data["eviction_mode"] == "natural"
    assert data["opacity"] == "100"
    assert data["font_size"] == "24"
    assert data["hotkey"] == "Ctrl+Shift+B"


def test_export_config_masks_custom_model_api_keys():
    cfg = FakeConfig()
    cfg.set_custom_models(
        [
            {
                "name": "Test",
                "modelId": "gpt-4o",
                "apiKey": "sk-custom-secret",
                "endpoint": "https://api.example.com",
                "mode": "openai",
            }
        ]
    )
    data = export_config(cfg)
    assert len(data["custom_models"]) == 1
    assert data["custom_models"][0]["apiKey"] == "********"
    assert "sk-custom-secret" not in str(data)


def test_apply_config_patch_preserves_masked_custom_model_key():
    config = FakeConfig()
    config.set_custom_models(
        [{"name": "M", "modelId": "m", "apiKey": "sk-keep", "endpoint": "https://x", "mode": "openai"}]
    )
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "custom_models": [
                {
                    "name": "M",
                    "modelId": "m",
                    "apiKey": "********",
                    "endpoint": "https://x",
                    "mode": "openai",
                }
            ]
        },
    )

    assert config.get_custom_models()[0]["apiKey"] == "sk-keep"


def test_apply_config_patch_updates_batch_and_key():
    config = FakeConfig({"api_endpoint": "old"})
    personae = MagicMock()
    app = MagicMock()
    app.config = config
    app.personae = personae

    apply_config_patch(
        app,
        {
            "api_endpoint": "https://new.example/v1",
            "model": "gpt-4o",
            "api_key": "sk-new-key",
            "active_personae": ["路人惊讶型"],
        },
    )

    assert config.get("api_endpoint") == "https://new.example/v1"
    assert config.get("model") == "gpt-4o"
    assert config.get_default_model_id() == "gpt-4o"
    assert config.get_api_key() == "sk-new-key"
    personae.set_active.assert_called_once()
    app.config_changed.emit.assert_called_once()


def test_apply_config_patch_skips_masked_key():
    config = FakeConfig({"_api_key": "keep-me"})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"api_key": "********", "api_endpoint": "https://x.com"})

    assert config.get_api_key() == "keep-me"


def _make_status_app():
    app = MagicMock()
    app.engine.running = False
    app.engine.get_dedup_profile_snapshot.return_value = {
        "enabled": True,
        "duplicate_checks": 3,
    }
    app.danmu_count = 0
    app.reply_buffer.size.return_value = 0
    app._visible_display_count.return_value = 0
    app._start_time = 0
    app._total_input_tokens = 0
    app._total_output_tokens = 0
    app.personae.get_active.return_value = []
    app.config.get_int.return_value = 0
    app.config.get_api_key.return_value = "sk-test"
    app._web_error_message = ""
    app._web_error_is_error = False
    app.window = None
    app.session_run_log = MagicMock()
    app.session_run_log.list_dicts_newest_first.return_value = [
        {
            "started_at": 1000.0,
            "ended_at": 1060.0,
            "model": "gpt-test",
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "danmu_count": 2,
        }
    ]
    return app


def test_refresh_status_omits_dedup_profile_when_disabled(monkeypatch):
    from app.danmu_engine import reset_dedup_profile_for_tests

    monkeypatch.delenv("DANMU_DEDUP_PROFILE", raising=False)
    reset_dedup_profile_for_tests()

    bridge = WebConsoleBridge(_make_status_app())
    status = bridge.refresh_status()

    assert status.dedup_profile is None
    assert len(status.session_runs) == 1
    assert status.session_runs[0]["model"] == "gpt-test"
    bridge.danmu_app.engine.get_dedup_profile_snapshot.assert_not_called()


def test_refresh_status_includes_dedup_profile_when_enabled(monkeypatch):
    from app.danmu_engine import reset_dedup_profile_for_tests

    monkeypatch.setenv("DANMU_DEDUP_PROFILE", "1")
    reset_dedup_profile_for_tests()

    bridge = WebConsoleBridge(_make_status_app())
    status = bridge.refresh_status()

    assert status.dedup_profile == {"enabled": True, "duplicate_checks": 3}
    bridge.danmu_app.engine.get_dedup_profile_snapshot.assert_called_once()


def test_extract_config_payload_accepts_wrapped_and_flat():
    wrapped = extract_config_payload({"data": {"memory_mode": "off", "api_endpoint": "https://x"}})
    assert wrapped["memory_mode"] == "off"
    flat = extract_config_payload({"memory_mode": "scene_card"})
    assert flat["memory_mode"] == "scene_card"


def test_extract_config_payload_rejects_empty():
    with pytest.raises(ValueError, match="配置数据为空"):
        extract_config_payload({})


def test_web_config_keys_cover_core_settings():
    assert "api_endpoint" in WEB_CONFIG_KEYS
    assert "screen_index" in WEB_CONFIG_KEYS
    assert "region_x" not in WEB_CONFIG_KEYS
    assert "hotkey" in WEB_CONFIG_KEYS
    assert "danmu_speed" in WEB_CONFIG_KEYS
    assert "danmu_max_chars" in WEB_CONFIG_KEYS
    assert "freq_mode" in WEB_CONFIG_KEYS
    assert "capture_mode" in WEB_CONFIG_KEYS
    assert "danmu_pool_enabled" in WEB_CONFIG_KEYS
    assert "min_on_screen" in WEB_CONFIG_KEYS
    assert "eviction_mode" in WEB_CONFIG_KEYS
    assert "image_max_width" in WEB_CONFIG_KEYS
    assert "image_quality" in WEB_CONFIG_KEYS
    assert "scene_probe_size" in WEB_CONFIG_KEYS
    assert "memory_mode" in WEB_CONFIG_KEYS
    assert "mic_mode_enabled" in WEB_CONFIG_KEYS
    assert "mic_window_sec" in WEB_CONFIG_KEYS
    assert "reply_scene_count" in WEB_CONFIG_KEYS
    assert "reply_filler_count" in WEB_CONFIG_KEYS


def test_web_config_keys_include_display_mode_settings():
    assert "danmu_display_mode" in WEB_CONFIG_KEYS
    assert "normal_recognition_interval_sec" in WEB_CONFIG_KEYS
    assert "normal_reply_count" in WEB_CONFIG_KEYS


def test_model_catalog_api_payload():
    """Contract for GET /api/model-catalog (implemented via list_platform_catalogs)."""
    from app.model_catalog import list_platform_catalogs

    platforms = list_platform_catalogs()
    assert len(platforms) == 3
    by_id = {p["platform_id"]: p for p in platforms}

    doubao = by_id["doubao"]
    assert doubao["provider_id"] == "doubao"
    assert len(doubao["models"]) == 6
    doubao_cheapest = [m for m in doubao["models"] if m["cheapest"]]
    assert len(doubao_cheapest) == 1
    assert doubao_cheapest[0]["id"] == "doubao-seed-1-6-flash-250828"
    doubao_mic = {m["id"] for m in doubao["models"] if m["supports_mic"]}
    assert doubao_mic == {
        "doubao-seed-2-0-lite-260428",
        "doubao-seed-2-0-mini-260428",
    }

    dashscope = by_id["dashscope"]
    assert dashscope["provider_id"] == "dashscope"
    assert len(dashscope["models"]) == 8
    dash_cheapest = [m for m in dashscope["models"] if m["cheapest"]]
    assert len(dash_cheapest) == 1
    assert dash_cheapest[0]["id"] == "qwen3-vl-flash"
    dash_mic = {m["id"] for m in dashscope["models"] if m["supports_mic"]}
    assert dash_mic == {"qwen-omni-turbo", "qwen2.5-omni-7b"}

    siliconflow = by_id["siliconflow"]
    assert siliconflow["platform_label"] == "轨迹流动"
    assert len(siliconflow["models"]) == 9
    sf_cheapest = [m for m in siliconflow["models"] if m["cheapest"]]
    assert len(sf_cheapest) == 1
    assert sf_cheapest[0]["id"] == "Qwen/Qwen3-VL-8B-Instruct"


def test_apply_config_patch_clamps_display_mode_settings():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "danmu_display_mode": "invalid",
            "normal_recognition_interval_sec": "0",
            "normal_reply_count": "99",
        },
    )

    assert config.get("danmu_display_mode") == "realtime"
    assert config.get("normal_recognition_interval_sec") == "1"
    assert config.get("normal_reply_count") == "20"


def test_apply_config_patch_clamps_danmu_lines():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"danmu_lines": "5"})
    assert config.get("danmu_lines") == "12"

    apply_config_patch(app, {"danmu_lines": "25"})
    assert config.get("danmu_lines") == "20"

    apply_config_patch(app, {"danmu_lines": "16"})
    assert config.get("danmu_lines") == "16"


def test_apply_config_patch_clamps_reply_counts():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"reply_scene_count": "1", "reply_filler_count": "99"})

    assert config.get("reply_scene_count") == "2"
    assert config.get("reply_filler_count") == "7"


def test_apply_config_patch_validates_memory_settings():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "memory_mode": "evil",
            "memory_clear_policy": "bogus",
            "memory_window": "abc",
        },
    )

    assert config.get("memory_mode") == "off"
    assert config.get("memory_clear_policy") == "medium"
    assert config.get("memory_window") == "10"
    assert "evil" not in config.values.values()
    assert "bogus" not in config.values.values()
    assert "abc" not in config.values.values()

    apply_config_patch(app, {"memory_window": "-1"})
    assert config.get("memory_window") == "1"

    apply_config_patch(app, {"memory_window": "0"})
    assert config.get("memory_window") == "1"

    apply_config_patch(app, {"memory_window": "999"})
    assert config.get("memory_window") == "20"

    apply_config_patch(
        app,
        {
            "memory_mode": "scene_card",
            "memory_clear_policy": "strict",
            "memory_window": "15",
        },
    )
    assert config.get("memory_mode") == "scene_card"
    assert config.get("memory_clear_policy") == "strict"
    assert config.get("memory_window") == "15"

    apply_config_patch(app, {"memory_mode": "dedup_only"})
    assert config.get("memory_mode") == "dedup_only"

    apply_config_patch(app, {"memory_mode": "strong"})
    assert config.get("memory_mode") == "strong"


def test_list_recent_logs_filters_by_since_ts():
    app = _make_status_app()
    app.logger = MagicMock()
    bridge = WebConsoleBridge(app)
    bridge._log_ring.append(("INFO", "older", 10.0))
    bridge._log_ring.append(("WARNING", "newer", 20.0))

    items = bridge.list_recent_logs(15.0)

    assert len(items) == 1
    assert items[0]["level"] == "WARNING"
    assert items[0]["message"] == "newer"
    assert items[0]["ts"] == 20.0


def test_register_status_consumer_logs_consumer_count():
    app = _make_status_app()
    app.logger = MagicMock()
    bridge = WebConsoleBridge(app)
    queue = __import__("asyncio").Queue(maxsize=4)
    bridge.register_status_consumer(queue)
    bridge.unregister_status_consumer(queue)
    debug_calls = [str(c) for c in app.logger.debug.call_args_list]
    assert any("register_status_consumer consumers=1" in c for c in debug_calls)
    assert any("unregister_status_consumer consumers=0" in c for c in debug_calls)


def test_enqueue_ws_replaces_oldest_on_full_queue():
    import asyncio

    from app.web_console import _enqueue_ws

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[int] = asyncio.Queue(maxsize=2)
        queue.put_nowait(1)
        queue.put_nowait(2)
        _enqueue_ws(loop, queue, 3)
        await asyncio.sleep(0.02)
        first = queue.get_nowait()
        second = queue.get_nowait()
        assert first == 2
        assert second == 3

    asyncio.run(_run())


def test_web_console_wait_ready_fails_fast_when_bind_failed():
    import threading

    from app.web_console import WebConsoleBridge, WebConsoleServer

    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)

    def _fail_without_ready() -> None:
        time.sleep(0.02)
        server._bind_failed.set()

    server._thread = threading.Thread(target=_fail_without_ready, daemon=True)
    server._thread.start()

    started = time.monotonic()
    assert server.wait_ready(timeout=2.0) is False
    assert time.monotonic() - started < 1.0


def test_web_console_server_stop_schedules_shutdown_callback():
    from app.web_console import WebConsoleBridge, WebConsoleServer

    class _FakeUvicornServer:
        should_exit = False

    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._server = _FakeUvicornServer()
    loop = MagicMock()
    server._loop = loop

    server.stop()

    loop.call_soon_threadsafe.assert_called_once()
    callback = loop.call_soon_threadsafe.call_args[0][0]
    assert callable(callback)
    callback()
    assert server._server.should_exit is True


def test_probe_route_accepts_json_body(monkeypatch):
    """Regression: /api/probe in web_console._run nested scope caused query: Field required 422."""
    from app.api_probe import ProbeResult
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "doubao-test",
            "api_mode": "doubao",
            "_api_key": "sk-test",
        }
    )

    def _check_token(_authorization: str | None = None) -> None:
        return None

    monkeypatch.setattr(
        "app.api_probe.probe_connection",
        lambda endpoint, api_key, model_id, mode: ProbeResult(True, "连接成功"),
    )
    register_web_routes(app, bridge, _check_token)

    client = TestClient(app)
    res = client.post(
        "/api/probe",
        json={
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": "sk-test",
            "model": "doubao-test",
            "api_mode": "doubao",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["message"] == "连接成功"


def test_session_route_does_not_require_query_request():
    """Regression: Request in nested scope with postponed annotations caused query.request 422."""
    from fastapi import FastAPI, Header
    from fastapi.testclient import TestClient

    app = FastAPI()
    token = "test-token"
    fallback = "http://127.0.0.1:18765"

    @app.get("/api/session")
    def read_console_session(host: str | None = Header(default=None)):
        host = (host or "").strip()
        base_url = f"http://{host}" if host else fallback
        return {"token": token, "base_url": base_url}

    client = TestClient(app)
    res = client.get("/api/session", headers={"host": "127.0.0.1:18765"})
    assert res.status_code == 200
    body = res.json()
    assert body["token"] == token
    assert body["base_url"] == "http://127.0.0.1:18765"
