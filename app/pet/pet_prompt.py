"""Append desktop-pet temporary command block to the visual user prompt."""

from __future__ import annotations

PET_COMMAND_BLOCK_TEMPLATE = (
    "【桌宠临时指令】\n"
    "用户刚刚通过桌宠输入了以下临时要求。请把它当作下一批弹幕的方向参考，而不是聊天请求。\n"
    "指令内容：\n"
    "{command_text}\n\n"
    "请注意：\n"
    "- 不要直接复述这句话。\n"
    "- 不要输出解释。\n"
    "- 仍然只输出符合 DanmuAI 弹幕格式的内容。\n"
    "- 仍然遵守字数、数量、风格、去重和安全限制。\n"
    "- 如果当前截图内容与该指令冲突，以当前截图和主规则为准。"
)


def build_pet_command_user_pt(user_pt: str, command_text: str) -> str:
    block = PET_COMMAND_BLOCK_TEMPLATE.format(command_text=(command_text or "").strip())
    base = (user_pt or "").rstrip()
    if not base:
        return block
    return f"{base}\n\n{block}"
