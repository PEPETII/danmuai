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
- 不引入 Qt timer/thread；独立 `knowledge-retrieval` executor 负责检索与计数写入；
- 所有写经 ``KnowledgeRepository`` / ``ImportOrchestrator``；
- Qt 主线程只读取完成的内存结果，不直接访问 ``retriever`` 或 SQLite。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
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
# One retrieval owner; reserve admission for HTTP previews and usage writes.
_RETRIEVAL_QUERY_LIMIT = 8
_VISUAL_QUERY_LIMIT = 6
_RETRIEVAL_CACHE_LIMIT = 64
_USAGE_PENDING_LIMIT = 64

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
    """知识包运行时服务（主线程只做内存组装，检索由专用 worker 负责）。"""

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
        self._lifecycle_state = "accepting"
        self._shutdown_deadline_at: float | None = None
        self._close_finalized = False
        self._lifecycle_lock = threading.RLock()
        self._retrieval_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="knowledge-retrieval",
        )
        self._retrieval_futures: set[Future] = set()
        self._retrieval_lock = threading.RLock()
        self._retrieval_accepting = True
        self._retrieval_executor_closed = False
        self._retrieval_drain_callback = None
        self._retrieval_pending_keys: set[tuple[Any, ...]] = set()
        self._retrieval_cache: dict[tuple[Any, ...], tuple[Any, float]] = {}
        self._retrieval_scene_generation = 0
        self._retrieval_deadline_sec = 0.25
        self._usage_pending: deque[tuple[Any, ...]] = deque()
        self._usage_drain_future: Future | None = None
        self._retrieval_rejected_count = 0
        self._retrieval_merged_count = 0
        self._usage_rejected_count = 0
        self._usage_expired_count = 0
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

    @property
    def lifecycle_state(self) -> str:
        with self._lifecycle_lock:
            return self._lifecycle_state

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
            with self._retrieval_lock:
                self._retrieval_scene_generation = gen
                self._retrieval_cache.clear()
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

    def _retrieval_key(
        self,
        scene_brief: str,
        keywords: list[str],
        scene_tags: list[str],
        scene_generation: int,
        *,
        purpose: str = "visual",
    ) -> tuple[Any, ...]:
        return (
            purpose,
            int(scene_generation or 0),
            str(scene_brief or "").strip(),
            tuple(str(value).strip() for value in keywords if str(value).strip()),
            tuple(str(value).strip() for value in scene_tags if str(value).strip()),
        )

    def _retrieval_future_done(self, future: Future) -> None:
        callback = None
        with self._retrieval_lock:
            self._retrieval_futures.discard(future)
            if not self._retrieval_futures:
                callback = self._retrieval_drain_callback
                self._retrieval_drain_callback = None
        if callable(callback):
            try:
                callback()
            except Exception:
                logger.exception("knowledge retrieval drain callback failed")

    def _submit_retrieval_job(self, fn, /, *args, **kwargs) -> Future | None:
        with self._retrieval_lock:
            if not self._retrieval_accepting or self._retrieval_executor_closed:
                return None
            try:
                future = self._retrieval_executor.submit(fn, *args, **kwargs)
            except RuntimeError:
                return None
            self._retrieval_futures.add(future)
            future.add_done_callback(self._retrieval_future_done)
            return future

    def is_retrieval_drained(self) -> bool:
        with self._retrieval_lock:
            return not self._retrieval_futures

    def _ensure_retrieval_state(self) -> None:
        """为未经过 ``__init__`` 的测试/兼容对象补齐检索生命周期状态。"""
        if not hasattr(self, "_retrieval_lock"):
            self._retrieval_lock = threading.RLock()
        if not hasattr(self, "_retrieval_executor"):
            self._retrieval_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="knowledge-retrieval",
            )
        if not hasattr(self, "_retrieval_futures"):
            self._retrieval_futures = set()
        if not hasattr(self, "_retrieval_accepting"):
            self._retrieval_accepting = True
        if not hasattr(self, "_retrieval_executor_closed"):
            self._retrieval_executor_closed = False
        if not hasattr(self, "_retrieval_drain_callback"):
            self._retrieval_drain_callback = None
        if not hasattr(self, "_retrieval_pending_keys"):
            self._retrieval_pending_keys = set()
        if not hasattr(self, "_retrieval_cache"):
            self._retrieval_cache = {}
        if not hasattr(self, "_usage_pending"):
            self._usage_pending = deque()
            self._usage_drain_future = None
            self._retrieval_rejected_count = 0
            self._retrieval_merged_count = 0
            self._usage_rejected_count = 0
            self._usage_expired_count = 0
        if not hasattr(self, "_retrieval_scene_generation"):
            self._retrieval_scene_generation = 0
        if not hasattr(self, "_retrieval_deadline_sec"):
            self._retrieval_deadline_sec = 0.25

    def _prune_retrieval_cache_locked(self, now: float) -> None:
        for key, (_, created_at) in list(self._retrieval_cache.items()):
            if (
                key[1] != self._retrieval_scene_generation
                or now - created_at > SCENE_CONTEXT_REUSE_MAX_AGE_SEC
            ):
                self._retrieval_cache.pop(key, None)
        while len(self._retrieval_cache) > _RETRIEVAL_CACHE_LIMIT:
            self._retrieval_cache.pop(next(iter(self._retrieval_cache)))

    def get_retrieval_pressure(self) -> dict[str, int]:
        """Return bounded owner counts without semantic text or item identities."""
        self._ensure_retrieval_state()
        with self._retrieval_lock:
            return {
                "query_pending": len(self._retrieval_pending_keys),
                "visual_pending": sum(key[0] == "visual" for key in self._retrieval_pending_keys),
                "usage_pending": len(self._usage_pending),
                "usage_future": int(self._usage_drain_future is not None),
                "cache_entries": len(self._retrieval_cache),
                "query_rejected": self._retrieval_rejected_count,
                "query_merged": self._retrieval_merged_count,
                "usage_rejected": self._usage_rejected_count,
                "usage_expired": self._usage_expired_count,
            }

    def _retrieval_query_done(self, future: Future, key: tuple[Any, ...]) -> None:
        with self._retrieval_lock:
            self._retrieval_pending_keys.discard(key)

    def _retrieval_query_worker(
        self,
        *,
        key: tuple[Any, ...],
        scene_brief: str,
        keywords: list[str],
        scene_tags: list[str],
        request_round: int,
        screenshot_id: int,
        scene_generation: int,
        deadline_at: float,
        cache_result: bool = True,
        queued_at: float = 0.0,
    ):
        try:
            now = time.monotonic()
            logger.debug(
                "knowledge retrieval start purpose=%s queue_wait_ms=%.3f",
                key[0], max(0.0, now - queued_at) * 1000,
            )
            with self._retrieval_lock:
                if (
                    not self._retrieval_accepting
                    or now > deadline_at
                    or (cache_result and self._retrieval_scene_generation != int(scene_generation))
                ):
                    return None
            retriever = self.retriever
            if retriever is None:
                return None
            result = retriever.retrieve(
                scene_brief=scene_brief,
                keywords=keywords,
                scene_tags=scene_tags,
                max_items=4,
                max_chars=360,
                request_round=request_round,
                screenshot_id=screenshot_id,
            )
            # Retrieval implementations cannot be force-killed. The deadline
            # therefore gates publication and all later writes, not the Python
            # call itself.
            if time.monotonic() > deadline_at:
                return None
            with self._retrieval_lock:
                current_generation = self._retrieval_scene_generation
                accepting = self._retrieval_accepting
                if cache_result and accepting and current_generation == int(scene_generation):
                    self._retrieval_cache.pop(key, None)
                    self._retrieval_cache[key] = (result, time.monotonic())
                    self._prune_retrieval_cache_locked(time.monotonic())
            return result
        except Exception as exc:
            logger.warning("knowledge retrieval worker failed type=%s", type(exc).__name__)
            return None

    def _queue_retrieval(
        self,
        *,
        key: tuple[Any, ...],
        scene_brief: str,
        keywords: list[str],
        scene_tags: list[str],
        request_round: int,
        screenshot_id: int,
        scene_generation: int,
        deadline_sec: float,
        cache_result: bool = True,
    ) -> Future | None:
        self._ensure_retrieval_state()
        with self._retrieval_lock:
            self._prune_retrieval_cache_locked(time.monotonic())
            if not self._retrieval_accepting or self._retrieval_executor_closed:
                self.set_retrieval_diagnostic("knowledge_disabled")
                return None
            if key in self._retrieval_pending_keys:
                self._retrieval_merged_count += 1
                self.set_retrieval_diagnostic("retrieval_pending")
                return None
            visual_pending = sum(k[0] == "visual" for k in self._retrieval_pending_keys)
            if (
                len(self._retrieval_pending_keys) >= _RETRIEVAL_QUERY_LIMIT
                or (key[0] == "visual" and visual_pending >= _VISUAL_QUERY_LIMIT)
            ):
                self._retrieval_rejected_count += 1
                self.set_retrieval_diagnostic("retrieval_busy")
                return None
            self._retrieval_pending_keys.add(key)
            queued_at = time.monotonic()
            future = self._submit_retrieval_job(
                self._retrieval_query_worker,
                key=key,
                scene_brief=scene_brief,
                keywords=keywords,
                scene_tags=scene_tags,
                request_round=request_round,
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                deadline_at=queued_at + max(0.01, float(deadline_sec)),
                cache_result=cache_result,
                queued_at=queued_at,
            )
            if future is None:
                self._retrieval_pending_keys.discard(key)
            else:
                future.add_done_callback(lambda done: self._retrieval_query_done(done, key))
        return future

    @staticmethod
    def _injection_from_result(
        result: Any,
        *,
        scene_brief: str,
        keywords: list[str],
        request_round: int,
        screenshot_id: int,
    ) -> KnowledgeInjectionResult | None:
        if result is None:
            return None
        prompt_text = str(getattr(result, "prompt_text", "") or "")
        items = list(getattr(result, "items", []) or [])
        hit_count = int(getattr(result, "hit_count", 0) or 0)
        retrieval_ms = int(getattr(result, "retrieval_ms", 0) or 0)
        if not prompt_text or hit_count <= 0 or not items:
            return None
        item_ids: list[int] = []
        public_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                if item.get("id") is not None:
                    item_ids.append(int(item["id"]))
            except (TypeError, ValueError):
                pass
            public_id = item.get("public_id")
            if isinstance(public_id, str) and public_id:
                public_ids.append(public_id)
        return KnowledgeInjectionResult(
            prompt_text=prompt_text,
            item_ids=tuple(item_ids),
            public_ids=tuple(public_ids),
            request_round=int(request_round or 0),
            screenshot_id=int(screenshot_id or 0),
            hit_count=hit_count,
            retrieval_ms=retrieval_ms,
            scene_brief=scene_brief,
            keywords=tuple(keywords),
        )

    def _queue_injection_usage(
        self,
        injection: KnowledgeInjectionResult,
        *,
        contents: list[str],
        scene_generation: int,
        deadline_sec: float,
    ) -> bool:
        deadline_at = time.monotonic() + max(0.01, float(deadline_sec))
        return self._queue_usage_event(
            ("injection", injection.item_ids, tuple(contents), int(scene_generation), deadline_at)
        )

    def _prune_usage_pending_locked(self, now: float) -> None:
        kept = deque()
        for event in self._usage_pending:
            generation, deadline_at = event[3], event[4]
            if now > deadline_at or (
                generation is not None and generation != self._retrieval_scene_generation
            ):
                self._usage_expired_count += 1
            else:
                kept.append(event)
        self._usage_pending = kept

    def _queue_usage_event(self, event: tuple[Any, ...]) -> bool:
        """Batch events under one Future; retain each deadline and use increment."""
        self._ensure_retrieval_state()
        with self._retrieval_lock:
            if not self._retrieval_accepting or self._retrieval_executor_closed:
                return False
            self._prune_usage_pending_locked(time.monotonic())
            if len(self._usage_pending) >= _USAGE_PENDING_LIMIT:
                self._usage_rejected_count += 1
                self.set_retrieval_diagnostic("count_write_failed")
                return False
            self._usage_pending.append(event)
            if self._usage_drain_future is None:
                self._schedule_usage_drain_locked()
            return self._usage_drain_future is not None

    def _schedule_usage_drain_locked(self) -> None:
        future = self._submit_retrieval_job(self._drain_usage_writes)
        self._usage_drain_future = future
        if future is not None:
            future.add_done_callback(self._usage_drain_done)
        else:
            self._usage_pending.clear()
            self.set_retrieval_diagnostic("count_write_failed")

    def _usage_drain_done(self, future: Future) -> None:
        with self._retrieval_lock:
            if self._usage_drain_future is future:
                self._usage_drain_future = None
            if self._usage_pending and self._retrieval_accepting:
                self._schedule_usage_drain_locked()

    def _drain_usage_writes(self) -> None:
        # Yield to already queued queries even if producers keep replenishing usage.
        # The completion callback schedules the next bounded batch at the tail.
        for _ in range(_USAGE_PENDING_LIMIT):
            with self._retrieval_lock:
                if not self._retrieval_accepting:
                    self._usage_pending.clear()
                    return
                self._prune_usage_pending_locked(time.monotonic())
                if not self._usage_pending:
                    return
                kind, ids, contents, generation, deadline_at = self._usage_pending.popleft()
            retriever = self.retriever
            if retriever is None:
                continue
            try:
                if kind == "injection":
                    with self._retrieval_lock:
                        if generation != self._retrieval_scene_generation:
                            continue
                    retriever.set_last_injected(list(contents))
                    internal_ids = list(ids)
                else:
                    repo = self.repository
                    if repo is None:
                        continue
                    internal_ids = repo.get_item_ids_by_public_ids(list(ids))
                if internal_ids and time.monotonic() <= deadline_at:
                    retriever.mark_items_used(internal_ids)
            except Exception as exc:
                self.set_retrieval_diagnostic("count_write_failed")
                logger.warning("knowledge usage write failed type=%s", type(exc).__name__)

    def prepare_visual_prompt_injection(
        self,
        scene_brief: str,
        keywords: list[str],
        *,
        request_round: int,
        screenshot_id: int,
        scene_tags: list[str] | None = None,
        scene_generation: int | None = None,
        deadline_sec: float | None = None,
    ) -> KnowledgeInjectionResult | None:
        """Return only a completed cache hit; queue retrieval without blocking Qt."""
        brief = str(scene_brief or "").strip()
        kw_list = [str(value).strip() for value in (keywords or []) if str(value or "").strip()]
        tag_list = [str(value).strip() for value in (scene_tags or []) if str(value or "").strip()]
        if not brief and not kw_list:
            self.set_retrieval_diagnostic("empty_query")
            return None
        generation = int(
            self._cached_scene_generation if scene_generation is None else scene_generation
        )
        with self._retrieval_lock:
            self._retrieval_scene_generation = generation
        key = self._retrieval_key(brief, kw_list, tag_list, generation)
        now = time.monotonic()
        result = None
        cache_available = False
        with self._retrieval_lock:
            self._prune_retrieval_cache_locked(now)
            entry = self._retrieval_cache.get(key)
            if entry is not None and now - entry[1] <= SCENE_CONTEXT_REUSE_MAX_AGE_SEC:
                cache_available = True
                result = entry[0]
            elif entry is not None:
                self._retrieval_cache.pop(key, None)
        if not cache_available:
            future = self._queue_retrieval(
                key=key,
                scene_brief=brief,
                keywords=kw_list,
                scene_tags=tag_list,
                request_round=request_round,
                screenshot_id=screenshot_id,
                scene_generation=generation,
                deadline_sec=deadline_sec or self._retrieval_deadline_sec,
            )
            if future is not None:
                self.set_retrieval_diagnostic("retrieval_pending")
            return None
        if result is None:
            self.set_retrieval_diagnostic("no_hit")
            return None
        injection = self._injection_from_result(
            result,
            scene_brief=brief,
            keywords=kw_list,
            request_round=request_round,
            screenshot_id=screenshot_id,
        )
        if injection is None:
            self.set_retrieval_diagnostic("no_hit")
            return None
        contents = [
            str(item.get("content"))
            for item in (getattr(result, "items", []) or [])
            if isinstance(item, dict) and item.get("content")
        ]
        self._last_injection = injection
        usage_accepted = self._queue_injection_usage(
            injection,
            contents=contents,
            scene_generation=generation,
            deadline_sec=deadline_sec or self._retrieval_deadline_sec,
        )
        if usage_accepted:
            self.set_retrieval_diagnostic("injected")
        return injection

    def preview_retrieval(
        self,
        payload: dict[str, Any],
        *,
        deadline_sec: float | None = None,
    ) -> dict[str, Any]:
        """Run preview retrieval on the retrieval owner, never through Qt."""
        brief = str(payload.get("scene_brief") or "").strip()
        keywords = [
            str(value).strip()
            for value in (payload.get("keywords") or [])
            if str(value or "").strip()
        ]
        if not brief and not keywords:
            return {"error": "missing_query"}
        deadline = max(0.01, float(deadline_sec or self._retrieval_deadline_sec))
        generation = int(self._cached_scene_generation or 0)
        key = self._retrieval_key(brief, keywords, [], generation, purpose="preview")
        future = self._queue_retrieval(
            key=key,
            scene_brief=brief,
            keywords=keywords,
            scene_tags=[],
            request_round=0,
            screenshot_id=0,
            scene_generation=generation,
            deadline_sec=deadline,
            cache_result=False,
        )
        if future is None:
            return {"error": "retrieval_pending"}
        try:
            result = future.result(timeout=deadline)
        except TimeoutError:
            return {"error": "retrieval_timeout"}
        if result is None:
            return {"items": [], "prompt_text": "", "hit_count": 0, "retrieval_ms": 0, "fts_backend": ""}
        return {
            "items": list(getattr(result, "items", []) or []),
            "prompt_text": str(getattr(result, "prompt_text", "") or ""),
            "hit_count": int(getattr(result, "hit_count", 0) or 0),
            "retrieval_ms": int(getattr(result, "retrieval_ms", 0) or 0),
            "fts_backend": str(getattr(result, "fts_backend", "") or ""),
        }

    def submit_usage_write(self, public_ids: list[str], *, deadline_sec: float | None = None) -> None:
        """Queue reply-consumption count writes; the caller never touches SQLite."""
        # 保留原有 repository 输入契约；无效值由 repository 的批量解析统一跳过。
        ids = list(public_ids or [])
        if not ids:
            return
        deadline_at = time.monotonic() + max(0.01, float(deadline_sec or self._retrieval_deadline_sec))

        self._queue_usage_event(("reply", tuple(ids), (), None, deadline_at))

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
            "retrieval_pending",
            "retrieval_busy",
            "retrieval_timeout",
            "scene_generation_lagged",
            "count_write_failed",
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
        self.submit_usage_write(knowledge_used_item_ids)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def close(self, *, wait: bool = False) -> None:
        """Close the runtime; optionally wait for import cancellation to drain.

        This is only reached by whole-application teardown. ``wait`` is kept
        for compatibility but does not make the caller block: shutdown always
        starts cooperative cancellation and observes drain asynchronously.
        The database closes only after both route and import owners report no
        remaining Future.
        """
        self.begin_shutdown(observe_async=True)
        self.poll_shutdown()

    def begin_shutdown(
        self,
        *,
        deadline_at: float | None = None,
        observe_async: bool = False,
    ) -> str:
        """Transition accepting -> draining without waiting on Qt's caller."""
        if not hasattr(self, "_lifecycle_lock"):
            self._lifecycle_lock = threading.RLock()
            self._lifecycle_state = "accepting"
            self._shutdown_deadline_at = None
            self._close_finalized = False
        self._ensure_retrieval_state()
        with self._lifecycle_lock:
            if self._lifecycle_state in {"closed", "timeout"}:
                return self._lifecycle_state
            if self._lifecycle_state == "draining":
                if deadline_at is not None and self._shutdown_deadline_at is None:
                    self._shutdown_deadline_at = deadline_at
                return self._lifecycle_state
            self._lifecycle_state = "draining"
            self._closing = True
            self._mount_result = False
            self._shutdown_deadline_at = deadline_at
            self._close_finalized = False

        observation_ready = False

        def observe() -> None:
            if observe_async and observation_ready:
                self.poll_shutdown()

        try:
            from app.web_api.knowledge_routes import (
                begin_shutdown_knowledge_route_executor,
            )

            begin_shutdown_knowledge_route_executor(observe if observe_async else None)
        except Exception as exc:
            logger.warning("knowledge route executor shutdown start failed: %r", exc)

        orch = self.import_orchestrator
        if orch is not None:
            try:
                orch.begin_shutdown(observe if observe_async else None)
            except Exception as exc:
                logger.warning("knowledge import shutdown start failed: %r", exc)
        self._begin_retrieval_shutdown(observe if observe_async else None)
        observation_ready = True
        if observe_async:
            self.poll_shutdown()
        return "draining"

    def _begin_retrieval_shutdown(self, on_drained=None) -> None:
        with self._retrieval_lock:
            self._retrieval_accepting = False
            self._usage_pending.clear()
            self._retrieval_cache.clear()
            if callable(on_drained):
                self._retrieval_drain_callback = on_drained
            if self._retrieval_executor_closed:
                return
            self._retrieval_executor.shutdown(wait=False, cancel_futures=True)

    def _close_retrieval_executor_if_drained(self) -> bool:
        with self._retrieval_lock:
            if self._retrieval_executor_closed:
                return True
            if self._retrieval_futures:
                return False
            self._retrieval_executor_closed = True
        return True

    def _all_workers_drained(self) -> bool:
        orch = self.import_orchestrator
        imports_drained = orch is None or bool(orch.is_drained())
        try:
            from app.web_api.knowledge_routes import knowledge_route_executor_is_drained

            routes_drained = knowledge_route_executor_is_drained()
        except Exception as exc:
            logger.warning("knowledge route drain observation failed: %r", exc)
            routes_drained = False
        return imports_drained and routes_drained and self.is_retrieval_drained()

    def poll_shutdown(self, *, now: float | None = None) -> str:
        """Observe drain from Qt/event-loop code and finalize only after drain."""
        with self._lifecycle_lock:
            state = self._lifecycle_state
            deadline_at = self._shutdown_deadline_at
        if state == "closed":
            return state
        if state not in {"draining", "timeout"}:
            return state
        if self._all_workers_drained():
            self._finish_close_after_imports()
            with self._lifecycle_lock:
                return self._lifecycle_state
        if state == "draining" and deadline_at is not None:
            if (time.monotonic() if now is None else now) >= deadline_at:
                with self._lifecycle_lock:
                    self._lifecycle_state = "timeout"
                logger.error(
                    "knowledge shutdown deadline reached; keeping DB and workers open"
                )
                return "timeout"
        return state

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
        with self._lifecycle_lock:
            if not self._closing or self._close_finalized:
                return
            self._close_finalized = True
        if not self._all_workers_drained():
            with self._lifecycle_lock:
                self._close_finalized = False
            return
        try:
            from app.web_api.knowledge_routes import (
                close_knowledge_route_executor_if_drained,
            )

            if not close_knowledge_route_executor_if_drained():
                with self._lifecycle_lock:
                    self._close_finalized = False
                return
            # Import worker 已排空后先释放其所有权，再关闭 retrieval executor，
            # 最后才释放数据库；这样退出顺序与生命周期登记表一致。
            if self.import_orchestrator is not None:
                self.import_orchestrator.close(wait=False)
                self.import_orchestrator = None
            if not self._close_retrieval_executor_if_drained():
                with self._lifecycle_lock:
                    self._close_finalized = False
                return
            self._discard_partial_state()
        except Exception as exc:
            logger.warning("knowledge runtime final close failed: %r", exc)
            with self._lifecycle_lock:
                self._close_finalized = False
            return
        self._last_injection = None
        self._last_scene_context = None
        self._cached_scene_generation = None
        self._last_retrieval_diagnostic = "knowledge_disabled"
        with self._lifecycle_lock:
            self._closing = False
            self._closed = True
            self._lifecycle_state = "closed"
