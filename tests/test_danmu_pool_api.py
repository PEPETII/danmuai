"""Danmu formula pool web API tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.web_api import danmu_pool as pool_api


@pytest.fixture
def pool_app(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config.db")
    app = SimpleNamespace(config=config, config_changed=MagicMock())
    return app


def test_get_meta_defaults(pool_app):
    meta = pool_api.get_meta(pool_app)
    assert meta["custom_enabled"] is False
    assert meta["min_on_screen"] == 5
    assert meta["custom_count"] == 0
    assert meta["custom_max"] == 2500
    assert meta["effective_pool_enabled"] is False
    assert "builtin_enabled" not in meta
    assert "builtin_count" not in meta


def test_save_settings_maps_keys(pool_app):
    pool_api.save_settings(
        pool_app,
        {
            "custom_enabled": True,
            "min_on_screen": 7,
        },
    )
    assert pool_app.config.get("danmu_pool_use_custom") == "1"
    assert pool_app.config.get("min_on_screen") == "7"
    pool_app.config_changed.emit.assert_called_once()


def test_append_custom_dedupes_and_accepts_long_lines(pool_app):
    pool_app.config.set("danmu_max_chars", "5")
    long_line = "这是一句明显超长的公式化弹幕句子用于完整展示测试"
    result = pool_api.append_custom(
        pool_app,
        {"items": ["短句A", "短句A", long_line]},
    )
    assert result["added"] == 2
    assert result["skipped"] == 1
    reasons = {item["reason"] for item in result["skipped_items"]}
    assert reasons == {"duplicate"}
    assert pool_app.config.get_custom_danmu_pool() == ["短句A", long_line]


def test_append_custom_via_textarea(pool_app):
    result = pool_api.append_custom(pool_app, {"text": "第一行\n\n第二行\n第一行"})
    assert result["added"] == 2
    assert pool_app.config.get_custom_danmu_pool() == ["第一行", "第二行"]


def test_append_custom_respects_pool_limit(pool_app):
    pool_app.config.set_custom_danmu_pool([f"句{i}" for i in range(pool_api.CUSTOM_POOL_MAX)])
    result = pool_api.append_custom(pool_app, {"items": ["新句"]})
    assert result["added"] == 0
    assert any(item["reason"] == "limit_reached" for item in result["skipped_items"])


def test_append_custom_accepts_large_text_batch(pool_app):
    lines = [f"导入句{i}" for i in range(150)]
    result = pool_api.append_custom(pool_app, {"text": "\n".join(lines)})
    assert result["added"] == 150
    assert len(pool_app.config.get_custom_danmu_pool()) == 150


def test_delete_custom_by_texts(pool_app):
    pool_app.config.set_custom_danmu_pool(["保留", "删除A", "删除B"])
    result = pool_api.delete_custom(pool_app, {"texts": ["删除A", "删除B"]})
    assert result["removed"] == 2
    assert result["items"] == ["保留"]


def test_danmu_pool_routes_registered(tmp_path):
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    config = ConfigStore(db_path=tmp_path / "routes.db")
    bridge.danmu_app.config = config
    bridge.danmu_app.config_changed = MagicMock()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    meta = client.get("/api/danmu-pool/meta")
    assert meta.status_code == 200
    body = meta.json()
    assert "builtin_enabled" not in body
    assert "builtin_count" not in body
    assert body["custom_max"] == 2500

    settings = client.put(
        "/api/danmu-pool/settings",
        json={"custom_enabled": True, "min_on_screen": 4},
    )
    assert settings.status_code == 200

    listed = client.get("/api/danmu-pool/custom")
    assert listed.status_code == 200
    assert listed.json()["items"] == []

    posted = client.post("/api/danmu-pool/custom", json={"items": ["测试句"]})
    assert posted.status_code == 200
    assert posted.json()["added"] == 1

    deleted = client.request(
        "DELETE",
        "/api/danmu-pool/custom",
        json={"texts": ["测试句"]},
    )
    assert deleted.status_code == 200
    assert deleted.json()["removed"] == 1
