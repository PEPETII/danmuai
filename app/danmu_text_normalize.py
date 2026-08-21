"""弹幕正文外层包裹引号规范化（解析层与显示层共用，无 Qt / provider 依赖）。"""

from __future__ import annotations

# (open, close) — 仅当整段正文被成对包裹时才剥离最外层。
_OUTER_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("'", "'"),
    ("\u201c", "\u201d"),  # “ ”
    ("\u2018", "\u2019"),  # ‘ ’
)


def strip_outer_wrapping_quotes(text: str) -> str:
    """移除正文最外层的成对包裹引号，并再次 strip 外层空白。

    支持 ASCII 双/单引号与常见中文弯引号；正文内部的引用引号保持不变。
    若存在多层外层包裹（如 ``"“文本”"``），逐层剥离直至无匹配外层对。
    """
    value = str(text).strip()
    if not value:
        return value

    changed = True
    while changed:
        changed = False
        for open_q, close_q in _OUTER_QUOTE_PAIRS:
            o_len = len(open_q)
            c_len = len(close_q)
            if len(value) < o_len + c_len:
                continue
            if value.startswith(open_q) and value.endswith(close_q):
                value = value[o_len:-c_len].strip()
                changed = True
                break
    return value
