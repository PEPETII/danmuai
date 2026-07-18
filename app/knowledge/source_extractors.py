"""来源提取器（知识包功能 A2.2）。

4 类提取器 + SSRF 防护 + 统一分派入口（spec §7.1 / §7.2 / §7.3）：

- :class:`TextExtractor`（``pasted_text``）：直接调 normalizer。
- :class:`TxtExtractor`（``txt``）：Base64 → bytes → :func:`decode_bytes` → :func:`normalize_text`。
- :class:`MarkdownExtractor`（``markdown``）：用 ``markdown-it-py`` 解析 token，
  保留 heading/paragraph/list/quote/link_text/alt，移除 fence/code_inline/html_block/html_inline。
- :class:`WebpageExtractor`（``webpage``）：用 ``httpx`` 抓取 + SSRF 防护 +
  ``trafilatura.extract`` 提取正文。

统一入口 :func:`extract(source_type, payload) -> ExtractionResult`。

安全约束（spec §7.3）：
    - 仅允许 http/https；
    - SSRF 防护：拒绝 localhost/私网/链路本地/云元数据/非 http(s)；
    - 超时 15s；重定向 ≤5；响应 ≤10 MiB；UA="DanmuAI/1.0"；
    - 单来源 normalized_text > 5 MiB 返回 ``error="source_too_large"``。
"""
from __future__ import annotations

import base64
import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
import trafilatura
from markdown_it import MarkdownIt

from app.knowledge.normalizer import decode_bytes, normalize_text

logger = logging.getLogger(__name__)

__all__ = [
    "ExtractionResult",
    "TextExtractor",
    "TxtExtractor",
    "MarkdownExtractor",
    "WebpageExtractor",
    "extract",
    "MAX_SOURCE_CHARS",
    "MAX_RESPONSE_BYTES",
    "HTTP_TIMEOUT_SEC",
    "MAX_REDIRECTS",
    "USER_AGENT",
]


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 单来源 normalized_text 上限：5 MiB 字符（spec §2.1 / §7.3）
MAX_SOURCE_CHARS = 5 * 1024 * 1024

# 单 HTTP 响应大小上限：10 MiB 字节（spec §7.3 "限制响应大小"）
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# HTTP 超时（秒）（spec §7.3 "超时建议 10～15 秒"）
HTTP_TIMEOUT_SEC = 15.0

# 最大重定向次数（spec §7.3 "限制重定向次数"）
MAX_REDIRECTS = 5

# User-Agent（spec §7.3 "User-Agent 明确标识 DanmuAI"）
USER_AGENT = "DanmuAI/1.0"


# ---------------------------------------------------------------------------
# ExtractionResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionResult:
    """提取结果（不可变）。

    Attributes:
        normalized_text: 清洗后的正文文本。空字符串表示无有效内容或出错。
        metadata: 来源元数据（如 final_url、encoding、content_type 等）；可变 dict
            但构造后不应再修改。
        error: 错误标识，空字符串表示成功。常见值：``decode_failed`` /
            ``source_too_large`` / ``ssrf_blocked`` / ``fetch_failed`` /
            ``http_error`` / ``unsupported_content_type`` / ``unsupported_scheme`` /
            ``empty_content`` / ``invalid_url`` / ``timeout`` / ``unknown_source_type`` /
            ``extract_failed``。
        warning: 警告标识，空字符串表示无警告。常见值：``response_truncated``。
    """

    normalized_text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    warning: str = ""


# ---------------------------------------------------------------------------
# TextExtractor (pasted_text)
# ---------------------------------------------------------------------------


class TextExtractor:
    """纯文本提取器（spec §7.1）：直接调 :func:`normalize_text`。"""

    def extract(self, payload: dict) -> ExtractionResult:
        text = payload.get("pasted_text") or ""
        if not text:
            return ExtractionResult("", {"source_type": "pasted_text"}, error="empty_content")
        normalized = normalize_text(text)
        if not normalized:
            return ExtractionResult("", {"source_type": "pasted_text"}, error="empty_content")
        if len(normalized) > MAX_SOURCE_CHARS:
            return ExtractionResult("", {"source_type": "pasted_text"}, error="source_too_large")
        return ExtractionResult(normalized, {"source_type": "pasted_text"})


# ---------------------------------------------------------------------------
# TxtExtractor (txt)
# ---------------------------------------------------------------------------


class TxtExtractor:
    """TXT 文件提取器（spec §7.1）：Base64 → bytes → decode → normalize。

    前端用 ``File.arrayBuffer()`` → Base64 提交，后端负责解码（spec §7.1 末段）。
    """

    def extract(self, payload: dict) -> ExtractionResult:
        b64 = payload.get("content_base64") or ""
        if not b64:
            return ExtractionResult("", {"source_type": "txt"}, error="empty_content")
        try:
            data = base64.b64decode(b64, validate=False)
        except ValueError:
            return ExtractionResult("", {"source_type": "txt"}, error="decode_failed")
        if not data:
            return ExtractionResult("", {"source_type": "txt"}, error="empty_content")
        try:
            text, encoding = decode_bytes(data)
        except ValueError:
            return ExtractionResult("", {"source_type": "txt"}, error="decode_failed")
        normalized = normalize_text(text)
        if not normalized:
            return ExtractionResult("", {"source_type": "txt", "encoding": encoding}, error="empty_content")
        if len(normalized) > MAX_SOURCE_CHARS:
            return ExtractionResult("", {"source_type": "txt", "encoding": encoding}, error="source_too_large")
        return ExtractionResult(normalized, {"source_type": "txt", "encoding": encoding})


# ---------------------------------------------------------------------------
# MarkdownExtractor (markdown)
# ---------------------------------------------------------------------------

# commonmark preset + html=True（保留 html_block/html_inline token 以便识别并跳过）
_MD = MarkdownIt("commonmark", {"html": True})

# inline 子 token 中需要跳过的类型（不取 content）
_MD_INLINE_SKIP_TYPES: frozenset[str] = frozenset(
    {
        "link_open",
        "link_close",
        "code_inline",  # 行内代码默认移除（spec §7.2 "默认移除代码块"）
        "html_inline",
    }
)


def _extract_inline_text(token) -> str:
    """从 inline token 的 children 中提取纯文本。

    - ``text`` → 保留 content
    - ``softbreak`` / ``hardbreak`` → 转为换行
    - ``image`` → 保留 alt 文本（content 字段）
    - ``link_open`` / ``link_close`` / ``code_inline`` / ``html_inline`` → 跳过
      （link 的显示文本是其间的 ``text`` 子 token，会被保留）
    """
    if not token.children:
        return token.content or ""
    parts: list[str] = []
    for child in token.children:
        ctype = child.type
        if ctype == "text":
            parts.append(child.content)
        elif ctype in ("softbreak", "hardbreak"):
            parts.append("\n")
        elif ctype == "image":
            # image 的 content 字段是 alt 文本（spec §7.2 "图片只保留可用 alt 文本"）
            if child.content:
                parts.append(child.content)
        elif ctype in _MD_INLINE_SKIP_TYPES:
            continue
        else:
            # 其他开/闭环 token（em_open/strong_open/...）无 content，跳过；
            # 若有 content 则兜底保留
            if child.content:
                parts.append(child.content)
    return "".join(parts)


class MarkdownExtractor:
    """Markdown 文件提取器（spec §7.2）。

    保留：heading（含层级 ``#`` 标记）/ paragraph / list_item / blockquote /
    link 显示文本 / image alt。

    移除：fence / code_block / code_inline / html_block / html_inline /
    script / style。
    """

    def extract(self, payload: dict) -> ExtractionResult:
        b64 = payload.get("content_base64") or ""
        if not b64:
            return ExtractionResult("", {"source_type": "markdown"}, error="empty_content")
        try:
            data = base64.b64decode(b64, validate=False)
        except ValueError:
            return ExtractionResult("", {"source_type": "markdown"}, error="decode_failed")
        if not data:
            return ExtractionResult("", {"source_type": "markdown"}, error="empty_content")
        try:
            text, encoding = decode_bytes(data)
        except ValueError:
            return ExtractionResult("", {"source_type": "markdown"}, error="decode_failed")
        if not text.strip():
            return ExtractionResult("", {"source_type": "markdown", "encoding": encoding}, error="empty_content")

        blocks = self._extract_blocks(text)
        raw = "\n\n".join(blocks)
        normalized = normalize_text(raw)
        if not normalized:
            return ExtractionResult("", {"source_type": "markdown", "encoding": encoding}, error="empty_content")
        if len(normalized) > MAX_SOURCE_CHARS:
            return ExtractionResult("", {"source_type": "markdown", "encoding": encoding}, error="source_too_large")
        return ExtractionResult(normalized, {"source_type": "markdown", "encoding": encoding})

    @staticmethod
    def _extract_blocks(text: str) -> list[str]:
        """从 Markdown 文本中提取文本块列表。

        每个 block 是一个字符串（heading 带 ``#`` 前缀，paragraph/list/quote 是纯文本）。
        block 之间用空行分隔（由调用方 join 后 normalize_text 合并空行）。
        """
        tokens = _MD.parse(text, {})
        blocks: list[str] = []
        pending_heading_level: int | None = None
        for t in tokens:
            ttype = t.type
            if ttype == "heading_open":
                try:
                    pending_heading_level = int(t.tag[1:])
                except (ValueError, IndexError):
                    pending_heading_level = 1
            elif ttype == "heading_close":
                pending_heading_level = None
            elif ttype == "inline":
                content = _extract_inline_text(t).strip()
                if not content:
                    continue
                if pending_heading_level is not None:
                    level = max(1, min(6, pending_heading_level))
                    blocks.append("#" * level + " " + content)
                else:
                    blocks.append(content)
            # 其他类型（fence / code_block / html_block / *_open / *_close 等）跳过
        return blocks


# ---------------------------------------------------------------------------
# WebpageExtractor (webpage) + SSRF 防护
# ---------------------------------------------------------------------------

# 云元数据 IP（精确匹配；link-local 已被 is_link_local 覆盖，此处补充非 link-local 的元数据 IP）
_CLOUD_METADATA_IPS: frozenset[str] = frozenset(
    {
        "169.254.169.254",  # AWS / Azure / GCP / OpenStack（link-local，双保险）
        "100.100.100.200",  # Alibaba Cloud（非 link-local，需显式匹配）
        "fd00:ec2::254",  # AWS IPv6 元数据
    }
)


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """判断 IP 是否应被 SSRF 防护阻止。

    阻止：私网 / 回环 / 链路本地 / 多播 / 未指定 / 保留地址 / 云元数据 IP。
    """
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        return True
    if str(ip) in _CLOUD_METADATA_IPS:
        return True
    return False


def _check_ssrf(host: str) -> str | None:
    """检查 host 是否触发 SSRF 防护。

    Args:
        host: URL 中的 hostname（已由 urlparse 提取，不含端口）。

    Returns:
        阻止原因字符串（``"ssrf_blocked"`` / ``"dns_failed"``）；``None`` 表示通过。
    """
    if not host:
        return "invalid_url"
    # 直接 IP 主机
    try:
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            return "ssrf_blocked"
        return None
    except ValueError:
        pass  # 不是 IP，按域名处理
    # 域名解析后检查所有 A/AAAA 记录
    try:
        addrinfos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return "dns_failed"
    for addrinfo in addrinfos:
        addr = addrinfo[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            return "ssrf_blocked"
    return None


def _is_allowed_scheme(scheme: str) -> bool:
    return scheme in ("http", "https")


class WebpageExtractor:
    """网页提取器（spec §7.3）。

    安全要求：
        - 仅允许 http/https；
        - SSRF 防护：拒绝 localhost/私网/链路本地/云元数据；
        - 超时 15s；重定向 ≤5；响应 ≤10 MiB；UA="DanmuAI/1.0"；
        - 仅接受 text/html 或 text/plain；
        - 用 :func:`trafilatura.extract` 提取正文。
    """

    def extract(self, payload: dict) -> ExtractionResult:
        url = (payload.get("source_url") or "").strip()
        if not url:
            return ExtractionResult("", {"source_type": "webpage"}, error="invalid_url")
        parsed = urlparse(url)
        if not _is_allowed_scheme(parsed.scheme):
            return ExtractionResult(
                "",
                {"source_type": "webpage", "url": url, "scheme": parsed.scheme},
                error="unsupported_scheme",
            )
        if not parsed.hostname:
            return ExtractionResult("", {"source_type": "webpage", "url": url}, error="invalid_url")

        ssrf_reason = _check_ssrf(parsed.hostname)
        if ssrf_reason is not None:
            return ExtractionResult(
                "",
                {"source_type": "webpage", "url": url, "host": parsed.hostname},
                error=ssrf_reason,
            )

        headers = {"User-Agent": USER_AGENT}
        try:
            with httpx.Client(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=HTTP_TIMEOUT_SEC,
                headers=headers,
            ) as client:
                with client.stream("GET", url) as resp:
                    if resp.status_code >= 400:
                        return ExtractionResult(
                            "",
                            {"source_type": "webpage", "url": url, "status_code": resp.status_code},
                            error="http_error",
                        )
                    content_type = (resp.headers.get("content-type") or "").lower()
                    if not (
                        content_type.startswith("text/html")
                        or content_type.startswith("text/plain")
                    ):
                        return ExtractionResult(
                            "",
                            {"source_type": "webpage", "url": url, "content_type": content_type},
                            error="unsupported_content_type",
                        )
                    charset = resp.charset_encoding
                    # 流式读取，严格控制响应大小
                    total = 0
                    chunks: list[bytes] = []
                    truncated = False
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        total += len(chunk)
                        if total > MAX_RESPONSE_BYTES:
                            truncated = True
                            break
                        chunks.append(chunk)
                    raw_bytes = b"".join(chunks)
        except httpx.TimeoutException:
            return ExtractionResult("", {"source_type": "webpage", "url": url}, error="timeout")
        except httpx.HTTPError as exc:
            return ExtractionResult(
                "",
                {"source_type": "webpage", "url": url, "exception": str(exc)},
                error="fetch_failed",
            )

        # 解码（优先用 HTTP charset，失败回退到 normalizer.decode_bytes）
        text, encoding = self._decode_response(raw_bytes, charset)
        if text is None:
            return ExtractionResult(
                "",
                {"source_type": "webpage", "url": url, "content_type": content_type},
                error="decode_failed",
            )
        if not text.strip():
            return ExtractionResult(
                "",
                {"source_type": "webpage", "url": url, "content_type": content_type},
                error="empty_content",
            )

        # 用 trafilatura 提取正文
        try:
            extracted = trafilatura.extract(
                text,
                include_links=False,
                include_tables=False,
                include_images=False,
            )
        except Exception as exc:
            logger.warning("trafilatura.extract failed for %s: %s", url, exc)
            return ExtractionResult(
                "",
                {"source_type": "webpage", "url": url, "exception": str(exc)},
                error="extract_failed",
            )

        if not extracted or not extracted.strip():
            return ExtractionResult(
                "",
                {"source_type": "webpage", "url": url, "content_type": content_type},
                error="empty_content",
            )

        normalized = normalize_text(extracted)
        if not normalized:
            return ExtractionResult(
                "",
                {"source_type": "webpage", "url": url, "content_type": content_type},
                error="empty_content",
            )
        if len(normalized) > MAX_SOURCE_CHARS:
            return ExtractionResult(
                "",
                {"source_type": "webpage", "url": url, "content_type": content_type},
                error="source_too_large",
            )

        metadata: dict[str, Any] = {
            "source_type": "webpage",
            "url": url,
            "encoding": encoding,
            "content_type": content_type,
        }
        warning = ""
        if truncated:
            metadata["response_truncated"] = True
            warning = "response_truncated"
        return ExtractionResult(normalized, metadata, warning=warning)

    @staticmethod
    def _decode_response(raw_bytes: bytes, charset: str | None) -> tuple[str | None, str]:
        """解码 HTTP 响应字节。

        优先用 HTTP charset；失败回退到 :func:`decode_bytes`。

        Returns:
            ``(text, encoding)``；解码失败返回 ``(None, "")``。
        """
        if charset:
            try:
                return raw_bytes.decode(charset), charset
            except (UnicodeDecodeError, LookupError):
                pass
        try:
            return decode_bytes(raw_bytes)
        except ValueError:
            return None, ""


# ---------------------------------------------------------------------------
# 统一分派
# ---------------------------------------------------------------------------

_EXTRACTORS: dict[str, Any] = {
    "pasted_text": TextExtractor(),
    "txt": TxtExtractor(),
    "markdown": MarkdownExtractor(),
    "webpage": WebpageExtractor(),
}


def extract(source_type: str, payload: dict) -> ExtractionResult:
    """统一提取入口。

    Args:
        source_type: ``"pasted_text"`` / ``"txt"`` / ``"markdown"`` / ``"webpage"``。
        payload: 各提取器所需字段：
            - ``pasted_text`` → ``pasted_text`` 字段
            - ``txt`` / ``markdown`` → ``content_base64`` 字段
            - ``webpage`` → ``source_url`` 字段

    Returns:
        :class:`ExtractionResult`。出错时 ``error`` 非空、``normalized_text`` 为空。
    """
    extractor = _EXTRACTORS.get(source_type)
    if extractor is None:
        return ExtractionResult("", {"source_type": source_type}, error="unknown_source_type")
    try:
        return extractor.extract(payload or {})
    except Exception as exc:  # pragma: no cover — 兜底，避免单来源异常炸掉整个导入
        logger.exception("extractor %s failed", source_type)
        return ExtractionResult(
            "",
            {"source_type": source_type, "exception": str(exc)},
            error="extract_failed",
        )
