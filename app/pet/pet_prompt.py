"""Append desktop-pet command blocks to visual AI prompts (user + system)."""

from __future__ import annotations

from app.translations import Translator

PET_COMMAND_BLOCK_TEMPLATE = (
    "【桌宠观众指令 · 本批优先】\n"
    "用户刚刚通过桌宠输入了以下内容。本批弹幕必须同时回应这条指令与当前截图画面，"
    "不能只评论画面而忽略指令。\n"
    "指令内容：\n"
    "{command_text}\n\n"
    "请注意：\n"
    "- 至少半数弹幕要围绕或呼应这条指令（可用同义、拆句、接梗等方式，短句口语化）。\n"
    "- 其余弹幕结合当前画面细节，把指令主题自然带入场景（例如问候配画面氛围、吐槽配画面元素）。\n"
    "- 若指令是问候、口号或情绪句，允许输出相近的弹幕句式，让观众能感知到用户在说什么。\n"
    "- 不要输出解释；仍只输出符合 DanmuAI 弹幕格式的 JSON 字符串数组。\n"
    "- 仍遵守字数、数量、风格、去重和安全限制。"
)

PET_COMMAND_BLOCK_TEMPLATE_EN = (
    "[Desktop pet viewer command · priority this batch]\n"
    "The user just sent the following via the desktop pet. This batch must respond to "
    "both this command and the current screenshot — do not comment on the screen alone "
    "while ignoring the command.\n"
    "Command:\n"
    "{command_text}\n\n"
    "Notes:\n"
    "- At least half the danmu should echo or riff on this command (synonyms, split "
    "phrases, callbacks — short and colloquial).\n"
    "- The rest should weave the command theme into on-screen details (greetings match "
    "the mood, roasts match visible elements).\n"
    "- For greetings, slogans, or mood lines, similar phrasing is fine so viewers sense "
    "what the user said.\n"
    "- No explanations; output only a JSON string array in DanmuAI danmu format.\n"
    "- Still obey length, count, style, dedup, and safety limits."
)

PET_COMMAND_SYSTEM_LINE_TEMPLATE = (
    "[桌宠指令：{command_text}；本批须同时回应此指令与当前画面，指令主题不可忽视，"
    "不可只评论画面]"
)

PET_COMMAND_SYSTEM_LINE_TEMPLATE_EN = (
    "[Pet command: {command_text}; this batch must respond to this command and the "
    "current screen — the command theme must not be ignored; do not comment on screen only]"
)


def _pet_command_block_template() -> str:
    if Translator.get_language() == "en":
        return PET_COMMAND_BLOCK_TEMPLATE_EN
    return PET_COMMAND_BLOCK_TEMPLATE


def _pet_command_system_line_template() -> str:
    if Translator.get_language() == "en":
        return PET_COMMAND_SYSTEM_LINE_TEMPLATE_EN
    return PET_COMMAND_SYSTEM_LINE_TEMPLATE


def build_pet_command_user_pt(user_pt: str, command_text: str) -> str:
    block = _pet_command_block_template().format(command_text=(command_text or "").strip())
    base = (user_pt or "").rstrip()
    if not base:
        return block
    return f"{base}\n\n{block}"


def append_pet_command_to_system_pt(system_pt: str, command_text: str) -> str:
    """Raise pet-command priority in system prompt for this visual request only."""
    cleaned = (command_text or "").strip()
    if not cleaned:
        return system_pt
    suffix = _pet_command_system_line_template().format(command_text=cleaned)
    base = (system_pt or "").rstrip()
    if not base:
        return suffix
    return f"{base}\n{suffix}"
