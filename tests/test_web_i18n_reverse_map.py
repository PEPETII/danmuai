"""Reverse-map coverage for Web locale zh/en bidirectional i18n."""

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


def _load_lang(lang: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for shard in SHARDS:
        path = LOCALES / lang / f"{shard}.json"
        merged.update(_flatten(json.loads(path.read_text(encoding="utf-8"))))
    return merged


def _build_reverse_map(*dicts: dict[str, str]) -> dict[str, str]:
    """Mirror web/static/modules/i18n.js rebuildSourceTextToKey()."""
    out: dict[str, str] = {}
    for d in dicts:
        for key, text in d.items():
            trimmed = str(text or "").strip()
            if trimmed and trimmed not in out:
                out[trimmed] = key
    return out


def test_reverse_map_covers_all_zh_and_en_values():
    zh = _load_lang("zh")
    en = _load_lang("en")
    assert zh.keys() == en.keys(), "zh/en key parity required for reverse map test"
    reverse = _build_reverse_map(zh, en)
    missing_zh: list[str] = []
    missing_en: list[str] = []
    for key, text in zh.items():
        trimmed = text.strip()
        if trimmed and trimmed not in reverse:
            missing_zh.append(key)
    for key, text in en.items():
        trimmed = text.strip()
        if trimmed and trimmed not in reverse:
            missing_en.append(key)
    assert not missing_zh, f"zh values missing from reverse map: {missing_zh[:10]}"
    assert not missing_en, f"en values missing from reverse map: {missing_en[:10]}"


def test_reverse_map_resolves_cross_language_samples():
    zh = _load_lang("zh")
    en = _load_lang("en")
    reverse = _build_reverse_map(zh, en)
    samples = [
        ("nav.overview", "温馨控制台", "Dashboard"),
        ("settings.text.API_与模型", "API 与模型", "API & model"),
        ("common.darkMode", "黑夜模式", "Dark mode"),
    ]
    for key, zh_text, en_text in samples:
        assert zh[key] == zh_text
        assert en[key] == en_text
        assert reverse[zh_text.strip()] == key
        assert reverse[en_text.strip()] == key
