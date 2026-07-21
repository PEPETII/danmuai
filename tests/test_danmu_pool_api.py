"""Danmu formula pool web API tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.danmu_pool import CUSTOM_DANMU_POOL_MAX
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
    assert meta["manual_count"] == 0
    assert meta["import_count"] == 0
    assert meta["custom_max"] == CUSTOM_DANMU_POOL_MAX
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


def test_append_custom_respects_pool_limit(pool_app, monkeypatch):
    monkeypatch.setattr(pool_api, "CUSTOM_POOL_MAX", 5)
    pool_app.config.set_custom_danmu_pool([f"句{i}" for i in range(5)])
    result = pool_api.append_custom(pool_app, {"items": ["新句"]})
    assert result["added"] == 0
    assert any(item["reason"] == "limit_reached" for item in result["skipped_items"])


def test_append_custom_accepts_large_text_batch(pool_app):
    lines = [f"导入句{i}" for i in range(150)]
    result = pool_api.append_custom(pool_app, {"text": "\n".join(lines), "source": "import"})
    assert result["added"] == 150
    assert pool_app.config.custom_danmu_count() == 150
    assert pool_app.config.custom_danmu_count("manual") == 0
    assert "items" not in result


def test_append_import_not_listed_in_manual_page(pool_app):
    pool_api.append_custom(pool_app, {"items": ["导入句"], "source": "import"})
    listed = pool_api.list_custom(pool_app, source="manual")
    assert listed["items"] == []
    assert listed["total"] == 0
    assert pool_app.config.custom_danmu_count() == 1


def test_list_custom_paginates_manual_only(pool_app):
    pool_app.config.set_custom_danmu_pool([f"手动{i}" for i in range(3)])
    pool_api.append_custom(pool_app, {"items": ["导入句"], "source": "import"})
    page = pool_api.list_custom(pool_app, page=1, page_size=50, source="manual")
    assert page["total"] == 3
    assert len(page["items"]) == 3
    assert all("id" in item and "text" in item for item in page["items"])


def test_delete_custom_by_texts(pool_app):
    pool_app.config.set_custom_danmu_pool(["保留", "删除A", "删除B"])
    result = pool_api.delete_custom(pool_app, {"texts": ["删除A", "删除B"]})
    assert result["removed"] == 2
    assert "items" not in result
    assert pool_app.config.get_custom_danmu_pool() == ["保留"]


def test_delete_custom_by_ids(pool_app):
    pool_app.config.set_custom_danmu_pool(["保留", "删除A"])
    listed = pool_api.list_custom(pool_app)
    delete_id = next(item["id"] for item in listed["items"] if item["text"] == "删除A")
    result = pool_api.delete_custom(pool_app, {"ids": [delete_id]})
    assert result["removed"] == 1
    assert pool_app.config.get_custom_danmu_pool() == ["保留"]


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
    assert body["custom_max"] == CUSTOM_DANMU_POOL_MAX

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

    page = client.get("/api/danmu-pool/custom")
    entry_id = page.json()["items"][0]["id"]

    deleted = client.request(
        "DELETE",
        "/api/danmu-pool/custom",
        json={"ids": [entry_id]},
    )
    assert deleted.status_code == 200
    assert deleted.json()["removed"] == 1


def test_append_custom_5000_items_does_not_block_main_thread(pool_app):
    """BUG-AUD-003: 5000 条 unique 短句导入主线程耗时 < 2s。

    旧实现：循环内逐条调用 contains(text) + custom_pool_size(config)，
    5000 × 2 ≈ 10000 次 SQL，主线程阻塞 10s+。
    修复后：循环前一次性批量 IN 查询 + 1 次 COUNT，主线程耗时 < 2s。

    注：使用 ``f"句{i}"`` 模式避免 ``REPEAT_CHAR_RE`` 误判（如 ``句00000`` 含 5 个 0
    会被 ``is_overlay_safe`` 标记为 unsafe）。
    """
    import time as _time

    lines = [f"句{i}" for i in range(5000)]
    payload = {"items": lines, "source": "import"}

    start = _time.monotonic()
    result = pool_api.append_custom(pool_app, payload)
    elapsed = _time.monotonic() - start

    assert result["added"] == 5000
    assert elapsed < 2.0, f"5000 条导入耗时 {elapsed:.2f}s，超过 2s 阈值（旧实现约 10s+）"
    assert pool_app.config.custom_danmu_count("import") == 5000
