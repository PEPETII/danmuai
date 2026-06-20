"""Danmu pool loader tests."""

from __future__ import annotations


def test_danmu_pool_use_custom_from_config(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import danmu_pool_use_custom_from_config

    store = ConfigStore(db_path=tmp_path / "custom_flag.db")
    assert danmu_pool_use_custom_from_config(store) is False
    store.set("danmu_pool_use_custom", "1")
    assert danmu_pool_use_custom_from_config(store) is True


def test_any_danmu_pool_source_enabled(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import any_danmu_pool_source_enabled

    store = ConfigStore(db_path=tmp_path / "any_source.db")
    assert any_danmu_pool_source_enabled(store) is False
    store.set("danmu_pool_use_custom", "1")
    assert any_danmu_pool_source_enabled(store) is True


def test_pool_for_config_disabled_returns_empty(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import load_danmu_pool_for_config, sample_danmu_for_config

    store = ConfigStore(db_path=tmp_path / "pool_gate.db")
    store.set("danmu_pool_use_custom", "0")
    assert load_danmu_pool_for_config(store) == []
    assert sample_danmu_for_config(store, 5) == []


def test_custom_only_pool_for_config(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import (
        effective_min_on_screen,
        load_danmu_pool_for_config,
        sample_danmu_for_config,
    )

    store = ConfigStore(db_path=tmp_path / "custom_only.db")
    store.set("danmu_pool_use_custom", "1")
    store.set_custom_danmu_pool(["自定义A", "自定义B", "自定义C"])
    result = load_danmu_pool_for_config(store)
    # BUG-A01: load_danmu_pool_for_config now uses SQL RANDOM() sampling, order is not guaranteed
    assert sorted(result) == ["自定义A", "自定义B", "自定义C"]
    picked = sample_danmu_for_config(store, 2)
    assert len(picked) == 2
    assert all(p in store.get_custom_danmu_pool() for p in picked)
    store.set("min_on_screen", "5")
    assert effective_min_on_screen(store) == 5


def test_pool_topup_returns_0_when_entry_zone_overloaded(qapp, workspace_tmp):
    """W-DANMU-POOL-003: 用户配了 danmu_pending_entry_cap 时，入口区满则池补足早返 0。"""
    from unittest.mock import MagicMock

    from app.config_store import ConfigStore
    from app.danmu_engine import DanmuEngine
    from app.danmu_pool import maybe_pool_topup

    store = ConfigStore(db_path=workspace_tmp / "pool_topup_overload.db")
    store.set("danmu_pool_use_custom", "1")
    store.set("min_on_screen", "5")
    store.set_custom_danmu_pool(["句1", "句2", "句3", "句4", "句5", "句6"])

    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    engine.running = True
    engine.entry_zone_overloaded = MagicMock(return_value=True)
    add_text_calls: list[str] = []
    original_add_text = engine.add_text
    engine.add_text = MagicMock(side_effect=lambda *a, **kw: add_text_calls.append(a[0]) or original_add_text(*a, **kw))

    added = maybe_pool_topup(engine, store, scene_generation=0)

    assert added == 0
    assert engine.add_text.call_count == 0
    assert add_text_calls == []


def test_pool_topup_skips_recent_dedup_window(qapp, workspace_tmp):
    """W-DANMU-POOL-001: 池补足 add_text(skip_dedup=True) 不受 deque(30) 窗口误伤。"""
    from app.config_store import ConfigStore
    from app.danmu_engine import DanmuEngine
    from app.danmu_pool import maybe_pool_topup

    store = ConfigStore(db_path=workspace_tmp / "pool_topup_skip_dedup.db")
    store.set("danmu_pool_use_custom", "1")
    store.set("min_on_screen", "3")
    store.set_custom_danmu_pool(["撞车句"])

    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    engine.running = True
    engine.recent.clear()
    engine.recent_exact_set.clear()

    for i in range(30):
        engine._remember_content("history-" + str(i))
    engine._remember_content("撞车句")
    assert "撞车句" in engine.recent_exact_set

    added = maybe_pool_topup(engine, store, scene_generation=0)

    assert added == 1
    all_texts = [
        item.content
        for track in engine.tracks
        for item in track.items
    ]
    assert "撞车句" in all_texts


def test_formula_text_cache_reuses_custom_pool_contains(tmp_path, monkeypatch):
    from app.config_store import ConfigStore
    from app.danmu_pool import is_stored_custom_pool_text

    store = ConfigStore(db_path=tmp_path / "formula_cache_custom.db")
    store.set_custom_danmu_pool(["公式句A"])
    calls: list[int] = []
    original = store.get_custom_danmu_pool

    def _counting_get():
        calls.append(1)
        return original()

    monkeypatch.setattr(store, "get_custom_danmu_pool", _counting_get)
    assert is_stored_custom_pool_text(store, "公式句A") is True
    assert is_stored_custom_pool_text(store, "公式句A") is True
    assert len(calls) == 1


def test_formula_text_cache_invalidates_on_pool_write(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import is_stored_custom_pool_text

    store = ConfigStore(db_path=tmp_path / "formula_cache_invalidate.db")
    store.set_custom_danmu_pool(["旧句"])
    assert is_stored_custom_pool_text(store, "旧句") is True
    assert is_stored_custom_pool_text(store, "新句") is False
    store.set_custom_danmu_pool(["旧句", "新句"])
    assert is_stored_custom_pool_text(store, "新句") is True


def test_formula_text_cache_reuses_meme_library_set(tmp_path, monkeypatch):
    from app.config_store import ConfigStore
    from app.danmu_pool import is_stored_meme_barrage_text

    store = ConfigStore(db_path=tmp_path / "formula_cache_meme.db")
    store.meme_barrage_library_insert_many(
        [("烂梗句", None, None)],
        collected_at=0.0,
        max_rows=10_000,
    )
    calls: list[int] = []
    original = store.meme_barrage_library_all_texts

    def _counting_all():
        calls.append(1)
        return original()

    monkeypatch.setattr(store, "meme_barrage_library_all_texts", _counting_all)
    assert is_stored_meme_barrage_text(store, "烂梗句") is True
    assert is_stored_meme_barrage_text(store, "烂梗句") is True
    assert len(calls) == 1


def test_sample_danmu_uses_sql_sampler(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import sample_danmu_for_config

    store = ConfigStore(db_path=tmp_path / "pool_sample.db")
    store.set("danmu_pool_use_custom", "1")
    store.set_custom_danmu_pool(["自定义A", "自定义B", "自定义C"])
    picked = sample_danmu_for_config(store, 2)
    assert len(picked) == 2
    assert all(p in store.get_custom_danmu_pool() for p in picked)


def test_pool_topup_entry_zone_overloaded_non_callable_no_error(qapp, workspace_tmp):
    from app.config_store import ConfigStore
    from app.danmu_engine import DanmuEngine
    from app.danmu_pool import maybe_pool_topup

    store = ConfigStore(db_path=workspace_tmp / "pool_topup_bool.db")
    store.set("danmu_pool_use_custom", "1")
    store.set("min_on_screen", "5")
    store.set_custom_danmu_pool(["句1"])

    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    engine.running = True
    engine.entry_zone_overloaded = True  # bool, not callable — must not TypeError

    added = maybe_pool_topup(engine, store, scene_generation=0)
    assert added >= 0


def test_custom_danmu_list_search_like_escape_percent(tmp_path):
    """F02: 搜索 '100%' 不匹配 '100X'。"""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "like_escape.db")
    store.set_custom_danmu_pool(["100%", "100X", "完成率100%", "测试句"])
    found = store.custom_danmu_list(page=1, page_size=50, search="100%", source="manual")
    assert found["total"] == 2
    texts = [item["text"] for item in found["items"]]
    assert "100%" in texts
    assert "完成率100%" in texts
    assert "100X" not in texts
    store.close()


def test_custom_danmu_list_search_like_escape_underscore(tmp_path):
    """F02: 搜索 '_test' 不匹配 'atest'。"""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "like_escape_us.db")
    store.set_custom_danmu_pool(["_test", "atest", "b_test", "xtest"])
    found = store.custom_danmu_list(page=1, page_size=50, search="_test", source="manual")
    texts = [item["text"] for item in found["items"]]
    assert "_test" in texts
    assert "b_test" in texts
    assert "atest" not in texts
    assert "xtest" not in texts
    store.close()


def test_custom_danmu_list_search_like_escape_backslash(tmp_path):
    """F02: 搜索含反斜杠的文本正确匹配。"""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "like_escape_bs.db")
    store.set_custom_danmu_pool([r"path\to\file", "pathXtoYfile", "normal"])
    found = store.custom_danmu_list(page=1, page_size=50, search=r"path\to", source="manual")
    texts = [item["text"] for item in found["items"]]
    assert r"path\to\file" in texts
    assert "pathXtoYfile" not in texts
    store.close()


def test_set_custom_danmu_pool_respects_max(tmp_path, monkeypatch):
    """F03: set_custom_danmu_pool 超过 CUSTOM_DANMU_POOL_MAX 时截断。"""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "pool_set_max.db")
    monkeypatch.setattr("app.danmu_pool.CUSTOM_DANMU_POOL_MAX", 5)
    store.set_custom_danmu_pool([f"句{i}" for i in range(10)])
    assert store.custom_danmu_count() == 5
    store.close()


def test_read_without_write_lock_no_deadlock(tmp_path):
    """BUG-A02: Read operations should not hold _write_lock, avoiding deadlock with writes."""
    from app.config_store import ConfigStore
    import threading

    store = ConfigStore(tmp_path / "test_concurrency.db")
    store.custom_danmu_insert_many(["弹幕A", "弹幕B", "弹幕C"])

    errors = []
    barrier = threading.Barrier(2, timeout=5)

    def reader():
        try:
            barrier.wait()
            store.custom_danmu_count()
        except Exception as e:
            errors.append(e)

    def writer():
        try:
            barrier.wait()
            store.custom_danmu_insert_many(["弹幕D"])
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=reader)
    t2 = threading.Thread(target=writer)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"Concurrent read/write errors: {errors}"
    assert store.custom_danmu_count() >= 3
    store.close()


def test_pool_write_lock_independent_from_config_lock(tmp_path):
    """W-PERF-CONFIG-POOL-LOCK-SPLIT-001: pool 写锁不阻塞配置读写。"""
    from app.config_store import ConfigStore
    import threading

    store = ConfigStore(tmp_path / "pool_lock_split.db")
    store.custom_danmu_insert_many(["弹幕A"])

    errors = []
    barrier = threading.Barrier(2, timeout=5)

    def pool_writer():
        """持 _pool_write_lock 写弹幕库。"""
        try:
            barrier.wait()
            store.custom_danmu_insert_many(["弹幕B"])
        except Exception as e:
            errors.append(e)

    def config_writer():
        """持 _write_lock 写配置。应不被 pool 锁阻塞。"""
        try:
            barrier.wait()
            store.set("test_key", "test_value")
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=pool_writer)
    t2 = threading.Thread(target=config_writer)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"Concurrent pool/config write errors: {errors}"
    assert store.get("test_key") == "test_value"
    assert store.custom_danmu_count() >= 2
    store.close()


def test_load_danmu_pool_for_config_uses_sampling(tmp_path):
    """BUG-A01: load_danmu_pool_for_config should use SQL sampling, not full load."""
    from app.config_store import ConfigStore
    from app.danmu_pool import load_danmu_pool_for_config

    store = ConfigStore(tmp_path / "test_sampling.db")
    # Insert 500 entries
    texts = [f"弹幕{i:04d}" for i in range(500)]
    store.custom_danmu_insert_many(texts)
    store.set("danmu_pool_use_custom", "1")

    result = load_danmu_pool_for_config(store)
    # Should return at most 200 (sample size), not 500 (full load)
    assert len(result) <= 200
    assert len(result) > 0
    # All results should be from the pool
    assert all(t.startswith("弹幕") for t in result)
    store.close()


def test_custom_pool_cache_invalidates_on_insert(tmp_path):
    """BUG-A04: Custom pool cache invalidates after insert, new text becomes visible."""
    from app.config_store import ConfigStore
    from app.danmu_pool import is_stored_custom_pool_text

    store = ConfigStore(db_path=tmp_path / "cache_invalidate_insert.db")
    store.set_custom_danmu_pool(["旧句"])
    assert is_stored_custom_pool_text(store, "旧句") is True
    assert is_stored_custom_pool_text(store, "新句") is False
    # Insert new text — cache should be invalidated
    store.custom_danmu_insert_many(["新句"])
    assert is_stored_custom_pool_text(store, "新句") is True
    store.close()


def test_invalidate_formula_text_cache_none_clears_all(tmp_path):
    """BUG-A04: invalidate_formula_text_cache(None) clears both custom and meme caches."""
    from app.config_store import ConfigStore
    from app.danmu_pool import (
        _formula_custom_sets,
        _formula_meme_sets,
        invalidate_formula_text_cache,
        is_stored_custom_pool_text,
    )

    store = ConfigStore(db_path=tmp_path / "cache_clear_all.db")
    store.set_custom_danmu_pool(["句A"])
    # Populate caches
    assert is_stored_custom_pool_text(store, "句A") is True
    assert id(store) in _formula_custom_sets
    # Clear all
    invalidate_formula_text_cache(None)
    assert id(store) not in _formula_custom_sets
    assert len(_formula_custom_sets) == 0
    assert len(_formula_meme_sets) == 0
    # Cache is rebuilt on next access
    assert is_stored_custom_pool_text(store, "句A") is True
    assert id(store) in _formula_custom_sets
    store.close()


# --- 增量 diff 测试 ---


def test_diff_custom_danmu_pool_add_to_empty():
    from app.danmu_pool import _diff_custom_danmu_pool

    to_add, to_remove = _diff_custom_danmu_pool(set(), ["A", "B", "C"], 100)
    assert to_add == ["A", "B", "C"]
    assert to_remove == []


def test_diff_custom_danmu_pool_partial_overlap():
    from app.danmu_pool import _diff_custom_danmu_pool

    existing = {"A", "B", "C"}
    to_add, to_remove = _diff_custom_danmu_pool(existing, ["B", "C", "D"], 100)
    assert to_add == ["D"]
    assert set(to_remove) == {"A"}


def test_diff_custom_danmu_pool_no_change():
    from app.danmu_pool import _diff_custom_danmu_pool

    existing = {"A", "B", "C"}
    to_add, to_remove = _diff_custom_danmu_pool(existing, ["A", "B", "C"], 100)
    assert to_add == []
    assert to_remove == []


def test_diff_custom_danmu_pool_respects_max():
    from app.danmu_pool import _diff_custom_danmu_pool

    existing = {"A", "B"}
    # max=3, keep 2, budget=1 → only 1 new item
    to_add, to_remove = _diff_custom_danmu_pool(existing, ["A", "B", "C", "D"], 3)
    assert to_add == ["C"]
    assert to_remove == []


def test_set_custom_danmu_pool_incremental_noop(tmp_path):
    """替换为相同内容时无数据库操作。"""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "incr_noop.db")
    store.set_custom_danmu_pool(["句A", "句B"])
    changes_before = store.conn.total_changes
    store.set_custom_danmu_pool(["句A", "句B"])
    changes_after = store.conn.total_changes
    assert changes_after == changes_before
    assert store.custom_danmu_count() == 2
    store.close()


def test_set_custom_danmu_pool_incremental_partial(tmp_path):
    """部分新增/删除，保留不变项。"""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "incr_partial.db")
    store.set_custom_danmu_pool(["旧A", "旧B", "旧C"])
    store.set_custom_danmu_pool(["旧B", "新D", "新E"])
    pool = store.get_custom_danmu_pool()
    assert "旧B" in pool
    assert "新D" in pool
    assert "新E" in pool
    assert "旧A" not in pool
    assert "旧C" not in pool
    assert store.custom_danmu_count() == 3
    store.close()
