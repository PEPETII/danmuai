import os
import time  # noqa: F401 — used as danmu_engine_dedup.time from app.danmu_engine
from dataclasses import dataclass

_LEVENSHTEIN_RATIO = None
_LEVENSHTEIN_UNAVAILABLE = object()
_DEDUP_PROFILE_FLAG: bool | None = None


@dataclass
class DedupProfileStats:
    duplicate_checks: int = 0
    duplicate_hits: int = 0
    exact_set_hits: int = 0
    length_pruned: int = 0
    similarity_calls: int = 0
    similarity_fallback_calls: int = 0
    is_duplicate_ns: int = 0
    similarity_ns: int = 0


_dedup_profile_stats = DedupProfileStats()


def dedup_profile_enabled() -> bool:
    global _DEDUP_PROFILE_FLAG
    if _DEDUP_PROFILE_FLAG is None:
        value = os.environ.get("DANMU_DEDUP_PROFILE", "").strip().lower()
        _DEDUP_PROFILE_FLAG = value in ("1", "true", "yes", "on")
    return _DEDUP_PROFILE_FLAG


def reset_dedup_profile_for_tests(clear_env_cache: bool = True) -> None:
    global _DEDUP_PROFILE_FLAG, _dedup_profile_stats
    if clear_env_cache:
        _DEDUP_PROFILE_FLAG = None
    _dedup_profile_stats = DedupProfileStats()


def snapshot_dedup_profile() -> dict:
    stats = _dedup_profile_stats
    checks = max(stats.duplicate_checks, 1)
    similarity_calls = max(stats.similarity_calls, 1)
    return {
        "enabled": dedup_profile_enabled(),
        "duplicate_checks": stats.duplicate_checks,
        "duplicate_hits": stats.duplicate_hits,
        "exact_set_hits": stats.exact_set_hits,
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


def _get_levenshtein_ratio():
    global _LEVENSHTEIN_RATIO
    if _LEVENSHTEIN_RATIO is None:
        try:
            from Levenshtein import ratio as _ratio

            _LEVENSHTEIN_RATIO = _ratio
        except ImportError:
            _LEVENSHTEIN_RATIO = _LEVENSHTEIN_UNAVAILABLE
    if _LEVENSHTEIN_RATIO is _LEVENSHTEIN_UNAVAILABLE:
        return None
    return _LEVENSHTEIN_RATIO


__all__ = [
    "DedupProfileStats",
    "dedup_profile_enabled",
    "reset_dedup_profile_for_tests",
    "snapshot_dedup_profile",
    "log_dedup_profile_summary",
]
