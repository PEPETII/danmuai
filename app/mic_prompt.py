"""Prompt helpers when microphone insert mode is enabled.

``build_mic_insert_user_pt`` 把麦克风插入说明拼到用户提示词末尾，告诉 AI
「用户刚说完一句话，请同时回应语音和截图」。仅在 ``mic_mode_enabled`` 与
``model_supports_mic_audio`` 同时为真时由 ``_trigger_mic_api_call`` 调用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.personae import normal_reply_count_from_config

if TYPE_CHECKING:
    from app.config_store import ConfigStore


def mic_insert_reply_count(config: "ConfigStore | None" = None) -> int:
    """麦克风插入条数契约与普通回复总条数保持一致，不单独引入配置键。"""
    return normal_reply_count_from_config(config)


def _build_mic_insert_block(reply_count: int) -> str:
    return (
        f"【麦克风插入】用户刚说完一句话，附带了真实语音。请生成 {reply_count} 条 JSON 数组弹幕。\n"
        f"这 {reply_count} 条弹幕必须全部同时结合当前画面与用户刚才说话内容，把用户说话内容优化成适合直播弹幕展示的短句。\n"
        "每一条都要既体现听到了用户说话，又贴合当前画面氛围。\n"
        "不要只复述语音，也不要只描述截图。\n"
        "表达要自然、口语化、像真实观众弹幕，可以接话、提问、吐槽、补充或玩梗。\n"
        "每条尽量短，不要解释，不要输出多余内容，只输出 JSON 字符串数组。"
    )


def build_mic_insert_user_pt(user_pt: str, config: "ConfigStore | None" = None) -> str:
    reply_count = mic_insert_reply_count(config)
    block = _build_mic_insert_block(reply_count)
    base = (user_pt or "").rstrip()
    if not base:
        return block
    return f"{base}\n\n{block}"
