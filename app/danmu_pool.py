"""Built-in danmu text pool (curated from DDmkTCCorpus + formula doc)."""

from __future__ import annotations

import json
import random
from functools import lru_cache

from app.bundle_paths import resource_path

_DATA_DIR = resource_path("data")
_POOL_PATH = _DATA_DIR / "danmu_pool_zh.json"
_BOOTSTRAP_PATH = _DATA_DIR / "danmu_pool_zh_bootstrap.txt"
_POOL_VERSION = 1


def danmu_pool_enabled_from_config(config) -> bool:
    """True when local formula pool is enabled (default on if unset)."""
    raw = config.get("danmu_pool_enabled", "")
    if raw in ("", None):
        return True
    return str(raw).strip() != "0"


def pool_enabled(config) -> bool:
    """Respect danmu_pool_enabled; None config keeps legacy test behavior (enabled)."""
    if config is None:
        return True
    return danmu_pool_enabled_from_config(config)


def load_danmu_pool_for_config(config) -> list[str]:
    if not pool_enabled(config):
        return []
    return load_danmu_pool()


def sample_danmu_for_config(
    config,
    count: int,
    *,
    rng: random.Random | None = None,
) -> list[str]:
    if not pool_enabled(config) or count <= 0:
        return []
    return sample_danmu(count, rng=rng)


def _dedupe_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


@lru_cache(maxsize=1)
def load_danmu_pool() -> list[str]:
    if _POOL_PATH.is_file():
        try:
            payload = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            items = payload.get("items")
            if isinstance(items, list) and items:
                return _dedupe_lines(items)
        elif isinstance(payload, list) and payload:
            return _dedupe_lines(payload)

    if _BOOTSTRAP_PATH.is_file():
        try:
            lines = _BOOTSTRAP_PATH.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        if lines:
            return _dedupe_lines(lines)
    return []


def pool_size() -> int:
    return len(load_danmu_pool())


def sample_danmu(count: int, *, rng: random.Random | None = None) -> list[str]:
    pool = load_danmu_pool()
    if not pool or count <= 0:
        return []
    rng = rng or random
    if count >= len(pool):
        return rng.sample(pool, len(pool))
    return rng.sample(pool, count)


def pool_metadata() -> dict:
    if not _POOL_PATH.is_file():
        return {"version": _POOL_VERSION, "count": 0, "path": str(_POOL_PATH)}
    try:
        payload = json.loads(_POOL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "version": payload.get("version", _POOL_VERSION),
        "count": pool_size(),
        "target": payload.get("target"),
        "sources": payload.get("sources"),
        "path": str(_POOL_PATH),
    }
