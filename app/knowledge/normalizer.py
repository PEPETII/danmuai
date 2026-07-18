"""确定性文本清洗模块（知识包功能 A2.1）。

提供 3 个纯函数（无 IO、无副作用）：

- :func:`normalize_text`：BOM 去除、换行统一、控制字符清理、空行合并、连续重复行删除。
- :func:`decode_bytes`：按 BOM → UTF-8 → GB18030 → Big5 → Shift-JIS 顺序确定性解码；
  全部失败抛 ``ValueError("decode_failed")``；**不**依赖 ``charset-normalizer``。
- :func:`clean_livestream_log`：清理直播弹幕日志结构（时间戳、用户名、房间号、
  礼物/关注/进场/系统提示、空消息、纯标点、超长复制文本）。

设计原则（spec §7.1 / §8.2）：

- 文本提取是确定性步骤，不让 AI 直接处理文件格式；
- 保留原始段落顺序；
- 直播弹幕日志清理目标是让 AI 总结模式，不机械保存全部原句。
"""
from __future__ import annotations

import re

__all__ = ["normalize_text", "decode_bytes", "clean_livestream_log"]


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 3+ 连续换行折叠为 2 个（即最多保留 1 个空行）
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# 直播弹幕日志时间戳前缀（按特异性从高到低尝试）
_TIMESTAMP_PATTERNS: tuple[re.Pattern, ...] = (
    # 2024-01-01 12:00:00 或 2024-01-01T12:00:00.123
    re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s*"),
    # [2024-01-01 12:00:00]
    re.compile(r"^\[\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]\s*"),
    # [12:00:00] 或 [12:00:00.123]
    re.compile(r"^\[\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]\s*"),
    # 12:00:00 或 12:00:00.123（行首）
    re.compile(r"^\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s*"),
)

# 直播弹幕日志用户名前缀
_USERNAME_PATTERNS: tuple[re.Pattern, ...] = (
    # 用户名: / 用户名： （1-32 个非空白非括号非冒号字符 + 半角/全角冒号）
    re.compile(r"^[^\s:：\[\]<>]{1,32}[:：]\s*"),
    # <用户名> 后可选冒号
    re.compile(r"^<[^\s<>]{1,32}>\s*[:：]?\s*"),
    # [用户名] 后可选冒号
    re.compile(r"^\[[^\s\[\]]{1,32}\]\s*[:：]?\s*"),
)

# 房间号前缀 #12345
_ROOM_PREFIX_RE = re.compile(r"^#\d+\s*")

# 礼物/关注/进场/系统提示/房间号 关键词（出现即跳过整行）
_SYSTEM_KEYWORDS: tuple[str, ...] = (
    "进入直播间",
    "关注了主播",
    "送出",
    "系统",
    "房间号",
    "欢迎",
    "赠送",
    "抽奖",
    "进场",
)

# C0 控制字符（0x00-0x1F）需移除，但保留 \t=0x09 与 \n=0x0A；DEL=0x7F 也移除
_CONTROL_CHARS_TO_REMOVE: frozenset[int] = frozenset(
    cp for cp in range(0x20) if cp not in (0x09, 0x0A)
) | {0x7F}

# 零宽字符与软连字符等不可见字符
_ZERO_WIDTH_CHARS: frozenset[int] = frozenset(
    {
        0x00AD,  # SOFT HYPHEN
        0x200B,  # ZERO WIDTH SPACE
        0x200C,  # ZERO WIDTH NON-JOINER
        0x200D,  # ZERO WIDTH JOINER
        0x200E,  # LEFT-TO-RIGHT MARK
        0x200F,  # RIGHT-TO-LEFT MARK
        0x2060,  # WORD JOINER
        0xFEFF,  # ZERO WIDTH NO-BREAK SPACE (BOM)
    }
)

# Unicode 行/段分隔符 → 转为 \n
_LINE_SEPARATORS: frozenset[int] = frozenset({0x2028, 0x2029})


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


def _normalize_text_base(text: str) -> str:
    """对已解码字符串做基础清洗（**不**做连续重复行删除）。

    与 :func:`normalize_text` 的区别：本函数保留所有行（含连续重复行），
    供 :func:`clean_livestream_log` 等需要自行统计重复次数的调用方使用。

    步骤：
        1. 去除开头 BOM（``\\ufeff``）；
        2. 换行统一为 ``\\n``（``\\r\\n`` → ``\\n``、``\\r`` → ``\\n``）；
        3. 清理控制字符（保留 ``\\t`` / ``\\n``；移除其他 C0 与 DEL）；
           转换 Unicode 行/段分隔符为 ``\\n``；移除零宽字符；
        4. 合并 3+ 连续换行为 2 个（最多保留 1 个空行）。

    Args:
        text: 已解码的字符串。空字符串原样返回。

    Returns:
        基础清洗后的字符串（首尾空白未 strip，由调用方决定）。
    """
    if not text:
        return ""

    # 1. BOM
    if text.startswith("\ufeff"):
        text = text[1:]

    # 2. 换行统一
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. 控制字符 / 零宽字符 / 行段分隔符
    cleaned: list[str] = []
    for ch in text:
        cp = ord(ch)
        if cp in _CONTROL_CHARS_TO_REMOVE:
            continue
        if cp in _ZERO_WIDTH_CHARS:
            continue
        if cp in _LINE_SEPARATORS:
            cleaned.append("\n")
            continue
        cleaned.append(ch)
    text = "".join(cleaned)

    # 4. 合并空行
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text


def normalize_text(text: str) -> str:
    """对已解码字符串做确定性清洗。

    在 :func:`_normalize_text_base` 基础上额外执行：

        5. 删除连续完全重复的行（保留首次出现）；
        6. 去除首尾空白。

    Args:
        text: 已解码的字符串。空字符串原样返回。

    Returns:
        清洗后的字符串。
    """
    text = _normalize_text_base(text)
    if not text:
        return ""

    # 5. 删除连续重复行
    lines = text.split("\n")
    deduped: list[str] = []
    prev: str | None = None
    for line in lines:
        if line != prev:
            deduped.append(line)
        prev = line
    text = "\n".join(deduped)

    # 6. 首尾空白
    return text.strip()


# ---------------------------------------------------------------------------
# decode_bytes
# ---------------------------------------------------------------------------

# 编码尝试顺序（BOM 已先行检测，此处为非 BOM 路径）
_DECODE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("utf-8", "utf-8"),
    ("gb18030", "gb18030"),
    ("big5", "big5"),
    ("shift_jis", "shift_jis"),
)


def decode_bytes(data: bytes) -> tuple[str, str]:
    """按确定性顺序解码字节串。

    顺序：BOM 检测 → UTF-8 → GB18030 → Big5 → Shift-JIS。

    - BOM 检测覆盖 UTF-8/UTF-16/UTF-32 的 LE/BE 变体；
    - 非 BOM 路径严格按上述顺序尝试，首个成功者胜出；
    - 全部失败抛 ``ValueError("decode_failed")``；
    - **不**依赖 ``charset-normalizer``。

    Args:
        data: 原始字节串。``b""`` 返回 ``("", "utf-8")``。

    Returns:
        ``(decoded_text, encoding_used)``。``encoding_used`` 为实际解码所用编码名
        （如 ``"utf-8-sig"`` / ``"utf-8"`` / ``"gb18030"`` / ``"big5"`` /
        ``"shift_jis"`` / ``"utf-16-le"`` 等）。

    Raises:
        ValueError: 所有候选编码均解码失败时，``raise ValueError("decode_failed")``。
    """
    if data is None:
        raise ValueError("decode_failed")
    if data == b"":
        return "", "utf-8"

    # BOM 检测（注意顺序：UTF-32 BOM 与 UTF-16 LE BOM 前 2 字节相同，需先判 UTF-32）。
    # 用端序无关的 "utf-16" / "utf-32" 解码（自动从 BOM 推断端序并剥离 BOM 字符），
    # 避免使用 "utf-16-le" / "utf-32-le" 时 BOM 被当作 \ufeff 保留在解码结果中。
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if data.startswith(b"\xff\xfe\x00\x00"):
        return data.decode("utf-32"), "utf-32-le"
    if data.startswith(b"\x00\x00\xfe\xff"):
        return data.decode("utf-32"), "utf-32-be"
    if data.startswith(b"\xff\xfe"):
        return data.decode("utf-16"), "utf-16-le"
    if data.startswith(b"\xfe\xff"):
        return data.decode("utf-16"), "utf-16-be"

    # 非 BOM：严格按顺序尝试
    for encoding, name in _DECODE_CANDIDATES:
        try:
            return data.decode(encoding), name
        except UnicodeDecodeError:
            continue

    raise ValueError("decode_failed")


# ---------------------------------------------------------------------------
# clean_livestream_log
# ---------------------------------------------------------------------------


def _strip_prefix(line: str, patterns: tuple[re.Pattern, ...]) -> str:
    """用 patterns 中首个匹配的正则去掉行首前缀；不匹配则原样返回。"""
    for pat in patterns:
        new_line = pat.sub("", line, count=1)
        if new_line != line:
            return new_line.strip()
    return line


def _has_alphanumeric(text: str) -> bool:
    """是否含至少一个 Unicode 字母或数字（用于过滤纯标点/符号行）。"""
    for ch in text:
        if ch.isalnum():
            return True
    return False


def clean_livestream_log(text: str) -> str:
    """清理直播弹幕日志结构。

    处理规则（spec §8.2）：
        - 移除时间戳前缀（``2024-01-01 12:00:00``、``[12:00:00]``、``12:00:00``）；
        - 移除用户名前缀（``用户名:``、``用户名：``、``<用户名>``、``[用户名]``）；
        - 移除房间号前缀（``#12345``）；
        - 移除礼物/关注/进场/系统提示行（含 ``进入直播间``、``关注了主播``、
          ``送出``、``系统``、``房间号`` 等关键词的整行）；
        - 移除空消息；
        - 移除纯标点/符号行（无任何字母或数字）；
        - 移除超长复制文本（同一条消息连续重复 ≥5 次合并为一条）；
        - 保留有意义的弹幕文本，每条一行。

    Args:
        text: 原始直播弹幕日志文本。

    Returns:
        清理后的文本，每条有效弹幕一行。空文本返回空字符串。
    """
    if not text:
        return ""

    # 使用 base 版本（不做连续重复行删除），保留原始重复次数供下方 spam collapse 判断
    text = _normalize_text_base(text).strip()
    lines = text.split("\n")

    cleaned: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # 时间戳前缀
        line = _strip_prefix(line, _TIMESTAMP_PATTERNS)
        if not line:
            continue

        # 用户名前缀
        line = _strip_prefix(line, _USERNAME_PATTERNS)
        if not line:
            continue

        # 房间号前缀
        new_line = _ROOM_PREFIX_RE.sub("", line, count=1)
        if new_line != line:
            line = new_line.strip()
        if not line:
            continue

        # 系统/礼物/关注/进场/房间号 整行跳过
        if any(kw in line for kw in _SYSTEM_KEYWORDS):
            continue

        # 纯标点/符号行（无字母数字）
        if not _has_alphanumeric(line):
            continue

        cleaned.append(line)

    # 同一条消息连续重复 ≥5 次合并为 1 条；<5 次保留全部
    result: list[str] = []
    i = 0
    n = len(cleaned)
    while i < n:
        line = cleaned[i]
        j = i + 1
        while j < n and cleaned[j] == line:
            j += 1
        run_length = j - i
        if run_length >= 5:
            result.append(line)
        else:
            result.extend([line] * run_length)
        i = j

    return "\n".join(result)
