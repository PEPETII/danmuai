"""Dedicated Qt thread pools (S-014).

Visual/mic AI use a small isolated pool so hung meme/TTS/probe tasks on the global
pool cannot occupy every worker thread.

W-PERF-HIGH-001: capture_worker_pool isolates screen grab from AI HTTP workers.
BUG-G05: meme_ai_pool isolates meme AI select from main visual AI requests.
"""

from __future__ import annotations

import threading

from PyQt6.QtCore import QRunnable, QThreadPool

_ai_pool: QThreadPool | None = None
_capture_pool: QThreadPool | None = None
_meme_ai_pool: QThreadPool | None = None
_meme_fetch_pool: QThreadPool | None = None
_virtual_host_pool: QThreadPool | None = None
_pool_lock = threading.Lock()
_virtual_host_admission_lock = threading.Lock()
_virtual_host_pending = 0
_virtual_host_running = 0
_virtual_host_rejected = 0
VIRTUAL_HOST_POOL_MAX_THREADS = 2
VIRTUAL_HOST_POOL_MAX_QUEUED_OR_RUNNING = 6


class _VirtualHostBoundedRunnable(QRunnable):
    def __init__(self, runnable: QRunnable) -> None:
        super().__init__()
        self._runnable = runnable
        self.setAutoDelete(True)

    def run(self) -> None:
        global _virtual_host_pending, _virtual_host_running
        with _virtual_host_admission_lock:
            _virtual_host_pending -= 1
            _virtual_host_running += 1
        try:
            self._runnable.run()
        finally:
            with _virtual_host_admission_lock:
                _virtual_host_running -= 1


def ai_worker_pool() -> QThreadPool:
    global _ai_pool
    if _ai_pool is None:
        with _pool_lock:
            if _ai_pool is None:
                pool = QThreadPool()
                pool.setMaxThreadCount(2)
                _ai_pool = pool
    return _ai_pool


def capture_worker_pool() -> QThreadPool:
    global _capture_pool
    if _capture_pool is None:
        with _pool_lock:
            if _capture_pool is None:
                pool = QThreadPool()
                pool.setMaxThreadCount(1)
                _capture_pool = pool
    return _capture_pool


def meme_ai_pool() -> QThreadPool:
    """Isolated pool for meme AI select; does not compete with main visual AI."""
    global _meme_ai_pool
    if _meme_ai_pool is None:
        with _pool_lock:
            if _meme_ai_pool is None:
                pool = QThreadPool()
                pool.setMaxThreadCount(1)
                _meme_ai_pool = pool
    return _meme_ai_pool


def meme_fetch_pool() -> QThreadPool:
    """Isolated pool for meme remote fetch; quit() must waitForDone before config.close()."""
    global _meme_fetch_pool
    if _meme_fetch_pool is None:
        with _pool_lock:
            if _meme_fetch_pool is None:
                pool = QThreadPool()
                pool.setMaxThreadCount(1)
                _meme_fetch_pool = pool
    return _meme_fetch_pool


def virtual_host_worker_pool() -> QThreadPool:
    """Bounded dedicated pool for virtual-host ASR/chat/vision/TTS jobs."""
    global _virtual_host_pool
    if _virtual_host_pool is None:
        with _pool_lock:
            if _virtual_host_pool is None:
                pool = QThreadPool()
                pool.setMaxThreadCount(VIRTUAL_HOST_POOL_MAX_THREADS)
                _virtual_host_pool = pool
    return _virtual_host_pool


def submit_virtual_host_job(runnable: QRunnable) -> bool:
    """Admit a virtual-host job or reject it before QThreadPool queues it."""
    global _virtual_host_pending, _virtual_host_rejected
    with _virtual_host_admission_lock:
        if _virtual_host_pending + _virtual_host_running >= VIRTUAL_HOST_POOL_MAX_QUEUED_OR_RUNNING:
            _virtual_host_rejected += 1
            return False
        _virtual_host_pending += 1
    try:
        virtual_host_worker_pool().start(_VirtualHostBoundedRunnable(runnable))
    except Exception:
        with _virtual_host_admission_lock:
            _virtual_host_pending -= 1
        raise
    return True


def virtual_host_pool_snapshot() -> dict[str, int]:
    with _virtual_host_admission_lock:
        return {
            "pending": _virtual_host_pending,
            "running": _virtual_host_running,
            "rejected": _virtual_host_rejected,
            "capacity": VIRTUAL_HOST_POOL_MAX_QUEUED_OR_RUNNING,
        }


def wait_all_worker_pools_done(timeout_ms: int = 2000) -> dict[str, bool]:
    """Parallel waitForDone for dedicated pools + globalInstance (BUG-019).

    Each pool gets its own ``waitForDone(timeout_ms)`` on a daemon thread so
    quit() wall-clock is ~timeout_ms instead of sum(5 * timeout_ms).
    """
    pools: list[tuple[str, QThreadPool]] = [
        ("capture", capture_worker_pool()),
        ("ai", ai_worker_pool()),
        ("meme_ai", meme_ai_pool()),
        ("meme_fetch", meme_fetch_pool()),
        ("virtual_host", virtual_host_worker_pool()),
        ("global", QThreadPool.globalInstance()),
    ]
    results: dict[str, bool] = {}
    threads: list[threading.Thread] = []

    def _wait(label: str, pool: QThreadPool) -> None:
        results[label] = pool.waitForDone(timeout_ms)

    for label, pool in pools:
        thread = threading.Thread(target=_wait, args=(label, pool), daemon=True)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    return results


def worker_pool_for_label(label: str) -> QThreadPool | None:
    """Return the QThreadPool for a wait label (for quit timeout logging)."""
    if label == "capture":
        return capture_worker_pool()
    if label == "ai":
        return ai_worker_pool()
    if label == "meme_ai":
        return meme_ai_pool()
    if label == "meme_fetch":
        return meme_fetch_pool()
    if label == "virtual_host":
        return virtual_host_worker_pool()
    if label == "global":
        return QThreadPool.globalInstance()
    return None
