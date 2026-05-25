"""Danmu pool loader tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
POOL_JSON = REPO_ROOT / "data" / "danmu_pool_zh.json"
BOOTSTRAP_TXT = REPO_ROOT / "data" / "danmu_pool_zh_bootstrap.txt"


def test_bootstrap_txt_has_400_lines():
    assert BOOTSTRAP_TXT.is_file(), "missing data/danmu_pool_zh_bootstrap.txt"
    lines = [ln.strip() for ln in BOOTSTRAP_TXT.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 400
    # Formula #251–253 are single-char (顶/行/顺); overlay allows ≤15.
    assert all(1 <= len(ln) <= 15 for ln in lines)


def test_danmu_pool_enabled_from_config(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import danmu_pool_enabled_from_config

    store = ConfigStore(db_path=tmp_path / "pool_flag.db")
    assert danmu_pool_enabled_from_config(store) is True
    store.set("danmu_pool_enabled", "1")
    assert danmu_pool_enabled_from_config(store) is True
    store.set("danmu_pool_enabled", "0")
    assert danmu_pool_enabled_from_config(store) is False


def test_pool_for_config_disabled_returns_empty(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import (
        load_danmu_pool,
        load_danmu_pool_for_config,
        sample_danmu_for_config,
    )

    store = ConfigStore(db_path=tmp_path / "pool_gate.db")
    store.set("danmu_pool_enabled", "0")
    assert load_danmu_pool_for_config(store) == []
    assert sample_danmu_for_config(store, 5) == []
    if load_danmu_pool():
        store.set("danmu_pool_enabled", "1")
        assert load_danmu_pool_for_config(store)
        assert sample_danmu_for_config(store, 3)


def test_load_danmu_pool_has_merged_bootstrap():
    from app.danmu_pool import load_danmu_pool

    pool = load_danmu_pool()
    if POOL_JSON.is_file():
        assert len(pool) >= 1300
        assert "懂了" in pool and "这操作有点秀" in pool
    else:
        assert len(pool) >= 400


@pytest.mark.skipif(not POOL_JSON.is_file(), reason="run scripts/extract_danmu_pool.py first")
def test_extracted_pool_has_corpus_and_bootstrap():
    data = json.loads(POOL_JSON.read_text(encoding="utf-8"))
    assert data["count"] >= 1300
    items = data["items"]
    assert len(items) == data["count"]
    assert items[0] == "这操作有点秀"
    assert data.get("bootstrap_count", 0) >= 400
    assert all(1 <= len(str(t)) <= 15 for t in items[:50])


def test_pool_items_pass_overlay_safety_filter():
    from scripts.extract_danmu_pool import is_overlay_safe

    if not POOL_JSON.is_file():
        pytest.skip("missing pool json")
    items = json.loads(POOL_JSON.read_text(encoding="utf-8")).get("items", [])
    bad = [t for t in items if not is_overlay_safe(str(t))]
    assert not bad, f"sensitive or unsafe pool lines: {bad[:10]}"


def test_sample_danmu_unique():
    from app.danmu_pool import load_danmu_pool, sample_danmu

    pool = load_danmu_pool()
    assert pool
    picked = sample_danmu(20)
    assert len(picked) == 20
    assert len(set(picked)) == 20
