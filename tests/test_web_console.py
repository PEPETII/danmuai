"""Tests for local web console helpers."""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.application.generation_pipeline_state import GenerationPipelineState
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.web_console import (
    WEB_CONFIG_KEYS,
    WebConsoleBridge,
    apply_config_patch,
    export_config,
    extract_config_payload,
    save_config_via_bridge,
)
from main import DanmuApp


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

    def get_region(self):
        return (
            self.get_int("region_x", 0),
            self.get_int("region_y", 0),
            self.get_int("region_w", 0),
            self.get_int("region_h", 0),
        )

    def set_region(self, x, y, w, h):
        self.values["region_x"] = str(x)
        self.values["region_y"] = str(y)
        self.values["region_w"] = str(w)
        self.values["region_h"] = str(h)

    def get_json(self, key: str, default=None):
        val = self.get(key)
        if not val:
            return default if default is not None else {}
        return json.loads(val)

    def set_json(self, key: str, value):
        self.values[key] = json.dumps(value, ensure_ascii=False)


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
    assert data["normal_recognition_interval_sec"] == "5"
    assert data["normal_reply_count"] == "5"
    assert "freshness" not in data
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


def test_apply_config_patch_skips_blank_key():
    config = FakeConfig({"_api_key": "keep-me"})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"api_key": "   ", "api_endpoint": "https://x.com"})

    assert config.get_api_key() == "keep-me"


def test_apply_config_patch_preserves_masked_custom_model_key_by_identity():
    config = FakeConfig()
    config.set_custom_models(
        [
            {"name": "A", "modelId": "model-a", "apiKey": "sk-a", "endpoint": "https://a", "mode": "openai"},
            {"name": "B", "modelId": "model-b", "apiKey": "sk-b", "endpoint": "https://b", "mode": "openai"},
        ]
    )
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "custom_models": [
                {"name": "B", "modelId": "model-b", "apiKey": "********", "endpoint": "https://b2", "mode": "openai"},
                {"name": "A", "modelId": "model-a", "apiKey": "********", "endpoint": "https://a2", "mode": "openai"},
            ]
        },
    )

    models = config.get_custom_models()
    assert models[0]["apiKey"] == "sk-b"
    assert models[1]["apiKey"] == "sk-a"


def _make_status_app():
    app = MagicMock()
    app.build_status_snapshot.return_value = {
        "running": False,
        "danmu_count": 0,
        "queue_count": 0,
        "display_count": 0,
        "total_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "runtime_sec": 0.0,
        "error_message": "",
        "is_error": False,
        "live_analyzing": False,
        "live_local_fallback": False,
        "live_delay_sec": 0.0,
        "live_stale_drops": 0,
        "live_message": "",
        "persona_names": [],
        "screen_index": 0,
        "has_api_key": True,
        "dedup_profile": None,
        "lifetime_danmu_count": 0,
        "lifetime_runtime_sec": 0.0,
        "lifetime_total_tokens": 0,
        "lifetime_input_tokens": 0,
        "lifetime_output_tokens": 0,
        "session_runs": [
            {
                "started_at": 1000.0,
                "ended_at": 1060.0,
                "model": "gpt-test",
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "danmu_count": 2,
            }
        ],
    }
    return app


def test_refresh_status_uses_public_status_snapshot():
    bridge = WebConsoleBridge(_make_status_app())
    status = bridge.refresh_status()

    assert status.dedup_profile is None
    assert len(status.session_runs) == 1
    assert status.session_runs[0]["model"] == "gpt-test"
    bridge.danmu_app.build_status_snapshot.assert_called_once()


def test_build_status_snapshot_delegates_to_builder(monkeypatch):
    calls = []

    class FakeBuilder:
        def __init__(self, app):
            calls.append(app)

        def build(self):
            return {"running": True}

    monkeypatch.setattr("main.StatusSnapshotBuilder", FakeBuilder)
    app = SimpleNamespace()

    status = DanmuApp.build_status_snapshot(app)

    assert status == {"running": True}
    assert calls == [app]


def test_build_status_snapshot_omits_dedup_profile_when_disabled(monkeypatch):
    from app.danmu_engine import reset_dedup_profile_for_tests

    app = SimpleNamespace(
        engine=SimpleNamespace(running=False, get_dedup_profile_snapshot=MagicMock(return_value={"enabled": True})),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        _visible_display_count=lambda: 0,
        _total_input_tokens=0,
        _total_output_tokens=0,
        _start_time=0.0,
        _web_error_message="",
        _web_error_is_error=False,
        danmu_count=0,
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "0", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        _build_live_status_snapshot=lambda: None,
    )

    monkeypatch.delenv("DANMU_DEDUP_PROFILE", raising=False)
    reset_dedup_profile_for_tests()

    status = DanmuApp.build_status_snapshot(app)

    assert status["dedup_profile"] is None
    app.engine.get_dedup_profile_snapshot.assert_not_called()


def test_build_status_snapshot_includes_dedup_profile_when_enabled(monkeypatch):
    from app.danmu_engine import reset_dedup_profile_for_tests

    app = SimpleNamespace(
        engine=SimpleNamespace(
            running=True,
            get_dedup_profile_snapshot=MagicMock(
                return_value={"enabled": True, "duplicate_checks": 3}
            ),
        ),
        reply_buffer=SimpleNamespace(size=lambda: 2),
        _visible_display_count=lambda: 1,
        _total_input_tokens=7,
        _total_output_tokens=5,
        _start_time=time.monotonic() - 3.0,
        _web_error_message="",
        _web_error_is_error=False,
        danmu_count=4,
        personae=SimpleNamespace(get_active=lambda: ["吐槽型"]),
        config=FakeConfig({"screen_index": "1", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {"lifetime_total_tokens": 12}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        _build_live_status_snapshot=lambda: SimpleNamespace(
            analyzing=True,
            local_fallback=False,
            delay_sec=1.2,
            stale_drops=2,
            primary_message=lambda: "analyzing",
        ),
    )

    monkeypatch.setenv("DANMU_DEDUP_PROFILE", "1")
    reset_dedup_profile_for_tests()

    status = DanmuApp.build_status_snapshot(app)

    assert status["dedup_profile"] == {"enabled": True, "duplicate_checks": 3}
    assert status["live_message"] == "analyzing"
    app.engine.get_dedup_profile_snapshot.assert_called_once()


def test_build_status_snapshot_prefers_web_runtime_state_cache_and_keeps_output_compatible():
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        _visible_display_count=lambda: 0,
        stats_state=StatsState(danmu_count=2, total_input_tokens=5, total_output_tokens=4),
        web_runtime_state=WebRuntimeState(
            error_message="warn",
            is_error=True,
            cached_danmu_lines=18,
            cached_layout_mode="windowed",
        ),
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "0", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        _build_live_status_snapshot=lambda: None,
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["error_message"] == "warn"
    assert status["is_error"] is True
    assert status["total_tokens"] == 9
    assert "cached_danmu_lines" not in status
    assert "cached_layout_mode" not in status


def test_build_status_snapshot_collects_generation_projection_without_exposing_new_fields():
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        _visible_display_count=lambda: 0,
        stats_state=StatsState(),
        web_runtime_state=WebRuntimeState(),
        _active_scene_probe_size=24,
        _scene_generation_bumped_at=12.5,
        _last_activity_collect_at=7.5,
        _latest_displayed_round=9,
        _latest_requested_screenshot_id=11,
        _latest_queued_screenshot_id=10,
        _latest_displayed_screenshot_id=8,
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "0", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        _build_live_status_snapshot=lambda: None,
    )

    runtime_state = GenerationPipelineState.from_app(app)
    status = DanmuApp.build_status_snapshot(app)

    assert runtime_state.active_scene_probe_size == 24
    assert runtime_state.scene_generation_bumped_at == 12.5
    assert runtime_state.last_activity_collect_at == 7.5
    assert runtime_state.latest_displayed_round == 9
    assert runtime_state.latest_requested_screenshot_id == 11
    assert runtime_state.latest_queued_screenshot_id == 10
    assert runtime_state.latest_displayed_screenshot_id == 8
    assert "active_scene_probe_size" not in status
    assert "scene_generation_bumped_at" not in status
    assert "latest_displayed_round" not in status
    assert "latest_requested_screenshot_id" not in status
    assert "latest_queued_screenshot_id" not in status
    assert "latest_displayed_screenshot_id" not in status


def test_build_status_snapshot_prefers_state_objects_when_present():
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        _visible_display_count=lambda: 0,
        stats_state=StatsState(
            danmu_count=9,
            total_input_tokens=13,
            total_output_tokens=8,
            start_time=0.0,
        ),
        web_runtime_state=WebRuntimeState(error_message="web failed", is_error=True),
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "2", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        _build_live_status_snapshot=lambda: None,
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["danmu_count"] == 9
    assert status["input_tokens"] == 13
    assert status["output_tokens"] == 8
    assert status["total_tokens"] == 21
    assert status["error_message"] == "web failed"
    assert status["is_error"] is True


def test_bridge_save_config_uses_public_app_entry():
    app = _make_status_app()
    bridge = WebConsoleBridge(app)

    bridge._on_save_config({"api_endpoint": "https://new.example/v1"})

    app.apply_web_config_payload.assert_called_once_with({"api_endpoint": "https://new.example/v1"})
    assert app.build_status_snapshot.call_count >= 1


def test_save_config_via_bridge_returns_success_after_main_thread_ack():
    app = _make_status_app()
    bridge = WebConsoleBridge(app)

    result = save_config_via_bridge(bridge, {"api_endpoint": "https://new.example/v1"})

    assert result == {"ok": True}
    app.apply_web_config_payload.assert_called_once_with(
        {"api_endpoint": "https://new.example/v1"}
    )


def test_save_config_via_bridge_returns_timeout_when_main_thread_does_not_ack():
    bridge = SimpleNamespace(
        save_config_requested=SimpleNamespace(emit=lambda _payload: None),
        danmu_app=SimpleNamespace(logger=MagicMock()),
    )

    result = save_config_via_bridge(
        bridge,
        {"api_endpoint": "https://slow.example/v1"},
        timeout_sec=0.01,
    )

    assert result["ok"] is False
    assert result["error"] == "save_timeout"
    assert "超时" in result["detail"]
    bridge.danmu_app.logger.error.assert_called_once()


def test_save_config_via_bridge_returns_failure_when_main_thread_save_raises():
    app = _make_status_app()
    app.apply_web_config_payload.side_effect = RuntimeError("db broken")
    bridge = WebConsoleBridge(app)

    result = save_config_via_bridge(bridge, {"api_endpoint": "https://broken.example/v1"})

    assert result["ok"] is False
    assert result["error"] == "save_failed"
    assert "db broken" in result["detail"]
    app.apply_web_config_payload.assert_called_once_with(
        {"api_endpoint": "https://broken.example/v1"}
    )


def test_apply_config_patch_syncs_default_model_id_to_legacy_model():
    config = FakeConfig({"model": "old-model"})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"default_model_id": "model-b"})

    assert config.get_default_model_id() == "model-b"
    assert config.get("model") == "model-b"


def test_web_status_timer_lifecycle_public_api():
    first = MagicMock()
    second = MagicMock()
    app = SimpleNamespace()

    attached = DanmuApp.attach_web_status_timer(app, first)
    DanmuApp.attach_web_status_timer(app, second)
    DanmuApp.stop_web_status_timer(app)
    detached = DanmuApp.detach_web_status_timer(app)

    assert attached is first
    first.stop.assert_called_once_with()
    second.stop.assert_called_once_with()
    assert detached is second
    assert getattr(app, "_web_status_timer", None) is None


def test_resolve_request_credentials_public_wrapper():
    app = SimpleNamespace(ai_worker=MagicMock())
    app.ai_worker._resolve_request_credentials.return_value = ("https://x", "sk", "model", "doubao")

    resolved = DanmuApp.resolve_request_credentials(app)

    assert resolved == ("https://x", "sk", "model", "doubao")
    app.ai_worker._resolve_request_credentials.assert_called_once_with()


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
    assert "freq_mode" not in WEB_CONFIG_KEYS
    assert "capture_mode" not in WEB_CONFIG_KEYS
    assert "danmu_pool_enabled" not in WEB_CONFIG_KEYS
    assert "min_on_screen" not in WEB_CONFIG_KEYS
    assert "eviction_mode" in WEB_CONFIG_KEYS
    assert "image_max_width" in WEB_CONFIG_KEYS
    assert "image_quality" in WEB_CONFIG_KEYS
    assert "scene_probe_size" not in WEB_CONFIG_KEYS
    assert "memory_mode" in WEB_CONFIG_KEYS
    assert "mic_mode_enabled" in WEB_CONFIG_KEYS
    assert "mic_window_sec" in WEB_CONFIG_KEYS
    assert "reply_scene_count" not in WEB_CONFIG_KEYS
    assert "reply_filler_count" not in WEB_CONFIG_KEYS
    assert "danmu_display_mode" not in WEB_CONFIG_KEYS
    assert "normal_recognition_interval_sec" in WEB_CONFIG_KEYS
    assert "normal_reply_count" in WEB_CONFIG_KEYS


def test_export_web_config_defaults():
    from app.application.config_service import RESTORABLE_CONFIG_KEYS, WEB_CONFIG_KEYS
    from app.config_defaults import CONFIG_DEFAULTS, export_web_config_defaults
    from app.model_catalog import default_catalog_model_id
    from app.model_providers import get_provider

    data = export_web_config_defaults()

    assert set(data.keys()) == set(WEB_CONFIG_KEYS)
    assert RESTORABLE_CONFIG_KEYS == WEB_CONFIG_KEYS
    assert "api_key" not in data
    assert "has_api_key" not in data
    assert "custom_models" not in data

    doubao = get_provider("doubao")
    assert data["api_endpoint"] == doubao.default_endpoint
    assert data["api_mode"] == "doubao"
    assert data["model"] == default_catalog_model_id("doubao")

    for key in WEB_CONFIG_KEYS:
        if key in ("api_endpoint", "model"):
            continue
        assert data[key] == CONFIG_DEFAULTS.get(key, ""), key


def test_model_catalog_api_payload():
    """Contract for GET /api/model-catalog (implemented via list_platform_catalogs)."""
    from app.model_catalog import list_platform_catalogs

    platforms = list_platform_catalogs()
    assert len(platforms) == 4
    by_id = {p["platform_id"]: p for p in platforms}

    doubao = by_id["doubao"]
    assert doubao["provider_id"] == "doubao"
    assert len(doubao["models"]) == 5
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
    assert len(dashscope["models"]) == 6
    dash_cheapest = [m for m in dashscope["models"] if m["cheapest"]]
    assert len(dash_cheapest) == 1
    assert dash_cheapest[0]["id"] == "qwen3-vl-flash"
    dash_mic = {m["id"] for m in dashscope["models"] if m["supports_mic"]}
    assert dash_mic == set()

    siliconflow = by_id["siliconflow"]
    assert siliconflow["platform_label"] == "硅基流动"
    assert len(siliconflow["models"]) == 9
    sf_cheapest = [m for m in siliconflow["models"] if m["cheapest"]]
    assert len(sf_cheapest) == 1
    assert sf_cheapest[0]["id"] == "Qwen/Qwen3-VL-8B-Instruct"

    mimo = by_id["mimo"]
    assert mimo["provider_id"] == "mimo"
    assert mimo["default_model_id"] == "mimo-v2.5"
    assert len(mimo["models"]) == 1
    mimo_ids = {m["id"] for m in mimo["models"]}
    assert mimo_ids == {"mimo-v2.5"}
    assert mimo["models"][0]["supports_mic"] is True


def test_providers_excludes_deepseek():
    """GET /api/providers is built from PROVIDERS; DeepSeek is not an official preset."""
    from app.model_providers import PROVIDERS

    ids = [p.id for p in PROVIDERS]
    assert "deepseek" not in ids
    assert "doubao" in ids
    assert "dashscope" in ids
    assert "siliconflow" in ids
    assert "mimo" in ids
    assert "custom_openai" in ids


def test_web_settings_ui_uses_custom_wording_not_manual_fill():
    from app.bundle_paths import project_root

    root = project_root()
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "手动填写" not in html
    assert "手动输入" not in html
    assert "手动填写" not in app_js
    assert "手动输入" not in app_js
    assert 'value="">自定义</option>' in html or ">自定义</option>" in html
    assert "自定义模型" in app_js
    assert '选「自定义」则需自己逐项设置' in app_js


def test_web_app_js_provider_switch_resets_vision_model():
    from app.bundle_paths import project_root

    app_js = (project_root() / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "function pickDefaultCatalogModelId" in app_js
    assert "platform.default_model_id" in app_js
    assert "providerSwitch: true" in app_js
    assert "function syncProviderPresetFromEndpoint" in app_js
    assert "function resolveProviderIdForPicker" in app_js
    assert "renderVisionModelPicker(resolveProviderIdForPicker()" in app_js
    assert "syncProviderPresetAfterEndpointEdit" in app_js
    assert "renderVisionModelPicker(providerId, defaultModelId, { providerSwitch: true })" in app_js
    assert "apiKeyEl.value = ''" in app_js


def test_apply_config_patch_dashscope_model_syncs_default_model_id():
    from app.model_catalog import default_catalog_model_id

    dash_model = default_catalog_model_id("dashscope")
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
            "model": dash_model,
        },
    )

    assert config.get("model") == dash_model
    assert config.get_default_model_id() == dash_model


def test_export_config_mismatched_model_still_loads():
    from app.model_catalog import is_catalog_model_for_provider

    cfg = FakeConfig(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "model": "doubao-seed-1-6-flash-250828",
            "default_model_id": "doubao-seed-1-6-flash-250828",
        }
    )
    data = export_config(cfg)
    assert data["model"] == "doubao-seed-1-6-flash-250828"
    assert not is_catalog_model_for_provider("dashscope", data["active_model_id"])
    assert data["provider_model_mismatch"] is True
    assert data["inferred_provider_id"] == "dashscope"
    assert data["model_source"] == "freeform"


def test_export_config_includes_catalog_display_name():
    from app.model_catalog import default_catalog_model_id

    dash_model = default_catalog_model_id("dashscope")
    cfg = FakeConfig(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "model": dash_model,
            "default_model_id": dash_model,
        }
    )
    data = export_config(cfg)
    assert data["active_model_id"] == dash_model
    assert data["model_source"] == "catalog"
    assert data["model_display_name"]
    assert data["provider_model_mismatch"] is False


def test_build_status_snapshot_includes_model_projection():
    from app.model_catalog import default_catalog_model_id

    dash_model = default_catalog_model_id("dashscope")
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False, get_dedup_profile_snapshot=MagicMock()),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        _visible_display_count=lambda: 0,
        stats_state=StatsState(),
        _start_time=0.0,
        _web_error_message="",
        _web_error_is_error=False,
        danmu_count=0,
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig(
            {
                "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_mode": "openai",
                "model": dash_model,
                "default_model_id": dash_model,
                "_api_key": "sk-test",
            }
        ),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        _build_live_status_snapshot=lambda: None,
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["active_model_id"] == dash_model
    assert status["inferred_provider_id"] == "dashscope"
    assert status["model_source"] == "catalog"
    assert status["uses_custom_credentials"] is False


def test_build_status_snapshot_includes_capture_region():
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False, get_dedup_profile_snapshot=MagicMock()),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        _visible_display_count=lambda: 0,
        stats_state=StatsState(),
        _start_time=0.0,
        _web_error_message="",
        _web_error_is_error=False,
        danmu_count=0,
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig(
            {
                "screen_index": "0",
                "region_x": "12",
                "region_y": "34",
                "region_w": "320",
                "region_h": "180",
                "_api_key": "sk-test",
            }
        ),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        _build_live_status_snapshot=lambda: None,
        _region_selection_state="idle",
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["capture_region_mode"] == "custom"
    assert status["region_x"] == 12
    assert status["region_w"] == 320
    assert status["region_selection_state"] == "idle"
    assert status["provider_model_mismatch"] is False


def test_apply_config_patch_clamps_normal_batch_settings():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "normal_recognition_interval_sec": "0",
            "normal_reply_count": "99",
        },
    )

    assert config.get("normal_recognition_interval_sec") == "1"
    assert config.get("normal_reply_count") == "20"


def test_apply_config_patch_normalizes_legacy_realtime_display_mode():
    config = FakeConfig({"danmu_display_mode": "realtime"})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"danmu_display_mode": "realtime", "normal_reply_count": "6"})

    assert config.get("danmu_display_mode") == "normal"
    assert config.get("normal_reply_count") == "6"


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


def test_apply_config_patch_clamps_opacity():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"opacity": "30"})
    assert config.get("opacity") == "30"

    apply_config_patch(app, {"opacity": "-5"})
    assert config.get("opacity") == "0"

    apply_config_patch(app, {"opacity": "200"})
    assert config.get("opacity") == "100"


def test_apply_config_patch_validates_memory_settings():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "memory_mode": "evil",
            "memory_window": "abc",
        },
    )

    assert config.get("memory_mode") == "off"
    assert config.get("memory_window") == "10"
    assert "evil" not in config.values.values()
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
            "memory_window": "15",
        },
    )
    assert config.get("memory_mode") == "scene_card"
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

    danmu_app = MagicMock()
    bridge = WebConsoleBridge(danmu_app)
    server = WebConsoleServer(bridge)
    server._server = _FakeUvicornServer()
    loop = MagicMock()
    server._loop = loop

    server.stop()

    danmu_app.stop_web_status_timer.assert_called_once_with()
    danmu_app.detach_web_status_timer.assert_called_once_with()
    loop.call_soon_threadsafe.assert_called_once()
    callback = loop.call_soon_threadsafe.call_args[0][0]
    assert callable(callback)
    callback()
    assert server._server.should_exit is True


def test_quit_stops_web_status_timer_before_server_shutdown(monkeypatch):
    import PyQt6.QtCore as qtcore

    order = []
    fake_pool = MagicMock()
    fake_pool.waitForDone.side_effect = lambda ms: order.append(f"wait:{ms}") or True

    class _FakeQThreadPool:
        @staticmethod
        def globalInstance():
            return fake_pool

    monkeypatch.setattr(qtcore, "QThreadPool", _FakeQThreadPool)
    quit_mock = MagicMock()
    monkeypatch.setattr("main.QApplication.quit", quit_mock)

    app = SimpleNamespace(
        logger=MagicMock(),
        stop=MagicMock(),
        hotkey=MagicMock(),
        tray=MagicMock(),
        ai_worker=MagicMock(),
        history_writer=MagicMock(),
        config=MagicMock(),
        overlay=MagicMock(),
        webview_shell=None,
        web_server=MagicMock(),
        stop_web_status_timer=MagicMock(),
    )
    app.ai_worker.close.side_effect = lambda: order.append("close")
    app.history_writer.stop.side_effect = lambda: order.append("history_stop")
    app.config.close.side_effect = lambda: order.append("config_close")

    DanmuApp.quit(app)

    app.stop.assert_called_once_with()
    app.stop_web_status_timer.assert_called_once_with()
    app.web_server.stop.assert_called_once_with()
    fake_pool.waitForDone.assert_called_once_with(2000)
    assert order[:4] == ["wait:2000", "close", "history_stop", "config_close"]
    quit_mock.assert_called_once_with()


def test_quit_logs_warning_when_thread_pool_does_not_finish(monkeypatch):
    import PyQt6.QtCore as qtcore

    fake_pool = MagicMock()
    fake_pool.waitForDone.return_value = False

    class _FakeQThreadPool:
        @staticmethod
        def globalInstance():
            return fake_pool

    monkeypatch.setattr(qtcore, "QThreadPool", _FakeQThreadPool)
    monkeypatch.setattr("main.QApplication.quit", MagicMock())

    app = SimpleNamespace(
        logger=MagicMock(),
        stop=MagicMock(),
        hotkey=MagicMock(),
        tray=MagicMock(),
        ai_worker=MagicMock(),
        history_writer=MagicMock(),
        config=MagicMock(),
        overlay=MagicMock(),
        webview_shell=None,
        web_server=MagicMock(),
        stop_web_status_timer=MagicMock(),
    )

    DanmuApp.quit(app)

    app.logger.warning.assert_called_once_with(
        "quit timed out waiting for AI worker thread pool"
    )


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


def test_capture_region_get_route():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.get_capture_region_status.return_value = {
        "mode": "custom",
        "region": {"x": 10, "y": 20, "w": 100, "h": 80},
        "selection_state": "idle",
    }

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.get("/api/capture-region")
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "custom"
    assert body["region"]["w"] == 100
    bridge.danmu_app.get_capture_region_status.assert_called_once()


def test_capture_region_select_route_emits_signal():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.get_capture_region_status.return_value = {
        "mode": "full",
        "region": {"x": 0, "y": 0, "w": 0, "h": 0},
        "selection_state": "idle",
    }

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.post("/api/capture-region/select")
    assert res.status_code == 200
    assert res.json()["selection_state"] == "selecting"
    bridge.region_select_requested.emit.assert_called_once()


def test_capture_region_select_skips_emit_when_already_selecting():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.get_capture_region_status.return_value = {
        "mode": "full",
        "region": {"x": 0, "y": 0, "w": 0, "h": 0},
        "selection_state": "selecting",
    }

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.post("/api/capture-region/select")
    assert res.status_code == 200
    bridge.region_select_requested.emit.assert_not_called()


def test_capture_region_reset_route_emits_signal():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.post("/api/capture-region/reset")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    bridge.region_reset_requested.emit.assert_called_once()


def test_mic_test_route_uses_public_app_entry():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.run_mic_test.return_value = {
        "ok": True,
        "level": "ok",
        "pcm_bytes": 4096,
        "rms": 0.12,
    }
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.post("/api/mic/test", json={"duration_sec": 2.5, "send_to_ai": False})

    assert res.status_code == 200
    assert res.json()["ok"] is True
    bridge.invoke_on_main.assert_called_once_with(
        bridge.danmu_app.run_mic_test,
        2.5,
        send_to_ai=False,
    )


def test_mic_test_send_route_uses_public_app_entry():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.run_mic_test.return_value = {
        "ok": True,
        "level": "ok",
        "pcm_bytes": 2048,
        "audio_attached": True,
    }
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.post("/api/mic/test-send", json={"duration_sec": 3.0, "send_to_ai": False})

    assert res.status_code == 200
    assert res.json()["ok"] is True
    bridge.invoke_on_main.assert_called_once_with(
        bridge.danmu_app.run_mic_test,
        3.0,
        send_to_ai=True,
    )


def test_active_personae_route_uses_public_app_entry():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.put("/api/personae/active", json={"active": ["吐槽型"]})

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    bridge.invoke_on_main.assert_called_once_with(
        bridge.danmu_app.set_active_personae,
        ["吐槽型"],
    )


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


def _build_ws_status_test_app(bridge, token: str):
    """Mirror WebConsoleServer WebSocketRoute registration for /ws/status."""
    from app.web_console import _ws_token_valid
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from starlette.routing import WebSocketRoute

    app = FastAPI()

    async def _ws_status_endpoint(websocket: WebSocket):
        ws_token = websocket.query_params.get("ws_token")
        if not _ws_token_valid(ws_token, token):
            await websocket.close(code=1008, reason="需要登录令牌")
            return
        await websocket.accept()
        bridge._ws_log_debug("WebSocket /ws/status accepted peer=test")
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        bridge.register_status_consumer(queue)
        cached = bridge._last_status_payload
        if cached:
            await websocket.send_json(cached)
        bridge.status_refresh_requested.emit()
        try:
            while True:
                item = await queue.get()
                await websocket.send_json(item)
        except WebSocketDisconnect:
            pass
        finally:
            bridge.unregister_status_consumer(queue)

    app.router.routes.insert(0, WebSocketRoute("/ws/status", endpoint=_ws_status_endpoint))
    return app


def test_ws_status_websocket_accepts_valid_token_and_sends_status():
    """Regression: FastAPI @app.websocket must not be the only registration path."""
    from fastapi.testclient import TestClient

    token = "ws-test-token-valid"
    bridge = MagicMock()
    bridge._last_status_payload = {
        "running": True,
        "danmu_count": 2,
        "queue_count": 0,
        "display_count": 1,
    }

    app = _build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    with client.websocket_connect(f"/ws/status?ws_token={token}") as ws:
        payload = ws.receive_json()
        assert payload["running"] is True
        assert "danmu_count" in payload

    bridge.register_status_consumer.assert_called_once()
    bridge.unregister_status_consumer.assert_called_once()
    bridge.status_refresh_requested.emit.assert_called_once()


def test_ws_status_websocket_rejects_invalid_token_with_1008():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-valid"
    bridge = MagicMock()
    bridge._last_status_payload = {"running": False}

    app = _build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/status?ws_token=invalid-token"):
            pass

    assert exc_info.value.code == 1008
    bridge.register_status_consumer.assert_not_called()


def test_ws_status_websocket_rejects_missing_token_with_1008():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    token = "ws-test-token-valid"
    bridge = MagicMock()

    app = _build_ws_status_test_app(bridge, token)
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/status"):
            pass

    assert exc_info.value.code == 1008
    bridge.register_status_consumer.assert_not_called()


def test_invoke_on_main_runs_on_bridge_thread():
    from app.web_console import WebConsoleBridge
    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QApplication

    qt_app = QApplication.instance() or QApplication([])
    bridge = WebConsoleBridge(MagicMock())
    observed: dict[str, object] = {}

    class InvokeWorker(QThread):
        def run(self) -> None:
            def capture() -> int:
                observed["thread"] = QThread.currentThread()
                return 42

            observed["result"] = bridge.invoke_on_main(capture)

    worker = InvokeWorker()
    worker.start()
    while worker.isRunning():
        qt_app.processEvents()
        worker.wait(50)
    assert observed["result"] == 42
    assert observed["thread"] is bridge.thread()


def test_invoke_on_main_fast_path_on_bridge_thread():
    from app.web_console import WebConsoleBridge
    from PyQt6.QtWidgets import QApplication

    _ = QApplication.instance() or QApplication([])
    bridge = WebConsoleBridge(MagicMock())
    assert bridge.invoke_on_main(lambda: 7) == 7


def test_announcements_read_state_get_default():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.get("/api/announcements-read-state")
    assert res.status_code == 200
    assert res.json() == {
        "readIds": [],
        "lastSeenMs": 0,
        "overviewBannerDismissedId": "",
    }


def test_announcements_read_state_put_roundtrip():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    def _check_token(_authorization: str | None = None) -> None:
        if _authorization != "Bearer test-token":
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="unauthorized")

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    payload = {
        "readIds": [
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        ],
        "lastSeenMs": 1716969600000,
        "overviewBannerDismissedId": "33333333-3333-4333-8333-333333333333",
    }
    res = client.put(
        "/api/announcements-read-state",
        json=payload,
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    bridge.invoke_on_main.assert_called_once()

    res = client.get("/api/announcements-read-state")
    assert res.status_code == 200
    assert res.json() == payload


def test_announcements_read_state_put_rejects_invalid_body():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.put(
        "/api/announcements-read-state",
        json={"readIds": ["not-a-uuid"], "lastSeenMs": 0},
    )
    assert res.status_code == 400

    res = client.put(
        "/api/announcements-read-state",
        json={"readIds": [], "lastSeenMs": -1},
    )
    assert res.status_code == 400

    res = client.put(
        "/api/announcements-read-state",
        json={
            "readIds": [],
            "lastSeenMs": 0,
            "overviewBannerDismissedId": "not-a-uuid",
        },
    )
    assert res.status_code == 400
