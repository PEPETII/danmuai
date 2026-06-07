"""Web console tests: HTTP routes via bridge.invoke_on_main."""

from unittest.mock import MagicMock


def test_probe_route_accepts_json_body():
    """Regression: /api/probe in web_console._run nested scope caused query: Field required 422."""
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.probe_api_connection.return_value = {
        "ok": True,
        "message": "连接成功",
        "status_code": 200,
    }

    def _check_token(_authorization: str | None = None) -> None:
        return None

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


def test_test_danmu_route_uses_public_app_entry():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.inject_test_danmu_batch.return_value = {
        "ok": True,
        "queued": 1,
        "screenshot_id": 1,
    }
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    def _check_token(authorization: str | None = None) -> None:
        if authorization != "Bearer secret":
            from fastapi import HTTPException

            raise HTTPException(status_code=401)

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    denied = client.post("/api/test/danmu", json={"items": ["测试弹幕"]})
    assert denied.status_code == 401

    ok = client.post(
        "/api/test/danmu",
        json={"items": ["一二三四五六七八九十"], "persona": "验收"},
        headers={"Authorization": "Bearer secret"},
    )
    assert ok.status_code == 200
    assert ok.json()["ok"] is True
    bridge.danmu_app.inject_test_danmu_batch.assert_called_once_with(
        ["一二三四五六七八九十"],
        persona_id="验收",
    )


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
    from app.web_api.mic_test import run_mic_test

    bridge.invoke_on_main.assert_called_once_with(
        run_mic_test,
        bridge.danmu_app,
        2.5,
        False,
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
    from app.web_api.mic_test import run_mic_test

    bridge.invoke_on_main.assert_called_once_with(
        run_mic_test,
        bridge.danmu_app,
        3.0,
        True,
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


# W-NICKNAME-001
def test_user_nickname_round_trip_via_config_service(tmp_path):
    """PUT /api/config { user_nickname } must persist to ConfigStore and survive reload."""
    from app.application.config_service import apply_web_config_patch
    from app.config_store import ConfigStore
    from app.personae import append_nickname_to_system_pt

    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)
    # Sanity: seed should populate the new key with empty string.
    assert store.get("user_nickname", "") == ""

    class _PersonaeStub:
        def set_active(self, _active):
            return None

    class _DanmuAppStub:
        config_changed = MagicMock()

    app = _DanmuAppStub()
    app.config = store
    app.personae = _PersonaeStub()

    apply_web_config_patch(app, {"user_nickname": "小明"})
    assert store.get("user_nickname", "") == "小明"
    app.config_changed.emit.assert_called_once()

    # Reload from the same db file: persistence is durable, no Python state.
    store2 = ConfigStore(db_path)
    assert store2.get("user_nickname", "") == "小明"
    assert "[用户昵称：小明" in append_nickname_to_system_pt("你是主播。", store2)

    # Empty string should clear without raising and not inject anything.
    apply_web_config_patch(app, {"user_nickname": ""})
    assert store.get("user_nickname", "") == ""
    assert append_nickname_to_system_pt("你是主播。", store) == "你是主播。"


def test_user_nickname_default_in_config_defaults():
    """CONFIG_DEFAULTS must include user_nickname so 'restore defaults' is honest."""
    from app.config_defaults import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS.get("user_nickname", "") == ""


def test_user_nickname_in_web_config_keys():
    """WEB_CONFIG_KEYS must contain user_nickname so the whitelist accepts it."""
    from app.application.config_service import WEB_CONFIG_KEYS

    assert "user_nickname" in WEB_CONFIG_KEYS
    assert "user_nickname" in tuple(WEB_CONFIG_KEYS)


# W-FP-V2-001：danmu_render_mode 与悬浮窗 V2 配置走 PUT /api/config


def test_danmu_render_mode_persists_via_config_service(tmp_path):
    from app.application.config_service import apply_web_config_patch
    from app.config_store import ConfigStore

    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)

    class _PersonaeStub:
        def set_active(self, _active):
            return None

    class _DanmuAppStub:
        config_changed = MagicMock()

    app = _DanmuAppStub()
    app.config = store
    app.personae = _PersonaeStub()

    apply_web_config_patch(app, {"danmu_render_mode": "floating_panel"})
    assert store.get("danmu_render_mode") == "floating_panel"


def test_danmu_render_mode_invalid_falls_back_to_scrolling(tmp_path):
    from app.application.config_service import apply_web_config_patch
    from app.config_store import ConfigStore

    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)

    class _PersonaeStub:
        def set_active(self, _active):
            return None

    class _DanmuAppStub:
        config_changed = MagicMock()

    app = _DanmuAppStub()
    app.config = store
    app.personae = _PersonaeStub()

    apply_web_config_patch(app, {"danmu_render_mode": "both"})
    assert store.get("danmu_render_mode") == "scrolling"


def test_floating_panel_v2_config_keys_round_trip(tmp_path):
    from app.application.config_service import apply_web_config_patch
    from app.config_store import ConfigStore

    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)

    class _PersonaeStub:
        def set_active(self, _active):
            return None

    class _DanmuAppStub:
        config_changed = MagicMock()

    app = _DanmuAppStub()
    app.config = store
    app.personae = _PersonaeStub()

    payload = {
        "floating_panel_width": "380",
        "floating_panel_opacity": "70",
        "floating_panel_font_size": "22",
        "floating_panel_max_items": "8",
        "floating_panel_lifetime_sec": "9",
        "floating_panel_x_offset": "25",
        "floating_panel_y_offset": "70",
    }
    apply_web_config_patch(app, payload)
    for key, expected in payload.items():
        assert store.get(key) == expected, key


# W-FONT-001：字体设置走 PUT /api/config 端到端


def test_font_family_persists_via_config_service(tmp_path):
    """danmu_font_family 经 apply_web_config_patch 持久化到 ConfigStore。"""
    from app.application.config_service import apply_web_config_patch
    from app.config_store import ConfigStore

    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)

    class _PersonaeStub:
        def set_active(self, _active):
            return None

    class _DanmuAppStub:
        config_changed = MagicMock()

    app = _DanmuAppStub()
    app.config = store
    app.personae = _PersonaeStub()

    apply_web_config_patch(app, {"danmu_font_family": "SimHei"})
    assert store.get("danmu_font_family") == "SimHei"


def test_font_size_out_of_range_clamps_via_config_service(tmp_path):
    """font_size=9999 经 _normalize_items 钳到 72。"""
    from app.application.config_service import apply_web_config_patch
    from app.config_store import ConfigStore

    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)

    class _PersonaeStub:
        def set_active(self, _active):
            return None

    class _DanmuAppStub:
        config_changed = MagicMock()

    app = _DanmuAppStub()
    app.config = store
    app.personae = _PersonaeStub()

    apply_web_config_patch(app, {"font_size": "9999"})
    assert store.get("font_size") == "72"


def test_font_bold_truthy_strings_normalize_to_one(tmp_path):
    """danmu_font_bold=true 归一为 '1'。"""
    from app.application.config_service import apply_web_config_patch
    from app.config_store import ConfigStore

    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path)

    class _PersonaeStub:
        def set_active(self, _active):
            return None

    class _DanmuAppStub:
        config_changed = MagicMock()

    app = _DanmuAppStub()
    app.config = store
    app.personae = _PersonaeStub()

    apply_web_config_patch(app, {"danmu_font_bold": "true"})
    assert store.get("danmu_font_bold") == "1"


# W-FONT-002：字体导入 API（HTTP 契约；QFontDatabase 行为见 test_font_registry.py）


def _font_route_client(registry):
    from app.web_api.font_registry import register_font_registry_routes
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    app_stub = type("App", (), {"font_registry": registry})()

    class _BridgeStub:
        def __init__(self, danmu_app):
            self.danmu_app = danmu_app

        def invoke_on_main(self, fn, /, *args, **kwargs):
            return fn(*args, **kwargs)

    bridge = _BridgeStub(app_stub)

    def _check_token(authorization: str | None = None) -> None:
        if authorization != "Bearer font-secret":
            raise HTTPException(status_code=401)

    api = FastAPI()
    register_font_registry_routes(api, bridge, _check_token)
    return TestClient(api)


def _mock_registry():
    reg = MagicMock()
    reg.list_families.return_value = ["ImportedFont"]
    reg.list_imported.return_value = []
    return reg


def test_post_fonts_import_with_valid_ttf_returns_family():
    reg = _mock_registry()
    reg.import_bytes.return_value = {
        "sha256": "a" * 64,
        "family": "ImportedFont",
        "original_name": "my.ttf",
        "size": 12345,
        "imported_at": "2026-06-06T00:00:00+00:00",
    }
    client = _font_route_client(reg)
    res = client.post(
        "/api/fonts/import",
        headers={"Authorization": "Bearer font-secret"},
        files={"file": ("my.ttf", b"font-bytes", "application/octet-stream")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["family"] == "ImportedFont"
    reg.import_bytes.assert_called_once()
    listed = client.get("/api/fonts", headers={"Authorization": "Bearer font-secret"})
    assert listed.status_code == 200
    assert "ImportedFont" in listed.json()["families"]


def test_post_fonts_import_rejects_unsupported_extension():
    reg = _mock_registry()
    reg.import_bytes.side_effect = ValueError("unsupported_extension")
    client = _font_route_client(reg)
    res = client.post(
        "/api/fonts/import",
        headers={"Authorization": "Bearer font-secret"},
        files={"file": ("bad.zip", b"abc", "application/zip")},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "unsupported_extension"


def test_post_fonts_import_rejects_empty_file():
    reg = _mock_registry()
    reg.import_bytes.side_effect = ValueError("empty_file")
    client = _font_route_client(reg)
    res = client.post(
        "/api/fonts/import",
        headers={"Authorization": "Bearer font-secret"},
        files={"file": ("empty.ttf", b"", "application/octet-stream")},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "empty_file"


def test_post_fonts_import_rejects_oversized_file():
    reg = _mock_registry()
    reg.import_bytes.side_effect = ValueError("file_too_large")
    client = _font_route_client(reg)
    res = client.post(
        "/api/fonts/import",
        headers={"Authorization": "Bearer font-secret"},
        files={"file": ("big.ttf", b"x", "application/octet-stream")},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "file_too_large"


def test_pet_settings_and_command_routes():
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    bridge.danmu_app.get_pet_settings_snapshot.return_value = {
        "enabled": False,
        "visible": False,
        "has_pending_command": False,
    }
    bridge.danmu_app.apply_pet_settings_patch.return_value = {"enabled": True}
    bridge.danmu_app.show_pet.return_value = {"ok": True}
    bridge.danmu_app.submit_pet_command.return_value = {"ok": True, "id": "abc"}
    bridge.danmu_app.get_pet_status_snapshot.return_value = {"animation": "idle"}

    def _check_token(authorization: str | None = None) -> None:
        if authorization != "Bearer pet-secret":
            from fastapi import HTTPException

            raise HTTPException(status_code=401)

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    assert client.get("/api/pet/settings").status_code == 200
    assert client.get("/api/pet/status").json()["animation"] == "idle"

    denied = client.post("/api/pet/command", json={"text": "hi"})
    assert denied.status_code == 401

    ok = client.post(
        "/api/pet/command",
        json={"text": "接下来偏搞笑"},
        headers={"Authorization": "Bearer pet-secret"},
    )
    assert ok.status_code == 200
    bridge.danmu_app.submit_pet_command.assert_called_once_with("接下来偏搞笑", source="web_api")

    show = client.post("/api/pet/show", headers={"Authorization": "Bearer pet-secret"})
    assert show.status_code == 200
    bridge.danmu_app.show_pet.assert_called_once()


def test_delete_font_removes_from_list():
    reg = _mock_registry()
    reg.delete.return_value = True
    reg.list_families.return_value = []
    client = _font_route_client(reg)
    sha = "b" * 64
    deleted = client.delete(
        f"/api/fonts/{sha}",
        headers={"Authorization": "Bearer font-secret"},
    )
    assert deleted.status_code == 200
    reg.delete.assert_called_once_with(sha)

