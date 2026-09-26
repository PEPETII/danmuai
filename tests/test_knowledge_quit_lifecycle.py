"""P2-13 knowledge/route shutdown ownership tests."""

from __future__ import annotations

import threading
from unittest.mock import patch

from app.knowledge.runtime_service import KnowledgeRuntimeService


class _FakeOrganizer:
    def __init__(self, order: list[str]) -> None:
        self.done = threading.Event()
        self.begin_calls = 0
        self.close_calls = 0
        self._order = order

    def begin_shutdown(self, callback=None) -> None:
        self.begin_calls += 1
        if callback is not None:
            self.callback = callback

    def is_drained(self) -> bool:
        return self.done.is_set()

    def close(self, *, wait=True) -> None:
        self.close_calls += 1
        self._order.append("import_close")


class _FakeDatabase:
    def __init__(self, order: list[str]) -> None:
        self.close_calls = 0
        self._order = order

    def close(self) -> None:
        self.close_calls += 1
        self._order.append("db_close")


def _runtime(order: list[str]):
    runtime = KnowledgeRuntimeService.__new__(KnowledgeRuntimeService)
    runtime._app = None
    runtime._db = _FakeDatabase(order)
    runtime.repository = object()
    runtime.import_orchestrator = _FakeOrganizer(order)
    runtime.retriever = object()
    runtime._last_injection = None
    runtime._last_scene_context = None
    runtime._cached_scene_generation = None
    runtime._last_retrieval_diagnostic = "empty_query"
    runtime._closing = False
    runtime._closed = False
    runtime._mount_result = True
    runtime._lifecycle_state = "accepting"
    runtime._shutdown_deadline_at = None
    runtime._close_finalized = False
    runtime._lifecycle_lock = threading.RLock()
    runtime._retrieval_lock = threading.RLock()
    runtime._retrieval_futures = set()
    runtime._retrieval_accepting = False
    runtime._retrieval_executor_closed = True
    return runtime


def _route_fakes(order: list[str]):
    route_done = threading.Event()
    calls = {"begin": 0, "close": 0}

    def begin(callback=None):
        calls["begin"] += 1

    def drained():
        return route_done.is_set()

    def close():
        calls["close"] += 1
        order.append("route_close")
        return True

    return route_done, calls, begin, drained, close


def test_normal_drain_closes_route_before_import_and_db_once():
    order: list[str] = []
    runtime = _runtime(order)
    route_done, route_calls, begin, drained, close = _route_fakes(order)
    with patch(
        "app.web_api.knowledge_routes.begin_shutdown_knowledge_route_executor",
        side_effect=begin,
    ), patch(
        "app.web_api.knowledge_routes.knowledge_route_executor_is_drained",
        side_effect=drained,
    ), patch(
        "app.web_api.knowledge_routes.close_knowledge_route_executor_if_drained",
        side_effect=close,
    ):
        assert runtime.begin_shutdown(deadline_at=100.0) == "draining"
        assert runtime.begin_shutdown(deadline_at=100.0) == "draining"
        assert runtime.poll_shutdown(now=1.0) == "draining"

        route_done.set()
        runtime.import_orchestrator.done.set()
        assert runtime.poll_shutdown(now=2.0) == "closed"
        assert runtime.poll_shutdown(now=3.0) == "closed"

    assert route_calls == {"begin": 1, "close": 1}
    assert runtime.import_orchestrator is None
    assert runtime._db is None
    assert order == ["route_close", "import_close", "db_close"]


def test_deadline_timeout_keeps_worker_and_db_open_until_later_drain():
    order: list[str] = []
    runtime = _runtime(order)
    route_done, route_calls, begin, drained, close = _route_fakes(order)
    with patch(
        "app.web_api.knowledge_routes.begin_shutdown_knowledge_route_executor",
        side_effect=begin,
    ), patch(
        "app.web_api.knowledge_routes.knowledge_route_executor_is_drained",
        side_effect=drained,
    ), patch(
        "app.web_api.knowledge_routes.close_knowledge_route_executor_if_drained",
        side_effect=close,
    ):
        runtime.begin_shutdown(deadline_at=10.0)
        assert runtime.poll_shutdown(now=11.0) == "timeout"
        assert runtime.lifecycle_state == "timeout"
        assert runtime._db.close_calls == 0
        assert runtime.import_orchestrator.close_calls == 0
        assert order == []

        route_done.set()
        runtime.import_orchestrator.done.set()
        assert runtime.poll_shutdown(now=12.0) == "closed"

    assert route_calls == {"begin": 1, "close": 1}
    assert order == ["route_close", "import_close", "db_close"]


def test_repeated_close_does_not_reopen_or_close_resources_twice():
    order: list[str] = []
    runtime = _runtime(order)
    route_done, route_calls, begin, drained, close = _route_fakes(order)
    with patch(
        "app.web_api.knowledge_routes.begin_shutdown_knowledge_route_executor",
        side_effect=begin,
    ), patch(
        "app.web_api.knowledge_routes.knowledge_route_executor_is_drained",
        side_effect=drained,
    ), patch(
        "app.web_api.knowledge_routes.close_knowledge_route_executor_if_drained",
        side_effect=close,
    ):
        route_done.set()
        runtime.import_orchestrator.done.set()
        runtime.close()
        runtime.close(wait=True)

    assert runtime.lifecycle_state == "closed"
    assert route_calls == {"begin": 1, "close": 1}
    assert runtime._db is None
    assert order == ["route_close", "import_close", "db_close"]
