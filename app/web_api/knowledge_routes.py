"""知识包 Web API 路由注册（A8.2）。

风格仿 ``app/web_api/meme_barrage_routes.py``：
- GET 路由无 ``@require_auth``；POST/PATCH/DELETE 加 ``@require_auth(check_token)``。
- 写操作经 ``invoke_main(knowledge_api.fn, bridge.danmu_app, ...)`` 同步到主线程。
- Pydantic 模型直接复用 ``app/knowledge/models.py`` 已定义的
  ``PackageCreatePayload`` / ``PackageUpdatePayload`` / ``ImportPayload`` /
  ``ItemUpdatePayload`` / ``RetrievalPreviewPayload``，获得自动校验。
- 长任务（import_source）用 ``async def`` + ``loop.run_in_executor``；
  实际执行已在 ``ImportOrchestrator`` 内异步派发，
  路由层只创建 source/job 行后立即返回。

边界约束（AGENTS.md §9.4 / §A.5.3）：
- 不在 HTTP 线程读 DanmuApp 私有字段（``_<private>``）；
- 所有写操作经 ``invoke_main`` 错误映射（504/400/403/500）。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable

from fastapi import Header, HTTPException, Query

from app.knowledge.models import (
    ImportPayload,
    ItemUpdatePayload,
    PackageCreatePayload,
    PackageUpdatePayload,
    RetrievalPreviewPayload,
)
from app.web_api import knowledge as knowledge_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge

logger = logging.getLogger(__name__)

# 路由层专用执行器：仅用于把 import_source 的 invoke_main 调用移出事件循环
# （实际长任务在 ImportOrchestrator 内的 knowledge-import 执行器中跑）。
class KnowledgeRouteExecutor:
    """Own route-adapter workers and expose a bounded drain observation point."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="knowledge-route",
        )
        self._futures: set[Future] = set()
        self._drain_callbacks: list[Callable[[], None]] = []
        self._accepting = True
        self._shutdown_started = False
        self._closed = False
        self._lock = threading.Lock()

    def submit(self, fn, /, *args, **kwargs):
        with self._lock:
            if not self._accepting:
                raise RuntimeError("knowledge route executor is stopping")
            future = self._executor.submit(fn, *args, **kwargs)
            self._futures.add(future)
        future.add_done_callback(self._on_done)
        return future

    def begin_shutdown(self, on_drained: Callable[[], None] | None = None) -> None:
        with self._lock:
            if callable(on_drained):
                self._drain_callbacks.append(on_drained)
            first_shutdown = not self._shutdown_started
            self._accepting = False
            self._shutdown_started = True
        if first_shutdown:
            self._executor.shutdown(wait=False, cancel_futures=True)
        self._notify_if_drained()

    def is_accepting(self) -> bool:
        with self._lock:
            return self._accepting

    def is_drained(self) -> bool:
        with self._lock:
            return not self._futures

    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def close(self, *, wait: bool = False) -> None:
        """Close once; callers must only use ``wait=True`` after drain."""
        with self._lock:
            if self._closed:
                return
        self.begin_shutdown()
        self._executor.shutdown(wait=wait, cancel_futures=True)
        if not wait or self.is_drained():
            with self._lock:
                self._closed = True

    def _on_done(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)
        self._notify_if_drained()

    def _notify_if_drained(self) -> None:
        with self._lock:
            if self._futures:
                return
            callbacks, self._drain_callbacks = self._drain_callbacks, []
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception("knowledge route executor drain callback failed")


_KNOWLEDGE_EXECUTOR = KnowledgeRouteExecutor()
_KNOWLEDGE_EXECUTOR_LOCK = threading.Lock()


_KNOWLEDGE_ERROR_STATUSES = {
    "not_initialized": 503,
    "runtime_unavailable": 503,
    "service_unavailable": 503,
    "orchestrator_not_ready": 503,
    "retriever_not_ready": 503,
    "orchestrator_stopping": 409,
    "not_found": 404,
    "package_not_found": 404,
    "not_found_or_completed": 409,
}


def _knowledge_error_status(error_code: str) -> int:
    if error_code in _KNOWLEDGE_ERROR_STATUSES:
        return _KNOWLEDGE_ERROR_STATUSES[error_code]
    if (
        error_code.startswith(("missing_", "invalid_", "unknown_", "decode_"))
        or error_code in {"source_too_large", "parameter_bad"}
    ):
        return 400
    return 500


def _knowledge_result(result):
    """Turn legacy business ``{"error": code}`` results into HTTP errors."""
    if isinstance(result, dict):
        error_code = result.get("error")
        if error_code:
            code = str(error_code)
            raise HTTPException(
                status_code=_knowledge_error_status(code),
                detail={"ok": False, "error": code},
            )
    return result


def _knowledge_read(fn, *args, **kwargs):
    try:
        return _knowledge_result(fn(*args, **kwargs))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("knowledge read failed for %r", fn)
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "error": "internal_error"},
        ) from exc


def _knowledge_invoke(invoke_main, fn, *args, **kwargs):
    try:
        return _knowledge_result(invoke_main(fn, *args, **kwargs))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("knowledge invoke failed for %r", fn)
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "error": "internal_error"},
        ) from exc


def _get_knowledge_executor() -> KnowledgeRouteExecutor:
    global _KNOWLEDGE_EXECUTOR
    with _KNOWLEDGE_EXECUTOR_LOCK:
        if _KNOWLEDGE_EXECUTOR.is_closed():
            _KNOWLEDGE_EXECUTOR = KnowledgeRouteExecutor()
        return _KNOWLEDGE_EXECUTOR


def begin_shutdown_knowledge_route_executor(
    on_drained: Callable[[], None] | None = None,
) -> None:
    """Reject new route work and cancel queued adapter calls without waiting."""
    _get_knowledge_executor().begin_shutdown(on_drained)


def knowledge_route_executor_is_drained() -> bool:
    return _get_knowledge_executor().is_drained()


def close_knowledge_route_executor_if_drained() -> bool:
    executor = _get_knowledge_executor()
    if not executor.is_drained():
        return False
    executor.close(wait=True)
    return True


def shutdown_knowledge_route_executor(*, wait: bool = True) -> None:
    """Release route adapter threads during true whole-application teardown."""
    _get_knowledge_executor().close(wait=wait)


def register_knowledge_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    """注册知识包 Web API 路由。

    路由清单：
        GET    /api/knowledge/packages                      — 列出所有知识包
        POST   /api/knowledge/packages                      — 创建知识包
        GET    /api/knowledge/packages/{package_id}         — 知识包详情
        PATCH  /api/knowledge/packages/{package_id}         — 更新知识包
        DELETE /api/knowledge/packages/{package_id}         — 删除知识包（级联）
        POST   /api/knowledge/packages/{package_id}/imports — 创建来源 + 提交导入任务
        GET    /api/knowledge/jobs                          — 列出任务
        GET    /api/knowledge/jobs/{job_id}                 — 任务详情
        POST   /api/knowledge/jobs/{job_id}/cancel          — 协作式取消
        GET    /api/knowledge/items                         — 列出条目（分页+筛选）
        GET    /api/knowledge/items/{item_id}               — 条目详情
        PATCH  /api/knowledge/items/{item_id}               — 更新条目
        DELETE /api/knowledge/items/{item_id}               — 删除条目
        POST   /api/knowledge/retrieval/preview             — 检索预览
    """

    # ------------------------------------------------------------------
    # packages
    # ------------------------------------------------------------------

    @app.get("/api/knowledge/packages")
    def list_packages():
        return _knowledge_read(knowledge_api.list_packages, bridge.danmu_app)

    @app.post("/api/knowledge/packages")
    @require_auth(check_token)
    def create_package(
        body: PackageCreatePayload,
        authorization: str | None = Header(default=None),
    ):
        return _knowledge_invoke(
            invoke_main,
            knowledge_api.create_package,
            bridge.danmu_app,
            body.model_dump(exclude_none=True),
        )

    @app.get("/api/knowledge/packages/{package_id}")
    def get_package(package_id: str, summary: bool = Query(default=False)):
        return _knowledge_read(
            knowledge_api.get_package,
            bridge.danmu_app, package_id, summary=summary
        )

    @app.patch("/api/knowledge/packages/{package_id}")
    @require_auth(check_token)
    def update_package(
        package_id: str,
        body: PackageUpdatePayload,
        authorization: str | None = Header(default=None),
    ):
        return _knowledge_invoke(
            invoke_main,
            knowledge_api.update_package,
            bridge.danmu_app,
            package_id,
            body.model_dump(exclude_none=True),
        )

    @app.delete("/api/knowledge/packages/{package_id}")
    @require_auth(check_token)
    def delete_package(
        package_id: str,
        authorization: str | None = Header(default=None),
    ):
        return _knowledge_invoke(
            invoke_main,
            knowledge_api.delete_package, bridge.danmu_app, package_id
        )

    # ------------------------------------------------------------------
    # imports（长任务：async + run_in_executor）
    # ------------------------------------------------------------------

    @app.post("/api/knowledge/packages/{package_id}/imports")
    @require_auth(check_token)
    async def import_source(
        package_id: str,
        body: ImportPayload,
        authorization: str | None = Header(default=None),
    ):
        """创建 source 行 + 提交到 ImportOrchestrator，立即返回 job_id。

        实际处理在 ``ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-import")``
        中进行；前端轮询 ``GET /api/knowledge/jobs/{job_id}`` 获取进度。
        """
        payload = body.model_dump(exclude_none=True)
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                _get_knowledge_executor(),
                lambda: invoke_main(
                    knowledge_api.import_source,
                    bridge.danmu_app,
                    package_id,
                    payload,
                ),
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("knowledge import route failed")
            raise HTTPException(
                status_code=500,
                detail={"ok": False, "error": "internal_error"},
            ) from exc
        return _knowledge_result(result)

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------

    @app.get("/api/knowledge/jobs")
    def list_jobs(
        package_id: str | None = Query(default=None),
    ):
        return _knowledge_read(
            knowledge_api.list_jobs, bridge.danmu_app, package_id
        )

    @app.get("/api/knowledge/jobs/{job_id}")
    def get_job(job_id: str):
        return _knowledge_read(knowledge_api.get_job, bridge.danmu_app, job_id)

    @app.post("/api/knowledge/jobs/{job_id}/cancel")
    @require_auth(check_token)
    def cancel_job(
        job_id: str,
        authorization: str | None = Header(default=None),
    ):
        return _knowledge_invoke(
            invoke_main, knowledge_api.cancel_job, bridge.danmu_app, job_id
        )

    # ------------------------------------------------------------------
    # items
    # ------------------------------------------------------------------

    @app.get("/api/knowledge/items")
    def list_items(
        package_id: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        enabled: bool | None = Query(default=None),
        query: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ):
        return _knowledge_read(
            knowledge_api.list_items,
            bridge.danmu_app,
            package_id,
            kind,
            enabled,
            query,
            page,
            page_size,
        )

    @app.get("/api/knowledge/items/{item_id}")
    def get_item(item_id: str):
        return _knowledge_read(knowledge_api.get_item, bridge.danmu_app, item_id)

    @app.patch("/api/knowledge/items/{item_id}")
    @require_auth(check_token)
    def update_item(
        item_id: str,
        body: ItemUpdatePayload,
        authorization: str | None = Header(default=None),
    ):
        return _knowledge_invoke(
            invoke_main,
            knowledge_api.update_item,
            bridge.danmu_app,
            item_id,
            body.model_dump(exclude_none=True),
        )

    @app.delete("/api/knowledge/items/{item_id}")
    @require_auth(check_token)
    def delete_item(
        item_id: str,
        authorization: str | None = Header(default=None),
    ):
        return _knowledge_invoke(
            invoke_main, knowledge_api.delete_item, bridge.danmu_app, item_id
        )

    # ------------------------------------------------------------------
    # retrieval preview
    # ------------------------------------------------------------------

    @app.post("/api/knowledge/retrieval/preview")
    @require_auth(check_token)
    def preview_retrieval(
        body: RetrievalPreviewPayload,
        authorization: str | None = Header(default=None),
    ):
        return _knowledge_read(
            knowledge_api.preview_retrieval,
            bridge.danmu_app,
            body.model_dump(exclude_none=True),
        )
