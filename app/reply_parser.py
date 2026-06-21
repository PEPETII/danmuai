"""AI 回复解析：多格式容错、标准化批次与本地弹幕池补齐。

支持输入格式（按检测顺序）：
  1. JSON 数组 — 直接作为弹幕列表（主格式）
  2. JSON 对象 — comments/replies/items/data 键（兼容信封）
  3. 纯文本 — 按换行拆分

调用方：DanmuApp._on_ai_reply() → parse_ai_reply_payload → normalize_reply_batch
"""
from __future__ import annotations

import json
import random
import re
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from app.danmu_pool import load_danmu_pool_for_config, sample_danmu_for_config

if TYPE_CHECKING:
    pass

_COMMENT_KEYS = ("comments", "replies", "items", "data")
_COMMENTS_ARRAY_RE = re.compile(r'"comments"\s*:\s*\[([^\]]*)\]', re.DOTALL)
_HEURISTIC_SKIP = frozenset({"comments", "scene_brief", ":", ""})
_MAX_HEURISTIC_DEPTH = 16
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


def _scene_fillers(config=None) -> list[str]:
    pool = load_danmu_pool_for_config(config)
    if not pool:
        return []
    return sample_danmu_for_config(config, min(32, len(pool)), rng=random)


def _generic_fillers(config=None) -> list[str]:
    pool = load_danmu_pool_for_config(config)
    if not pool:
        return []
    return sample_danmu_for_config(config, min(48, len(pool)), rng=random)


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
    """模型偶发畸形 JSON（comments 非数组、重复对象拼接）时的兜底抽取。"""
    if "}{" in raw and depth < _MAX_HEURISTIC_DEPTH:
        merged: list[str] = []
        segments = raw.split("}{")
        for i, seg in enumerate(segments):
            if i > 0:
                seg = "{" + seg
            if i < len(segments) - 1:
                seg = seg + "}"
            merged.extend(_heuristic_comments_from_malformed_json(seg, depth=depth + 1))
        return _normalize_comment_list(merged)

    arr_match = _COMMENTS_ARRAY_RE.search(raw)
    if arr_match:
        items = re.findall(r'"((?:[^"\\]|\\.)*)"', arr_match.group(1))
        normalized = _normalize_comment_list(items)
        if normalized:
            return normalized

    open_arr = re.search(r'"comments"\s*:\s*\[(.*)$', raw, re.DOTALL)
    if open_arr:
        inner = open_arr.group(1)
        items = re.findall(r'"((?:[^"\\]|\\.)*)"', inner)
        normalized = _normalize_comment_list(items)
        if normalized:
            return normalized

    if '"comments"' not in raw:
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
        if SequenceMatcher(None, value, prev).ratio() >= threshold:
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
    if raw.startswith("[") or raw.startswith("{"):
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
            candidates = _heuristic_comments_from_malformed_json(raw)
    elif isinstance(parsed, list):
        candidates = parsed
    elif raw.startswith("{") and '"comments"' in raw:
        candidates = _heuristic_comments_from_malformed_json(raw)
    else:
        candidates = [
            part.strip(" -\t\r\n")
            for part in raw.replace("\r", "\n").split("\n")
            if part.strip() and not _is_reasoning_preamble_line(part)
        ]

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
