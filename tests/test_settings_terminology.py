"""Regression checks for the current user-facing settings vocabulary."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"


def _load_locale(lang: str, shard: str) -> dict:
    path = STATIC / "locales" / lang / f"{shard}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _leaf_values(node: object) -> list[str]:
    if isinstance(node, dict):
        values: list[str] = []
        for value in node.values():
            values.extend(_leaf_values(value))
        return values
    return [node] if isinstance(node, str) else []


def test_settings_has_five_categories_and_auto_save_guidance():
    sidebar = (STATIC / "partials" / "sidebar.html").read_text(encoding="utf-8")
    settings = (STATIC / "partials" / "settings.html").read_text(encoding="utf-8")
    tab_ids = re.findall(r'data-settings-tab="([^"]+)"', settings)

    assert tab_ids == ["api", "danmu", "capture", "mic", "danmu-read"]
    assert "5 个分类" in sidebar
    assert "AI 模型、弹幕生成与显示、AI 看哪里、语音输入、AI 播报" in sidebar
    assert "更改会自动保存" in sidebar
    assert "更改会自动保存" in settings
    assert "修改设置后请等状态显示「已自动保存」再测" in settings
    assert "定时朗读会在设置自动保存后，开始生成才会工作" in settings
    assert 'data-i18n="settings.text.语音输入">语音输入' in settings
    assert 'data-i18n="settings.text.AI播报">AI 播报' in settings

    stale_sidebar_copy = (
        "六个分页",
        "保存配置」立即生效",
        "API 与模型、麦克风模式、AI读弹幕、弹幕显示、AI识图相关、字体设置",
    )
    assert not any(text in sidebar for text in stale_sidebar_copy)
    assert "保存后立即生效" not in settings
    assert "请先点「保存配置」再测" not in settings
    assert "定时朗读须保存并开始生成" not in settings


def test_settings_terminology_is_translated_in_both_locale_shards():
    zh_nav = _load_locale("zh", "nav")
    en_nav = _load_locale("en", "nav")
    zh_settings = _load_locale("zh", "settings")
    en_settings = _load_locale("en", "settings")

    assert zh_nav["nav"]["tooltipTabsTitle"] == "5 个分类"
    assert en_nav["nav"]["tooltipTabsTitle"] == "Five categories"
    assert any("更改会自动保存" in text for text in _leaf_values(zh_nav))
    assert any("changes save automatically" in text for text in _leaf_values(en_nav))
    assert "Voice input" in _leaf_values(en_settings)
    assert "AI broadcast" in _leaf_values(en_settings)
    assert "语音输入（实验）" in _leaf_values(zh_settings)
    assert "麦克风模式（实验）" not in _leaf_values(zh_settings)
    assert "保存后立即生效" not in _leaf_values(zh_settings)
    assert "Save settings first" not in _leaf_values(en_settings)
