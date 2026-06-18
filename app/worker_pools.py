"""Dedicated Qt thread pools (S-014).

Visual/mic AI use a small isolated pool so hung meme/TTS/probe tasks on the global
pool cannot occupy every worker thread.

W-PERF-HIGH-001: capture_worker_pool isolates screen grab from AI HTTP workers.
"""

from __future__ import annotations

from PyQt6.QtCore import QThreadPool

_ai_pool: QThreadPool | None = None
_capture_pool: QThreadPool | None = None


def _pool_is_usable(pool) -> bool:
    if pool is None:
        return False
    try:
        pool.maxThreadCount()
    except RuntimeError:
        return False
    return True


def ai_worker_pool() -> QThreadPool:
    global _ai_pool
    if not _pool_is_usable(_ai_pool):
        pool = QThreadPool()
        pool.setMaxThreadCount(2)
        _ai_pool = pool
    return _ai_pool


def capture_worker_pool() -> QThreadPool:
    global _capture_pool
    if not _pool_is_usable(_capture_pool):
        pool = QThreadPool()
        pool.setMaxThreadCount(1)
        _capture_pool = pool
    return _capture_pool
