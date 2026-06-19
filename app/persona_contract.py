"""System prompt 契约（人设注入 AI 提示词的接口契约）。

职责：
- 构造/裁剪 AI 的 system prompt 契约段落（``REPLY_CONTRACT_ZH/EN``、``build_reply_contract_zh/en``、
  ``build_normal_reply_contract_zh/en``），保证模型按预期格式返回 JSON 弹幕数组。
- 注入用户级增强：``append_nickname_to_system_pt``（W-NICKNAME-001）、
  ``append_live_topic_to_system_pt``（W-LIVE-TOPIC-001）。
- 提供 ``strip_reply_contract`` / ``ensure_reply_contract`` 用于去重与刷新现有 prompt 中的契约段。

关键约定：
- ``append_nickname_to_system_pt``：当 ``user_nickname`` 缺失/键不存在/纯空白时**原样返回**
  ``system_pt``，不追加任何内容。空值兜底是 hot-patch 行为，必须保留。
- ``append_live_topic_to_system_pt``：按 ``Translator.get_language()`` 选择中/英模板追加。
"""

from __future__ import annotations

import re

from app.config_store import ConfigStore
from app.danmu_engine import (
    DEFAULT_DANMU_MAX_CHARS_EN,
    DEFAULT_DANMU_MAX_CHARS_ZH,
    resolve_danmu_max_chars,
)
from app.translations import Translator

REPLY_COUNT_MIN = 2
REPLY_COUNT_MAX = 7
DEFAULT_REPLY_SCENE_COUNT = 2
DEFAULT_REPLY_FILLER_COUNT = 3

DEFAULT_NORMAL_REPLY_COUNT = 5
NORMAL_REPLY_COUNT_MIN = 1
NORMAL_REPLY_COUNT_MAX = 50

DEFAULT_SYSTEM_STYLE_ZH = (
    "像多位真实观众：短句口语碎片化；优先贴当前画面，可少量接梗或气氛句；条间口吻可不同。"
    "禁 AI腔/总结腔/客服腔/长句/说教/重复。"
)
DEFAULT_SYSTEM_STYLE_EN = (
    "Multiple real viewers: short, casual, fragmented; prioritize the current frame; "
    "a few meme or vibe lines OK; vary voice per line. "
    "No AI tone, summaries, customer-service voice, long lines, preaching, or repetition."
)

_CONTRACT_ZH_RE = re.compile(
    r"你是直播弹幕评论员。必须且只能返回 JSON 字符串数组，不要解释，不要 Markdown。"
    r"固定返回 \d+ 条弹幕：前 \d+ 条必须强相关当前画面，后 \d+ 条必须是适合直播间氛围的泛用弹幕。"
    r"每条不超过 \d+ 个字，避免重复，输出格式："
    r'\["[^"]*"(?:, "[^"]*")*\]。'
)
_CONTRACT_EN_RE = re.compile(
    r"You are a live-stream danmu commentator\. You must return a JSON string array only, "
    r"with no explanations and no Markdown\. "
    r"Always return exactly \d+ comments: the first \d+ must be strongly tied to the current frame, "
    r"and the last \d+ must be generic danmu suitable for a live-stream atmosphere\. "
    r"All comments MUST be written in English only\. "
    r"Each comment must stay within \d+ characters\. Avoid repetition\. Output format: "
    r'\["[^"]*"(?:, "[^"]*")*\]\.'
)
_CONTRACT_NORMAL_ZH_RE = re.compile(
    r"直播弹幕评论员。只输出 JSON 字符串数组，无解释、无 Markdown。"
    r"固定 \d+ 条，每条≤\d+字。"
    r"像多位真实观众：短句口语碎片化；优先贴当前画面，可少量接梗或气氛句；条间口吻可不同。"
    r"禁 AI腔/总结腔/客服腔/长句/说教/重复。"
    r"格式："
    r'\["[^"]*"(?:, "[^"]*")*\]。'
)
# Matches the current build_normal_reply_contract_zh output (no style text)
_CONTRACT_NORMAL_ZH_PLAIN_RE = re.compile(
    r"直播弹幕评论员。只输出 JSON 字符串数组，无解释、无 Markdown。"
    r"固定 \d+ 条，每条≤\d+字。"
    r"格式："
    r'\["[^"]*"(?:, "[^"]*")*\]。?'
)
# Matches the new bullet-list contract format (v2)
_CONTRACT_NORMAL_ZH_V2_RE = re.compile(
    r"- 只输出JSON字符串数组格式，如：\[[^\]]+\]\n"
    r"- 每条弹幕不超过\d+个汉字\n"
    r"- 固定输出\d+条\n"
    r"- 不要任何解释、Markdown格式或其他文字"
)
_CONTRACT_NORMAL_ZH_LEGACY_RE = re.compile(
    r"你是直播弹幕评论员。必须且只能返回 JSON 字符串数组，不要解释，不要 Markdown。"
    r"固定返回 \d+ 条弹幕，必须与当前画面或直播氛围相关，避免重复。"
    r"每条不超过 \d+ 个字，输出格式："
    r'\["[^"]*"(?:, "[^"]*")*\]。'
)
_CONTRACT_NORMAL_EN_RE = re.compile(
    r"Live-stream danmu commentator\. JSON string array only, no explanation, no Markdown\. "
    r"Exactly \d+ comments, max \d+ chars each\. "
    r"Multiple real viewers: short, casual, fragmented; prioritize the current frame; "
    r"a few meme or vibe lines OK; vary voice per line\. "
    r"No AI tone, summaries, customer-service voice, long lines, preaching, or repetition\. "
    r"All comments MUST be in English only\. "
    r"Format: "
    r'\["[^"]*"(?:, "[^"]*")*\]\.'
)
# Matches the current build_normal_reply_contract_en output (no style text)
_CONTRACT_NORMAL_EN_PLAIN_RE = re.compile(
    r"Live-stream danmu commentator\. JSON string array only, no explanation, no Markdown\. "
    r"Exactly \d+ comments, max \d+ chars each\. "
    r"All comments MUST be in English only\. "
    r"Format: "
    r'\["[^"]*"(?:, "[^"]*")*\]\.?'
)
# Matches the new bullet-list contract format (v2)
_CONTRACT_NORMAL_EN_V2_RE = re.compile(
    r"- Only output JSON string array format, e\.g\.: \[[^\]]+\]\n"
    r"- Each danmu must not exceed \d+ characters\n"
    r"- Always output exactly \d+ danmu\n"
    r"- No explanations, Markdown formatting, or other text"
)
_CONTRACT_NORMAL_EN_LEGACY_RE = re.compile(
    r"You are a live-stream danmu commentator\. You must return a JSON string array only, "
    r"with no explanations and no Markdown\. "
    r"Always return exactly \d+ comments that must relate to the current frame or live-stream atmosphere\. "
    r"Avoid repetition\. All comments MUST be written in English only\. "
    r"Each comment must stay within \d+ characters\. Output format: "
    r'\["[^"]*"(?:, "[^"]*")*\]\.'
)
_CONTRACT_OBJECT_ZH_RE = re.compile(
    r"直播弹幕评论员。只输出 JSON 对象，无解释、无 Markdown。"
    r"固定 \d+ 条 comments，每条≤\d+字；scene_brief 为不超过 \d+ 字的当前场景简述。"
    r'格式：\{"scene_brief":"[^"]*","comments":\["[^"]*"(?:, "[^"]*")*\]\}。'
)
_CONTRACT_OBJECT_ZH_LEGACY_RE = re.compile(
    r"直播弹幕评论员。只输出 JSON 对象，无解释、无 Markdown。"
    r"固定 \d+ 条 comments，每条≤\d+字；scene_brief 为不超过 \d+ 字的当前场景简述。"
    r"像多位真实观众：短句口语碎片化；优先贴当前画面，可少量接梗或气氛句；条间口吻可不同。"
    r"禁 AI腔/总结腔/客服腔/长句/说教/重复。"
    r'格式：\{"scene_brief":"[^"]*","comments":\["[^"]*"(?:, "[^"]*")*\]\}。'
)
_CONTRACT_OBJECT_EN_RE = re.compile(
    r"Live-stream danmu commentator\. JSON object only, no explanation, no Markdown\. "
    r"Exactly \d+ comments, max \d+ chars each; scene_brief is a current-frame summary within \d+ characters\. "
    r"All comments MUST be in English only\. "
    r'Format: \{"scene_brief":"[^"]*","comments":\["[^"]*"(?:, "[^"]*")*\]\}\.'
)
_CONTRACT_OBJECT_EN_LEGACY_RE = re.compile(
    r"Live-stream danmu commentator\. JSON object only, no explanation, no Markdown\. "
    r"Exactly \d+ comments, max \d+ chars each; scene_brief is a current-frame summary within \d+ characters\. "
    r"Multiple real viewers: short, casual, fragmented; prioritize the current frame; "
    r"a few meme or vibe lines OK; vary voice per line\. "
    r"No AI tone, summaries, customer-service voice, long lines, preaching, or repetition\. "
    r"All comments MUST be in English only\. "
    r'Format: \{"scene_brief":"[^"]*","comments":\["[^"]*"(?:, "[^"]*")*\]\}\.'
)

REPLY_CONTRACT_ZH = ""
REPLY_CONTRACT_EN = ""
REPLY_CONTRACT_ALIASES: set[str] = set()
REPLY_CONTRACT = ""


def _clamp_reply_count(value: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(REPLY_COUNT_MIN, min(REPLY_COUNT_MAX, n))


def reply_counts_from_config(config: ConfigStore | None) -> tuple[int, int]:
    if config is None:
        return DEFAULT_REPLY_SCENE_COUNT, DEFAULT_REPLY_FILLER_COUNT
    scene = _clamp_reply_count(
        config.get_int("reply_scene_count", DEFAULT_REPLY_SCENE_COUNT),
        DEFAULT_REPLY_SCENE_COUNT,
    )
    filler = _clamp_reply_count(
        config.get_int("reply_filler_count", DEFAULT_REPLY_FILLER_COUNT),
        DEFAULT_REPLY_FILLER_COUNT,
    )
    return scene, filler


def _clamp_normal_reply_count(value: int, default: int = DEFAULT_NORMAL_REPLY_COUNT) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(NORMAL_REPLY_COUNT_MIN, min(NORMAL_REPLY_COUNT_MAX, n))


def normal_reply_count_from_config(config: ConfigStore | None) -> int:
    if config is None:
        return DEFAULT_NORMAL_REPLY_COUNT
    from app.config_defaults import default_normal_reply_count_for_mode, resolve_danmu_render_mode

    default = default_normal_reply_count_for_mode(resolve_danmu_render_mode(config))
    return _clamp_normal_reply_count(
        config.get_int("normal_reply_count", default),
        default,
    )


def _json_example_zh(total: int) -> str:
    items = ["这波可以", "有点离谱", "什么情况", "别急别急", "绷不住了"]
    if total <= len(items):
        return '["' + '", "'.join(items[:total]) + '"]'
    extra = [f"示例短句{idx}" for idx in range(1, total - len(items) + 1)]
    items = items + extra
    return '["' + '", "'.join(items) + '"]'


def _json_example_en(total: int) -> str:
    items = ["nice play", "what happened", "that was close", "no way", "calm down"]
    if total <= len(items):
        return '["' + '", "'.join(items[:total]) + '"]'
    extra = [f"sample line {idx}" for idx in range(1, total - len(items) + 1)]
    items = items + extra
    return '["' + '", "'.join(items) + '"]'


def build_normal_reply_contract_zh(
    count: int,
    max_chars: int | None = None,
) -> str:
    total = _clamp_normal_reply_count(count, DEFAULT_NORMAL_REPLY_COUNT)
    limit = max_chars if max_chars is not None else DEFAULT_DANMU_MAX_CHARS_ZH
    return (
        "- 只输出JSON字符串数组格式，如："
        f'{_json_example_zh(total)}\n'
        f"- 每条弹幕不超过{limit}个汉字\n"
        f"- 固定输出{total}条\n"
        "- 不要任何解释、Markdown格式或其他文字"
    )


def build_normal_reply_contract_en(
    count: int,
    max_chars: int | None = None,
) -> str:
    total = _clamp_normal_reply_count(count, DEFAULT_NORMAL_REPLY_COUNT)
    limit = max_chars if max_chars is not None else DEFAULT_DANMU_MAX_CHARS_EN
    return (
        "- Only output JSON string array format, e.g.: "
        f'{_json_example_en(total)}\n'
        f"- Each danmu must not exceed {limit} characters\n"
        f"- Always output exactly {total} danmu\n"
        "- No explanations, Markdown formatting, or other text"
    )


def build_reply_contract_zh(
    scene_count: int,
    filler_count: int,
    max_chars: int | None = None,
) -> str:
    scene = _clamp_reply_count(scene_count, DEFAULT_REPLY_SCENE_COUNT)
    filler = _clamp_reply_count(filler_count, DEFAULT_REPLY_FILLER_COUNT)
    total = scene + filler
    limit = max_chars if max_chars is not None else DEFAULT_DANMU_MAX_CHARS_ZH
    return (
        "- 只输出JSON字符串数组格式，如："
        f'{_json_example_zh(total)}\n'
        f"- 每条弹幕不超过{limit}个汉字\n"
        f"- 固定输出{total}条\n"
        "- 不要任何解释、Markdown格式或其他文字"
    )


def build_reply_contract_en(
    scene_count: int,
    filler_count: int,
    max_chars: int | None = None,
) -> str:
    scene = _clamp_reply_count(scene_count, DEFAULT_REPLY_SCENE_COUNT)
    filler = _clamp_reply_count(filler_count, DEFAULT_REPLY_FILLER_COUNT)
    total = scene + filler
    limit = max_chars if max_chars is not None else DEFAULT_DANMU_MAX_CHARS_EN
    return (
        "- Only output JSON string array format, e.g.: "
        f'{_json_example_en(total)}\n'
        f"- Each danmu must not exceed {limit} characters\n"
        f"- Always output exactly {total} danmu\n"
        "- No explanations, Markdown formatting, or other text"
    )


def _refresh_legacy_contract_aliases() -> None:
    global REPLY_CONTRACT_ZH, REPLY_CONTRACT_EN, REPLY_CONTRACT, REPLY_CONTRACT_ALIASES
    REPLY_CONTRACT_ZH = build_reply_contract_zh(
        DEFAULT_REPLY_SCENE_COUNT,
        DEFAULT_REPLY_FILLER_COUNT,
        DEFAULT_DANMU_MAX_CHARS_ZH,
    )
    REPLY_CONTRACT_EN = build_reply_contract_en(
        DEFAULT_REPLY_SCENE_COUNT,
        DEFAULT_REPLY_FILLER_COUNT,
        DEFAULT_DANMU_MAX_CHARS_EN,
    )
    REPLY_CONTRACT = REPLY_CONTRACT_ZH
    normal_zh = build_normal_reply_contract_zh(DEFAULT_NORMAL_REPLY_COUNT, DEFAULT_DANMU_MAX_CHARS_ZH)
    normal_en = build_normal_reply_contract_en(DEFAULT_NORMAL_REPLY_COUNT, DEFAULT_DANMU_MAX_CHARS_EN)
    REPLY_CONTRACT_ALIASES = {REPLY_CONTRACT_ZH, REPLY_CONTRACT_EN, normal_zh, normal_en}


_refresh_legacy_contract_aliases()


def get_default_system_style() -> str:
    if Translator.get_language() == "en":
        return DEFAULT_SYSTEM_STYLE_EN
    return DEFAULT_SYSTEM_STYLE_ZH


def strip_system_style(system_custom: str) -> str:
    base = (system_custom or "").strip()
    for style in (DEFAULT_SYSTEM_STYLE_ZH, DEFAULT_SYSTEM_STYLE_EN):
        if base.startswith(style):
            base = base[len(style) :].strip()
    return base


def ensure_system_style(system_custom: str) -> str:
    persona_part = strip_system_style(system_custom)
    style = get_default_system_style()
    return f"{style} {persona_part}".strip() if persona_part else style


def get_reply_contract(config: ConfigStore | None = None) -> str:
    lang = Translator.get_language()
    if config is None:
        max_chars = (
            DEFAULT_DANMU_MAX_CHARS_EN if lang == "en" else DEFAULT_DANMU_MAX_CHARS_ZH
        )
    else:
        max_chars = resolve_danmu_max_chars(config, lang=lang)
    count = normal_reply_count_from_config(config)
    if lang == "en":
        return build_normal_reply_contract_en(count, max_chars)
    return build_normal_reply_contract_zh(count, max_chars)


def strip_reply_contract(system_pt: str) -> str:
    base = (system_pt or "").strip()
    for pattern in (
        _CONTRACT_OBJECT_ZH_LEGACY_RE,
        _CONTRACT_OBJECT_EN_LEGACY_RE,
        _CONTRACT_OBJECT_ZH_RE,
        _CONTRACT_OBJECT_EN_RE,
        _CONTRACT_ZH_RE,
        _CONTRACT_EN_RE,
        _CONTRACT_NORMAL_ZH_V2_RE,
        _CONTRACT_NORMAL_ZH_RE,
        _CONTRACT_NORMAL_ZH_PLAIN_RE,
        _CONTRACT_NORMAL_ZH_LEGACY_RE,
        _CONTRACT_NORMAL_EN_V2_RE,
        _CONTRACT_NORMAL_EN_RE,
        _CONTRACT_NORMAL_EN_PLAIN_RE,
        _CONTRACT_NORMAL_EN_LEGACY_RE,
    ):
        base = pattern.sub("", base).strip()
    for contract in REPLY_CONTRACT_ALIASES:
        if base.startswith(contract):
            base = base[len(contract) :].strip()
    return base


def ensure_reply_contract(system_pt: str, config: ConfigStore | None = None) -> str:
    persona_part = strip_system_style(strip_reply_contract(system_pt))
    contract = get_reply_contract(config)
    return f"{contract} {persona_part}".strip() if persona_part else contract


# W-NICKNAME-001
NICKNAME_MAX_LEN = 20
_NICKNAME_LINE_ZH = "[用户昵称：{nick}；可在合适时自然称呼用户，但不要每条回复都重复]"
_NICKNAME_LINE_EN = "[User nickname: {nick}; you may address the user naturally, but do not repeat it in every reply]"


def _read_user_nickname(config: ConfigStore | None) -> str:
    if config is None:
        return ""
    try:
        value = config.get("user_nickname", "")
    except Exception:
        return ""
    return str(value or "")


def append_nickname_to_system_pt(system_pt: str, config: ConfigStore | None) -> str:
    """Append a single nickname line to system_pt; returns unchanged prompt when empty."""
    nick = _read_user_nickname(config).strip()
    if not nick:
        return system_pt
    nick = nick[:NICKNAME_MAX_LEN]
    template = _NICKNAME_LINE_EN if Translator.get_language() == "en" else _NICKNAME_LINE_ZH
    suffix = template.format(nick=nick)
    base = (system_pt or "").rstrip()
    if not base:
        return suffix
    return f"{base}\n{suffix}"


# W-LIVE-TOPIC-001
LIVE_TOPIC_MAX_LEN = 200
_LIVE_TOPIC_LINE_ZH = "[本次直播主题：{topic}；请围绕此主题营造氛围并自然带入弹幕风格]"
_LIVE_TOPIC_LINE_EN = "[Live stream topic: {topic}; please set the tone around this topic and weave it naturally into your danmu]"


def _read_live_topic(config: ConfigStore | None) -> str:
    if config is None:
        return ""
    try:
        value = config.get("live_topic", "")
    except Exception:
        return ""
    return str(value or "")


def append_live_topic_to_system_pt(system_pt: str, config: ConfigStore | None) -> str:
    """Append a live-topic line to system_pt; returns unchanged prompt when empty."""
    topic = _read_live_topic(config).strip()
    if not topic:
        return system_pt
    topic = topic[:LIVE_TOPIC_MAX_LEN]
    template = _LIVE_TOPIC_LINE_EN if Translator.get_language() == "en" else _LIVE_TOPIC_LINE_ZH
    suffix = template.format(topic=topic)
    base = (system_pt or "").rstrip()
    if not base:
        return suffix
    return f"{base}\n{suffix}"
