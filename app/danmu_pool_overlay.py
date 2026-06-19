"""Overlay-safe validation for custom formula danmu lines."""

from __future__ import annotations

import re

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
REPEAT_CHAR_RE = re.compile(r"(.)\1{4,}")
URL_RE = re.compile(r"https?://|www\.", re.I)

BLOCK_SUBSTRINGS = (
    "死妈",
    "傻逼",
    "操你",
    "nmsl",
    "cnm",
    "草泥马",
    "卧槽",
    "我操",
    "我特么",
    "我TM",
    "TMD",
    "tmd",
    "妈的",
    "牛逼",
    "牛壁",
    "装逼",
    "挂逼",
    "憨批",
    "吃口屎",
    "吔屎",
    "口也屎",
    "吃屎",
    "搓屁",
    "放屁",
    "大吊",
    "命根子",
    "嘴臭",
    "小jb",
    "摸奈子",
    "裆锯",
    "avi.",
    "尾行",
    "女少口阿",
    "沉迷女色",
    "沉迷美色",
    "妇炎洁",
    "卢本伟",
    "卢姥爷",
    "卢老爷",
    "lbw",
    "lbwnb",
    "芦苇",
    "肖战",
    "蔡徐坤",
    "吴亦凡",
    "乔碧萝",
    "药水哥",
    "脏话一堆",
    "你爹是我儿",
    "漂移~身边的小妞",
    "和天皇作对",
    "复兴华夏",
    "中华人民共和国",
    "红军加油",
    "川国同志",
    "兴兵北伐",
    "治死",
    "治一个，死一个",
    "一年治死",
    "你们杀了我",
    "鸡~你~太~美",
    "坤牛壁",
    "公开处刑",
    "澳门皇家赌场",
    "woc",
    "wdnmd",
    "我擦",
    "我透",
    "杀死",
    "李易峰",
    "普京",
    "奥巴马",
    "特朗普",
)
BLOCK_CHARS = set("▓█▅▆▇")
BLOCK_REGEX_PATTERNS: tuple[str, ...] = (
    r"♂",
    r"lbw",
    r"芦苇",
)


def is_overlay_safe(text: str, *, max_chars: int | None = 15, min_chars: int = 2) -> bool:
    text = text.strip()
    if not text or len(text) < min_chars:
        return False
    if max_chars is not None and len(text) > max_chars:
        return False
    if any(ch in text for ch in ("\n", "\r", "\t")):
        return False
    # CJK 不再是硬性前置条件：有 CJK 时检查数量，无 CJK 但满足其他条件也可通过
    has_cjk = bool(CJK_RE.search(text))
    if has_cjk:
        cjk = len(CJK_RE.findall(text))
        if cjk < min(2, len(text)):
            return False
    if REPEAT_CHAR_RE.search(text):
        return False
    if URL_RE.search(text):
        return False
    low = text.lower()
    if any(marker in text or marker.lower() in low for marker in BLOCK_SUBSTRINGS):
        return False
    for pat in BLOCK_REGEX_PATTERNS:
        if re.search(pat, text, flags=re.I):
            return False
    if any(ch in BLOCK_CHARS for ch in text):
        return False
    if text.count(" ") > 2:
        return False
    unique_chars = len(set(text))
    if unique_chars < 2 and len(text) > 4:
        return False
    return True
