"""BUG-02: set_custom_danmu_pool_for_store 大数据量 diff 性能与正确性测试。

验证全表扫描修复（LIMIT {CUSTOM_DANMU_POOL_MAX}）后：
1. 大库保存不阻塞主线程
2. diff 结果正确性
3. 无变化时零写操作
"""

from __future__ import annotations

import time


def test_set_pool_large_baseline_completes_fast(tmp_path):
    """BUG-02: 15000 条弹幕库的增量替换应在合理时间内完成（< 2s）。"""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "large_baseline.db")
    # 插入 15000 条旧数据
    old_items = [f"旧弹幕{i:05d}" for i in range(15_000)]
    store.custom_danmu_insert_many(old_items)
    assert store.custom_danmu_count() == 15_000

    # 替换为 10000 条新数据（5000 条重叠）
    new_items = [f"旧弹幕{i:05d}" for i in range(5_000, 15_000)] + [
        f"新弹幕{j:05d}" for j in range(10_000)
    ]

    start = time.perf_counter()
    store.set_custom_danmu_pool(new_items)
    elapsed = time.perf_counter() - start

    # 应在 2s 内完成（无 LIMIT 全表扫描在慢机器上可能 >5s）
    assert elapsed < 2.0, f"Large pool save took {elapsed:.2f}s, expected < 2s"
    store.close()


def test_diff_large_pool_correctness(tmp_path):
    """BUG-02: 10000 条 → 10000 条替换后，库内容与预期一致。"""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "large_diff_correct.db")
    # 初始 10000 条
    old_items = [f"句A-{i:05d}" for i in range(10_000)]
    store.set_custom_danmu_pool(old_items)
    assert store.custom_danmu_count() == 10_000

    # 替换：保留后半 5000 条，新增 5000 条，删除前半 5000 条
    new_items = [f"句A-{i:05d}" for i in range(5_000, 10_000)] + [
        f"句B-{j:05d}" for j in range(5_000)
    ]
    store.set_custom_danmu_pool(new_items)

    pool = store.get_custom_danmu_pool()
    assert len(pool) == 10_000
    # 保留的旧条目都在
    for i in range(5_000, 10_000):
        assert f"句A-{i:05d}" in pool
    # 新增的条目都在
    for j in range(5_000):
        assert f"句B-{j:05d}" in pool
    # 被删的不在
    for i in range(5_000):
        assert f"句A-{i:05d}" not in pool
    store.close()


def test_diff_no_change_large_pool_is_noop(tmp_path):
    """BUG-02: 10000 条相同内容替换应产生零数据库写操作。"""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "large_noop.db")
    items = [f"不变弹幕{k:05d}" for k in range(10_000)]
    store.set_custom_danmu_pool(items)

    changes_before = store.conn.total_changes
    # 用完全相同的列表再次保存
    store.set_custom_danmu_pool(items[:])  # 拷贝，确保不是同一对象
    changes_after = store.conn.total_changes

    assert changes_after == changes_before, (
        f"Expected no DB writes on identical pool, "
        f"but total_changes went from {changes_before} to {changes_after}"
    )
    assert store.custom_danmu_count() == 10_000
    store.close()


def test_get_custom_danmu_pool_large_completes_fast(tmp_path):
    """W-ARCH-DANMU-POOL-PERF-001: paged get_custom_danmu_pool on 10k rows stays fast."""
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "large_get.db")
    store.custom_danmu_insert_many([f"句{k:05d}" for k in range(10_000)])

    start = time.perf_counter()
    pool = store.get_custom_danmu_pool()
    elapsed = time.perf_counter() - start

    assert len(pool) == 10_000
    assert elapsed < 2.0, f"Paged get_custom_danmu_pool took {elapsed:.2f}s, expected < 2s"
    store.close()
