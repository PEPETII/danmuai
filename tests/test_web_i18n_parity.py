"""Web locale JSON parity between zh and en shards."""

from __future__ import annotations

import json
from pathlib import Path

LOCALES = Path(__file__).resolve().parents[1] / "web" / "static" / "locales"
SHARDS = [
    "common",
    "nav",
    "overview",
    "settings",
    "content",
    "modals",
    "hints",
    "dynamic",
]


def _flatten(obj: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in obj.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            out.update(_flatten(val, full))
        else:
            out[full] = str(val)
    return out


def _load_shard(lang: str, name: str) -> dict[str, str]:
    path = LOCALES / lang / f"{name}.json"
    return _flatten(json.loads(path.read_text(encoding="utf-8")))


def test_zh_en_locale_key_parity():
    zh_keys: set[str] = set()
    en_keys: set[str] = set()
    for shard in SHARDS:
        zh_keys.update(_load_shard("zh", shard))
        en_keys.update(_load_shard("en", shard))
    missing_in_en = zh_keys - en_keys
    missing_in_zh = en_keys - zh_keys
    assert not missing_in_en, f"en missing keys: {sorted(missing_in_en)[:20]}"
    assert not missing_in_zh, f"zh missing keys: {sorted(missing_in_zh)[:20]}"


def test_en_locale_has_no_cjk():
    import re

    cjk = re.compile(r"[\u4e00-\u9fff]")
    bad: list[str] = []
    for shard in SHARDS:
        for key, val in _load_shard("en", shard).items():
            if cjk.search(val):
                bad.append(f"{shard}:{key}={val[:40]}")
    assert not bad, f"EN locale contains CJK: {bad[:10]}"
