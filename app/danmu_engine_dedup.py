import logging
import threading
import time  # noqa: F401 — used as danmu_engine_dedup.time from app.danmu_engine
from collections import deque
from dataclasses import dataclass

from app.env_config import get as get_env

logger = logging.getLogger(__name__)

_LEVENSHTEIN_RATIO = None
_LEVENSHTEIN_UNAVAILABLE = object()
_LEVENSHTEIN_FALLBACK_WARNED = False
_DEDUP_PROFILE_FLAG: bool | None = None
_DEDUP_THRESHOLD_FALLBACK = 0.5
# English live-comment phrases often share a prefix ("what a", "that was") while
# the trailing word carries the meaning. Require near-typo similarity on the
# last word before treating multi-word ASCII phrases as fuzzy duplicates.
_ASCII_SUFFIX_TYPO_THRESHOLD = 0.75
# BUG-009: pure-Python Levenshtein fallback is O(m×n); truncate long strings to
# protect the 60fps Overlay main thread when neither python-Levenshtein nor
# rapidfuzz is installed. Only the fallback path truncates — the C extension
# path remains untouched. 32 chars covers typical danmu (15 中文字 / 40 英文字)
# without measurable recall loss; longer danmu is rare and unlikely to repeat.
_FALLBACK_MAX_LEN = 32
# 仅保护 _LEVENSHTEIN_RATIO 懒加载；_dedup_profile_stats / _last_duplicate_observation
# 是 best-effort profile/观察数据，刻意不加锁（AGENTS.md §11 避免过度工程）。
_lazy_lock = threading.Lock()
_last_duplicate_observation = {
    "content": "",
    "match_type": "",
    "threshold": _DEDUP_THRESHOLD_FALLBACK,
    "result": False,
}


@dataclass
class DedupProfileStats:
    duplicate_checks: int = 0
    duplicate_hits: int = 0
    exact_set_hits: int = 0
    similarity_hits: int = 0
    length_pruned: int = 0
    similarity_calls: int = 0
    similarity_fallback_calls: int = 0
    is_duplicate_ns: int = 0
    similarity_ns: int = 0


_dedup_profile_stats = DedupProfileStats()


def dedup_profile_enabled() -> bool:
    global _DEDUP_PROFILE_FLAG
    if _DEDUP_PROFILE_FLAG is None:
        value = get_env("DANMU_DEDUP_PROFILE").strip().lower()
        _DEDUP_PROFILE_FLAG = value in ("1", "true", "yes", "on")
    return _DEDUP_PROFILE_FLAG


def reset_dedup_profile_for_tests(clear_env_cache: bool = True) -> None:
    global _DEDUP_PROFILE_FLAG, _dedup_profile_stats, _last_duplicate_observation
    if clear_env_cache:
        _DEDUP_PROFILE_FLAG = None
    _dedup_profile_stats = DedupProfileStats()
    _last_duplicate_observation = {
        "content": "",
        "match_type": "",
        "threshold": _DEDUP_THRESHOLD_FALLBACK,
        "result": False,
    }


def snapshot_dedup_profile() -> dict:
    stats = _dedup_profile_stats
    checks = max(stats.duplicate_checks, 1)
    similarity_calls = max(stats.similarity_calls, 1)
    return {
        "enabled": dedup_profile_enabled(),
        "duplicate_checks": stats.duplicate_checks,
        "duplicate_hits": stats.duplicate_hits,
        "exact_set_hits": stats.exact_set_hits,
        "similarity_hits": stats.similarity_hits,
        "length_pruned": stats.length_pruned,
        "similarity_calls": stats.similarity_calls,
        "similarity_fallback_calls": stats.similarity_fallback_calls,
        "avg_is_duplicate_us": round(stats.is_duplicate_ns / checks / 1000, 3),
        "avg_similarity_us": round(stats.similarity_ns / similarity_calls / 1000, 3)
        if stats.similarity_calls
        else 0.0,
        "is_duplicate_total_ms": round(stats.is_duplicate_ns / 1_000_000, 3),
        "similarity_total_ms": round(stats.similarity_ns / 1_000_000, 3),
    }


def log_dedup_profile_summary(logger) -> None:
    if not dedup_profile_enabled():
        return
    logger.debug(f"dedup profile: {snapshot_dedup_profile()}")


def get_last_duplicate_observation() -> dict[str, object]:
    return dict(_last_duplicate_observation)


def _get_levenshtein_ratio():
    global _LEVENSHTEIN_RATIO, _LEVENSHTEIN_FALLBACK_WARNED
    if _LEVENSHTEIN_RATIO is None:
        with _lazy_lock:
            if _LEVENSHTEIN_RATIO is None:
                try:
                    from Levenshtein import ratio as _ratio

                    _LEVENSHTEIN_RATIO = _ratio
                except ImportError:
                    try:
                        from rapidfuzz.distance import Levenshtein as _rf_lev

                        _LEVENSHTEIN_RATIO = _rf_lev.normalized_similarity
                    except ImportError:
                        _LEVENSHTEIN_RATIO = _LEVENSHTEIN_UNAVAILABLE
                        if not _LEVENSHTEIN_FALLBACK_WARNED:
                            _LEVENSHTEIN_FALLBACK_WARNED = True
                            logger.warning(
                                "Levenshtein C extension unavailable; "
                                "danmu dedup will use slow pure-Python fallback"
                            )
    if _LEVENSHTEIN_RATIO is _LEVENSHTEIN_UNAVAILABLE:
        return None
    return _LEVENSHTEIN_RATIO


def similarity(a: str, b: str) -> float:
    """Levenshtein 相似度；无第三方库时用编辑距离回退。"""
    profile = dedup_profile_enabled()
    started = time.perf_counter_ns() if profile else 0

    if not a or not b:
        result = 0.0
    else:
        ratio_fn = _get_levenshtein_ratio()
        if ratio_fn is not None:
            result = ratio_fn(a, b)
        else:
            if profile:
                _dedup_profile_stats.similarity_fallback_calls += 1
            # BUG-009: bound the O(m×n) work in the pure-Python fallback so
            # a 30-item dedup window of 80-char danmu can't stall the
            # 60fps Overlay tick. Truncate before length-swap so the
            # denominator stays consistent.
            if len(a) > _FALLBACK_MAX_LEN:
                a = a[:_FALLBACK_MAX_LEN]
            if len(b) > _FALLBACK_MAX_LEN:
                b = b[:_FALLBACK_MAX_LEN]
            m, n = len(a), len(b)
            if m > n:
                a, b = b, a
                m, n = n, m
            prev_row = list(range(n + 1))
            for i in range(1, m + 1):
                curr = [i] + [0] * n
                for j in range(1, n + 1):
                    cost = 0 if a[i - 1] == b[j - 1] else 1
                    curr[j] = min(curr[j - 1] + 1, prev_row[j] + 1, prev_row[j - 1] + cost)
                prev_row = curr
            dist = prev_row[n]
            result = 1 - dist / max(len(a), len(b))

    if profile:
        _dedup_profile_stats.similarity_calls += 1
        _dedup_profile_stats.similarity_ns += time.perf_counter_ns() - started
    return result


def _is_ascii_space_phrase(text: str) -> bool:
    """True for short ASCII live-comment phrases with at least one space."""
    return bool(text) and text.isascii() and " " in text


def _ascii_trailing_words_clearly_distinct(a: str, b: str) -> bool:
    """True when multi-word ASCII phrases differ in trailing vocabulary, not typo."""
    words_a = a.lower().split()
    words_b = b.lower().split()
    if len(words_a) < 2 or len(words_a) != len(words_b):
        return False

    prefix_len = 0
    for word_a, word_b in zip(words_a, words_b):
        if word_a != word_b:
            break
        prefix_len += 1

    if prefix_len != len(words_a) - 1:
        return False

    last_a = words_a[-1]
    last_b = words_b[-1]
    if last_a == last_b:
        return False
    return similarity(last_a, last_b) < _ASCII_SUFFIX_TYPO_THRESHOLD


def texts_are_similar(a: str, b: str, threshold: float) -> bool:
    """Shared fuzzy duplicate check for display-layer and batch cleaning."""
    if a == b:
        return True
    if (
        _is_ascii_space_phrase(a)
        and _is_ascii_space_phrase(b)
        and _ascii_trailing_words_clearly_distinct(a, b)
    ):
        return False
    return similarity(a, b) > threshold


def is_duplicate_in_recent(
    content: str,
    recent: deque[str],
    recent_exact_set: set[str],
    config,
    *,
    threshold_fallback: float = _DEDUP_THRESHOLD_FALLBACK,
) -> bool:
    """横向/悬浮窗共用：exact_set → 长度剪枝 → Levenshtein。"""
    profile = dedup_profile_enabled()
    started = time.perf_counter_ns() if profile else 0
    match_type = ""
    threshold = config.get_float("dedup_threshold", threshold_fallback)

    if content in recent_exact_set:
        if profile:
            _dedup_profile_stats.exact_set_hits += 1
        match_type = "exact_set_hit"
        result = True
    elif not recent:
        result = False
    else:
        result = False
        for prev in recent:
            if content == prev:
                match_type = "exact_window_hit"
                result = True
                break
            if threshold >= 1.0:
                continue
            len_diff = abs(len(content) - len(prev))
            max_len = max(len(content), len(prev))
            if max_len > 0 and len_diff / max_len > (1 - threshold):
                if profile:
                    _dedup_profile_stats.length_pruned += 1
                continue
            if texts_are_similar(content, prev, threshold):
                match_type = "similarity_hit"
                result = True
                break

    _last_duplicate_observation.update(
        {
            "content": content,
            "match_type": match_type,
            "threshold": threshold,
            "result": result,
        }
    )

    if profile:
        _dedup_profile_stats.duplicate_checks += 1
        if result:
            _dedup_profile_stats.duplicate_hits += 1
            if match_type == "similarity_hit":
                _dedup_profile_stats.similarity_hits += 1
        _dedup_profile_stats.is_duplicate_ns += time.perf_counter_ns() - started
    return result


__all__ = [
    "DedupProfileStats",
    "dedup_profile_enabled",
    "reset_dedup_profile_for_tests",
    "snapshot_dedup_profile",
    "log_dedup_profile_summary",
    "get_last_duplicate_observation",
    "is_duplicate_in_recent",
    "similarity",
    "texts_are_similar",
]
