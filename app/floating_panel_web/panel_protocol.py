"""浮动面板 WebSocket 消息协议（服务端 ↔ 页面）。

字段契约见 docs/floating_panel_web/PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md §4。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping

CLEAR_REASONS = frozenset({"config_changed", "user_action", "scene_reset"})

ClearReason = Literal["config_changed", "user_action", "scene_reset"]


@dataclass(frozen=True)
class CardStyle:
    card_bg: str = "#fff7ed"
    card_border: str = "#fbbf24"
    username_color: str = "#f59e0b"
    content_color: str = "#1f2937"
    outline_color: str = "#ffffff"
    font_family: str = "Microsoft YaHei, PingFang SC, sans-serif"
    font_size_username: int = 12
    font_size_content: int = 14
    border_radius: int = 12
    max_width: int = 280
    box_shadow: str = (
        "0 2px 4px rgba(0,0,0,0.10), "
        "0 4px 8px rgba(0,0,0,0.08), "
        "0 8px 16px rgba(0,0,0,0.06)"
    )
    # === 新增字段（向后兼容，缺省有默认值） ===
    shape: str = "bubble"
    card_opacity: int = 88
    border_enabled: bool = False
    border_width: int = 1
    border_opacity: int = 40
    outline_enabled: bool = False
    outline_width: int = 2
    shadow_enabled: bool = True
    padding_x: int = 14
    padding_y: int = 10
    tail_enabled: bool = True
    tail_style: str = "round"
    tail_width: int = 8
    tail_height: int = 10
    tail_offset_y: int = 38
    username_enabled: bool = True
    username_weight: int = 700
    username_separator: str = "："
    content_weight: int = 400
    content_line_height: int = 140
    gap_username_content: int = 4
    font_bold: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> CardStyle:
        if not data:
            return cls()
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        kwargs = {k: data[k] for k in known if k in data}
        return cls(**kwargs)


@dataclass(frozen=True)
class CardMessage:
    id: str
    username: str
    content: str
    persona_id: str = ""
    style: CardStyle = field(default_factory=CardStyle)
    timestamp: int = 0
    type: Literal["card"] = "card"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "username": self.username,
            "content": self.content,
            "persona_id": self.persona_id,
            "style": self.style.to_dict() if isinstance(self.style, CardStyle) else dict(self.style),
            "timestamp": int(self.timestamp or _now_ms()),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> CardMessage:
        require_keys(data, ("type", "id", "username", "content"))
        if data.get("type") != "card":
            raise ValueError("type must be 'card'")
        return cls(
            id=str(data["id"]),
            username=str(data["username"]),
            content=str(data["content"]),
            persona_id=str(data.get("persona_id") or ""),
            style=CardStyle.from_mapping(data.get("style") if isinstance(data.get("style"), Mapping) else None),
            timestamp=int(data.get("timestamp") or _now_ms()),
        )


@dataclass(frozen=True)
class ConfigMessage:
    max_cards: int = 6
    stack_gap: int = 8
    panel_padding: int = 16
    entry_duration_ms: int = 250
    exit_duration_ms: int = 250
    panel_position: str = "bottom-left"
    panel_width: int = 360
    panel_height: int = 600
    panel_opacity: int = 85
    type: Literal["config"] = "config"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "max_cards": int(self.max_cards),
            "stack_gap": int(self.stack_gap),
            "panel_padding": int(self.panel_padding),
            "entry_duration_ms": int(self.entry_duration_ms),
            "exit_duration_ms": int(self.exit_duration_ms),
            "panel_position": str(self.panel_position),
            "panel_width": int(self.panel_width),
            "panel_height": int(self.panel_height),
            "panel_opacity": int(self.panel_opacity),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ConfigMessage:
        require_keys(
            data,
            (
                "type",
                "max_cards",
                "stack_gap",
                "panel_padding",
                "entry_duration_ms",
                "exit_duration_ms",
                "panel_position",
                "panel_width",
                "panel_height",
            ),
        )
        if data.get("type") != "config":
            raise ValueError("type must be 'config'")
        return cls(
            max_cards=int(data["max_cards"]),
            stack_gap=int(data["stack_gap"]),
            panel_padding=int(data["panel_padding"]),
            entry_duration_ms=int(data["entry_duration_ms"]),
            exit_duration_ms=int(data["exit_duration_ms"]),
            panel_position=str(data["panel_position"]),
            panel_width=int(data["panel_width"]),
            panel_height=int(data["panel_height"]),
            panel_opacity=int(data.get("panel_opacity", 85)),
        )


@dataclass(frozen=True)
class ClearMessage:
    reason: ClearReason
    type: Literal["clear"] = "clear"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "reason": self.reason}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ClearMessage:
        require_keys(data, ("type", "reason"))
        if data.get("type") != "clear":
            raise ValueError("type must be 'clear'")
        reason = str(data["reason"])
        if reason not in CLEAR_REASONS:
            raise ValueError(f"clear.reason must be one of {sorted(CLEAR_REASONS)}")
        return cls(reason=reason)  # type: ignore[arg-type]


@dataclass(frozen=True)
class PingMessage:
    t: float
    type: Literal["ping"] = "ping"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "t": self.t}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PingMessage:
        require_keys(data, ("type", "t"))
        if data.get("type") != "ping":
            raise ValueError("type must be 'ping'")
        return cls(t=_as_number(data["t"]))


@dataclass(frozen=True)
class PongMessage:
    t: float
    type: Literal["pong"] = "pong"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "t": self.t}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PongMessage:
        require_keys(data, ("type", "t"))
        if data.get("type") != "pong":
            raise ValueError("type must be 'pong'")
        return cls(t=_as_number(data["t"]))


@dataclass(frozen=True)
class GetStateMessage:
    type: Literal["get-state"] = "get-state"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> GetStateMessage:
        require_keys(data, ("type",))
        if data.get("type") != "get-state":
            raise ValueError("type must be 'get-state'")
        return cls()


@dataclass(frozen=True)
class ReloadMessage:
    type: Literal["reload"] = "reload"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ReloadMessage:
        require_keys(data, ("type",))
        if data.get("type") != "reload":
            raise ValueError("type must be 'reload'")
        return cls()


@dataclass(frozen=True)
class AuthMessage:
    token: str
    type: Literal["auth"] = "auth"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "token": self.token}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> AuthMessage:
        require_keys(data, ("type", "token"))
        if data.get("type") != "auth":
            raise ValueError("type must be 'auth'")
        token = str(data.get("token") or "").strip()
        if not token:
            raise ValueError("auth.token must be a non-empty string")
        return cls(token=token)


@dataclass(frozen=True)
class UserEventMessage:
    event: str
    card_id: str | None = None
    timestamp: int = 0
    type: Literal["user-event"] = "user-event"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "event": self.event,
            "timestamp": int(self.timestamp or _now_ms()),
        }
        if self.card_id is not None:
            payload["cardId"] = self.card_id
        return payload

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> UserEventMessage:
        require_keys(data, ("type", "event"))
        if data.get("type") != "user-event":
            raise ValueError("type must be 'user-event'")
        event = str(data.get("event") or "").strip()
        if not event:
            raise ValueError("user-event.event is required")
        card_id = data.get("cardId")
        return cls(
            event=event,
            card_id=None if card_id is None else str(card_id),
            timestamp=int(data.get("timestamp") or _now_ms()),
        )


@dataclass(frozen=True)
class ErrorMessage:
    message: str
    stack: str | None = None
    timestamp: int = 0
    type: Literal["error"] = "error"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "message": self.message,
            "timestamp": int(self.timestamp or _now_ms()),
        }
        if self.stack is not None:
            payload["stack"] = self.stack
        return payload

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ErrorMessage:
        require_keys(data, ("type", "message"))
        if data.get("type") != "error":
            raise ValueError("type must be 'error'")
        message = str(data.get("message") or "").strip()
        if not message:
            raise ValueError("error.message is required")
        stack = data.get("stack")
        return cls(
            message=message,
            stack=None if stack is None else str(stack),
            timestamp=int(data.get("timestamp") or _now_ms()),
        )


@dataclass(frozen=True)
class StateReportMessage:
    cards_count: int
    body_bg: str
    html_bg: str
    panel_bg: str
    animation_frame: int
    ws_received: int
    ws_open: bool
    card_info: dict[str, Any] | None = None
    timestamp: int = 0
    type: Literal["state-report"] = "state-report"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "cardsCount": int(self.cards_count),
            "cardInfo": self.card_info,
            "bodyBg": self.body_bg,
            "htmlBg": self.html_bg,
            "panelBg": self.panel_bg,
            "animationFrame": int(self.animation_frame),
            "wsReceived": int(self.ws_received),
            "wsOpen": bool(self.ws_open),
            "timestamp": int(self.timestamp or _now_ms()),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> StateReportMessage:
        require_keys(
            data,
            (
                "type",
                "cardsCount",
                "cardInfo",
                "bodyBg",
                "htmlBg",
                "panelBg",
                "animationFrame",
                "wsReceived",
                "wsOpen",
                "timestamp",
            ),
        )
        if data.get("type") != "state-report":
            raise ValueError("type must be 'state-report'")
        card_info = data.get("cardInfo")
        if card_info is not None and not isinstance(card_info, Mapping):
            raise ValueError("state-report.cardInfo must be object or null")
        return cls(
            cards_count=int(data["cardsCount"]),
            card_info=None if card_info is None else dict(card_info),
            body_bg=str(data["bodyBg"]),
            html_bg=str(data["htmlBg"]),
            panel_bg=str(data["panelBg"]),
            animation_frame=int(data["animationFrame"]),
            ws_received=int(data["wsReceived"]),
            ws_open=bool(data["wsOpen"]),
            timestamp=int(data["timestamp"]),
        )


_MESSAGE_PARSERS = {
    "card": CardMessage.from_mapping,
    "config": ConfigMessage.from_mapping,
    "clear": ClearMessage.from_mapping,
    "ping": PingMessage.from_mapping,
    "pong": PongMessage.from_mapping,
    "get-state": GetStateMessage.from_mapping,
    "reload": ReloadMessage.from_mapping,
    "auth": AuthMessage.from_mapping,
    "user-event": UserEventMessage.from_mapping,
    "error": ErrorMessage.from_mapping,
    "state-report": StateReportMessage.from_mapping,
}


def parse_message(data: Mapping[str, Any]) -> Any:
    """Parse a raw WS JSON object into a typed message dataclass."""
    if not isinstance(data, Mapping):
        raise TypeError("message must be a mapping")
    msg_type = data.get("type")
    parser = _MESSAGE_PARSERS.get(str(msg_type or ""))
    if parser is None:
        raise ValueError(f"unknown message type: {msg_type!r}")
    return parser(data)


def require_keys(data: Mapping[str, Any], keys: tuple[str, ...]) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise ValueError(f"missing required fields: {missing}")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _as_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timestamp field must be int or float")
    return float(value)
