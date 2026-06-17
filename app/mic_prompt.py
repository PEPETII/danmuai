"""Prompt helpers when microphone insert mode is enabled.

``build_mic_insert_user_pt`` 把麦克风插入说明拼到用户提示词末尾，告诉 AI
「用户刚说完一句话，请同时回应语音和截图」。仅在 ``mic_mode_enabled`` 与
``model_supports_mic_audio`` 同时为真时由 ``_trigger_mic_api_call`` 调用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config_store import ConfigStore

MIC_INSERT_BLOCK = (
    "【麦克风插入】用户刚说完一句话，附带了真实语音。请生成 6 条 JSON 数组弹幕。\n"
    "这 6 条弹幕必须全部同时结合当前画面与用户刚才说话内容，把用户说话内容优化成适合直播弹幕展示的短句。\n"
    "每一条都要既体现听到了用户说话，又贴合当前画面氛围。\n"
    "不要只复述语音，也不要只描述截图。\n"
    "表达要自然、口语化、像真实观众弹幕，可以接话、提问、吐槽、补充或玩梗。\n"
    "每条尽量短，不要解释，不要输出多余内容，只输出 JSON 字符串数组。"
)


def build_mic_insert_user_pt(user_pt: str, config: "ConfigStore | None" = None) -> str:
    _ = config  # retained for call-site compatibility; insert contract is fixed
    base = (user_pt or "").rstrip()
    if not base:
        return MIC_INSERT_BLOCK
    return f"{base}\n\n{MIC_INSERT_BLOCK}"
