from __future__ import annotations

from pathlib import Path
import re


STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
SETTINGS_HTML = STATIC_ROOT / "partials" / "settings.html"


def _danmu_tab_html() -> str:
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    start = html.index('id="settingsTab-danmu"')
    end = html.index('id="settingsTab-capture"', start)
    return html[start:end]


def test_danmu_accordion_wraps_only_target_sections():
    section = _danmu_tab_html()

    assert section.count('data-settings-rhythm-accordion') == 1
    assert 'id="settingsDanmuBatchAccordionTrigger"' in section
    assert 'id="settingsDanmuAppearanceAccordionTrigger"' in section
    assert 'id="settingsDanmuScrollingAccordionTrigger"' in section
    assert 'id="normalModeOptions"' in section
    assert 'id="scrollingModeFields"' in section
    assert 'id="danmu_render_mode"' in section
    assert section.index('id="danmu_render_mode"') < section.index('data-settings-rhythm-accordion')


def test_danmu_accordion_preserves_field_ids_and_aria():
    section = _danmu_tab_html()

    for field_id in (
        "normal_recognition_interval_sec",
        "normal_reply_count",
        "danmu_max_chars",
        "dedup_threshold",
        "reply_queue_max_items",
        "danmu_speed",
        "opacity",
        "hotkey",
        "eviction_mode",
        "danmu_pending_entry_cap",
        "danmu_track_retention_cap",
        "empty_accel",
    ):
        assert f'id="{field_id}"' in section
        assert section.count(f'id="{field_id}"') == 1

    # 默认全部折叠：用户未点击前不自动展开首项
    assert 'aria-expanded="true"' not in section
    assert 'settings-rhythm-accordion-item is-open' not in section
    assert re.search(r'id="settingsDanmuBatchAccordionPanel"[^>]*\bhidden\b', section)
    assert re.search(r'id="settingsDanmuAppearanceAccordionPanel"[^>]*\bhidden\b', section)
    assert re.search(r'id="settingsDanmuScrollingAccordionPanel"[^>]*\bhidden\b', section)
    assert 'aria-controls="settingsDanmuBatchAccordionPanel"' in section
    assert 'aria-labelledby="settingsDanmuBatchAccordionTrigger"' in section