from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from app.knowledge.runtime_service import KnowledgeRuntimeService


class _BlockingRetriever:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls: list[str] = []
        self.marked: list[list[int]] = []

    def retrieve(self, **kwargs):
        self.calls.append(threading.current_thread().name)
        self.started.set()
        self.release.wait(timeout=2)
        return SimpleNamespace(
            prompt_text="知识注入",
            items=[{"id": 7, "public_id": "ki_7", "content": "内容"}],
            hit_count=1,
            retrieval_ms=1,
            fts_backend="fallback",
        )

    def set_last_injected(self, contents):
        self.calls.append(threading.current_thread().name)

    def mark_items_used(self, item_ids):
        self.marked.append(list(item_ids))
        self.calls.append(threading.current_thread().name)


class _BlockingRepository:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def get_item_ids_by_public_ids(self, public_ids):
        self.started.set()
        self.release.wait(timeout=2)
        return [7]


def _runtime(retriever, repository=None):
    runtime = KnowledgeRuntimeService.__new__(KnowledgeRuntimeService)
    runtime._app = None
    runtime._db = object()
    runtime.repository = repository
    runtime.import_orchestrator = None
    runtime.retriever = retriever
    runtime._last_injection = None
    runtime._last_scene_context = None
    runtime._cached_scene_generation = 1
    runtime._last_retrieval_diagnostic = "empty_query"
    runtime._closing = False
    runtime._closed = False
    runtime._lifecycle_state = "accepting"
    runtime._shutdown_deadline_at = None
    runtime._close_finalized = False
    runtime._lifecycle_lock = threading.RLock()
    runtime._retrieval_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="knowledge-retrieval",
    )
    runtime._retrieval_futures = set()
    runtime._retrieval_lock = threading.RLock()
    runtime._retrieval_accepting = True
    runtime._retrieval_executor_closed = False
    runtime._retrieval_drain_callback = None
    runtime._retrieval_pending_keys = set()
    runtime._retrieval_cache = {}
    runtime._retrieval_scene_generation = 1
    runtime._retrieval_deadline_sec = 0.05
    return runtime


def _close_runtime(runtime):
    runtime._retrieval_executor.shutdown(wait=True, cancel_futures=True)


def test_visual_retrieval_and_count_write_do_not_block_main_thread():
    retriever = _BlockingRetriever()
    runtime = _runtime(retriever)
    try:
        started_at = time.monotonic()
        assert (
            runtime.prepare_visual_prompt_injection(
                "主题", ["关键词"], request_round=1, screenshot_id=2, scene_generation=1
            )
            is None
        )
        assert time.monotonic() - started_at < 0.15
        assert retriever.started.wait(timeout=1)

        retriever.release.set()
        deadline = time.monotonic() + 1
        while not runtime._retrieval_cache and time.monotonic() < deadline:
            time.sleep(0.01)

        injection = runtime.prepare_visual_prompt_injection(
            "主题", ["关键词"], request_round=2, screenshot_id=3, scene_generation=1
        )
        assert injection is not None
        assert injection.item_ids == (7,)
        deadline = time.monotonic() + 1
        while not retriever.marked and time.monotonic() < deadline:
            time.sleep(0.01)
        assert retriever.marked == [[7]]
        assert all(name.startswith("knowledge-retrieval") for name in retriever.calls)
    finally:
        _close_runtime(runtime)


def test_preview_has_deadline_without_blocking_qt_owner():
    retriever = _BlockingRetriever()
    runtime = _runtime(retriever)
    try:
        started_at = time.monotonic()
        result = runtime.preview_retrieval(
            {"scene_brief": "主题", "keywords": ["关键词"]}, deadline_sec=0.03
        )
        elapsed = time.monotonic() - started_at
        assert result == {"error": "retrieval_timeout"}
        assert elapsed < 0.2
        assert retriever.started.wait(timeout=1)
    finally:
        retriever.release.set()
        _close_runtime(runtime)


def test_late_scene_result_is_not_published_to_new_generation():
    retriever = _BlockingRetriever()
    runtime = _runtime(retriever)
    try:
        runtime.prepare_visual_prompt_injection(
            "主题", ["关键词"], request_round=1, screenshot_id=2, scene_generation=1
        )
        assert retriever.started.wait(timeout=1)
        runtime.note_scene_generation(2)
        retriever.release.set()
        deadline = time.monotonic() + 1
        while runtime._retrieval_futures and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runtime._retrieval_cache == {}
    finally:
        _close_runtime(runtime)


def test_reply_consumption_count_write_is_queued():
    retriever = _BlockingRetriever()
    repository = _BlockingRepository()
    runtime = _runtime(retriever, repository)
    try:
        started_at = time.monotonic()
        runtime.on_reply_consumed(["ki_7"])
        assert time.monotonic() - started_at < 0.15
        assert repository.started.wait(timeout=1)
        repository.release.set()
        deadline = time.monotonic() + 1
        while not retriever.marked and time.monotonic() < deadline:
            time.sleep(0.01)
        assert retriever.marked == [[7]]
    finally:
        _close_runtime(runtime)
