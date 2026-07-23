"""WS message protocol contract for floating panel web."""

from __future__ import annotations

import pytest

from app.floating_panel_web.panel_protocol import (
    CLEAR_REASONS,
    AuthMessage,
    CardMessage,
    ClearMessage,
    ConfigMessage,
    ErrorMessage,
    GetStateMessage,
    PingMessage,
    PongMessage,
    ReloadMessage,
    StateReportMessage,
    UserEventMessage,
    parse_message,
)


def test_card_message_fields():
    msg = CardMessage(
        id="c1",
        username="AI 管家",
        content="你好",
        persona_id="butler",
        timestamp=123,
    )
    data = msg.to_dict()
    for key in ("type", "id", "username", "content", "persona_id", "style", "timestamp"):
        assert key in data
    assert data["type"] == "card"
    parsed = CardMessage.from_mapping(data)
    assert parsed.id == "c1"
    assert parsed.content == "你好"
    style_dict = parsed.style.to_dict()
    assert "card_bg" in style_dict
    # 扩展字段
    assert "shape" in style_dict
    assert "card_opacity" in style_dict
    assert "tail_enabled" in style_dict
    assert "username_enabled" in style_dict
    assert "padding_x" in style_dict


def test_config_message_fields():
    msg = ConfigMessage()
    data = msg.to_dict()
    for key in (
        "max_cards",
        "stack_gap",
        "panel_padding",
        "entry_duration_ms",
        "exit_duration_ms",
        "panel_position",
        "panel_width",
        "panel_height",
        "panel_opacity",
    ):
        assert key in data
    assert ConfigMessage.from_mapping(data).max_cards == 6
    assert data["panel_opacity"] == 85
    # 旧消息缺 panel_opacity 应默认
    old = dict(data)
    del old["panel_opacity"]
    parsed = ConfigMessage.from_mapping(old)
    assert parsed.panel_opacity == 85


def test_clear_message_reason_enum():
    for reason in CLEAR_REASONS:
        msg = ClearMessage.from_mapping({"type": "clear", "reason": reason})
        assert msg.reason == reason
    with pytest.raises(ValueError):
        ClearMessage.from_mapping({"type": "clear", "reason": "other"})


def test_ping_pong_timestamp():
    ping = PingMessage.from_mapping({"type": "ping", "t": 1.5})
    pong = PongMessage.from_mapping({"type": "pong", "t": 2})
    assert isinstance(ping.t, float)
    assert isinstance(pong.t, float)
    with pytest.raises(ValueError):
        PingMessage.from_mapping({"type": "ping", "t": "x"})


def test_state_report_required_fields():
    data = {
        "type": "state-report",
        "cardsCount": 1,
        "cardInfo": {"transform": "none"},
        "bodyBg": "rgba(0, 0, 0, 0)",
        "htmlBg": "rgba(0, 0, 0, 0)",
        "panelBg": "rgba(0, 0, 0, 0)",
        "animationFrame": 3,
        "wsReceived": 2,
        "wsOpen": True,
        "timestamp": 99,
    }
    msg = StateReportMessage.from_mapping(data)
    out = msg.to_dict()
    for key in (
        "cardsCount",
        "cardInfo",
        "bodyBg",
        "htmlBg",
        "panelBg",
        "animationFrame",
        "wsReceived",
        "wsOpen",
        "timestamp",
    ):
        assert key in out


def test_auth_message_format():
    msg = AuthMessage.from_mapping({"type": "auth", "token": "abc"})
    assert msg.token == "abc"
    with pytest.raises(ValueError):
        AuthMessage.from_mapping({"type": "auth", "token": "  "})


def test_user_event_optional_fields():
    msg = UserEventMessage.from_mapping({"type": "user-event", "event": "card-clicked"})
    assert msg.event == "card-clicked"
    assert msg.card_id is None
    msg2 = UserEventMessage.from_mapping(
        {"type": "user-event", "event": "card-clicked", "cardId": "c1"}
    )
    assert msg2.card_id == "c1"
    with pytest.raises(ValueError):
        UserEventMessage.from_mapping({"type": "user-event", "event": ""})


def test_error_message_stack_optional():
    msg = ErrorMessage.from_mapping({"type": "error", "message": "boom"})
    assert msg.stack is None
    msg2 = ErrorMessage.from_mapping(
        {"type": "error", "message": "boom", "stack": "trace"}
    )
    assert msg2.stack == "trace"


def test_reload_message_no_payload():
    msg = ReloadMessage.from_mapping({"type": "reload"})
    assert msg.to_dict() == {"type": "reload"}
    assert parse_message({"type": "get-state"}).to_dict() == GetStateMessage().to_dict()
