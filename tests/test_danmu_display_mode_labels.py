"""Regression checks for the user-facing danmu display-mode names."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web" / "static"


def _load_locale(lang: str, shard: str) -> str:
    path = STATIC / "locales" / lang / f"{shard}.json"
    return path.read_text(encoding="utf-8")


def test_display_mode_labels_are_vertical_danmu_without_changing_backend_values():
    overview = (STATIC / "partials" / "overview.html").read_text(encoding="utf-8")
    settings = (STATIC / "partials" / "settings.html").read_text(encoding="utf-8")
    style_generator = (STATIC / "partials" / "style-generator.html").read_text(encoding="utf-8")

    assert 'value="floating_panel" data-i18n="settings.text.竖向弹幕">竖向弹幕</option>' in overview
    assert 'name="danmu_render_mode"' in settings
    assert 'value="floating_panel" data-i18n="settings.text.竖向弹幕">竖向弹幕</option>' in settings
    assert 'data-sg-tab="bottom-up"' in style_generator
    assert "竖向弹幕模式" in style_generator
    assert "从下到上" not in overview + settings + style_generator

    zh_settings = json.loads(_load_locale("zh", "settings"))
    en_settings = json.loads(_load_locale("en", "settings"))
    zh_content = json.loads(_load_locale("zh", "content"))
    en_content = json.loads(_load_locale("en", "content"))
    zh_dynamic = json.loads(_load_locale("zh", "dynamic"))
    en_dynamic = json.loads(_load_locale("en", "dynamic"))

    assert zh_settings["settings"]["text"]["竖向弹幕"] == "竖向弹幕"
    assert en_settings["settings"]["text"]["竖向弹幕"] == "Vertical danmu"
    assert zh_content["content"]["text"]["竖向弹幕模式"] == "竖向弹幕模式"
    assert en_content["content"]["text"]["竖向弹幕模式"] == "Vertical danmu"
    assert "竖向弹幕" in zh_dynamic["dynamic"]["settingsHints"]["竖向弹幕模式窗口宽度_200_800_px_默"]
    assert "Vertical danmu" in en_dynamic["dynamic"]["settingsHints"]["竖向弹幕模式窗口宽度_200_800_px_默"]


def test_ai_model_configuration_uses_danmu_display_labels():
    settings = (STATIC / "partials" / "settings.html").read_text(encoding="utf-8")

    assert ">弹幕展示方式</label>" in settings
    assert ">弹幕显示器</label>" in settings
    assert ">弹幕显示模式</label>" not in settings
    assert ">识图显示器</label>" not in settings
