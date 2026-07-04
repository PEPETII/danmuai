"""Web console tests: server."""

import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest
from app.application.web_runtime_state import WebRuntimeState
from app.translations import Translator
from app.web_console import (
    WebConsoleBridge,
)

from tests.fakes import FakeConfig
from tests.web_console_helpers import make_status_app


def test_model_catalog_api_payload():
    """Contract for GET /api/model-catalog (implemented via list_platform_catalogs)."""
    from app.model_catalog import list_platform_catalogs

    platforms = list_platform_catalogs()
    assert len(platforms) == 11
    by_id = {p["platform_id"]: p for p in platforms}

    doubao = by_id["doubao"]
    assert doubao["provider_id"] == "doubao"
    assert len(doubao["models"]) == 7
    doubao_cheapest = [m for m in doubao["models"] if m["cheapest"]]
    assert len(doubao_cheapest) == 1
    assert doubao_cheapest[0]["id"] == "doubao-seed-1-6-flash-250828"
    doubao_mic = {m["id"] for m in doubao["models"] if m["supports_mic"]}
    assert doubao_mic == {
        "doubao-seed-2-0-pro-260215",
        "doubao-seed-2-0-lite-260428",
        "doubao-seed-2-0-mini-260428",
    }

    dashscope = by_id["dashscope"]
    assert dashscope["provider_id"] == "dashscope"
    assert len(dashscope["models"]) == 10
    dash_cheapest = [m for m in dashscope["models"] if m["cheapest"]]
    assert len(dash_cheapest) == 1
    assert dash_cheapest[0]["id"] == "qwen3-vl-flash"
    assert all(m["id"] != "qwen3-vl-max" for m in dashscope["models"])
    dash_mic = {m["id"] for m in dashscope["models"] if m["supports_mic"]}
    assert dash_mic == set()

    siliconflow = by_id["siliconflow"]
    assert siliconflow["platform_label"] == "硅基流动"
    assert len(siliconflow["models"]) == 10
    sf_cheapest = [m for m in siliconflow["models"] if m["cheapest"]]
    assert len(sf_cheapest) == 1
    assert sf_cheapest[0]["id"] == "Qwen/Qwen3-VL-8B-Instruct"
    assert all(m["id"] != "zai-org/GLM-4.6V" for m in siliconflow["models"])

    mimo = by_id["mimo"]
    assert mimo["provider_id"] == "mimo"
    assert mimo["default_model_id"] == "mimo-v2.5"
    assert len(mimo["models"]) == 1
    mimo_ids = {m["id"] for m in mimo["models"]}
    assert mimo_ids == {"mimo-v2.5"}
    assert mimo["models"][0]["supports_mic"] is True

    zai = by_id["zai"]
    assert zai["provider_id"] == "zai"
    assert zai["default_model_id"] == "glm-4.6v"
    assert {m["id"] for m in zai["models"]} == {"glm-4.6v", "glm-4.5v"}


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


def test_providers_api_labels_follow_translator_language():
    from app.model_providers import PROVIDERS, provider_label
    from app.translations import Translator
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.get("/api/providers")
    def providers():
        lang = Translator.get_language()
        return [
            {
                "id": provider.id,
                "label": provider_label(provider.id, lang),
                "default_endpoint": provider.default_endpoint,
                "mode": provider.mode,
                "hint": (
                    provider.model_id_hint_en
                    if lang == "en"
                    else provider.model_id_hint_zh
                ),
                "website": provider.website,
            }
            for provider in PROVIDERS
        ]

    client = TestClient(app)
    Translator.set_language("en")
    try:
        payload = client.get("/api/providers").json()
        mimo = next(item for item in payload if item["id"] == "mimo")
        assert mimo["label"] == "Xiaomi MiMo"
        assert "Vision danmu" in mimo["hint"]
    finally:
        Translator.set_language("zh")


def test_provider_rules_endpoint():
    from app.model_providers import DEFAULT_PROVIDER_ID, provider_rules_for_api
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

    res = client.get("/api/provider-rules")
    assert res.status_code == 200
    payload = res.json()
    assert payload == provider_rules_for_api()
    assert payload["default_provider_id"] == DEFAULT_PROVIDER_ID
    assert payload["editable_api_mode_provider_ids"] == ["custom_openai", "custom_doubao"]
    fragments = [entry["fragment"] for entry in payload["host_entries"]]
    assert fragments == sorted(fragments, key=len, reverse=True)


def test_provider_rules_resolve_endpoint():
    from app.model_providers import resolve_provider_for_ui
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

    cases = [
        ("https://ark.cn-beijing.volces.com/api/v3", "openai"),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", "doubao"),
        ("https://unknown.example/v1", "doubao"),
    ]
    for endpoint, api_mode in cases:
        res = client.get(
            "/api/provider-rules/resolve",
            params={"endpoint": endpoint, "api_mode": api_mode},
        )
        assert res.status_code == 200
        assert res.json() == resolve_provider_for_ui(endpoint, api_mode)


def test_mic_devices_endpoint_payload(monkeypatch):
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    monkeypatch.setattr(
        "app.web_api.mic_test.list_mic_devices",
        lambda _app: {
            "available": True,
            "default_input_device_id": 2,
            "default_input_device_label": "Mic 2",
            "devices": [
                {"id": 2, "name": "Mic 2", "is_default": True, "max_input_channels": 1},
                {"id": 5, "name": "Mic 5", "is_default": False, "max_input_channels": 2},
            ],
        },
    )

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.get("/api/mic/devices")
    assert res.status_code == 200
    payload = res.json()
    assert payload["available"] is True
    assert payload["default_input_device_id"] == 2
    assert payload["default_input_device_label"] == "Mic 2"
    assert payload["devices"][0]["is_default"] is True


def test_web_settings_ui_contains_mic_input_device_field():
    from app.bundle_paths import project_root

    root = project_root()
    html = (root / "web" / "static" / "partials" / "settings.html").read_text(encoding="utf-8")
    settings_defaults = (
        root / "web" / "static" / "modules" / "settings-defaults.js"
    ).read_text(encoding="utf-8")
    settings_js = (root / "web" / "static" / "modules" / "settings.js").read_text(
        encoding="utf-8"
    )
    mic_tools_js = (
        root / "web" / "static" / "modules" / "settings-mic-tools.js"
    ).read_text(encoding="utf-8")

    assert 'id="mic_input_device_id"' in html
    assert "mic_input_device_id" in settings_defaults
    assert "populateMicInputDevices" in settings_js
    assert "active_input_device_label" in mic_tools_js


def test_settings_providers_js_no_hardcoded_host_table():
    from app.bundle_paths import project_root

    providers_js = (
        project_root() / "web" / "static" / "modules" / "settings-providers.js"
    ).read_text(encoding="utf-8")
    assert "ark.cn-beijing.volces.com" not in providers_js
    assert "api.xiaomimimo.com" not in providers_js
    assert "hostEntriesCache" in providers_js
    assert "/api/provider-rules" in providers_js
    assert "const EDITABLE_API_MODE_PROVIDER_IDS" not in providers_js


def test_web_settings_ui_provider_naming_unified():
    import json

    from app.bundle_paths import project_root

    root = project_root()
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    providers_js = (
        root / "web" / "static" / "modules" / "settings-providers.js"
    ).read_text(encoding="utf-8")
    hints_js = (root / "web" / "static" / "modules" / "settings-hints.js").read_text(
        encoding="utf-8"
    )
    settings_js = (root / "web" / "static" / "modules" / "settings.js").read_text(
        encoding="utf-8"
    )
    zh_hints = json.loads(
        (root / "web" / "static" / "locales" / "zh" / "hints.json").read_text(
            encoding="utf-8"
        )
    )
    assert "手动填写" in html
    assert "模型配置档案" in html
    assert 'value="">自定义</option>' not in html
    assert ">自定义</option>" not in html
    assert "MANUAL_PROVIDER_LABEL" in providers_js
    assert "MIC_LABEL_SUFFIX" in providers_js
    assert "micProviderPreset:" in hints_js
    assert (
        "dynamic.settingsHints.为麦克风接话选择服务商预设_会自动填入麦克风_A" in hints_js
    )
    assert "为麦克风接话选择服务商预设" in zh_hints["hints"]["micProviderPreset"]
    assert "dynamic.settings.当前默认模型来自模型配置档案_name" in settings_js


def test_web_content_page_field_hints_wired():
    from app.bundle_paths import project_root

    root = project_root()
    hints_js = (root / "web" / "static" / "modules" / "settings-hints.js").read_text(
        encoding="utf-8"
    )
    app_js = (root / "web" / "static" / "app.js").read_text(encoding="utf-8")
    settings_js = (root / "web" / "static" / "modules" / "settings.js").read_text(
        encoding="utf-8"
    )
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "initContentPageFieldHints" in hints_js
    assert "OVERVIEW_FIELD_TIPS" in hints_js
    assert "liveTopicInput" in hints_js
    assert "page-overview" in hints_js
    assert "loadOverviewGlobalFields" in app_js
    assert "memeBarrageEnabled" in hints_js
    assert "petScale" in hints_js
    assert "initContentPageFieldHints()" in app_js
    assert "initContentPageFieldHints" in settings_js
    assert 'id="hintMemeCategoryTitle"' in html
    assert 'for="personaSelect"' in html
    assert 'id="hintPersonaActiveTitle"' in html


def test_web_api_mode_select_initialized():
    from app.bundle_paths import project_root

    root = project_root()
    providers_js = (
        root / "web" / "static" / "modules" / "settings-providers.js"
    ).read_text(encoding="utf-8")
    settings_html = (root / "web" / "static" / "partials" / "settings.html").read_text(
        encoding="utf-8"
    )
    html = (root / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "API_MODE_OPTIONS" in providers_js
    assert "function initApiModeSelect" in providers_js or "export function initApiModeSelect" in providers_js
    assert "initApiModeSelect()" in providers_js
    assert "applyApiModeValue" in providers_js
    assert "syncApiModeLockState" in providers_js
    assert 'id="api_mode"' in settings_html
    assert 'option value="doubao"' in settings_html
    assert 'option value="openai"' in settings_html
    assert 'id="api_mode"' in html
    assert 'option value="doubao"' in html


def test_web_app_js_provider_switch_resets_vision_model():
    from app.bundle_paths import project_root

    settings_js = (
        project_root() / "web" / "static" / "modules" / "settings.js"
    ).read_text(encoding="utf-8")
    assert "function pickDefaultCatalogModelId" in settings_js
    assert "platform.default_model_id" in settings_js
    assert "providerSwitch: true" in settings_js
    assert "function syncProviderPresetFromEndpoint" in settings_js
    assert "function resolveProviderIdForPicker" in settings_js
    assert "renderVisionModelPicker(resolveProviderIdForPicker()" in settings_js
    assert "syncProviderPresetAfterEndpointEdit" in settings_js
    assert "renderVisionModelPicker(providerId, defaultModelId, { providerSwitch: true })" in settings_js
    assert "apiKeyEl.value = ''" in settings_js


def test_list_recent_logs_filters_by_since_ts():
    app = make_status_app()
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
    app = make_status_app()
    app.logger = MagicMock()
    bridge = WebConsoleBridge(app)
    queue = __import__("asyncio").Queue(maxsize=4)
    bridge.register_status_consumer(queue)
    bridge.unregister_status_consumer(queue)
    debug_calls = [str(c) for c in app.logger.debug.call_args_list]
    assert any("register_status_consumer consumers=1" in c for c in debug_calls)
    assert any("unregister_status_consumer consumers=0" in c for c in debug_calls)


def test_enqueue_ws_replaces_oldest_on_full_queue():

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


def test_log_broadcast_coalesces_call_soon_threadsafe():
    """P-36: burst log lines schedule one call_soon_threadsafe flush."""
    app = make_status_app()
    app.logger = MagicMock()
    bridge = WebConsoleBridge(app)
    loop = asyncio.new_event_loop()
    bridge.set_event_loop(loop)
    scheduled: list = []

    def _capture(cb, *_args, **_kwargs):
        scheduled.append(cb)

    loop.call_soon_threadsafe = _capture  # type: ignore[method-assign]
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    bridge.register_log_consumer(queue)

    for index in range(50):
        bridge._broadcast_log("INFO", f"log-{index}", float(index))

    assert len(scheduled) == 1
    scheduled[0]()
    received = []
    while not queue.empty():
        received.append(queue.get_nowait())
    assert len(received) == 50
    assert received[0]["message"] == "log-0"
    assert received[49]["message"] == "log-49"
    loop.close()


def test_publish_diagnostic_snapshot_skips_without_subscribers():
    app = make_status_app()
    app.logger = MagicMock()
    bridge = WebConsoleBridge(app)
    bridge._diagnostics_hub = __import__(
        "app.application.diagnostics_hub", fromlist=["DiagnosticsHub"]
    ).DiagnosticsHub()
    bridge.publish_diagnostic_snapshot()
    app.build_diagnostic_snapshot.assert_not_called()


def test_publish_diagnostic_snapshot_broadcasts_to_hub():
    import asyncio

    from app.application.diagnostics_hub import DiagnosticsHub

    app = make_status_app()
    app.build_diagnostic_snapshot.return_value = {
        "scheduler": {},
        "timing": {},
        "runtime_state": {},
        "diagnosis": {},
    }
    app.logger = MagicMock()
    bridge = WebConsoleBridge(app)
    hub = DiagnosticsHub()
    loop = asyncio.new_event_loop()
    hub.set_loop(loop)
    bridge._diagnostics_hub = hub
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    hub.register(queue)
    bridge.publish_diagnostic_snapshot()
    loop.run_until_complete(asyncio.sleep(0.05))
    item = queue.get_nowait()
    assert item["data"] == app.build_diagnostic_snapshot.return_value
    loop.close()


def test_web_console_wait_ready_fails_fast_when_bind_failed():

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


def test_wait_ready_returns_false_when_thread_dies_before_bind():
    from app.web_console import WebConsoleBridge, WebConsoleServer

    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    dead_thread = MagicMock()
    dead_thread.is_alive.return_value = False
    server._thread = dead_thread

    started = time.monotonic()
    assert server.wait_ready(timeout=2.0) is False
    assert time.monotonic() - started < 0.2


def test_notify_wait_ready_timeout_warns_when_thread_still_starting():

    from app.web_console import (
        WebConsoleBridge,
        WebConsoleServer,
        _notify_wait_ready_timeout,
    )

    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    danmu_app = MagicMock()
    danmu_app.logger = MagicMock()

    def _sleep_forever() -> None:
        time.sleep(5.0)

    server._thread = threading.Thread(target=_sleep_forever, daemon=True)
    server._thread.start()
    try:
        _notify_wait_ready_timeout(server, danmu_app)
        danmu_app.logger.warning.assert_called_once()
        danmu_app.logger.error.assert_not_called()
        danmu_app.set_web_error_status.assert_not_called()
        warning_msg = danmu_app.logger.warning.call_args[0][0]
        assert "启动较慢" in warning_msg
        assert server.base_url in warning_msg
    finally:
        server._bind_failed.set()


def test_notify_wait_ready_timeout_errors_when_bind_failed():
    from app.web_console import (
        WebConsoleBridge,
        WebConsoleServer,
        _notify_wait_ready_timeout,
    )

    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    danmu_app = MagicMock()
    danmu_app.logger = MagicMock()
    server._bind_failed.set()

    _notify_wait_ready_timeout(server, danmu_app)

    danmu_app.logger.error.assert_called_once()
    danmu_app.logger.warning.assert_not_called()
    danmu_app.set_web_error_status.assert_called_once()
    error_msg = danmu_app.logger.error.call_args[0][0]
    assert "未在" in error_msg
    assert "pip install" in error_msg


def test_notify_wait_ready_timeout_errors_when_thread_dead():
    from app.web_console import (
        WebConsoleBridge,
        WebConsoleServer,
        _notify_wait_ready_timeout,
    )

    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    danmu_app = MagicMock()
    danmu_app.logger = MagicMock()
    server._thread = None

    _notify_wait_ready_timeout(server, danmu_app)

    danmu_app.logger.error.assert_called_once()
    danmu_app.set_web_error_status.assert_called_once_with(
        danmu_app.logger.error.call_args[0][0],
        is_error=True,
    )
    assert server._startup_error_from_attach is True


def test_maybe_restart_web_console_capped(monkeypatch):
    """S-006: failed web console gets bounded auto-restart from main-thread helper."""
    from app.web_console import (
        WEB_CONSOLE_MAX_RESTART_ATTEMPTS,
        WebConsoleBridge,
        WebConsoleServer,
        maybe_restart_web_console,
    )

    danmu_app = MagicMock()
    danmu_app.logger = MagicMock()
    bridge = WebConsoleBridge(danmu_app)
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    server._thread = None
    start_calls: list[int] = []
    monkeypatch.setattr(server, "start", lambda: start_calls.append(1))

    assert maybe_restart_web_console(server) is True
    assert server._restart_attempts == 1
    assert len(start_calls) == 1
    assert maybe_restart_web_console(server) is False

    server._last_restart_at = 0.0
    while server._restart_attempts < WEB_CONSOLE_MAX_RESTART_ATTEMPTS:
        maybe_restart_web_console(server)

    assert server._restart_attempts == WEB_CONSOLE_MAX_RESTART_ATTEMPTS
    server._last_restart_at = 0.0
    before = len(start_calls)
    assert maybe_restart_web_console(server) is False
    assert len(start_calls) == before


def test_startup_error_clears_when_uvicorn_started():
    from app.web_console import (
        WebConsoleBridge,
        WebConsoleServer,
    )

    danmu_app = MagicMock()
    danmu_app.web_runtime_state = WebRuntimeState()
    danmu_app.set_web_error_status = lambda msg, *, is_error: danmu_app.web_runtime_state.set_error_status(
        msg, is_error=is_error
    )
    bridge = WebConsoleBridge(danmu_app)
    server = WebConsoleServer(bridge)
    server._startup_error_from_attach = True
    danmu_app.web_runtime_state.set_error_status("startup failed", is_error=True)

    server._on_uvicorn_started()

    assert server._startup_error_from_attach is False
    assert danmu_app.web_runtime_state.is_error is False
    assert danmu_app.web_runtime_state.error_message == ""


def test_startup_warning_does_not_persist_after_server_ready():
    from app.web_console import (
        WebConsoleBridge,
        WebConsoleServer,
        classify_web_console_startup,
        clear_startup_attach_error_if_needed,
    )

    danmu_app = MagicMock()
    danmu_app.web_runtime_state = WebRuntimeState()
    danmu_app.set_web_error_status = lambda msg, *, is_error: danmu_app.web_runtime_state.set_error_status(
        msg, is_error=is_error
    )
    bridge = WebConsoleBridge(danmu_app)
    server = WebConsoleServer(bridge)
    server._startup_error_from_attach = True
    danmu_app.web_runtime_state.set_error_status("未就绪", is_error=True)

    server.startup_ok = True
    server._ready.set()
    clear_startup_attach_error_if_needed(server)

    assert classify_web_console_startup(server) == "ready"
    assert danmu_app.web_runtime_state.is_error is False
    assert server._startup_error_from_attach is False









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


def test_announcements_state_normalize_drops_invalid_overview_id():
    from app.web_api.announcements_state import normalize_state

    state = normalize_state(
        {
            "readIds": [],
            "lastSeenMs": 0,
            "overviewBannerDismissedId": "not-a-uuid",
        }
    )
    assert state["overviewBannerDismissedId"] == ""


def test_announcements_state_validate_payload_rejects_bad_uuid():
    from app.web_api.announcements_state import validate_payload
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        validate_payload({"readIds": ["not-a-uuid"], "lastSeenMs": 0})
    assert exc.value.status_code == 400


# -- W-SEC-001：/api/session 鉴权测试 -----------------------------------------
# 覆盖 bug-audit/bug-03.md 缺陷 1：缺 / 错 token / 非 loopback 来源 / 无 Origin
# 一律 401/403；同源 loopback 握手或正确 token 放行。

def _build_session_app(expected_token: str = "secret-token"):
    """构造一个最小 FastAPI app，仅挂载 /api/session，模拟 web_console_runtime.py 的闭包逻辑。

    通过 mock 复制其核心行为，避开构造完整 WebConsoleServer 的繁重 fixture。
    """
    from app.web_console_session_auth import enforce_session_authorization
    from fastapi import FastAPI, Header

    app = FastAPI()

    @app.get("/api/session")
    def read_console_session(
        host: str | None = Header(default=None),
        origin: str | None = Header(default=None),
        referer: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        enforce_session_authorization(
            authorization=authorization,
            origin=origin,
            referer=referer,
            host=host,
            expected_token=expected_token,
        )
        host = (host or "").strip()
        base_url = f"http://{host}" if host else "http://127.0.0.1:18765"
        return {"token": expected_token, "base_url": base_url}

    return app


def test_session_rejects_no_auth_no_origin():
    """curl 风格调用（无 Authorization、无 Origin）→ 401。"""
    from fastapi.testclient import TestClient

    client = TestClient(_build_session_app())
    res = client.get("/api/session", headers={"Host": "127.0.0.1:18765"})
    assert res.status_code == 401


def test_session_rejects_wrong_token():
    """携带错误 token → 403。"""
    from fastapi.testclient import TestClient

    client = TestClient(_build_session_app(expected_token="right"))
    res = client.get(
        "/api/session",
        headers={
            "Host": "127.0.0.1:18765",
            "Authorization": "Bearer wrong-token",
        },
    )
    assert res.status_code == 403


def test_session_allows_correct_token_regardless_of_origin():
    """携带正确 token → 200；不要求 Origin/Referer。"""
    from fastapi.testclient import TestClient

    client = TestClient(_build_session_app(expected_token="right"))
    res = client.get(
        "/api/session",
        headers={
            "Host": "127.0.0.1:18765",
            "Authorization": "Bearer right",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token"] == "right"
    assert body["base_url"] == "http://127.0.0.1:18765"


def test_session_allows_loopback_origin_handshake():
    """控制台同源 loopback fetch（无 token）→ 200；同源握手。"""
    from fastapi.testclient import TestClient

    client = TestClient(_build_session_app(expected_token="right"))
    res = client.get(
        "/api/session",
        headers={
            "Host": "127.0.0.1:18765",
            "Origin": "http://127.0.0.1:18765",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token"] == "right"


def test_session_rejects_mismatched_loopback_origin():
    """Origin 域名与 Host 不一致（同为 loopback 也拒）→ 403。"""
    from fastapi.testclient import TestClient

    client = TestClient(_build_session_app(expected_token="right"))
    res = client.get(
        "/api/session",
        headers={
            "Host": "127.0.0.1:18765",
            "Origin": "http://localhost:9999",
        },
    )
    assert res.status_code == 403


def test_session_rejects_non_loopback_host():
    """非 loopback Host + 无 token → 401（不能从外部拿 token）。"""
    from fastapi.testclient import TestClient

    client = TestClient(_build_session_app(expected_token="right"))
    res = client.get(
        "/api/session",
        headers={
            "Host": "evil.example.com",
            "Origin": "http://evil.example.com",
        },
    )
    assert res.status_code == 401


def test_session_rejects_port_mismatch_on_same_loopback():
    """端口不一致的 loopback Origin 应被拒绝（防御端口剥离绕过）。

    攻击场景：Host=127.0.0.1:18765, Origin=http://127.0.0.1:9999
    两者主机名相同但端口不同，应 403。
    """
    from fastapi.testclient import TestClient

    client = TestClient(_build_session_app(expected_token="right"))
    res = client.get(
        "/api/session",
        headers={
            "Host": "127.0.0.1:18765",
            "Origin": "http://127.0.0.1:9999",
        },
    )
    assert res.status_code == 403


def test_session_allows_exact_same_port_loopback():
    """端口完全一致的 loopback Origin 应放行（正常浏览器行为）。"""
    from fastapi.testclient import TestClient

    client = TestClient(_build_session_app(expected_token="right"))
    res = client.get(
        "/api/session",
        headers={
            "Host": "127.0.0.1:18765",
            "Origin": "http://127.0.0.1:18765",
        },
    )
    assert res.status_code == 200


def test_session_rejects_loopback_origin_without_request_port():
    """Host 有端口但 Origin 无端口 → 应拒绝。"""
    from fastapi.testclient import TestClient

    client = TestClient(_build_session_app(expected_token="right"))
    res = client.get(
        "/api/session",
        headers={
            "Host": "127.0.0.1:18765",
            "Origin": "http://127.0.0.1",
        },
    )
    assert res.status_code == 403


def _register_invoke_main_test_routes(bridge):
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI

    app = FastAPI()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    return app


def test_invoke_main_route_success():
    from fastapi.testclient import TestClient

    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    client = TestClient(_register_invoke_main_test_routes(bridge), raise_server_exceptions=False)

    res = client.put(
        "/api/danmu-pool/settings",
        json={"custom_enabled": True},
        headers={"Authorization": "Bearer x"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    bridge.invoke_on_main.assert_called_once()


def test_invoke_main_route_timeout_returns_504():
    from app.web_console import MainThreadInvokeTimeout
    from fastapi.testclient import TestClient

    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = MainThreadInvokeTimeout(10.0)
    client = TestClient(_register_invoke_main_test_routes(bridge), raise_server_exceptions=False)

    res = client.put(
        "/api/danmu-pool/settings",
        json={"custom_enabled": True},
        headers={"Authorization": "Bearer x"},
    )
    assert res.status_code == 504
    assert res.json()["detail"] == {
        "ok": False,
        "error": "main_thread_timeout",
        "detail": "主线程操作超时，请稍后重试。",
    }


def test_invoke_main_route_runtime_error_returns_400():
    from fastapi.testclient import TestClient

    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = RuntimeError("engine not running")
    client = TestClient(_register_invoke_main_test_routes(bridge), raise_server_exceptions=False)

    res = client.put(
        "/api/danmu-pool/settings",
        json={"custom_enabled": False},
        headers={"Authorization": "Bearer x"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "engine not running"


def test_ensure_web_static_mime_types_overrides_plain_js():
    import mimetypes

    from app.web_static_mime import ensure_web_static_mime_types

    mimetypes.add_type("text/plain", ".js", strict=True)
    ensure_web_static_mime_types()
    assert mimetypes.guess_type("app.js")[0] == "application/javascript"


def test_static_js_response_content_type(tmp_path):
    import mimetypes

    from app.web_static_mime import ensure_web_static_mime_types
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient

    mimetypes.add_type("text/plain", ".js", strict=True)
    (tmp_path / "test.js").write_text("export const ok = true;\n", encoding="utf-8")

    app = FastAPI()
    ensure_web_static_mime_types()
    app.mount("/static", StaticFiles(directory=str(tmp_path)), name="static")
    client = TestClient(app)

    res = client.get("/static/test.js")
    assert res.status_code == 200
    assert "javascript" in res.headers.get("content-type", "").lower()


def test_invoke_main_route_timeout_returns_504_in_english():
    from app.web_console import MainThreadInvokeTimeout
    from fastapi.testclient import TestClient

    Translator.set_language("en")
    try:
        bridge = MagicMock()
        bridge.invoke_on_main.side_effect = MainThreadInvokeTimeout(10.0)
        client = TestClient(
            _register_invoke_main_test_routes(bridge), raise_server_exceptions=False
        )

        res = client.put(
            "/api/danmu-pool/settings",
            json={"custom_enabled": True},
            headers={"Authorization": "Bearer x"},
        )
        assert res.status_code == 504
        assert res.json()["detail"] == {
            "ok": False,
            "error": "main_thread_timeout",
            "detail": "Main thread operation timed out; please try again later.",
        }
    finally:
        Translator.set_language("zh")
