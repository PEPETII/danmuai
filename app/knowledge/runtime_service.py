"""知识包运行时服务：DanmuApp 启动期挂载、prompt 注入、回复消费闭环。

由 DanmuApp 经 ``self.knowledge_runtime = KnowledgeRuntimeService(self)`` 装配
（在 ``_init_startup_services`` 中），供 ``app/web_api/knowledge.py`` 通过
``getattr(app, "knowledge_runtime", None)`` 访问。

职责：
1. 持有 ``KnowledgeDatabase`` / ``KnowledgeRepository`` /
   ``ImportOrchestrator`` / ``KnowledgeRetriever``；
2. 提供 ``build_visual_prompt_injection(scene_brief, keywords, request_round,
   screenshot_id) -> str | None``，供 ``main.py:_build_visual_prompts`` 注入到
   ``system_pt`` 末尾；
3. 提供 ``on_reply_consumed(knowledge_used_item_ids)``，供
   ``generation_pipeline.handle_reply_parsed`` 调用以
   ``retriever.mark_items_used(item_ids)`` 更新最近使用窗口；
4. 异常隔离：任何方法失败不抛出，记录日志后返回空/None（保证主链路不被
   知识模块故障打断）。

边界约束（AGENTS.md §9.4 / §9.8）：
- 不在 HTTP 线程读 DanmuApp 私有字段；
- 不引入 QTimer / QThreadPool（检索器仅由主线程 Qt 定时器回调调用）；
- 所有写经 ``KnowledgeRepository`` / ``ImportOrchestrator``（已线程安全）；
- ``retriever`` 仅主线程访问（``_build_visual_prompts`` 调用方为主线程）。

Phase B / Wave 7（B2）。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from main import DanmuApp

logger = logging.getLogger(__name__)

__all__ = ["KnowledgeRuntimeService"]


class KnowledgeRuntimeService:
    """知识包运行时服务（异常隔离、主线程访问检索器）。

    用法：
        svc = KnowledgeRuntimeService(app)
        injection = svc.build_visual_prompt_injection(
            scene_brief="...", keywords=["..."],
            request_round=1, screenshot_id=1,
        )
        if injection:
            system_pt = system_pt + "\\n\\n" + injection
        # ...
        svc.on_reply_consumed(["item_public_id_1", "item_public_id_2"])
        svc.close()
    """

    def __init__(self, app: "DanmuApp") -> None:
        self._app = app
        self._db: Any = None
        self.repository: Any = None
        self.import_orchestrator: Any = None
        self.retriever: Any = None
        try:
            from app.knowledge.database import KnowledgeDatabase
            from app.knowledge.import_service import ImportOrchestrator
            from app.knowledge.repository import KnowledgeRepository
            from app.knowledge.retriever import KnowledgeRetriever

            db = KnowledgeDatabase.open()
            repo = KnowledgeRepository(db)
            orch = ImportOrchestrator(db, repo)
            retriever = KnowledgeRetriever(db)
            # 启动期恢复：把上次未完成的 import job 标记为 interrupted
            # （spec §5.2），避免永远显示处理中。
            try:
                repo.mark_job_interrupted_at_startup()
            except Exception as exc:  # boundary: 启动恢复不得中断装配
                logger.warning(
                    "knowledge_runtime mark_job_interrupted_at_startup failed: %r",
                    exc,
                )
            self._db = db
            self.repository = repo
            self.import_orchestrator = orch
            self.retriever = retriever
        except Exception as exc:
            # 降级模式：所有属性置 None，主链路调用全部 no-op。
            logger.warning("knowledge_runtime mount failed: %r", exc)
            self._db = None
            self.repository = None
            self.import_orchestrator = None
            self.retriever = None

    # ------------------------------------------------------------------
    # prompt 注入
    # ------------------------------------------------------------------

    def build_visual_prompt_injection(
        self,
        scene_brief: str,
        keywords: list[str],
        *,
        request_round: int,
        screenshot_id: int,
    ) -> str | None:
        """检索知识并返回可附加到 ``system_pt`` 末尾的提示词片段。

        Args:
            scene_brief: 场景简述（B 阶段先用 request_round/screenshot_id 组装）。
            keywords: 检索关键词列表（B 阶段可留空，仅靠 FTS scene_brief 检索）。
            request_round: 触发该次检索的 request_round（诊断用）。
            screenshot_id: 触发该次检索的 screenshot_id（诊断用）。

        Returns:
            非空提示词字符串（命中条目时）；None 表示无命中或降级模式。
            任何异常均返回 None，不抛出。
        """
        retriever = self.retriever
        if retriever is None:
            return None
        try:
            result = retriever.retrieve(
                scene_brief=scene_brief,
                keywords=keywords,
                max_items=4,
                max_chars=360,
                request_round=request_round,
                screenshot_id=screenshot_id,
            )
        except Exception as exc:
            logger.warning(
                "knowledge build_visual_prompt_injection retrieve failed: %r",
                exc,
            )
            return None
        if result is None:
            return None
        try:
            prompt_text = getattr(result, "prompt_text", "") or ""
            hit_count = int(getattr(result, "hit_count", 0) or 0)
        except Exception:
            return None
        if not prompt_text or hit_count <= 0:
            return None
        try:
            items = getattr(result, "items", []) or []
            contents = [
                str(it.get("content", "")) for it in items if isinstance(it, dict)
            ]
            retriever.set_last_injected(contents)
        except Exception as exc:  # boundary: dedup 跟踪失败不影响注入
            logger.debug(
                "knowledge set_last_injected failed (non-fatal): %r", exc
            )
        return prompt_text

    # ------------------------------------------------------------------
    # 回复消费闭环
    # ------------------------------------------------------------------

    def on_reply_consumed(
        self, knowledge_used_item_ids: list[str]
    ) -> None:
        """AI 回复消费后，按 AI 声明的 knowledge_used 更新条目最近使用窗口。

        Args:
            knowledge_used_item_ids: AI 在 envelope 中声明的 item public_id 列表。

        Note:
            ``retriever.mark_items_used`` 接收**内部 id**（int），这里通过
            ``repository.get_item(public_id)`` 把 public_id 翻译为内部 id。
            任何异常均 no-op，不抛出。
        """
        if not knowledge_used_item_ids:
            return
        retriever = self.retriever
        repo = self.repository
        if retriever is None or repo is None:
            return
        try:
            internal_ids: list[int] = []
            for public_id in knowledge_used_item_ids:
                if not isinstance(public_id, str) or not public_id:
                    continue
                item = repo.get_item(public_id)
                if item is None:
                    continue
                item_id = item.get("id")
                if item_id is None:
                    continue
                try:
                    internal_ids.append(int(item_id))
                except (TypeError, ValueError):
                    continue
            if not internal_ids:
                return
            retriever.mark_items_used(internal_ids)
        except Exception as exc:
            logger.warning(
                "knowledge on_reply_consumed failed: %r", exc
            )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭执行器与数据库连接（停止时调用）。异常隔离，不抛出。"""
        orch = self.import_orchestrator
        if orch is not None:
            try:
                orch.close()
            except Exception as exc:
                logger.warning(
                    "knowledge_runtime import_orchestrator close failed: %r",
                    exc,
                )
        db = self._db
        if db is not None:
            try:
                db.close()
            except Exception as exc:
                logger.warning(
                    "knowledge_runtime db close failed: %r", exc
                )
        self._db = None
        self.repository = None
        self.import_orchestrator = None
        self.retriever = None
