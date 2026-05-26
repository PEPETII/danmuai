from __future__ import annotations

import json
import random
import re

from app.config_store import ConfigStore
from app.danmu_engine import (
    DEFAULT_DANMU_MAX_CHARS_EN,
    DEFAULT_DANMU_MAX_CHARS_ZH,
    resolve_danmu_max_chars,
)
from app.translations import Translator, tr

REPLY_COUNT_MIN = 2
REPLY_COUNT_MAX = 7
DEFAULT_REPLY_SCENE_COUNT = 2
DEFAULT_REPLY_FILLER_COUNT = 3

DEFAULT_NORMAL_REPLY_COUNT = 5
NORMAL_REPLY_COUNT_MIN = 1
NORMAL_REPLY_COUNT_MAX = 20

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
    r"你是直播弹幕评论员。必须且只能返回 JSON 字符串数组，不要解释，不要 Markdown。"
    r"固定返回 \d+ 条弹幕，必须与当前画面或直播氛围相关，避免重复。"
    r"每条不超过 \d+ 个字，输出格式："
    r'\["[^"]*"(?:, "[^"]*")*\]。'
)
_CONTRACT_NORMAL_EN_RE = re.compile(
    r"You are a live-stream danmu commentator\. You must return a JSON string array only, "
    r"with no explanations and no Markdown\. "
    r"Always return exactly \d+ comments that must relate to the current frame or live-stream atmosphere\. "
    r"Avoid repetition\. All comments MUST be written in English only\. "
    r"Each comment must stay within \d+ characters\. Output format: "
    r'\["[^"]*"(?:, "[^"]*")*\]\.'
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
    return _clamp_normal_reply_count(
        config.get_int("normal_reply_count", DEFAULT_NORMAL_REPLY_COUNT),
        DEFAULT_NORMAL_REPLY_COUNT,
    )


def is_normal_display_mode(config: ConfigStore | None) -> bool:
    if config is None:
        return False
    return config.get("danmu_display_mode", "normal").strip().lower() == "normal"


def _json_example_zh(total: int) -> str:
    items = [f"弹幕{i}" for i in range(1, total + 1)]
    return '["' + '", "'.join(items) + '"]'


def _json_example_en(total: int) -> str:
    items = [f"comment {i}" for i in range(1, total + 1)]
    return '["' + '", "'.join(items) + '"]'


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
        "你是直播弹幕评论员。必须且只能返回 JSON 字符串数组，不要解释，不要 Markdown。"
        f"固定返回 {total} 条弹幕：前 {scene} 条必须强相关当前画面，后 {filler} 条必须是适合直播间氛围的泛用弹幕。"
        f"每条不超过 {limit} 个字，避免重复，输出格式："
        f"{_json_example_zh(total)}。"
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
        "You are a live-stream danmu commentator. You must return a JSON string array only, "
        "with no explanations and no Markdown. "
        f"Always return exactly {total} comments: the first {scene} must be strongly tied to the current frame, "
        f"and the last {filler} must be generic danmu suitable for a live-stream atmosphere. "
        "All comments MUST be written in English only. "
        f"Each comment must stay within {limit} characters. Avoid repetition. Output format: "
        f"{_json_example_en(total)}."
    )


def build_normal_reply_contract_zh(
    count: int,
    max_chars: int | None = None,
) -> str:
    total = _clamp_normal_reply_count(count, DEFAULT_NORMAL_REPLY_COUNT)
    limit = max_chars if max_chars is not None else DEFAULT_DANMU_MAX_CHARS_ZH
    return (
        "你是直播弹幕评论员。必须且只能返回 JSON 字符串数组，不要解释，不要 Markdown。"
        f"固定返回 {total} 条弹幕，必须与当前画面或直播氛围相关，避免重复。"
        f"每条不超过 {limit} 个字，输出格式："
        f"{_json_example_zh(total)}。"
    )


def build_normal_reply_contract_en(
    count: int,
    max_chars: int | None = None,
) -> str:
    total = _clamp_normal_reply_count(count, DEFAULT_NORMAL_REPLY_COUNT)
    limit = max_chars if max_chars is not None else DEFAULT_DANMU_MAX_CHARS_EN
    return (
        "You are a live-stream danmu commentator. You must return a JSON string array only, "
        "with no explanations and no Markdown. "
        f"Always return exactly {total} comments that must relate to the current frame "
        "or live-stream atmosphere. Avoid repetition. All comments MUST be written in English only. "
        f"Each comment must stay within {limit} characters. Output format: "
        f"{_json_example_en(total)}."
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


def get_reply_contract(config: ConfigStore | None = None) -> str:
    lang = Translator.get_language()
    if config is None:
        max_chars = (
            DEFAULT_DANMU_MAX_CHARS_EN if lang == "en" else DEFAULT_DANMU_MAX_CHARS_ZH
        )
    else:
        max_chars = resolve_danmu_max_chars(config, lang=lang)
    if is_normal_display_mode(config):
        count = normal_reply_count_from_config(config)
        if lang == "en":
            return build_normal_reply_contract_en(count, max_chars)
        return build_normal_reply_contract_zh(count, max_chars)
    scene, filler = reply_counts_from_config(config)
    if lang == "en":
        return build_reply_contract_en(scene, filler, max_chars)
    return build_reply_contract_zh(scene, filler, max_chars)


def strip_reply_contract(system_pt: str) -> str:
    base = (system_pt or "").strip()
    for pattern in (_CONTRACT_ZH_RE, _CONTRACT_EN_RE, _CONTRACT_NORMAL_ZH_RE, _CONTRACT_NORMAL_EN_RE):
        base = pattern.sub("", base).strip()
    for contract in REPLY_CONTRACT_ALIASES:
        if base.startswith(contract):
            base = base[len(contract) :].strip()
    return base


def ensure_reply_contract(system_pt: str, config: ConfigStore | None = None) -> str:
    custom_part = strip_reply_contract(system_pt)
    contract = get_reply_contract(config)
    return f"{contract} {custom_part}".strip() if custom_part else contract


def normalize_persona_name(name: str) -> str:
    if not name:
        return ""
    return LEGACY_NAME_MAP.get(name, name)


def persona_display_name(name: str) -> str:
    normalized = normalize_persona_name(name)
    key = PERSONA_NAME_KEYS.get(normalized)
    return tr(key) if key else normalized


def default_user_prompt() -> str:
    return tr("template.default_user_prompt")


_REMOVED_PERSONAE = frozenset({"阿静"})

LEGACY_NAME_MAP = {
    "閸氭劖蝎閸?": "吐槽型",
    "閺傚洩澹撻崹?": "文艺型",
    "閹垛偓閺堫垰鐎?": "技术型",
    "閽€宀€閮撮崹?": "萌系型",
}

PERSONA_NAME_KEYS = {
    "吐槽型": "persona.roast",
    "文艺型": "persona.poetic",
    "技术型": "persona.tech",
    "萌系型": "persona.cute",
    "路人惊讶型": "persona.surprised",
    "搞笑玩梗型": "persona.meme",
    "专业分析型": "persona.analyst",
    "捧场活跃型": "persona.cheerleader",
    "轻度吐槽型": "persona.light_roast",
}

BUILTIN_PERSONAE = {
    "吐槽型": {
        "system_zh": "风格要求：吐槽感更强一点，但不要恶意攻击。",
        "user_zh": "请基于这张截图生成弹幕：",
        "system_en": "Style requirement: sharper and more roast-driven, but never malicious. All comments must be in English.",
        "user_en": "Generate English danmu comments based on this screenshot:",
    },
    "文艺型": {
        "system_zh": "风格要求：更文艺一些，保留画面感和节奏感。",
        "user_zh": "用文艺的方式为这张截图配弹幕：",
        "system_en": "Style requirement: more poetic, while keeping imagery and rhythm. All comments must be in English.",
        "user_en": "Write poetic English danmu for this screenshot:",
    },
    "技术型": {
        "system_zh": "风格要求：偏技术观察，强调细节和判断。",
        "user_zh": "从技术视角点评这张截图：",
        "system_en": "Style requirement: technical and observant, with emphasis on detail and judgment. All comments must be in English.",
        "user_en": "Comment on this screenshot in English from a technical perspective:",
    },
    "萌系型": {
        "system_zh": "风格要求：轻松可爱，但不要过度撒娇。",
        "user_zh": "用萌系语气为这张截图发弹幕：",
        "system_en": "Style requirement: light and cute, but not overly sugary. All comments must be in English.",
        "user_en": "Send cute-style English danmu for this screenshot:",
    },
    "路人惊讶型": {
        "system_zh": "风格：像普通观众突然看到画面变化后的真实反应，语气惊讶、自然、有点好奇。",
        "user_zh": "请基于这张截图生成弹幕：",
        "system_en": "Style: like a regular viewer's genuine reaction to something surprising on screen—astonished, natural, curious. All comments must be in English.",
        "user_en": "Generate English danmu comments based on this screenshot:",
    },
    "搞笑玩梗型": {
        "system_zh": "风格：轻松搞笑，像直播间高频刷屏弹幕，有节目效果，但不要太尬。",
        "user_zh": "请基于这张截图生成弹幕：",
        "system_en": "Style: light and funny, like high-frequency chat memes with good comedic timing, but not cringy. All comments must be in English.",
        "user_en": "Generate English danmu comments based on this screenshot:",
    },
    "专业分析型": {
        "system_zh": "风格：像懂行观众在快速点评，简短、有信息量、但口语化，不要复杂术语。",
        "user_zh": "请基于这张截图生成弹幕：",
        "system_en": "Style: like a knowledgeable viewer giving quick takes—brief, informative, but conversational, no jargon. All comments must be in English.",
        "user_en": "Generate English danmu comments based on this screenshot:",
    },
    "捧场活跃型": {
        "system_zh": "风格：积极、热闹、会接话，像帮主播暖场的真实观众，不要夸张到虚假。",
        "user_zh": "请基于这张截图生成弹幕：",
        "system_en": "Style: positive, lively, chatty—like a real viewer helping warm up the stream, but not fake-exaggerated. All comments must be in English.",
        "user_en": "Generate English danmu comments based on this screenshot:",
    },
    "轻度吐槽型": {
        "system_zh": "风格：嘴上吐槽但不伤人，像真实观众的轻松调侃，不要人身攻击、低俗、恶意嘲讽。",
        "user_zh": "请基于这张截图生成弹幕：",
        "system_en": "Style: light roasting without hurting feelings, like a real viewer's playful teasing—no personal attacks, vulgarity, or malice. All comments must be in English.",
        "user_en": "Generate English danmu comments based on this screenshot:",
    },
}


class PersonaManager:
    DEFAULT_ACTIVE = ["路人惊讶型", "搞笑玩梗型", "专业分析型", "捧场活跃型", "轻度吐槽型"]
    _ACTIVE_VERSION = 3

    def __init__(self, config: ConfigStore):
        self.config = config
        self._custom: dict = {}
        self._migrate_active_personae()
        self._purge_removed_personae()

    def _migrate_active_personae(self):
        version = self.config.get_int("active_personae_version", 0)
        if version < self._ACTIVE_VERSION:
            if version < 2:
                self.config.set_json("active_personae", self.DEFAULT_ACTIVE)
            else:
                active = self.config.get_json("active_personae", self.DEFAULT_ACTIVE)
                filtered = self._filter_removed_active(active)
                self.config.set_json("active_personae", filtered)
            self.config.set("active_personae_version", str(self._ACTIVE_VERSION))

    def _filter_removed_active(self, names: list[str]) -> list[str]:
        filtered = [
            normalize_persona_name(name)
            for name in names
            if name and normalize_persona_name(name) not in _REMOVED_PERSONAE
        ]
        return filtered or list(self.DEFAULT_ACTIVE)

    def _purge_removed_personae(self):
        active = self.config.get_json("active_personae", None)
        if isinstance(active, list):
            filtered = self._filter_removed_active(active)
            if filtered != active:
                self.config.set_json("active_personae", filtered)

        custom = self._load_custom()
        removed = [name for name in custom if name in _REMOVED_PERSONAE]
        if removed:
            for name in removed:
                custom.pop(name, None)
            self._custom = custom
            self.config.set("custom_personae", json.dumps(custom, ensure_ascii=False))

    def list(self) -> list[str]:
        builtin = list(BUILTIN_PERSONAE.keys())
        builtin_set = set(builtin)
        custom = [name for name in self._load_custom_names() if name not in builtin_set]
        return builtin + custom

    def get_prompt(self, name: str) -> tuple[str, str]:
        normalized = normalize_persona_name(name)
        custom = self._load_custom()
        if normalized in custom:
            prompt = custom[normalized]
            system_pt = (prompt.get("system_pt") or "").strip()
            if system_pt:
                user_pt = prompt.get("user_pt") or default_user_prompt()
                return ensure_reply_contract(system_pt, self.config), user_pt

        if normalized in BUILTIN_PERSONAE:
            prompt = BUILTIN_PERSONAE[normalized]
            if Translator.get_language() == "en":
                return ensure_reply_contract(prompt["system_en"], self.config), prompt["user_en"]
            return ensure_reply_contract(prompt["system_zh"], self.config), prompt["user_zh"]
        return "", ""

    def get_active(self) -> list[str]:
        names = self.config.get_json("active_personae", self.DEFAULT_ACTIVE)
        normalized = self._filter_removed_active(names if isinstance(names, list) else [])
        return normalized

    def set_active(self, names: list[str]):
        normalized = self._filter_removed_active([normalize_persona_name(name) for name in names if name])
        self.config.set_json("active_personae", normalized)

    def _load_custom_names(self) -> list[str]:
        return list(self._load_custom().keys())

    def _load_custom(self) -> dict:
        if not self._custom:
            raw = self.config.get("custom_personae", "{}")
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                self._custom = {normalize_persona_name(name): value for name, value in loaded.items()}
            else:
                self._custom = {}
        return self._custom

    def save_custom(self, name: str, system_pt: str, user_pt: str):
        custom = self._load_custom()
        custom[normalize_persona_name(name)] = {"system_pt": system_pt, "user_pt": user_pt}
        self._custom = custom
        self.config.set("custom_personae", json.dumps(custom, ensure_ascii=False))

    def delete_custom(self, name: str):
        custom = self._load_custom()
        custom.pop(normalize_persona_name(name), None)
        self._custom = custom
        self.config.set("custom_personae", json.dumps(custom, ensure_ascii=False))

    def pick_random(self) -> str:
        active = self.get_active()
        return random.choice(active) if active else self.DEFAULT_ACTIVE[0]
