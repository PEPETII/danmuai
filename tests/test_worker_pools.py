"""S-014: dedicated AI and capture thread pools."""

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
