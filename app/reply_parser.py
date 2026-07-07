"""AI 回复解析：多格式容错、标准化批次与本地弹幕池补齐。

支持输入格式（按检测顺序）：
  1. JSON 数组 — 直接作为弹幕列表（主格式）
  2. JSON 对象 — comments/replies/items/data 键（兼容信封）
  3. 纯文本 — 按换行拆分

调用方：DanmuApp._on_ai_reply() → parse_ai_reply_payload → normalize_reply_batch
"""
from __future__ import annotations

import json
import logging
import random
import re
from app.danmu_engine_dedup import texts_are_similar

logger = logging.getLogger(__name__)

from app.danmu_pool import (
    _sample_custom_pool_texts,
    custom_pool_size,
    pool_enabled,
)

_COMMENT_KEYS = ("comments", "replies", "items", "data")
_HEURISTIC_SKIP = frozenset({"comments", ":", ""})
_MAX_HEURISTIC_DEPTH = 16
# Defense-in-depth: even though the iterative stack replaces the call stack,
# a pathological input could still grow the worklist. Cap the total number of
# segments we'll process so an adversarial }{ flood can't pin a worker.
_MAX_HEURISTIC_NODES = 4096
_PLACEHOLDER_COMMENT_RE = re.compile(
    r"^(?:comment|comments|评论|弹幕)\s*[-_#:]?\s*\d{1,3}$",
    re.IGNORECASE,
)
_FUZZY_BATCH_THRESHOLD = 0.82

# MiniMax reasoning tags: <think>...</think> blocks leak into replies when
# reasoning_split is not honored; strip them before parsing.
_REASONING_OPEN = "<think>"
_REASONING_CLOSE = "</think>"
_REASONING_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_REASONING_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL)
_REASONING_CLOSE_LEADING_RE = re.compile(r"^.*?</think>", re.DOTALL)

# Plain-text reasoning preamble prefixes (conservative: only obvious leakage).
# Note: no \b after Chinese prefixes — \b doesn't work between CJK chars.
_REASONING_PREAMBLE_LINE_RE = re.compile(
    r"^\s*(?:\.{3}|>>|让我想想|让我思考|思考一下|思考[：:]|reasoning\s*[:：]|let me think)",
    re.IGNORECASE,
)


def _strip_reasoning_tags(raw: str) -> str:
    """Remove MiniMax-style </think>...</think> reasoning blocks from raw text.

    Handles three cases:
    1. Complete ``\u200b...\u200b`` blocks (tags included).
    2. Unclosed ``\u200b...`` (from ``\u200b`` to end of string).
    3. Unclosed ``...\u200b`` (from start of string to ``\u200b``).
    """
    if not raw or _REASONING_OPEN not in raw and _REASONING_CLOSE not in raw:
        return raw
    result = _REASONING_BLOCK_RE.sub("", raw)
    result = _REASONING_OPEN_RE.sub("", result)
    result = _REASONING_CLOSE_LEADING_RE.sub("", result)
    return result


def _is_reasoning_preamble_line(line: str) -> bool:
    """Detect obvious reasoning preamble leakage in plain-text fallback.

    Conservative: only matches lines that clearly look like reasoning preamble
    (e.g. ``让我想想...``, ``思考：...``, ``reasoning: ...``, ``>> ...``).
    """
    return _REASONING_PREAMBLE_LINE_RE.match(line) is not None


def _is_usable_comment(value: str) -> bool:
    """过滤 JSON 碎片、纯标点等不可上屏的伪弹幕。"""
    text = str(value).strip()
    if not text or text in _HEURISTIC_SKIP:
        return False
    if _PLACEHOLDER_COMMENT_RE.match(text):
        return False
    if len(text) == 1 and not text.isalnum():
        return False
    return any(ch.isalnum() for ch in text)


def _fillers_from_pool_snapshot(pool: list[str], count: int, *, rng=None) -> list[str]:
    if not pool or count <= 0:
        return []
    rng = rng or random
    n = min(count, len(pool))
    if n >= len(pool):
        return list(rng.sample(pool, len(pool)))
    return rng.sample(pool, n)


def _scene_fillers(config=None) -> list[str]:
    if not pool_enabled(config):
        return []
    pool_size = custom_pool_size(config)
    return _sample_custom_pool_texts(config, min(32, pool_size), rng=random)


def _raw_has_envelope_key(raw: str) -> bool:
    return any(f'"{key}"' in raw for key in _COMMENT_KEYS)


def _envelope_array_re(key: str) -> re.Pattern[str]:
    return re.compile(rf'"{re.escape(key)}"\s*:\s*\[([^\]]*)\]', re.DOTALL)


def _generic_fillers(config=None) -> list[str]:
    if not pool_enabled(config):
        return []
    pool_size = custom_pool_size(config)
    return _sample_custom_pool_texts(config, min(48, pool_size), rng=random)


def _try_parse_json_object(raw: str):
    """解析 JSON 对象；遇 ``}{`` 拼接（流式重复）时只取第一段 ``{...}``。"""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    if not raw.startswith("{"):
        return None
    if "}{" in raw:
        head = raw.split("}{", 1)[0] + "}"
        try:
            parsed = json.loads(head)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    stripped = raw.rstrip()
    if not stripped.endswith("}"):
        for suffix in ("]}", "}", '"]}'):
            try:
                parsed = json.loads(raw + suffix)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _heuristic_comments_from_malformed_json(raw: str, *, depth: int = 0) -> list[str]:
    """模型偶发畸形 JSON（comments 非数组、重复对象拼接）时的兜底抽取。

    Iterative stack walk (BUG-011 修复)：原递归实现对 ``}{`` 反复分裂会
    产生 ``O(2^N)`` 次调用，17+ 个 ``}{`` 即可能触达 Python 1000 帧递归
    限制。改为显式栈后每个 unique segment 仅处理一次，复杂度退化为
    ``O(N · L)``（L = 单段正则抽取成本）。

    ``_MAX_HEURISTIC_DEPTH`` 仍限定单条分裂链的最大深度；``_MAX_HEURISTIC_NODES``
    作为全局节点预算（防御性，对抗性输入不让 worklist 无界增长）。
    """
    merged: list[str] = []
    # (segment_text, segment_depth) — pop from the back so we process in DFS order.
    stack: list[tuple[str, int]] = [(raw, depth)]
    nodes_processed = 0

    while stack:
        seg, seg_depth = stack.pop()
        nodes_processed += 1
        if nodes_processed > _MAX_HEURISTIC_NODES:
            # Budget exhausted: stop splitting and treat remaining work as leaves
            # so we still attempt regex extraction on the segments already in hand.
            for remaining, _ in stack:
                merged.extend(_extract_comments_from_leaf(remaining))
            break

        if "}{" in seg and seg_depth < _MAX_HEURISTIC_DEPTH:
            parts = seg.split("}{")
            # Push in reverse so iteration order matches the recursive original.
            for i in range(len(parts) - 1, -1, -1):
                piece = parts[i]
                if i > 0:
                    piece = "{" + piece
                if i < len(parts) - 1:
                    piece = piece + "}"
                stack.append((piece, seg_depth + 1))
            continue

        merged.extend(_extract_comments_from_leaf(seg))

    return _normalize_comment_list(merged)


def _extract_comments_from_leaf(raw: str) -> list[str]:
    """单段（无 ``}{``）的兜底弹幕抽取；与原递归实现的 leaf 分支等价。"""
    for key in _COMMENT_KEYS:
        arr_match = _envelope_array_re(key).search(raw)
        if arr_match:
            items = re.findall(r'"((?:[^"\\]|\\.)*)"', arr_match.group(1))
            normalized = _normalize_comment_list(items)
            if normalized:
                return normalized

        open_arr = re.search(rf'"{re.escape(key)}"\s*:\s*\[(.*)$', raw, re.DOTALL)
        if open_arr:
            inner = open_arr.group(1)
            items = re.findall(r'"((?:[^"\\]|\\.)*)"', inner)
            normalized = _normalize_comment_list(items)
            if normalized:
                return normalized

    if not _raw_has_envelope_key(raw):
        return []

    filtered: list[str] = []
    for value in re.findall(r'"((?:[^"\\]|\\.)*)"', raw):
        if not value or value in _HEURISTIC_SKIP or value in _COMMENT_KEYS:
            continue
        if len(value) == 1 and not value.isalnum():
            continue
        filtered.append(value)
    return _normalize_comment_list(filtered)


def _try_parse_json_array(raw: str):
    """解析 JSON 数组；遇 ``][`` 拼接（流式截断）时只取第一段 ``[...]``。"""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return parsed
    if "][" in raw:
        head = raw.split("][", 1)[0] + "]"
        try:
            parsed = json.loads(head)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            return parsed
    return None


def _normalize_comment_list(candidates) -> list[str]:
    normalized: list[str] = []
    for item in candidates:
        value = str(item).strip().strip('"').strip("'")
        if _is_usable_comment(value):
            normalized.append(value)
    return normalized


def _batch_has_similar_text(
    value: str,
    existing: list[str],
    *,
    threshold: float = _FUZZY_BATCH_THRESHOLD,
) -> bool:
    """批内模糊去重：只拦截已经出现过的近似重复短句。"""
    for prev in existing:
        if value == prev:
            return True
        if abs(len(value) - len(prev)) > 3:
            continue
        if texts_are_similar(value, prev, threshold):
            return True
    return False


def _extract_comments_from_dict(parsed: dict) -> list[str]:
    for key in _COMMENT_KEYS:
        value = parsed.get(key)
        if isinstance(value, list):
            return _normalize_comment_list(value)
        if isinstance(value, str) and value.strip():
            return _normalize_comment_list([value])
    return []


def parse_ai_reply_payload(text: str) -> list[str]:
    """解析 AI 原始文本为弹幕列表。"""
    raw = _strip_reasoning_tags(str(text or "").strip()).strip()
    if not raw:
        return []

    parsed = None
    tried_json = False
    used_heuristic = False
    if raw.startswith("[") or raw.startswith("{"):
        tried_json = True
        if raw.startswith("["):
            parsed = _try_parse_json_array(raw)
        elif "}{" in raw:
            # B03 修复：}{ 拼接时逐段解析并合并 comments
            merged: list[str] = []
            segments = raw.split("}{")
            for i, seg in enumerate(segments):
                if i > 0:
                    seg = "{" + seg
                if i < len(segments) - 1:
                    seg = seg + "}"
                obj = _try_parse_json_object(seg)
                if isinstance(obj, dict):
                    merged.extend(_extract_comments_from_dict(obj))
            parsed = merged if merged else None
        else:
            parsed = _try_parse_json_object(raw)

    if isinstance(parsed, dict):
        candidates = _extract_comments_from_dict(parsed)
        if not candidates and raw.startswith("{"):
            used_heuristic = True
            candidates = _heuristic_comments_from_malformed_json(raw)
    elif isinstance(parsed, list):
        candidates = parsed
    elif raw.startswith("{") and _raw_has_envelope_key(raw):
        used_heuristic = True
        if tried_json:
            logger.warning(
                "AI reply JSON parse yielded no comments; falling back to heuristic: "
                "raw_len=%s prefix=%.80s",
                len(raw),
                raw,
            )
        candidates = _heuristic_comments_from_malformed_json(raw)
    else:
        candidates = [
            part.strip(" -\t\r\n")
            for part in raw.replace("\r", "\n").split("\n")
            if part.strip() and not _is_reasoning_preamble_line(part)
        ]

    if (
        tried_json
        and not candidates
        and raw.startswith("{")
        and _raw_has_envelope_key(raw)
        and not used_heuristic
    ):
        logger.warning(
            "AI reply JSON parse yielded no comments; falling back to heuristic: "
            "raw_len=%s prefix=%.80s",
            len(raw),
            raw,
        )
        candidates = _heuristic_comments_from_malformed_json(raw)

    return _normalize_comment_list(candidates)


def _append_next_unique_from_pool(
    result: list[str],
    seen: set[str],
    pool: list[str],
    cursor: list[int],
) -> bool:
    """Rotate pool once; append one unseen phrase. False if pool has no new phrase."""
    if not pool:
        return False
    n = len(pool)
    for _ in range(n):
        text = pool[cursor[0] % n]
        cursor[0] += 1
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
        return True
    return False


def normalize_reply_batch(
    items: list[str],
    scene_count: int = 2,
    filler_count: int = 3,
    *,
    allow_shortfall: bool = False,
    config=None,
) -> list[str]:
    """将 AI 回复标准化为固定条数：前 scene_count 条视为场景相关，其余为填充条。"""
    _ = allow_shortfall

    scene_count = max(1, int(scene_count))
    filler_count = int(filler_count)
    if filler_count <= 0:
        desired_count = scene_count
    else:
        filler_count = max(1, filler_count)
        desired_count = scene_count + filler_count

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        if not _is_usable_comment(value) or value in seen:
            continue
        if _batch_has_similar_text(value, cleaned):
            continue
        seen.add(value)
        cleaned.append(value)

    result = cleaned[:desired_count]
    scene_fillers: list[str] = []
    generic_fillers: list[str] = []
    if config is not None and pool_enabled(config):
        count_fn = getattr(config, "custom_danmu_count", None)
        if not (callable(count_fn) and count_fn() <= 0):
            pool_size = custom_pool_size(config)
            combined = _sample_custom_pool_texts(config, min(80, pool_size), rng=random)
            scene_fillers = combined[: min(32, len(combined))]
            generic_fillers = combined[: min(48, len(combined))]
    if not scene_fillers and not generic_fillers:
        scene_fillers = _scene_fillers(config)
        generic_fillers = _generic_fillers(config)

    seen = set(result)
    scene_cursor = [0]
    while len(result) < min(scene_count, desired_count):
        if not _append_next_unique_from_pool(result, seen, scene_fillers, scene_cursor):
            break
    generic_cursor = [0]
    while len(result) < desired_count:
        if not _append_next_unique_from_pool(result, seen, generic_fillers, generic_cursor):
            break
    return result[:desired_count]
