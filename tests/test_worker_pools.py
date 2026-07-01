"""S-014: dedicated AI and capture thread pools."""

import threading

from app.worker_pools import ai_worker_pool, capture_worker_pool, meme_ai_pool


def test_ai_worker_pool_isolated_with_max_two_threads():
    pool = ai_worker_pool()
    assert pool.maxThreadCount() == 2
    assert pool is ai_worker_pool()


def test_capture_worker_pool_isolated_with_max_one_thread():
    pool = capture_worker_pool()
    assert pool.maxThreadCount() == 1
    assert pool is capture_worker_pool()


def test_meme_ai_pool_isolated_from_ai_worker_pool():
    """BUG-G05: meme AI pool is independent from main visual AI pool."""
    pool = meme_ai_pool()
    assert pool.maxThreadCount() == 1
    assert pool is meme_ai_pool()
    assert pool is not ai_worker_pool()
    assert pool is not capture_worker_pool()


def test_ai_worker_pool_concurrent_init_returns_singleton(monkeypatch):
    """并发首次调用应返回同一实例（double-checked locking 守护懒加载，W-WORKERPOOL-LOCK-001）。"""
    from app import worker_pools

    monkeypatch.setattr(worker_pools, "_ai_pool", None)
    results: list = []
    barrier = threading.Barrier(10)

    def call():
        barrier.wait()
        results.append(ai_worker_pool())

    threads = [threading.Thread(target=call) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 10
    assert all(r is results[0] for r in results)
    assert results[0] is not None
