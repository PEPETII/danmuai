"""Custom formula TXT pool and danmu pool API tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.custom_formula_txt_pool import (
    load_txt_pool_snapshot,
    pool_dir_for_config,
    refresh_txt_pool,
    sample_txt_pool_texts,
)
from app.danmu_pool import CUSTOM_DANMU_POOL_MAX, custom_pool_size, sample_danmu_for_config
from app.web_api import danmu_pool as pool_api


@pytest.fixture
def pool_app(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config.db")
    app = SimpleNamespace(config=config, config_changed=MagicMock())
    return app


def _write_pool_txt(config, name: str, lines: list[str]) -> None:
    directory = pool_dir_for_config(config)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_get_meta_includes_txt_status(pool_app):
    _write_pool_txt(pool_app.config, "demo.txt", ["太真实了", "这也行？"])
    meta = pool_api.get_meta(pool_app)
    assert meta["custom_enabled"] is False
    assert meta["txt_file_count"] == 1
    assert meta["txt_line_count"] == 2
    assert meta["custom_count"] == 2
    assert meta["txt_files"][0]["name"] == "demo.txt"
    assert meta["txt_files"][0]["line_count"] == 2
    assert "txt_dir" in meta


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


def test_refresh_custom_txt_pool(pool_app):
    _write_pool_txt(pool_app.config, "demo.txt", ["太真实了", "这也行？"])
    result = pool_api.refresh_custom_txt_pool(pool_app)
    assert result["ok"] is True
    assert result["txt_line_count"] == 2
    pool_app.config_changed.emit.assert_called_once()


def test_sample_danmu_from_txt_pool(pool_app):
    pool_app.config.set("danmu_pool_use_custom", "1")
    _write_pool_txt(pool_app.config, "demo.txt", ["自定义A句", "自定义B句", "自定义C句"])
    picked = sample_danmu_for_config(pool_app.config, 2)
    assert len(picked) == 2
    assert all(p in {"自定义A句", "自定义B句", "自定义C句"} for p in picked)


def test_migrate_sqlite_to_txt_once(pool_app):
    pool_app.config.set_custom_danmu_pool(["旧句甲", "旧句乙"])
    snapshot = load_txt_pool_snapshot(pool_app.config, force=True)
    migrated = pool_dir_for_config(pool_app.config) / "migrated_from_app.txt"
    assert migrated.is_file()
    assert snapshot.line_count == 2
    assert pool_app.config.get("custom_formula_txt_migrated") == "1"


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
    assert body["custom_max"] == CUSTOM_DANMU_POOL_MAX
    assert "txt_dir" in body

    settings = client.put(
        "/api/danmu-pool/settings",
        json={"custom_enabled": True, "min_on_screen": 4},
    )
    assert settings.status_code == 200

    pool_dir = pool_dir_for_config(config)
    pool_dir.mkdir(parents=True, exist_ok=True)
    (pool_dir / "routes.txt").write_text("测试句子\n", encoding="utf-8")

    refreshed = client.post("/api/danmu-pool/custom/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["txt_line_count"] == 1

    opened = client.post("/api/danmu-pool/custom/open-folder")
    assert opened.status_code == 200
    assert opened.json()["ok"] is True


def test_txt_pool_respects_overlay_safe_filter(pool_app):
    _write_pool_txt(
        pool_app.config,
        "mixed.txt",
        ["正常句子", "https://evil.example", "另一句子"],
    )
    snapshot = refresh_txt_pool(pool_app.config)
    assert snapshot["txt_line_count"] == 2
    assert snapshot["txt_skipped_unsafe"] == 1


def test_txt_pool_accepts_single_char_lines(pool_app):
    _write_pool_txt(pool_app.config, "short.txt", ["2", "2", "3"])
    snapshot = refresh_txt_pool(pool_app.config)
    assert snapshot["txt_line_count"] == 2


def test_txt_pool_dedupes_across_files(pool_app):
    _write_pool_txt(pool_app.config, "a.txt", ["重复句子", "句子甲"])
    _write_pool_txt(pool_app.config, "b.txt", ["重复句子", "句子乙"])
    texts = sample_txt_pool_texts(pool_app.config, 10)
    assert texts.count("重复句子") == 1
    assert len(texts) == 3
