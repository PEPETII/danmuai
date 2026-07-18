"""知识包 Web API 路由注册（A8.2）。

风格仿 ``app/web_api/meme_barrage_routes.py``：
- GET 路由无 ``@require_auth``；POST/PATCH/DELETE 加 ``@require_auth(check_token)``。
- 写操作经 ``invoke_main(knowledge_api.fn, bridge.danmu_app, ...)`` 同步到主线程。
- Pydantic 模型直接复用 ``app/knowledge/models.py`` 已定义的
  ``PackageCreatePayload`` / ``PackageUpdatePayload`` / ``ImportPayload`` /
  ``ItemUpdatePayload`` / ``RetrievalPreviewPayload``，获得自动校验。
- 长任务（import_source）用 ``async def`` + ``loop.run_in_executor`` 仿
  ``app/web_api/ai_butler.py``；实际执行已在 ``ImportOrchestrator`` 内异步派发，
  路由层只创建 source/job 行后立即返回。

边界约束（AGENTS.md §9.4 / §A.5.3）：
- 不在 HTTP 线程读 DanmuApp 私有字段（``_<private>``）；
- 所有写操作经 ``invoke_main`` 错误映射（504/400/403/500）。
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable

from fastapi import Header, Query

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
_KNOWLEDGE_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="knowledge-route"
)


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
        return knowledge_api.list_packages(bridge.danmu_app)

    @app.post("/api/knowledge/packages")
    @require_auth(check_token)
    def create_package(
        body: PackageCreatePayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(
            knowledge_api.create_package,
            bridge.danmu_app,
            body.model_dump(exclude_none=True),
        )

    @app.get("/api/knowledge/packages/{package_id}")
    def get_package(package_id: str):
        return knowledge_api.get_package(bridge.danmu_app, package_id)

    @app.patch("/api/knowledge/packages/{package_id}")
    @require_auth(check_token)
    def update_package(
        package_id: str,
        body: PackageUpdatePayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(
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
        return invoke_main(
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
        return await loop.run_in_executor(
            _KNOWLEDGE_EXECUTOR,
            lambda: invoke_main(
                knowledge_api.import_source,
                bridge.danmu_app,
                package_id,
                payload,
            ),
        )

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------

    @app.get("/api/knowledge/jobs")
    def list_jobs(
        package_id: str | None = Query(default=None),
    ):
        return knowledge_api.list_jobs(bridge.danmu_app, package_id)

    @app.get("/api/knowledge/jobs/{job_id}")
    def get_job(job_id: str):
        return knowledge_api.get_job(bridge.danmu_app, job_id)

    @app.post("/api/knowledge/jobs/{job_id}/cancel")
    @require_auth(check_token)
    def cancel_job(
        job_id: str,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(knowledge_api.cancel_job, bridge.danmu_app, job_id)

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
        return knowledge_api.list_items(
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
        return knowledge_api.get_item(bridge.danmu_app, item_id)

    @app.patch("/api/knowledge/items/{item_id}")
    @require_auth(check_token)
    def update_item(
        item_id: str,
        body: ItemUpdatePayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(
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
        return invoke_main(knowledge_api.delete_item, bridge.danmu_app, item_id)

    # ------------------------------------------------------------------
    # retrieval preview
    # ------------------------------------------------------------------

    @app.post("/api/knowledge/retrieval/preview")
    @require_auth(check_token)
    def preview_retrieval(
        body: RetrievalPreviewPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(
            knowledge_api.preview_retrieval,
            bridge.danmu_app,
            body.model_dump(exclude_none=True),
        )
