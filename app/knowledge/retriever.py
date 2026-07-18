"""知识包检索器（spec §6.3 / §13.4 / §ADDED Retrieval and Prompt Injection）。

检索流程：
    1. 只检索启用包 + 启用条目（``WHERE p.enabled=1 AND i.enabled=1``）；
    2. FTS5 优先（trigram → 普通 fts5 → LIKE 三级回退）；
    3. 评分：``-bm25 + scope_match*2 + pkg.priority*0.5 + item.priority*0.3
       + confidence*1.0 - recent_use_penalty - dedup_penalty``（LIKE 路径
       ``-bm25=0``，并附加触发词命中 ``+5`` 加分）；
    4. 类型配额：``fact≤2 / reaction_pattern≤1 / meme≤1 / style_example≤2``，
       总数 ≤ ``max_items``（默认 4）；
    5. 字符预算：``prompt_text`` ≤ ``max_chars``（默认 360，硬上限 600）；
    6. 异常降级：捕获 ``sqlite3.Error``，返回空 ``RetrievalResult`` 不抛异常。

线程安全：
    - 检索只读，不持 ``_write_lock``；
    - ``set_last_injected`` / ``mark_items_used`` 修改内部状态或写库，
      调用方需自行确保不会与 ``retrieve`` 并发（``runtime_service`` 用
      ``ThreadPoolExecutor(max_workers=1)`` 串行化）。

调用方：``KnowledgeRuntimeService``（B2 任务）。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from app.danmu_engine_dedup import texts_are_similar
from app.knowledge.database import KnowledgeDatabase
from app.knowledge.prompt_builder import build_prompt_text

logger = logging.getLogger(__name__)

# 类型配额（spec §6.3）
_KIND_QUOTA: dict[str, int] = {
    "fact": 2,
    "reaction_pattern": 1,
    "meme": 1,
    "style_example": 2,
}

_MAX_ITEMS_DEFAULT = 4
_MAX_CHARS_DEFAULT = 360
_HARD_MAX_CHARS = 600
_RECENT_USE_WINDOW_SEC_DEFAULT = 120
_FTS_HIT_LIMIT = 50
_DEDUP_THRESHOLD = 0.85

# Scope 推断关键词（spec §6.3 评分中的 scope 匹配）
_SCOPE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("游戏", "游戏"),
    ("直播", "直播"),
    ("日常", "日常"),
)

# JSON 列 → 列表字段映射
_JSON_COLUMNS: tuple[tuple[str, str], ...] = (
    ("examples_json", "examples"),
    ("triggers_json", "triggers"),
    ("tones_json", "tones"),
    ("scopes_json", "scopes"),
    ("entities_json", "entities"),
)


@dataclass(frozen=True)
class RetrievalResult:
    """检索结果（不可变）。

    字段：
        items: 命中条目列表（dict 含 id/kind/title/content/score/...）。
        prompt_text: 已格式化的提示词片段（≤ max_chars）。
        hit_count: FTS/LIKE 命中总数（评分前）。
        retrieval_ms: 检索耗时（毫秒）。
        fts_backend: 实际使用的后端（trigram/fts5/fallback）。
    """

    items: list[dict[str, Any]]
    prompt_text: str
    hit_count: int
    retrieval_ms: int
    fts_backend: str


class KnowledgeRetriever:
    """FTS5 + 类型配额 + 评分 + LIKE 回退的检索器。

    用法：
        retriever = KnowledgeRetriever(db)
        result = retriever.retrieve(scene_brief="葛瑞克二阶段", keywords=["葛瑞克"])
        if result.prompt_text:
            system_pt += result.prompt_text
            retriever.mark_items_used([it["id"] for it in result.items])
            retriever.set_last_injected([it["content"] for it in result.items])
    """

    def __init__(self, db: KnowledgeDatabase) -> None:
        self._db = db
        self._fts_backend: str = db.fts_backend
        self._last_injected_contents: list[str] = []

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def retrieve(
        self,
        *,
        scene_brief: str = "",
        keywords: list[str] | None = None,
        max_items: int = _MAX_ITEMS_DEFAULT,
        max_chars: int = _MAX_CHARS_DEFAULT,
        recent_use_window_sec: int = _RECENT_USE_WINDOW_SEC_DEFAULT,
        request_round: int = 0,
        screenshot_id: int = 0,
    ) -> RetrievalResult:
        """执行检索，返回 ``RetrievalResult``。

        Args:
            scene_brief: 场景简述（来自 ``ParsedAiReply.scene_brief``）。
            keywords: 关键词列表（来自 ``ParsedAiReply.keywords``）。
            max_items: 最大返回条目数（默认 4）。
            max_chars: 提示词字符预算（默认 360，硬上限 600）。
            recent_use_window_sec: 最近使用惩罚窗口（秒，默认 120）。
            request_round: 触发该检索的 request_round（仅用于诊断/快照）。
            screenshot_id: 触发该检索的 screenshot_id（仅用于诊断/快照）。

        Returns:
            ``RetrievalResult``；异常时返回空结果不抛异常。
        """
        start = time.perf_counter()
        keywords = [str(k) for k in (keywords or []) if k]
        scene_brief = str(scene_brief or "")
        max_items = max(1, min(int(max_items), _MAX_ITEMS_DEFAULT))
        max_chars = max(1, min(int(max_chars), _HARD_MAX_CHARS))

        try:
            hits = self._query_hits(scene_brief, keywords)
        except sqlite3.Error as exc:
            logger.warning("knowledge.retrieve sql error: %s", exc)
            return RetrievalResult(
                items=[],
                prompt_text="",
                hit_count=0,
                retrieval_ms=0,
                fts_backend=self._fts_backend,
            )

        if not hits:
            return RetrievalResult(
                items=[],
                prompt_text="",
                hit_count=0,
                retrieval_ms=_elapsed_ms(start),
                fts_backend=self._fts_backend,
            )

        hit_count = len(hits)
        scored = self._score_hits(hits, scene_brief, keywords, recent_use_window_sec)
        selected = self._apply_quotas(scored, max_items)
        prompt_text = build_prompt_text(selected, max_chars=max_chars)

        return RetrievalResult(
            items=selected,
            prompt_text=prompt_text,
            hit_count=hit_count,
            retrieval_ms=_elapsed_ms(start),
            fts_backend=self._fts_backend,
        )

    def set_last_injected(self, contents: list[str]) -> None:
        """更新上次注入的 content 列表，用于下次 ``dedup_penalty`` 计算。

        由 ``runtime_service`` 在注入成功后调用。
        """
        self._last_injected_contents = [str(c) for c in contents if c]

    def mark_items_used(
        self, item_ids: list[int], used_at: float | None = None
    ) -> None:
        """更新 ``use_count`` + ``last_used_at``。

        委托 ``repository.mark_items_used_for_db``（在 ``_db`` 的写锁内执行）。
        """
        if not item_ids:
            return
        # 延迟 import 避免循环依赖
        from app.knowledge.repository import mark_items_used_for_db

        mark_items_used_for_db(self._db, list(item_ids), used_at=used_at)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def _query_hits(
        self, scene_brief: str, keywords: list[str]
    ) -> list[dict[str, Any]]:
        """执行 FTS5 或 LIKE 查询，返回命中条目列表。"""
        query_text = _build_fts_query(scene_brief, keywords)
        # 空查询：跳过 FTS，hit_count=0
        if not query_text:
            return []

        if self._fts_backend in ("trigram", "fts5"):
            hits = self._query_fts(query_text)
            if hits:
                return hits
            # FTS 无命中 → 回退 LIKE
        return self._query_like(scene_brief, keywords)

    def _query_fts(self, query_text: str) -> list[dict[str, Any]]:
        """执行 FTS5 查询（``bm25`` 排序，LIMIT 50）。"""
        sql = (
            "SELECT i.*, p.priority AS pkg_priority, "
            "bm25(knowledge_items_fts) AS fts_score "
            "FROM knowledge_items_fts f "
            "JOIN knowledge_items i ON f.rowid = i.id "
            "JOIN knowledge_packages p ON i.package_id = p.id "
            "WHERE f MATCH ? AND p.enabled=1 AND i.enabled=1 "
            "ORDER BY fts_score ASC LIMIT ?"
        )
        try:
            rows = self._db.conn.execute(
                sql, (query_text, _FTS_HIT_LIMIT)
            ).fetchall()
        except sqlite3.OperationalError as exc:
            # FTS 查询语法错误或表损坏 → 回退 LIKE
            logger.debug("knowledge.fts query failed, fallback to LIKE: %s", exc)
            return []
        return [_deserialize_item_row(row) for row in rows]

    def _query_like(
        self, scene_brief: str, keywords: list[str]
    ) -> list[dict[str, Any]]:
        """执行 LIKE 回退查询。"""
        like_terms: list[str] = []
        for kw in keywords:
            if kw:
                like_terms.append(f"%{kw}%")
        for word in _split_words(scene_brief):
            if word:
                like_terms.append(f"%{word}%")
        if not like_terms:
            return []

        conditions: list[str] = []
        params: list[Any] = []
        for term in like_terms:
            conditions.append("(i.search_text LIKE ? OR i.title LIKE ?)")
            params.append(term)
            params.append(term)
        where_clause = " OR ".join(conditions)
        sql = (
            "SELECT i.*, p.priority AS pkg_priority "
            "FROM knowledge_items i "
            "JOIN knowledge_packages p ON i.package_id = p.id "
            f"WHERE p.enabled=1 AND i.enabled=1 AND ({where_clause}) "
            "ORDER BY i.priority DESC, i.id ASC LIMIT ?"
        )
        rows = self._db.conn.execute(
            sql, [*params, _FTS_HIT_LIMIT]
        ).fetchall()
        return [_deserialize_item_row(row) for row in rows]

    # ------------------------------------------------------------------
    # 评分
    # ------------------------------------------------------------------

    def _score_hits(
        self,
        hits: list[dict[str, Any]],
        scene_brief: str,
        keywords: list[str],
        recent_use_window_sec: int,
    ) -> list[dict[str, Any]]:
        """对命中条目评分，原地添加 ``score`` 字段并按 score 降序排序。"""
        now = time.time()
        inferred_scope = _infer_scope(scene_brief)
        is_like_path = not _has_fts_score(hits)

        for item in hits:
            # fts_score（FTS 路径取负；LIKE 路径为 0）
            fts_score = 0.0
            if not is_like_path:
                try:
                    fts_score = -float(item.get("fts_score") or 0.0)
                except (TypeError, ValueError):
                    fts_score = 0.0

            # 触发词命中加分（仅 LIKE 路径）
            trigger_bonus = 0.0
            if is_like_path and keywords:
                triggers = item.get("triggers") or []
                if any(kw in triggers for kw in keywords):
                    trigger_bonus = 5.0

            # scope 匹配
            scope_match = _scope_match_count(
                item.get("scopes") or [], inferred_scope
            )

            # 最近使用惩罚（spec line 165：last_used_at + use_count 双因子）
            recent_penalty = _recent_use_penalty(
                item.get("last_used_at"),
                now,
                recent_use_window_sec,
                use_count=int(item.get("use_count") or 0),
            )

            # dedup 惩罚
            dedup_penalty = self._dedup_penalty(str(item.get("content", "")))

            # package / item priority / confidence
            pkg_priority = _safe_float(item.get("pkg_priority"), 0.0)
            item_priority = _safe_float(item.get("priority"), 0.0)
            confidence = _safe_float(item.get("confidence"), 0.0)

            score = (
                fts_score
                + scope_match * 2.0
                + pkg_priority * 0.5
                + item_priority * 0.3
                + confidence * 1.0
                - recent_penalty
                - dedup_penalty
                + trigger_bonus
            )
            item["score"] = score

        hits.sort(key=lambda x: _safe_float(x.get("score"), 0.0), reverse=True)
        return hits

    def _apply_quotas(
        self, scored: list[dict[str, Any]], max_items: int
    ) -> list[dict[str, Any]]:
        """按类型配额选取条目（按 score 降序遍历，每个 kind 取到 quota 为止）。"""
        selected: list[dict[str, Any]] = []
        used_count: dict[str, int] = {}
        for item in scored:
            if len(selected) >= max_items:
                break
            kind = str(item.get("kind", ""))
            quota = _KIND_QUOTA.get(kind)
            if quota is None:
                continue
            if used_count.get(kind, 0) >= quota:
                continue
            selected.append(item)
            used_count[kind] = used_count.get(kind, 0) + 1
        return selected

    def _dedup_penalty(self, content: str) -> float:
        """与上次注入内容相似（threshold=0.85）→ 1.0 惩罚。"""
        if not content or not self._last_injected_contents:
            return 0.0
        for prev in self._last_injected_contents:
            if texts_are_similar(content, prev, _DEDUP_THRESHOLD):
                return 1.0
        return 0.0


# ---------------------------------------------------------------------------
# 模块级辅助函数
# ---------------------------------------------------------------------------


def _build_fts_query(scene_brief: str, keywords: list[str]) -> str:
    """构造 FTS5 MATCH 查询字符串：``scene_brief + ' ' + ' '.join(keywords)``。"""
    parts: list[str] = []
    if scene_brief:
        parts.append(scene_brief)
    for kw in keywords:
        if kw:
            parts.append(kw)
    return " ".join(parts).strip()


def _split_words(text: str) -> list[str]:
    """将文本拆分为词（用于 LIKE 查询参数）。

    按空白和常见中英文标点拆分；中文连续段视为一个词。
    """
    if not text:
        return []
    parts = re.split(r"[\s,，。.!！?？;；:：、()（）\[\]【】]+", text)
    return [p.strip() for p in parts if p.strip()]


def _infer_scope(scene_brief: str) -> str:
    """从 scene_brief 推断 scope（游戏/直播/日常；默认 global）。"""
    if not scene_brief:
        return "global"
    for keyword, scope in _SCOPE_KEYWORDS:
        if keyword in scene_brief:
            return scope
    return "global"


def _scope_match_count(item_scopes: list[str], inferred: str) -> int:
    """计算 scope 匹配数。

    - ``inferred="global"`` 匹配所有 → 返回 1；
    - 否则 ``inferred`` 在 ``item_scopes`` 中 → 1，不在 → 0；
    - ``item_scopes`` 为空且 ``inferred!="global"`` → 0。
    """
    if inferred == "global":
        return 1
    if not item_scopes:
        return 0
    return 1 if inferred in item_scopes else 0


def _recent_use_penalty(
    last_used_at: Any,
    now: float,
    window_sec: int,
    *,
    use_count: int = 0,
) -> float:
    """计算最近使用惩罚（双因子）。

    spec §15 / checklist line 165：基于 ``last_used_at`` + ``use_count`` 双因子。

    1. 时近因子：``last_used_at > 0`` 且 ``now - last_used_at < window_sec``：
       ``time_penalty = (window_sec - elapsed) / window_sec * 2.0``
       （窗口内最大 2.0；窗口外 0）。
    2. 频次因子：``use_count > 1`` 时追加 ``0.1 * (use_count - 1)``，上限 1.0；
       与 ``time_penalty`` 相加后总上限 2.0，避免高频条目被永久屏蔽。

    防 5 秒内重复生成"经典""又开始了"（spec line 167）：刚被注入（elapsed=0）+
    多次使用（use_count ≥ 5）的条目会被强惩罚（接近 2.0 上限），但仍可在评分
    其他维度（priority/confidence）足够高时被选中。

    Args:
        last_used_at: ISO8601 字符串或 None。
        now: 当前 epoch 秒。
        window_sec: 最近使用惩罚窗口（默认 120s）。
        use_count: 条目历史使用次数（来自 ``knowledge_items.use_count``）。
    """
    time_penalty = 0.0
    if last_used_at:
        used_at = _parse_iso_to_epoch(last_used_at)
        if used_at is not None:
            elapsed = now - used_at
            if elapsed < 0:
                # 时钟偏移，视为刚使用
                elapsed = 0.0
            if elapsed < window_sec:
                time_penalty = (window_sec - elapsed) / window_sec * 2.0

    count_penalty = 0.0
    if use_count and use_count > 1:
        count_penalty = min(1.0, 0.1 * (use_count - 1))

    return min(2.0, time_penalty + count_penalty)


def _parse_iso_to_epoch(iso_str: Any) -> float | None:
    """ISO8601 字符串（``%Y-%m-%dT%H:%M:%SZ``）→ epoch 秒。"""
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        # 优先解析 UTC ISO 格式（repository._now_iso 输出）
        # time.strptime 返回本地时间 struct，用 calendar.timegm 转 UTC epoch
        import calendar

        struct = time.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ")
        return float(calendar.timegm(struct))
    except (ValueError, TypeError):
        pass
    try:
        # 兜底：SQLite 默认 TEXT 格式
        import calendar

        struct = time.strptime(iso_str, "%Y-%m-%d %H:%M:%S")
        return float(calendar.timegm(struct))
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转 float；失败返回 default。"""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _elapsed_ms(start: float) -> int:
    """``time.perf_counter`` 差值 → 毫秒（int）。"""
    return int((time.perf_counter() - start) * 1000)


def _has_fts_score(hits: list[dict[str, Any]]) -> bool:
    """判断 hits 是否来自 FTS 路径（含 ``fts_score`` 字段）。"""
    return any("fts_score" in h for h in hits)


def _json_loads(value: Any, default: Any = None) -> Any:
    """安全 JSON 解析；空值或失败返回 default。"""
    if not value:
        return default if default is not None else []
    if not isinstance(value, str):
        return default if default is not None else []
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default if default is not None else []


def _deserialize_item_row(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row → dict；JSON 列反序列化为列表；enabled 转 bool。"""
    d = dict(row)
    for json_key, list_key in _JSON_COLUMNS:
        if json_key in d:
            d[list_key] = _json_loads(d.pop(json_key), default=[])
        elif list_key not in d:
            d[list_key] = []
    if "enabled" in d:
        d["enabled"] = bool(d["enabled"])
    return d


__all__ = ["KnowledgeRetriever", "RetrievalResult"]
