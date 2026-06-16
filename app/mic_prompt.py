"""Prompt helpers when microphone insert mode is enabled.

``build_mic_insert_user_pt`` 把麦克风插入说明拼到用户提示词末尾，告诉 AI
「用户刚说完一句话，请同时回应语音和截图」。仅在 ``mic_mode_enabled`` 与
``model_supports_mic_audio`` 同时为真时由 ``_trigger_mic_api_call`` 调用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config_defaults import (
    DEFAULT_MIC_INSERT_REPLY_COUNT,
    DEFAULT_MIC_INSERT_VOICE_REPLY_COUNT,
)
from app.personae import NORMAL_REPLY_COUNT_MAX, NORMAL_REPLY_COUNT_MIN

if TYPE_CHECKING:
    from app.config_store import ConfigStore


def _mic_insert_counts_from_config(config: "ConfigStore | None") -> tuple[int, int]:
    if config is None:
        return DEFAULT_MIC_INSERT_REPLY_COUNT, DEFAULT_MIC_INSERT_VOICE_REPLY_COUNT
    try:
        x = int(config.get("mic_insert_reply_count", str(DEFAULT_MIC_INSERT_REPLY_COUNT)))
    except (TypeError, ValueError):
        x = DEFAULT_MIC_INSERT_REPLY_COUNT
    x = max(NORMAL_REPLY_COUNT_MIN, min(x, NORMAL_REPLY_COUNT_MAX))
    try:
        y = int(config.get("mic_insert_voice_reply_count", str(DEFAULT_MIC_INSERT_VOICE_REPLY_COUNT)))
    except (TypeError, ValueError):
        y = DEFAULT_MIC_INSERT_VOICE_REPLY_COUNT
    y = max(0, min(y, x))
    return x, y


def _build_mic_insert_block(x: int, y: int) -> str:
    prefix = "【麦克风插入】用户刚说完一句话，附带了真实语音。"
    count_line = f"请生成 {x}条 JSON 数组弹幕。"

    if y == 0:
        voice_part = (
            "不强制要求某几条必须回应语音，但可以自然参考用户刚才说话内容；"
            "其余弹幕可结合截图氛围。"
        )
        footer = "若语音与截图无关，仍要体现听到了用户说话，不要只描述截图。"
    elif y == x:
        voice_part = (
            f"全部 {x} 条弹幕都需要直接回应用户刚才说了什么"
            "（复述要点、接话、提问或吐槽均可），可同时结合截图氛围。"
        )
        footer = ""
    else:
        rest = x - y
        voice_part = (
            f"前{y}条必须直接回应用户刚才说了什么（复述要点、接话、提问或吐槽均可）；"
            f"其余 {rest} 条可结合截图氛围。"
        )
        footer = (
            f"若语音与截图无关，仍要在前 {y} 条体现听到了用户说话，不要只描述截图。"
        )

    parts = [prefix, count_line, voice_part]
    if footer:
        parts.append(footer)
    return "".join(parts)


def build_mic_insert_user_pt(user_pt: str, config: "ConfigStore | None" = None) -> str:
    x, y = _mic_insert_counts_from_config(config)
    block = _build_mic_insert_block(x, y)
    base = (user_pt or "").rstrip()
    if not base:
        return block
    return f"{base}\n\n{block}"
