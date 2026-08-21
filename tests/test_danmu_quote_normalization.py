"""W-DANMU-QUOTE-NORMALIZATION-001: 外层包裹引号规范化回归。"""

from __future__ import annotations

import pytest
from app.config_store import ConfigStore
from app.danmu_engine import (
    DanmuEngine,
    normalize_danmu_display_text,
    resolve_danmu_display_text,
)
from app.danmu_text_normalize import strip_outer_wrapping_quotes
from app.reply_parser import normalize_reply_batch, parse_ai_reply_payload

from tests.fakes import FakeConfig


@pytest.fixture()
def engine(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "quote_norm.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    eng = DanmuEngine(store)
    eng.recent.clear()
    eng.recent_exact_set.clear()
    eng.screen_width = 1000.0
    return eng


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("   ", ""),
        ("无引号正文", "无引号正文"),
        ("“这桌宠是真的精致啊”", "这桌宠是真的精致啊"),
        ('  “带问号？”  ', "带问号？"),
        ('"ASCII双引号"', "ASCII双引号"),
        ("'ASCII单引号'", "ASCII单引号"),
        ("“  多层空白  ”", "多层空白"),
        ('"“嵌套外层”"', "嵌套外层"),
        ("他说“好”", "他说“好”"),
        ('版本"V2"已发布', '版本"V2"已发布'),
        ("“只有左引号", "“只有左引号"),
        ("只有右引号”", "只有右引号”"),
        ('"不匹配\'', '"不匹配\''),
    ],
)
def test_strip_outer_wrapping_quotes_cases(raw, expected):
    assert strip_outer_wrapping_quotes(raw) == expected


def test_parse_ai_reply_payload_strips_chinese_wrapped_quotes():
    assert parse_ai_reply_payload('["“第一条”", "第二条"]') == ["第一条", "第二条"]


def test_parse_ai_reply_payload_object_envelope_strips_wrapped_quotes():
    raw = '{"comments": ["“画面相关”", "氛围弹幕"]}'
    assert parse_ai_reply_payload(raw) == ["画面相关", "氛围弹幕"]


def test_parse_ai_reply_payload_plain_text_strips_wrapped_quotes():
    assert parse_ai_reply_payload("“纯文本一行”") == ["纯文本一行"]


def test_parse_ai_reply_payload_malformed_json_strips_wrapped_quotes():
    raw = '{"comments":"“这是啥代码工具？”","弹弹幕好有意思"}'
    items = parse_ai_reply_payload(raw)
    assert items[0] == "这是啥代码工具？"


def test_normalize_reply_batch_strips_wrapped_quotes_before_dedup(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser.pool_enabled",
        lambda _config=None: False,
    )
    items = normalize_reply_batch(["“同一句”", "同一句"], config=FakeConfig())
    assert items == ["同一句"]


def test_normalize_reply_batch_strips_ascii_wrapped_quotes(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser.pool_enabled",
        lambda _config=None: False,
    )
    items = normalize_reply_batch(['"唯一句"'], config=FakeConfig())
    assert items == ["唯一句"]


def test_normalize_danmu_display_text_strips_chinese_wrapped_quotes(engine):
    assert normalize_danmu_display_text("“上屏正文”", engine.config) == "上屏正文"


def test_normalize_danmu_display_text_keeps_internal_quotes(engine):
    assert normalize_danmu_display_text('版本"V2"已发布', engine.config) == '版本"V2"已发布'


def test_resolve_danmu_display_text_strips_wrapped_quotes_with_prefix(engine):
    engine.config.set("persona_name_prefix_enabled", "1")
    assert (
        resolve_danmu_display_text("“你好世界”", engine.config, "吐槽型")
        == "吐槽型：你好世界"
    )


def test_engine_add_text_content_strips_wrapped_quotes(engine):
    item = engine.add_text("“滚动弹幕”")
    assert item is not None
    assert item.content == "滚动弹幕"


def test_floating_panel_add_text_content_strips_wrapped_quotes(floating_panel_setup):
    _store, overlay = floating_panel_setup
    panel_engine = overlay.engine
    item = panel_engine.add_text("“浮动面板正文”", item_height=32.0)
    assert item is not None
    assert item.content == "浮动面板正文"


def test_mic_insert_parse_and_batch_strips_wrapped_quotes(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser.pool_enabled",
        lambda _config=None: False,
    )
    parsed = parse_ai_reply_payload('["“麦克风句”"]')
    assert parsed == ["麦克风句"]
    batched = normalize_reply_batch(parsed, config=FakeConfig())
    assert batched == ["麦克风句"]
