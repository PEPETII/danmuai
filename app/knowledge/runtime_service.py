"""知识包运行时服务：DanmuApp 启动期挂载、场景检索、prompt 注入、使用记录。

由 DanmuApp 经 ``self.knowledge_runtime = KnowledgeRuntimeService(self)`` 装配
（在 ``_init_startup_services`` 中），供 ``app/web_api/knowledge.py`` 通过
``getattr(app, "knowledge_runtime", None)`` 访问。

职责：
1. 持有 ``KnowledgeDatabase`` / ``KnowledgeRepository`` /
   ``ImportOrchestrator`` / ``KnowledgeRetriever``；
2. 组装真实场景语义（``build_knowledge_scene_context``），禁止
   ``round=… screenshot=…`` 占位查询；
3. ``build_visual_prompt_injection`` 返回 ``KnowledgeInjectionResult``，
   注入成功时程序侧 ``mark_items_used``（use_count = 注入次数）；
4. ``on_reply_consumed`` 仅作模型 ``knowledge_used`` 诊断辅助，非唯一依据；
5. 异常隔离：失败不抛出，主链路不因知识模块中断。

边界约束（AGENTS.md §9.4 / §9.8）：
- 不在 HTTP 线程读 DanmuApp 私有字段；
- 不引入 QTimer / QThreadPool（检索由主线程调用）；
- 所有写经 ``KnowledgeRepository`` / ``ImportOrchestrator``；
- ``retriever`` 仅主线程访问。
"""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

from app.knowledge.models import (
    KnowledgeContextSnapshot,
    KnowledgeInjectionResult,
    KnowledgeSceneContext,
)

if TYPE_CHECKING:
    from main import DanmuApp

logger = logging.getLogger(__name__)

__all__ = [
    "KnowledgeRuntimeService",
    "build_knowledge_scene_context",
    "KnowledgeSceneContext",
    "KnowledgeInjectionResult",
    "SCENE_CONTEXT_REUSE_MAX_AGE_SEC",
]

# 场景 brief 总长度上限（检索查询，非 prompt 注入预算）
_SCENE_BRIEF_MAX = 200
# 关键词上限
_KEYWORDS_MAX = 16
# 最近弹幕参与组装条数
_RECENT_DANMU_MAX = 8
# 场景上下文过期（秒）；generation 变化时立即失效
_SCENE_CONTEXT_TTL_SEC = 900.0
# 普通视觉链路复用「上一轮已产出的场景语义」时的最长年龄（秒）。
# 比 TTL 更短：仅用于同一场景代际内的连续性，避免陈旧上下文污染检索。
SCENE_CONTEXT_REUSE_MAX_AGE_SEC = 180.0

_STOPWORDS: frozenset[str] = frozenset(
    {
        "的",
        "了",
        "是",
        "在",
        "我",
        "你",
        "他",
        "她",
        "它",
        "和",
        "与",
        "或",
        "这",
        "那",
        "有",
        "不",
        "也",
        "就",
        "都",
        "而",
        "及",
        "等",
        "啊",
        "呢",
        "吧",
        "吗",
        "呀",
        "哦",
        "哈",
        "嘿",
        "a",
        "an",
        "the",
        "is",
        "are",
        "to",
        "of",
        "and",
        "or",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "this",
        "that",
        "it",
        "as",
        "be",
        "was",
        "were",
    }
)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,8}|[A-Za-z0-9][A-Za-z0-9_\-]{1,23}")


def _tokenize_keywords(text: str, *, max_tokens: int = _KEYWORDS_MAX) -> list[str]:
    """从自然语言中抽取短关键词（中文 2–8 字 / 英文词）。"""
    text = (text or "").strip()
    if not text or max_tokens <= 0:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(text):
        token = raw.strip()
        if not token:
            continue
        key = token.lower()
        if key in _STOPWORDS or key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= max_tokens:
            break
    return out


def _clip(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if max_len <= 0 or len(text) <= max_len:
        return text
    return text[:max_len].rstrip()


def build_knowledge_scene_context(
    *,
    live_topic: str = "",
    recent_danmu: list[str] | None = None,
    mic_text: str = "",
    user_nickname: str = "",
    extra_brief: str = "",
    extra_keywords: list[str] | None = None,
    request_round: int = 0,
    screenshot_id: int = 0,
    scene_generation: int = 0,
    now: float | None = None,
) -> KnowledgeSceneContext:
    """组装真实场景检索上下文；无语义时 keywords/brief 均为空。

    不使用 ``round=`` / ``screenshot=`` 等请求编号作为查询文本。
    """
    parts: list[str] = []
    keywords: list[str] = []
    tags: list[str] = []

    topic = _clip(str(live_topic or ""), 80)
    if topic:
        parts.append(topic)
        keywords.extend(_tokenize_keywords(topic, max_tokens=8))
        tags.extend(_tokenize_keywords(topic, max_tokens=6))

    extra = _clip(str(extra_brief or ""), 120)
    if extra:
        parts.append(extra)
        keywords.extend(_tokenize_keywords(extra, max_tokens=8))

    mic = _clip(str(mic_text or ""), 80)
    if mic:
        parts.append(mic)
        keywords.extend(_tokenize_keywords(mic, max_tokens=6))

    for raw in list(extra_keywords or []):
        token = str(raw or "").strip()
        if token:
            keywords.append(token)
            tags.append(token)

    recent = list(recent_danmu or [])[:_RECENT_DANMU_MAX]
    for line in recent:
        line_s = _clip(str(line or ""), 40)
        if not line_s:
            continue
        keywords.extend(_tokenize_keywords(line_s, max_tokens=4))

    nick = _clip(str(user_nickname or ""), 32)
    if nick:
        tags.append(nick)

    # 去重保持顺序
    seen_kw: set[str] = set()
    uniq_kw: list[str] = []
    for k in keywords:
        key = k.lower()
        if key in seen_kw:
            continue
        seen_kw.add(key)
        uniq_kw.append(k)
        if len(uniq_kw) >= _KEYWORDS_MAX:
            break

    seen_tag: set[str] = set()
    uniq_tags: list[str] = []
    for t in tags:
        key = t.lower()
        if not t or key in seen_tag:
            continue
        seen_tag.add(key)
        uniq_tags.append(t)
        if len(uniq_tags) >= 12:
            break

    brief = _clip(" ".join(parts), _SCENE_BRIEF_MAX)
    # 若只有关键词没有 brief，用关键词拼成可检索 brief
    if not brief and uniq_kw:
        brief = _clip(" ".join(uniq_kw[:8]), _SCENE_BRIEF_MAX)

    return KnowledgeSceneContext(
        scene_brief=brief,
        keywords=tuple(uniq_kw),
        scene_tags=tuple(uniq_tags),
        source_request_round=int(request_round or 0),
        source_screenshot_id=int(screenshot_id or 0),
        scene_generation=int(scene_generation or 0),
        updated_at=float(now if now is not None else time.time()),
    )


class KnowledgeRuntimeService:
    """知识包运行时服务（异常隔离、主线程访问检索器）。"""

    def __init__(self, app: "DanmuApp") -> None:
        self._app = app
        self._db: Any = None
        self.repository: Any = None
        self.import_orchestrator: Any = None
        self.retriever: Any = None
        self._last_injection: KnowledgeInjectionResult | None = None
        self._last_scene_context: KnowledgeSceneContext | None = None
        self._cached_scene_generation: int | None = None
        self._last_retrieval_diagnostic = "knowledge_disabled"
        self._closing = False
        # 终止态：只有真正的应用退出（quit / 启动失败回收）才会置位。
        # 置位后 mount() 永久拒绝，避免已关闭的运行时被重新打开。
        self._closed = False
        self._mount_result = self.mount()

    @property
    def is_ready(self) -> bool:
        """Return whether this same runtime instance is fully mounted and usable."""
        return bool(
            getattr(self, "_mount_result", False)
            and not getattr(self, "_closing", False)
            and not getattr(self, "_closed", False)
            and self._db is not None
            and self.repository is not None
            and self.import_orchestrator is not None
            and self.retriever is not None
        )

    @property
    def is_closed(self) -> bool:
        """True once the whole-application teardown finished closing this runtime."""
        return bool(getattr(self, "_closed", False))

    def mount(self) -> bool:
        """挂载或重新挂载知识库运行时。

        ``stop()`` 不会触碰知识库运行时；只有真正的应用退出才会调用
        ``close(wait=True)``。挂载失败时保留同一个运行时对象的降级状态，
        由调用方在后续启动时重试，避免创建第二个运行时或重建数据库。

        ``_closing``（关闭进行中）与 ``_closed``（已终止）都直接返回 ``False``，
        因此不会在关闭中途“假恢复”出一个半可用的运行时。
        """
        if self._closing or self._closed:
            self._mount_result = False
            return False
        if (
            self._db is not None
            and self.repository is not None
            and self.import_orchestrator is not None
            and self.retriever is not None
        ):
            self._mount_result = True
            return True

        # 清理上一次装配失败留下的部分状态。必须同步完成，不能在异步 close
        # 尚未结束时继续打开另一套 DB / executor；这里**不**进入终止态。
        self._discard_partial_state()
        db = None
        orch = None
        try:
            from app.knowledge.database import KnowledgeDatabase
            from app.knowledge.import_service import ImportOrchestrator
            from app.knowledge.repository import KnowledgeRepository
            from app.knowledge.retriever import KnowledgeRetriever

            db = KnowledgeDatabase.open()
            repo = KnowledgeRepository(db)
            orch = ImportOrchestrator(db, repo)
            retriever = KnowledgeRetriever(db)
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
            self._mount_result = True
            self._last_retrieval_diagnostic = "empty_query"
            return True
        except Exception as exc:
            if orch is not None:
                try:
                    orch.close()
                except Exception as close_exc:
                    logger.warning(
                        "knowledge_runtime import_orchestrator cleanup failed: %r",
                        close_exc,
                    )
            if db is not None:
                try:
                    db.close()
                except Exception as close_exc:
                    logger.warning(
                        "knowledge_runtime db cleanup failed: %r", close_exc
                    )
            logger.warning("knowledge_runtime mount failed: %r", exc)
            self._db = None
            self.repository = None
            self.import_orchestrator = None
            self.retriever = None
            self._mount_result = False
            self._last_retrieval_diagnostic = "knowledge_disabled"
            return False

    # ------------------------------------------------------------------
    # 场景上下文
    # ------------------------------------------------------------------

    def invalidate_scene_context(self) -> None:
        """场景版本变化或 stop/start 时清空缓存语义。"""
        self._last_scene_context = None
        self._cached_scene_generation = None

    def note_scene_generation(self, scene_generation: int) -> None:
        """若 scene_generation 变化则清空陈旧场景上下文。"""
        gen = int(scene_generation or 0)
        if (
            self._cached_scene_generation is not None
            and self._cached_scene_generation != gen
        ):
            self._last_scene_context = None
        self._cached_scene_generation = gen

    def remember_scene_context(self, ctx: KnowledgeSceneContext) -> None:
        """缓存最近一次有效场景（诊断 / 可选下一轮复用）。"""
        if ctx is None or not ctx.has_semantic_query:
            return
        self._last_scene_context = ctx
        self._cached_scene_generation = int(ctx.scene_generation or 0)

    def get_last_scene_context(
        self,
        *,
        scene_generation: int | None = None,
        now: float | None = None,
        max_age_sec: float | None = None,
    ) -> KnowledgeSceneContext | None:
        """返回未过期且 generation 匹配的缓存场景；否则 None。

        ``max_age_sec`` 可收紧默认 TTL（普通视觉链路复用上一轮语义时用更短
        窗口，避免陈旧上下文污染检索）。
        """
        ctx = self._last_scene_context
        if ctx is None:
            return None
        if scene_generation is not None and int(ctx.scene_generation or 0) != int(
            scene_generation or 0
        ):
            return None
        limit = (
            _SCENE_CONTEXT_TTL_SEC
            if max_age_sec is None
            else max(0.0, float(max_age_sec))
        )
        ts = float(now if now is not None else time.time())
        if ts - float(ctx.updated_at or 0.0) > limit:
            return None
        return ctx

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
        scene_tags: list[str] | None = None,
    ) -> KnowledgeInjectionResult | None:
        """检索知识并返回结构化注入结果；无语义查询或无命中时返回 None。

        成功注入时：
        - ``set_last_injected``（防重复惩罚）；
        - ``mark_items_used``（use_count = 被注入次数）。

        空 ``scene_brief`` 且空 ``keywords`` 时**不**发起检索，也不使用请求编号
        作为查询文本。
        """
        retriever = self.retriever
        if retriever is None:
            self.set_retrieval_diagnostic("knowledge_disabled")
            return None
        brief = str(scene_brief or "").strip()
        kw_list = [str(k).strip() for k in (keywords or []) if str(k or "").strip()]
        if not brief and not kw_list:
            self.set_retrieval_diagnostic("empty_query")
            return None
        try:
            tag_list = [
                str(t).strip()
                for t in (scene_tags or [])
                if str(t or "").strip()
            ]
            result = retriever.retrieve(
                scene_brief=brief,
                keywords=kw_list,
                scene_tags=tag_list,
                max_items=4,
                max_chars=360,
                request_round=request_round,
                screenshot_id=screenshot_id,
            )
        except Exception as exc:
            self.set_retrieval_diagnostic("retriever_error")
            logger.warning(
                "knowledge retrieval reason=retriever_error failed: %r",
                exc,
            )
            return None
        if result is None:
            self.set_retrieval_diagnostic("no_hit")
            return None
        try:
            prompt_text = getattr(result, "prompt_text", "") or ""
            hit_count = int(getattr(result, "hit_count", 0) or 0)
            retrieval_ms = int(getattr(result, "retrieval_ms", 0) or 0)
            items = list(getattr(result, "items", []) or [])
        except Exception:
            self.set_retrieval_diagnostic("retriever_error")
            return None
        if not prompt_text or hit_count <= 0 or not items:
            self.set_retrieval_diagnostic("no_hit")
            return None

        item_ids: list[int] = []
        public_ids: list[str] = []
        contents: list[str] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            raw_id = it.get("id")
            if raw_id is not None:
                try:
                    item_ids.append(int(raw_id))
                except (TypeError, ValueError):
                    pass
            pid = it.get("public_id")
            if isinstance(pid, str) and pid:
                public_ids.append(pid)
            content = it.get("content")
            if content:
                contents.append(str(content))

        try:
            retriever.set_last_injected(contents)
        except Exception as exc:
            logger.debug("knowledge set_last_injected failed (non-fatal): %r", exc)

        # 方案 A：注入即更新使用记录（use_count = 注入次数）
        if item_ids:
            try:
                retriever.mark_items_used(item_ids)
            except Exception as exc:
                logger.warning(
                    "knowledge mark_items_used on inject failed: %r", exc
                )

        injection = KnowledgeInjectionResult(
            prompt_text=prompt_text,
            item_ids=tuple(item_ids),
            public_ids=tuple(public_ids),
            request_round=int(request_round or 0),
            screenshot_id=int(screenshot_id or 0),
            hit_count=hit_count,
            retrieval_ms=retrieval_ms,
            scene_brief=brief,
            keywords=tuple(kw_list),
        )
        self._last_injection = injection
        try:
            previous_ctx = self._last_scene_context
            same_semantics = (
                previous_ctx is not None
                and previous_ctx.scene_brief == brief
                and tuple(previous_ctx.keywords) == tuple(kw_list)
            )
            self.remember_scene_context(
                KnowledgeSceneContext(
                    scene_brief=brief,
                    keywords=tuple(kw_list),
                    scene_tags=tuple(
                        str(t).strip()
                        for t in (scene_tags or [])
                        if str(t or "").strip()
                    ),
                    source_request_round=int(request_round or 0),
                    source_screenshot_id=int(screenshot_id or 0),
                    scene_generation=int(self._cached_scene_generation or 0),
                    # 复用同一批语义时保留最初时间戳：让复用窗口（见
                    # SCENE_CONTEXT_REUSE_MAX_AGE_SEC）成为硬上限，
                    # 而不是每次复用都把窗口往后推导致陈旧污染。
                    updated_at=(
                        float(previous_ctx.updated_at or 0.0)
                        if same_semantics
                        else time.time()
                    ),
                )
            )
        except Exception:
            pass
        self.set_retrieval_diagnostic("injected")
        return injection

    def set_retrieval_diagnostic(self, reason: str) -> None:
        """Record the latest non-sensitive retrieval outcome for diagnostics."""
        allowed = {
            "knowledge_disabled",
            "empty_query",
            "no_hit",
            "retriever_error",
            "injected",
        }
        self._last_retrieval_diagnostic = (
            reason if reason in allowed else "retriever_error"
        )

    def get_retrieval_diagnostic(self) -> str:
        """Return the latest structured retrieval outcome."""
        return str(
            getattr(self, "_last_retrieval_diagnostic", "knowledge_disabled")
            or "knowledge_disabled"
        )

    def get_last_injection(self) -> KnowledgeInjectionResult | None:
        return self._last_injection

    def get_last_snapshot(self) -> KnowledgeContextSnapshot | None:
        """兼容诊断：由最近注入构造 ``KnowledgeContextSnapshot``。"""
        inj = self._last_injection
        if inj is None:
            return None
        return KnowledgeContextSnapshot(
            prompt_text=inj.prompt_text,
            scene_brief=inj.scene_brief,
            keywords=inj.keywords,
            item_ids=inj.item_ids,
            source_request_round=inj.request_round,
            source_screenshot_id=inj.screenshot_id,
            updated_at=time.time(),
        )

    # ------------------------------------------------------------------
    # 回复消费（诊断辅助）
    # ------------------------------------------------------------------

    def on_reply_consumed(
        self, knowledge_used_item_ids: list[str]
    ) -> None:
        """模型声明的 knowledge_used 仅作诊断；不替代注入时的 use_count 更新。

        仍会 mark 一次（若模型返回了有效 ID），便于对照「注入 vs 声明」。
        任何异常 no-op。
        """
        if not knowledge_used_item_ids:
            return
        retriever = self.retriever
        repo = self.repository
        if retriever is None or repo is None:
            return
        try:
            internal_ids = repo.get_item_ids_by_public_ids(knowledge_used_item_ids)
            if not internal_ids:
                return
            retriever.mark_items_used(internal_ids)
        except Exception as exc:
            logger.warning("knowledge on_reply_consumed failed: %r", exc)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def close(self, *, wait: bool = False) -> None:
        """Close the runtime; optionally wait for import cancellation to drain.

        This is only reached by the whole-application teardown (``quit()`` /
        startup-failure release). The danmu business toggle (``stop()``) must
        never call it. ``wait=False`` keeps the historical non-blocking
        teardown for callers that are already leaving a background context;
        ``wait=True`` cancels and drains imports before closing the database
        so no importer thread or DB connection survives the process.
        """
        if self._closing:
            if wait:
                orch = self.import_orchestrator
                if orch is not None:
                    try:
                        orch.close()
                    except Exception as exc:
                        logger.warning(
                            "knowledge_runtime import_orchestrator close failed: %r",
                            exc,
                        )
                self._finish_close_after_imports()
            return
        self._closing = True
        self._mount_result = False
        orch = self.import_orchestrator
        if orch is not None:
            try:
                if wait:
                    orch.begin_shutdown()
                    orch.close()
                    self._finish_close_after_imports()
                else:
                    orch.begin_shutdown(self._finish_close_after_imports)
            except Exception as exc:
                logger.warning(
                    "knowledge_runtime import_orchestrator stop failed: %r",
                    exc,
                )
                try:
                    orch.close()
                except Exception as close_exc:
                    logger.warning(
                        "knowledge_runtime import_orchestrator close failed: %r",
                        close_exc,
                    )
                self._finish_close_after_imports()
            return
        self._finish_close_after_imports()

    def _discard_partial_state(self) -> None:
        """Synchronously release importer + DB handles without entering terminal state.

        Used by ``mount()`` to clean up a previous partial/failed assembly.
        Callers that are tearing the runtime down for good must go through
        ``close()``, which additionally latches ``_closed``.
        """
        orch = self.import_orchestrator
        if orch is not None:
            try:
                orch.close()
            except Exception as exc:
                logger.warning(
                    "knowledge_runtime import_orchestrator cleanup failed: %r", exc
                )
        db = self._db
        if db is not None:
            try:
                db.close()
            except Exception as exc:
                logger.warning("knowledge_runtime db cleanup failed: %r", exc)
        self._db = None
        self.repository = None
        self.import_orchestrator = None
        self.retriever = None

    def _finish_close_after_imports(self) -> None:
        """收尾：仅在 import worker 排空后由 close 路径执行。

        完成后再置 ``_closed=True``（终止态），此后 ``mount()`` 永久返回
        ``False``，不会因为 ``_closing`` 归位而被意外重新打开。
        """
        if not self._closing:
            return
        self._discard_partial_state()
        self._last_injection = None
        self._last_scene_context = None
        self._cached_scene_generation = None
        self._last_retrieval_diagnostic = "knowledge_disabled"
        self._closing = False
        self._closed = True

