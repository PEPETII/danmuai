"""知识包 Web API 服务函数（纯业务逻辑，参数 ``app``）。

风格仿 ``app/web_api/meme_barrage.py``：每个函数接受 ``app: DanmuApp`` 作为
第一参数，返回 dict 或 list。读操作直接读 ``app.knowledge_runtime``；写操作
经路由层 ``invoke_main`` 同步到主线程（与 ``meme_barrage`` 一致）。

边界约束（AGENTS.md §9.4 / §A.5.3）：
- 不在 HTTP 线程读 DanmuApp 私有字段（``_<private>``）；
- 只通过 ``getattr(app, "knowledge_runtime", None)`` 守卫访问（B2 任务挂载）；
- 写操作经路由层 ``invoke_main`` 同步到主线程；
- 错误返回沿用 ``{"error": "..."}`` 风格（与 meme_barrage 一致）。

异步导入：``import_source`` 创建 source 行 + 提交到 ``ImportOrchestrator``
后台执行器（``ThreadPoolExecutor(max_workers=1)``），立即返回 ``job_id``；
前端轮询 ``GET /api/knowledge/jobs/{id}`` 获取进度。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from main import DanmuApp


__all__ = [
    "list_packages",
    "get_package",
    "create_package",
    "update_package",
    "delete_package",
    "import_source",
    "get_job",
    "cancel_job",
    "list_jobs",
    "list_items",
    "get_item",
    "update_item",
    "delete_item",
    "preview_retrieval",
]


def _get_knowledge_runtime(app: "DanmuApp"):
    """获取 ``app.knowledge_runtime``（B2 任务挂载；A8 阶段可能为 None）。

    返回 None 时不抛异常，调用方各自处理。
    """
    return getattr(app, "knowledge_runtime", None)


def _get_or_create_repository(app: "DanmuApp"):
    """从 ``knowledge_runtime`` 取 repository；若 runtime 未初始化（B2 前），返回 None。"""
    runtime = _get_knowledge_runtime(app)
    if runtime is None:
        return None
    return getattr(runtime, "repository", None)


def list_packages(app: "DanmuApp") -> dict[str, Any]:
    """GET /api/knowledge/packages — 列出所有知识包。

    Returns:
        ``{"packages": [...], "total": N}``。每个 package 附加 ``source_count``
        与 ``item_count``。若 runtime 未初始化返回
        ``{"packages": [], "total": 0, "error": "not_initialized"}``。
    """
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"packages": [], "total": 0, "error": "not_initialized"}
    packages = repo.list_packages()
    # 为每个 package 附加 source_count 与 item_count
    for pkg in packages:
        sources = repo.list_sources(pkg["id"])
        items = repo.list_items(package_id=pkg["id"])
        pkg["source_count"] = len(sources)
        pkg["item_count"] = items["total"]
    return {"packages": packages, "total": len(packages)}


def get_package(app: "DanmuApp", package_public_id: str) -> dict[str, Any]:
    """GET /api/knowledge/packages/{id} — 详情（含 sources 与 items 概要）。"""
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"error": "not_initialized"}
    pkg = repo.get_package(package_public_id)
    if pkg is None:
        return {"error": "not_found"}
    sources = repo.list_sources(pkg["id"])
    items = repo.list_items(package_id=pkg["id"])
    pkg["sources"] = sources
    pkg["items"] = items
    return pkg


def create_package(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, Any]:
    """POST /api/knowledge/packages — 创建知识包。

    Returns:
        ``{"ok": True, "package_id": "<public_id>"}``（spec §ADDED Web API Scenario）。
        runtime 未初始化返回 ``{"error": "not_initialized"}``。
    """
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"error": "not_initialized"}
    pkg = repo.create_package(
        name=payload.get("name", ""),
        description=payload.get("description", ""),
        content_kind=payload.get("content_kind", "auto"),
        scope_mode=payload.get("scope_mode", "global"),
        scope_tags=payload.get("scope_tags", []),
        enabled=payload.get("enabled", True),
        priority=payload.get("priority", 0),
    )
    return {"ok": True, "package_id": pkg["public_id"]}


def update_package(
    app: "DanmuApp", package_public_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """PATCH /api/knowledge/packages/{id} — 更新。返回更新后 package dict。"""
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"error": "not_initialized"}
    updated = repo.update_package(package_public_id, **payload)
    if updated is None:
        return {"error": "not_found"}
    return updated


def delete_package(
    app: "DanmuApp", package_public_id: str
) -> dict[str, Any]:
    """DELETE /api/knowledge/packages/{id} — 删除（级联）。

    Returns:
        ``{"ok": True}`` 或 ``{"error": ...}``。
    """
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"error": "not_initialized"}
    ok = repo.delete_package(package_public_id)
    if not ok:
        return {"error": "not_found"}
    return {"ok": True}


def _validate_import_payload(payload: dict[str, Any]) -> str | None:
    """导入请求跨字段校验；通过返回 ``None``，否则返回稳定 error code。

    在 ``create_source`` / ``submit_import`` 之前调用，避免无效 payload 留下
    空 source / job。与 ``ImportPayload`` 的 model_validator 错误码对齐。
    """
    import base64
    from urllib.parse import urlparse

    # 与 source_extractors.MAX_RESPONSE_BYTES 同量级（避免循环 import）
    max_response_bytes = 10 * 1024 * 1024

    source_type = payload.get("source_type") or "pasted_text"
    if source_type == "pasted_text":
        if not str(payload.get("pasted_text") or "").strip():
            return "missing_pasted_text"
        return None

    if source_type in ("txt", "markdown"):
        b64 = str(payload.get("content_base64") or "").strip()
        if not b64:
            return "missing_content_base64"
        max_b64_len = (max_response_bytes * 4) // 3 + 8
        if len(b64) > max_b64_len:
            return "source_too_large"
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception:
            try:
                raw = base64.b64decode(b64, validate=False)
            except Exception:
                return "invalid_base64"
        if len(raw) > max_response_bytes:
            return "source_too_large"
        return None

    if source_type == "webpage":
        url = str(payload.get("source_url") or "").strip()
        if not url:
            return "missing_source_url"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return "invalid_source_url"
        return None

    return "unknown_source_type"


def import_source(
    app: "DanmuApp", package_public_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """POST /api/knowledge/packages/{id}/imports — 创建 source + 提交导入任务。

    立即返回 ``job_id``；实际处理在 ``ImportOrchestrator`` 后台执行器中
    （``ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-import")``）。
    前端轮询 ``GET /api/knowledge/jobs/{job_id}`` 获取进度。

    Returns:
        ``{"job_id": "...", "source_id": "..."}`` 或 ``{"error": ...}``。
    """
    runtime = _get_knowledge_runtime(app)
    if runtime is None:
        return {"error": "not_initialized"}
    repo = runtime.repository
    orchestrator = getattr(runtime, "import_orchestrator", None)
    if orchestrator is None:
        return {"error": "orchestrator_not_ready"}

    pkg = repo.get_package(package_public_id)
    if pkg is None:
        return {"error": "package_not_found"}

    # 校验必须在 create_source 之前，避免无效 payload 留下空 source/job
    validation_error = _validate_import_payload(payload or {})
    if validation_error:
        return {"error": validation_error}

    # 创建 source 行
    source_type = payload.get("source_type", "pasted_text")
    source = repo.create_source(
        package_id=pkg["id"],
        source_type=source_type,
        display_name=payload.get("display_name", ""),
        source_url=payload.get("source_url"),
    )

    # 提交到 ImportOrchestrator（立即返回 job_id）
    job_public_id = orchestrator.submit_import(
        config=app.config,
        package_id=pkg["id"],
        source_id=source["id"],
        source_type=source_type,
        payload=payload,
        document_kind=payload.get("document_kind", "auto"),
        content_kind=pkg.get("content_kind", "auto"),
    )
    return {"ok": True, "job_id": job_public_id, "source_id": source["public_id"]}


def get_job(app: "DanmuApp", job_public_id: str) -> dict[str, Any]:
    """GET /api/knowledge/jobs/{id} — 任务详情。"""
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"error": "not_initialized"}
    job = repo.get_job(job_public_id)
    if job is None:
        return {"error": "not_found"}
    return job


def cancel_job(app: "DanmuApp", job_public_id: str) -> dict[str, Any]:
    """POST /api/knowledge/jobs/{id}/cancel — 协作式取消。

    设置 ``cancel_flag``，执行器在下一 chunk 边界检查并停止。
    """
    runtime = _get_knowledge_runtime(app)
    if runtime is None:
        return {"error": "not_initialized"}
    orchestrator = getattr(runtime, "import_orchestrator", None)
    if orchestrator is None:
        return {"error": "orchestrator_not_ready"}
    ok = orchestrator.cancel_job(job_public_id)
    if not ok:
        return {"error": "not_found_or_completed"}
    return {"ok": True}


def list_jobs(
    app: "DanmuApp", package_public_id: str | None = None
) -> dict[str, Any]:
    """GET /api/knowledge/jobs — 列出任务（可选按 package 过滤）。"""
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"jobs": [], "error": "not_initialized"}
    package_id = None
    if package_public_id:
        pkg = repo.get_package(package_public_id)
        if pkg is None:
            return {"error": "package_not_found"}
        package_id = pkg["id"]
    jobs = repo.list_jobs(package_id=package_id)
    return {"jobs": jobs, "total": len(jobs)}


def list_items(
    app: "DanmuApp",
    package_public_id: str | None = None,
    kind: str | None = None,
    enabled: bool | None = None,
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """GET /api/knowledge/items — 列出条目（分页+筛选）。"""
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"items": [], "total": 0, "error": "not_initialized"}
    # 解析 package_id（若提供了 package_public_id）
    package_id = None
    if package_public_id:
        pkg = repo.get_package(package_public_id)
        if pkg is None:
            return {"error": "package_not_found"}
        package_id = pkg["id"]
    return repo.list_items(
        package_id=package_id,
        kind=kind,
        enabled=enabled,
        query=query,
        page=page,
        page_size=page_size,
    )


def get_item(app: "DanmuApp", item_public_id: str) -> dict[str, Any]:
    """GET /api/knowledge/items/{id} — 条目详情。"""
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"error": "not_initialized"}
    item = repo.get_item(item_public_id)
    if item is None:
        return {"error": "not_found"}
    return item


def update_item(
    app: "DanmuApp", item_public_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """PATCH /api/knowledge/items/{id} — 更新条目。"""
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"error": "not_initialized"}
    updated = repo.update_item(item_public_id, **payload)
    if updated is None:
        return {"error": "not_found"}
    return updated


def delete_item(app: "DanmuApp", item_public_id: str) -> dict[str, Any]:
    """DELETE /api/knowledge/items/{id} — 删除条目。"""
    repo = _get_or_create_repository(app)
    if repo is None:
        return {"error": "not_initialized"}
    ok = repo.delete_item(item_public_id)
    if not ok:
        return {"error": "not_found"}
    return {"ok": True}


def preview_retrieval(
    app: "DanmuApp", payload: dict[str, Any]
) -> dict[str, Any]:
    """POST /api/knowledge/retrieval/preview — 检索预览（不更新运行时缓存）。

    Returns:
        ``{"items": [...], "prompt_text": "...", "hit_count": N,
           "retrieval_ms": N, "fts_backend": "..."}``。
    """
    runtime = _get_knowledge_runtime(app)
    if runtime is None:
        return {"error": "not_initialized"}
    retriever = getattr(runtime, "retriever", None)
    if retriever is None:
        return {"error": "retriever_not_ready"}
    result = retriever.retrieve(
        scene_brief=payload.get("scene_brief", ""),
        keywords=payload.get("keywords", []),
        max_items=payload.get("max_items") or 4,
        max_chars=payload.get("max_chars") or 360,
    )
    return {
        "items": result.items,
        "prompt_text": result.prompt_text,
        "hit_count": result.hit_count,
        "retrieval_ms": result.retrieval_ms,
        "fts_backend": result.fts_backend,
    }
