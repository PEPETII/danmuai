"""烂梗 AI 识别展示：截图 + 候选列表 → 筛选弹幕 JSON。"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from app.reply_parser import parse_ai_reply_payload

if TYPE_CHECKING:
    from app.config_store import ConfigStore

_MEME_SELECT_SYSTEM_ZH = (
    "你是直播弹幕筛选助手。根据当前画面，从候选烂梗弹幕中挑选最贴合画面氛围的短句。"
    "只输出 JSON 字符串数组，无 Markdown、无解释。"
    "每条必须是候选列表中的原文或截断后的子串，不要编造新句子。"
)

_MEME_SELECT_SYSTEM_EN = (
    "You filter meme barrage lines for the current screen. "
    "Return only a JSON string array, no markdown."
)


def build_meme_select_user_prompt(candidates: list[str], pick_count: int) -> str:
    numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(candidates))
    return (
        f"请从以下候选弹幕中挑选约 {pick_count} 条最符合当前画面的短句，"
        f"按 JSON 字符串数组输出（条数不超过 {pick_count}）：\n{numbered}"
    )


def build_meme_select_system_prompt(config: "ConfigStore") -> str:
    lang = str(config.get("language", "zh") or "zh").strip().lower()
    if lang.startswith("en"):
        return _MEME_SELECT_SYSTEM_EN
    return _MEME_SELECT_SYSTEM_ZH


def parse_meme_ai_selection(text: str, candidates: list[str]) -> list[str]:
    """Parse AI JSON array; keep only lines that match candidates (normalized)."""
    raw_items = parse_ai_reply_payload(text)
    if not raw_items:
        # Fallback: try bare JSON array extraction
        stripped = text.strip()
        match = re.search(r"\[[\s\S]*\]", stripped)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, list):
                    raw_items = [str(x).strip() for x in parsed if str(x).strip()]
            except json.JSONDecodeError:
                raw_items = []
    if not raw_items:
        return []
    candidate_set = {c.strip() for c in candidates if c.strip()}
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text_item = str(item).strip()
        if not text_item or text_item in seen:
            continue
        if text_item in candidate_set:
            out.append(text_item)
            seen.add(text_item)
    return out
