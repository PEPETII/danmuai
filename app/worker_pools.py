"""Dedicated Qt thread pools (S-014).

Visual/mic AI use a small isolated pool so hung meme/TTS/probe tasks on the global
pool cannot occupy every worker thread.

W-PERF-HIGH-001: capture_worker_pool isolates screen grab from AI HTTP workers.
BUG-G05: meme_ai_pool isolates meme AI select from main visual AI requests.
"""

from __future__ import annotations

from PyQt6.QtCore import QThreadPool

_ai_pool: QThreadPool | None = None
_capture_pool: QThreadPool | None = None
_meme_ai_pool: QThreadPool | None = None


def ai_worker_pool() -> QThreadPool:
    global _ai_pool
    if _ai_pool is None:
        pool = QThreadPool()
        pool.setMaxThreadCount(2)
        _ai_pool = pool
    return _ai_pool


def capture_worker_pool() -> QThreadPool:
    global _capture_pool
    if _capture_pool is None:
        pool = QThreadPool()
        pool.setMaxThreadCount(1)
        _capture_pool = pool
    return _capture_pool


def meme_ai_pool() -> QThreadPool:
    """Isolated pool for meme AI select; does not compete with main visual AI."""
    global _meme_ai_pool
    if _meme_ai_pool is None:
        pool = QThreadPool()
        pool.setMaxThreadCount(1)
        _meme_ai_pool = pool
    return _meme_ai_pool
