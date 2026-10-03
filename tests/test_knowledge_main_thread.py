from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from app.knowledge.database import KnowledgeDatabase
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.retriever import KnowledgeRetriever
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


def _wait_for_retrieval_drain(runtime):
    deadline = time.monotonic() + 3
    while not runtime.is_retrieval_drained() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert runtime.is_retrieval_drained()


def test_burst_bounds_queries_and_usage_preserving_sqlite_increments(tmp_path):
    db = KnowledgeDatabase._open_at(tmp_path / "capacity.db")
    repo = KnowledgeRepository(db)
    package = repo.create_package(name="capacity")
    package = repo.get_package(package["public_id"])
    assert package is not None
    source = repo.create_source(package_id=package["id"], source_type="pasted_text", display_name="test")
    from app.knowledge.repository import insert_item_for_db

    item = insert_item_for_db(
        db, package_id=package["id"], source_id=source["id"], chunk_id=None,
        kind="fact", title="test", content="test content",
    )
    retriever = _BlockingRetriever()
    real_retriever = KnowledgeRetriever(db)
    retriever.mark_items_used = real_retriever.mark_items_used
    runtime = _runtime(retriever, repo)
    try:
        started_at = time.monotonic()
        for index in range(1000):
            runtime.prepare_visual_prompt_injection(
                f"query-{index}", [], request_round=index, screenshot_id=index,
                scene_generation=1, deadline_sec=30,
            )
        assert time.monotonic() - started_at < 1.0
        assert retriever.started.wait(timeout=1)
        assert runtime.get_retrieval_diagnostic() == "retrieval_busy"

        # Visual saturation must leave two preview query slots available.
        for index in range(2):
            key = runtime._retrieval_key(f"preview-{index}", [], [], 1, purpose="preview")
            assert runtime._queue_retrieval(
                key=key, scene_brief=f"preview-{index}", keywords=[], scene_tags=[],
                request_round=0, screenshot_id=0, scene_generation=1,
                deadline_sec=30, cache_result=False,
            ) is not None
        assert runtime.preview_retrieval({"scene_brief": "over-cap"}) == {"error": "retrieval_pending"}

        for _ in range(1000):
            runtime.submit_usage_write([item["public_id"]], deadline_sec=30)
        pressure = runtime.get_retrieval_pressure()
        assert pressure["query_pending"] == 8
        assert pressure["visual_pending"] == 6
        assert pressure["usage_pending"] == 64
        assert pressure["usage_future"] == 1
        assert pressure["query_rejected"] == 995
        assert pressure["usage_rejected"] == 936
        assert len(runtime._retrieval_futures) == 9
        assert runtime.get_retrieval_diagnostic() == "count_write_failed"

        retriever.release.set()
        _wait_for_retrieval_drain(runtime)
        with db.read_connection() as conn:
            assert conn.execute(
                "SELECT use_count FROM knowledge_items WHERE id=?", (item["id"],)
            ).fetchone()[0] == 64
        assert runtime.get_retrieval_pressure()["usage_pending"] == 0
    finally:
        retriever.release.set()
        _close_runtime(runtime)
        db.close()


def test_usage_expiration_and_scene_change_skip_writes():
    retriever = _BlockingRetriever()
    repo = SimpleNamespace(get_item_ids_by_public_ids=lambda public_ids: [7])
    runtime = _runtime(retriever, repo)
    try:
        runtime.prepare_visual_prompt_injection(
            "blocked", [], request_round=1, screenshot_id=1, scene_generation=1,
            deadline_sec=30,
        )
        assert retriever.started.wait(timeout=1)
        runtime.submit_usage_write(["ki_7"], deadline_sec=0.01)
        injection = SimpleNamespace(item_ids=(7,))
        runtime._queue_injection_usage(
            injection, contents=["old"], scene_generation=1, deadline_sec=30,
        )
        time.sleep(0.02)
        runtime.note_scene_generation(2)
        retriever.release.set()
        _wait_for_retrieval_drain(runtime)
        assert retriever.marked == []
        assert runtime.get_retrieval_pressure()["usage_expired"] == 2
        assert runtime._retrieval_cache == {}
    finally:
        retriever.release.set()
        _close_runtime(runtime)


def test_expired_queued_queries_do_not_access_retriever():
    retriever = _BlockingRetriever()
    runtime = _runtime(retriever)
    try:
        runtime.prepare_visual_prompt_injection(
            "first", [], request_round=1, screenshot_id=1, scene_generation=1,
            deadline_sec=30,
        )
        assert retriever.started.wait(timeout=1)
        runtime.prepare_visual_prompt_injection(
            "expired", [], request_round=2, screenshot_id=2, scene_generation=1,
            deadline_sec=0.01,
        )
        time.sleep(0.02)
        retriever.release.set()
        _wait_for_retrieval_drain(runtime)
        assert len(retriever.calls) == 1
        assert runtime._retrieval_pending_keys == set()
    finally:
        retriever.release.set()
        _close_runtime(runtime)


def test_cache_capacity_and_full_expiration_sweep():
    retriever = _BlockingRetriever()
    retriever.release.set()
    runtime = _runtime(retriever)
    try:
        for index in range(200):
            runtime.prepare_visual_prompt_injection(
                f"unique-{index}", [], request_round=index, screenshot_id=index,
                scene_generation=1, deadline_sec=30,
            )
            _wait_for_retrieval_drain(runtime)
        assert len(runtime._retrieval_cache) == 64
        assert all("unique-0" != key[2] for key in runtime._retrieval_cache)
        for key, (result, _) in list(runtime._retrieval_cache.items()):
            runtime._retrieval_cache[key] = (result, time.monotonic() - 181)
        runtime.prepare_visual_prompt_injection(
            "fresh", [], request_round=201, screenshot_id=201,
            scene_generation=1, deadline_sec=30,
        )
        _wait_for_retrieval_drain(runtime)
        assert len(runtime._retrieval_cache) == 1
        assert next(iter(runtime._retrieval_cache))[2] == "fresh"
    finally:
        _close_runtime(runtime)


def test_continuous_usage_producer_yields_to_waiting_queries():
    retriever = _BlockingRetriever()
    runtime = _runtime(retriever)
    started = threading.Event()
    release = threading.Event()
    order = []

    def mark(item_ids):
        order.append('usage')
        if len(order) == 1:
            started.set()
            assert release.wait(timeout=2)
        # Keep the drain nonempty beyond a full batch.
        if order.count('usage') < 70:
            assert runtime._queue_usage_event(('injection', (7,), (), 1, time.monotonic() + 30))

    def retrieve(**kwargs):
        order.append('query')
        return None

    retriever.mark_items_used = mark
    retriever.retrieve = retrieve
    try:
        assert runtime._queue_usage_event(('injection', (7,), (), 1, time.monotonic() + 30))
        assert started.wait(timeout=1)
        key = runtime._retrieval_key('waiting', [], [], 1, purpose='preview')
        assert runtime._queue_retrieval(
            key=key, scene_brief='waiting', keywords=[], scene_tags=[],
            request_round=0, screenshot_id=0, scene_generation=1,
            deadline_sec=30, cache_result=False,
        ) is not None
        release.set()
        _wait_for_retrieval_drain(runtime)
        assert order.index('query') == 64
        assert order.count('usage') == 70
    finally:
        release.set()
        _close_runtime(runtime)


def test_retrieval_worker_error_log_does_not_include_query_text(caplog):
    retriever = _BlockingRetriever()
    runtime = _runtime(retriever)

    def fail(**kwargs):
        raise RuntimeError('synthetic-private-query')

    retriever.retrieve = fail
    try:
        runtime.prepare_visual_prompt_injection(
            'synthetic-private-query', [], request_round=1, screenshot_id=1,
            scene_generation=1, deadline_sec=30,
        )
        _wait_for_retrieval_drain(runtime)
        assert 'type=RuntimeError' in caplog.text
        assert 'synthetic-private-query' not in caplog.text
    finally:
        _close_runtime(runtime)
