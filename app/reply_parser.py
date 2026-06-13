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
from typing import TYPE_CHECKING

from app.danmu_pool import load_danmu_pool_for_config, sample_danmu_for_config

if TYPE_CHECKING:
    pass

_COMMENT_KEYS = ("comments", "replies", "items", "data")
_COMMENTS_ARRAY_RE = re.compile(r'"comments"\s*:\s*\[([^\]]*)\]', re.DOTALL)
_SCENE_BRIEF_VALUE_RE = re.compile(r'"scene_brief"\s*:\s*"([^"]*)"')
_HEURISTIC_SKIP = frozenset({"comments", "scene_brief", ":", ""})


def _is_usable_comment(value: str) -> bool:
    """过滤 JSON 碎片、纯标点等不可上屏的伪弹幕。"""
    text = str(value).strip()
    if not text or text in _HEURISTIC_SKIP:
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


def _heuristic_comments_from_malformed_json(raw: str) -> list[str]:
    """模型偶发畸形 JSON（comments 非数组、重复对象拼接）时的兜底抽取。"""
    if "}{" in raw:
        raw = raw.split("}{", 1)[0] + "}"

    scene_brief_match = _SCENE_BRIEF_VALUE_RE.search(raw)
    scene_brief_value = scene_brief_match.group(1) if scene_brief_match else None

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
        if scene_brief_value and value == scene_brief_value:
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
    raw = str(text or "").strip()
    if not raw:
        return []

    parsed = None
    if raw.startswith("[") or raw.startswith("{"):
        if raw.startswith("["):
            parsed = _try_parse_json_array(raw)
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
            if part.strip()
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
