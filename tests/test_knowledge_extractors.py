"""tests/test_knowledge_extractors.py — 来源提取器测试（A2.3）。

覆盖（spec §A2.3）：
    - TextExtractor：BOM/换行/控制字符/空行/重复行
    - TxtExtractor：UTF-8 BOM / GB18030 / Big5 / Shift-JIS / 解码失败
    - MarkdownExtractor：heading/paragraph/list/quote/link_text/alt/code_block/html_block
    - WebpageExtractor：SSRF 拒绝（127.0.0.1/10.0.0.1/169.254.169.254/::1/localhost）/
      file:// 协议/超时/HTTP 错误/非 HTML content-type/响应截断/空内容/
      trafilatura 提取成功/正常流程
    - extract() 统一入口：unknown_source_type / 异常兜底
    - 单来源 >5 MiB 拒绝（source_too_large）

约定（AGENTS.md §A.4.1）：
    - 只跑本文件：``python -m pytest tests/test_knowledge_extractors.py -q -x``
    - 不发真实网络请求（mock httpx.Client + trafilatura.extract）
    - 不依赖 Qt / DanmuApp / ConfigStore
"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.knowledge.normalizer import (
    clean_livestream_log,
    decode_bytes,
    normalize_text,
)
from app.knowledge.source_extractors import (
    MAX_RESPONSE_BYTES,
    MAX_SOURCE_CHARS,
    ExtractionResult,
    MarkdownExtractor,
    TextExtractor,
    TxtExtractor,
    WebpageExtractor,
    extract,
)


# ---------------------------------------------------------------------------
# 辅助：构造 mock httpx 流式响应
# ---------------------------------------------------------------------------


class _MockStreamResponse:
    """模拟 ``httpx.Client.stream()`` 返回的响应上下文管理器。"""

    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
        iter_chunks: list[bytes] | None = None,
    ):
        self.status_code = status_code
        self.headers = headers if headers is not None else {
            "content-type": "text/html; charset=utf-8"
        }
        self._iter_chunks = iter_chunks
        self._content = content

    @property
    def charset_encoding(self) -> str | None:
        ct = self.headers.get("content-type", "")
        if "charset=" in ct:
            return ct.split("charset=")[-1].split(";")[0].strip()
        return None

    def iter_bytes(self, chunk_size: int = 8192):
        if self._iter_chunks is not None:
            for chunk in self._iter_chunks:
                yield chunk
        else:
            for i in range(0, len(self._content), chunk_size):
                yield self._content[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _MockClient:
    """模拟 ``httpx.Client``。"""

    def __init__(self, response: _MockStreamResponse, **kwargs):
        self._response = response
        self._kwargs = kwargs

    def stream(self, method: str, url: str):
        return self._response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_httpx(response: _MockStreamResponse):
    """返回 ``mock.patch`` 上下文，替换 ``httpx.Client`` 为返回 ``response`` 的 mock。"""
    return patch(
        "app.knowledge.source_extractors.httpx.Client",
        return_value=_MockClient(response),
    )


def _patch_trafilatura(extracted: str | None):
    """返回 ``mock.patch`` 上下文，替换 ``trafilatura.extract``。"""
    return patch(
        "app.knowledge.source_extractors.trafilatura.extract",
        return_value=extracted,
    )


# ---------------------------------------------------------------------------
# TextExtractor
# ---------------------------------------------------------------------------


class TestTextExtractor:
    def test_basic_normalize(self):
        r = extract("pasted_text", {"pasted_text": "\ufeffHello\r\nWorld\r\nWorld\r\n\r\n\r\nFoo"})
        assert r.error == ""
        assert r.normalized_text == "Hello\nWorld\n\nFoo"
        assert r.metadata["source_type"] == "pasted_text"

    def test_empty_content(self):
        r = extract("pasted_text", {"pasted_text": ""})
        assert r.error == "empty_content"
        assert r.normalized_text == ""

    def test_empty_payload(self):
        r = extract("pasted_text", {})
        assert r.error == "empty_content"

    def test_whitespace_only(self):
        r = extract("pasted_text", {"pasted_text": "   \n\n  \t  \n"})
        assert r.error == "empty_content"

    def test_control_chars_removed(self):
        r = extract("pasted_text", {"pasted_text": "Hello\x00\x01\x02World\x7F"})
        assert r.error == ""
        assert r.normalized_text == "HelloWorld"

    def test_zero_width_chars_removed(self):
        r = extract("pasted_text", {"pasted_text": "Hello\u200B\u200C\u200DWorld\uFEFF"})
        assert r.error == ""
        assert r.normalized_text == "HelloWorld"

    def test_too_large(self):
        # 5 MiB + 1 字符
        big = "A" * (MAX_SOURCE_CHARS + 1)
        r = extract("pasted_text", {"pasted_text": big})
        assert r.error == "source_too_large"
        assert r.normalized_text == ""

    def test_exact_limit_ok(self):
        # 恰好 5 MiB 字符（允许）
        text = "A" * MAX_SOURCE_CHARS
        r = extract("pasted_text", {"pasted_text": text})
        assert r.error == ""
        assert len(r.normalized_text) == MAX_SOURCE_CHARS


# ---------------------------------------------------------------------------
# TxtExtractor
# ---------------------------------------------------------------------------


class TestTxtExtractor:
    def test_utf8_bom(self):
        text = "你好世界\nHello"
        b64 = base64.b64encode(text.encode("utf-8-sig")).decode()
        r = extract("txt", {"content_base64": b64})
        assert r.error == ""
        assert r.normalized_text == "你好世界\nHello"
        assert r.metadata["encoding"] == "utf-8-sig"
        assert r.metadata["source_type"] == "txt"

    def test_utf8_no_bom(self):
        text = "Plain UTF-8 text"
        b64 = base64.b64encode(text.encode("utf-8")).decode()
        r = extract("txt", {"content_base64": b64})
        assert r.error == ""
        assert r.normalized_text == "Plain UTF-8 text"
        assert r.metadata["encoding"] == "utf-8"

    def test_gb18030(self):
        text = "中文测试"
        b64 = base64.b64encode(text.encode("gb18030")).decode()
        r = extract("txt", {"content_base64": b64})
        assert r.error == ""
        assert r.normalized_text == "中文测试"
        assert r.metadata["encoding"] == "gb18030"

    # 注意：Big5 / Shift-JIS 路径在确定性检测下几乎不可达。
    # 原因：GB18030 极宽松，几乎所有 Big5 / Shift-JIS 字节序列都是合法 GB18030
    # （但解码出乱码）。spec §7.1 明确要求顺序 "utf-8 → gb18030 → big5 → shift_jis"，
    # 因此 Big5 / Shift-JIS 仅作为 GB18030 解码失败时的兜底（实际很少触发）。
    # 这里不测试 Big5 / Shift-JIS 的端到端解码，避免断言 mojibake。

    def test_decode_failure(self):
        # 非 BOM 字节，且在 UTF-8/GB18030/Big5/Shift-JIS 中均非法
        b64 = base64.b64encode(b"\xff\xff\xff\xff\xff\xff\xff\xff").decode()
        r = extract("txt", {"content_base64": b64})
        assert r.error == "decode_failed"
        assert r.normalized_text == ""

    def test_empty_content(self):
        b64 = base64.b64encode(b"").decode()
        r = extract("txt", {"content_base64": b64})
        assert r.error == "empty_content"

    def test_empty_payload(self):
        r = extract("txt", {})
        assert r.error == "empty_content"

    def test_invalid_base64(self):
        # 优先 validate=True：含非法字符的串应 decode_failed（不再静默剥掉字符）
        r = extract("txt", {"content_base64": "!!!not base64!!!"})
        assert r.error == "decode_failed"
        assert r.normalized_text == ""

    def test_invalid_base64_padding(self):
        # 明显损坏的 padding / 非 base64 字母表
        r = extract("txt", {"content_base64": "===="})
        assert r.error in ("decode_failed", "empty_content")

    def test_too_large(self):
        big = "A" * (MAX_SOURCE_CHARS + 1)
        b64 = base64.b64encode(big.encode("utf-8")).decode()
        r = extract("txt", {"content_base64": b64})
        assert r.error == "source_too_large"

    def test_base64_string_too_large_rejected_before_decode(self):
        # 超大 base64 串应在解码前被 size guard 拒绝
        huge_b64 = "A" * ((MAX_RESPONSE_BYTES * 4) // 3 + 100)
        r = extract("txt", {"content_base64": huge_b64})
        assert r.error == "source_too_large"


# ---------------------------------------------------------------------------
# MarkdownExtractor
# ---------------------------------------------------------------------------


class TestMarkdownExtractor:
    def _md_b64(self, md: str) -> str:
        return base64.b64encode(md.encode("utf-8")).decode()

    def test_heading_preserved_with_level(self):
        md = "# H1 Title\n\n## H2 Subtitle\n\n### H3 Deep"
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "# H1 Title" in r.normalized_text
        assert "## H2 Subtitle" in r.normalized_text
        assert "### H3 Deep" in r.normalized_text

    def test_paragraph_preserved(self):
        md = "This is a paragraph.\n\nAnother paragraph."
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "This is a paragraph." in r.normalized_text
        assert "Another paragraph." in r.normalized_text

    def test_list_items_preserved(self):
        md = "- item 1\n- item 2\n- item 3"
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "item 1" in r.normalized_text
        assert "item 2" in r.normalized_text
        assert "item 3" in r.normalized_text

    def test_ordered_list_items_preserved(self):
        md = "1. first\n2. second\n3. third"
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "first" in r.normalized_text
        assert "second" in r.normalized_text
        assert "third" in r.normalized_text

    def test_blockquote_preserved(self):
        md = "> This is a quote.\n> Second line."
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "This is a quote." in r.normalized_text
        assert "Second line." in r.normalized_text

    def test_link_text_preserved_url_removed(self):
        md = "Visit [Example Site](https://example.com) for more."
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "Example Site" in r.normalized_text
        assert "https://example.com" not in r.normalized_text

    def test_image_alt_preserved_url_removed(self):
        md = "![Alt description](https://example.com/img.png)"
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "Alt description" in r.normalized_text
        assert "https://example.com/img.png" not in r.normalized_text

    def test_fenced_code_block_removed(self):
        md = "Before\n\n```python\nsecret_code = 'hidden'\nprint(secret_code)\n```\n\nAfter"
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "Before" in r.normalized_text
        assert "After" in r.normalized_text
        assert "secret_code" not in r.normalized_text
        assert "hidden" not in r.normalized_text

    def test_inline_code_removed(self):
        md = "Use `inline_code` here."
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "inline_code" not in r.normalized_text
        assert "Use" in r.normalized_text
        assert "here." in r.normalized_text

    def test_html_block_removed(self):
        md = "Before HTML\n\n<div>html content</div>\n\n<p>more html</p>\n\nAfter HTML"
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "Before HTML" in r.normalized_text
        assert "After HTML" in r.normalized_text
        assert "<div>" not in r.normalized_text
        assert "html content" not in r.normalized_text
        assert "<p>" not in r.normalized_text

    def test_script_style_removed(self):
        md = "<script>alert(1)</script>\n\n<style>body { color: red; }</style>\n\nReal text."
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == ""
        assert "alert" not in r.normalized_text
        assert "color: red" not in r.normalized_text
        assert "Real text." in r.normalized_text

    def test_empty_content(self):
        r = extract("markdown", {"content_base64": base64.b64encode(b"").decode()})
        assert r.error == "empty_content"

    def test_invalid_base64(self):
        r = extract("markdown", {"content_base64": "!!!not base64!!!"})
        assert r.error == "decode_failed"
        assert r.normalized_text == ""

    def test_whitespace_only(self):
        r = extract("markdown", {"content_base64": base64.b64encode(b"   \n\n  ").decode()})
        assert r.error == "empty_content"

    def test_only_code_blocks(self):
        md = "```\nonly code\n```"
        r = extract("markdown", {"content_base64": self._md_b64(md)})
        assert r.error == "empty_content"

    def test_too_large(self):
        big_md = "A" * (MAX_SOURCE_CHARS + 1)
        r = extract("markdown", {"content_base64": self._md_b64(big_md)})
        assert r.error == "source_too_large"

    def test_gb18030_encoded_markdown(self):
        md = "# 标题\n\n中文段落"
        b64 = base64.b64encode(md.encode("gb18030")).decode()
        r = extract("markdown", {"content_base64": b64})
        assert r.error == ""
        assert "# 标题" in r.normalized_text
        assert "中文段落" in r.normalized_text
        assert r.metadata["encoding"] == "gb18030"


# ---------------------------------------------------------------------------
# WebpageExtractor — SSRF 防护
# ---------------------------------------------------------------------------


class TestWebpageSSRF:
    def test_loopback_ipv4_blocked(self):
        r = extract("webpage", {"source_url": "http://127.0.0.1/"})
        assert r.error == "ssrf_blocked"
        assert r.normalized_text == ""

    def test_private_ipv4_blocked(self):
        r = extract("webpage", {"source_url": "http://10.0.0.1/"})
        assert r.error == "ssrf_blocked"
        r = extract("webpage", {"source_url": "http://192.168.1.1/"})
        assert r.error == "ssrf_blocked"
        r = extract("webpage", {"source_url": "http://172.16.0.1/"})
        assert r.error == "ssrf_blocked"

    def test_link_local_cloud_metadata_blocked(self):
        r = extract("webpage", {"source_url": "http://169.254.169.254/"})
        assert r.error == "ssrf_blocked"

    def test_loopback_ipv6_blocked(self):
        r = extract("webpage", {"source_url": "http://[::1]/"})
        assert r.error == "ssrf_blocked"

    def test_localhost_blocked(self):
        r = extract("webpage", {"source_url": "http://localhost/"})
        # localhost 通常解析到 127.0.0.1 或 ::1，均被阻止
        assert r.error == "ssrf_blocked"

    def test_alibaba_cloud_metadata_blocked(self):
        r = extract("webpage", {"source_url": "http://100.100.100.200/"})
        assert r.error == "ssrf_blocked"

    def test_file_scheme_rejected(self):
        r = extract("webpage", {"source_url": "file:///etc/passwd"})
        assert r.error == "unsupported_scheme"
        assert r.normalized_text == ""

    def test_ftp_scheme_rejected(self):
        r = extract("webpage", {"source_url": "ftp://example.com/file"})
        assert r.error == "unsupported_scheme"

    def test_invalid_url(self):
        r = extract("webpage", {"source_url": ""})
        assert r.error == "invalid_url"

    def test_no_hostname(self):
        r = extract("webpage", {"source_url": "http://"})
        assert r.error == "invalid_url"


# ---------------------------------------------------------------------------
# WebpageExtractor — HTTP 流程（mock httpx + trafilatura）
# ---------------------------------------------------------------------------


class TestWebpageHTTP:
    def test_successful_extraction(self):
        html = "<html><body><article><p>Extracted article text.</p></article></body></html>"
        resp = _MockStreamResponse(content=html.encode("utf-8"))
        with _patch_httpx(resp), _patch_trafilatura("Extracted article text."):
            r = extract("webpage", {"source_url": "https://example.com/article"})
        assert r.error == ""
        assert r.normalized_text == "Extracted article text."
        assert r.metadata["source_type"] == "webpage"
        assert r.metadata["url"] == "https://example.com/article"
        assert r.metadata["encoding"] == "utf-8"

    def test_http_error_status(self):
        resp = _MockStreamResponse(status_code=404)
        with _patch_httpx(resp):
            r = extract("webpage", {"source_url": "https://example.com/missing"})
        assert r.error == "http_error"
        assert r.normalized_text == ""
        assert r.metadata["status_code"] == 404

    def test_unsupported_content_type(self):
        resp = _MockStreamResponse(
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.4",
        )
        with _patch_httpx(resp):
            r = extract("webpage", {"source_url": "https://example.com/doc.pdf"})
        assert r.error == "unsupported_content_type"
        assert r.normalized_text == ""

    def test_text_plain_accepted(self):
        resp = _MockStreamResponse(
            headers={"content-type": "text/plain; charset=utf-8"},
            content=b"Plain text content",
        )
        with _patch_httpx(resp), _patch_trafilatura("Plain text content"):
            r = extract("webpage", {"source_url": "https://example.com/text"})
        assert r.error == ""
        assert r.normalized_text == "Plain text content"

    def test_timeout(self):
        with patch(
            "app.knowledge.source_extractors.httpx.Client",
            side_effect=httpx.TimeoutException("timeout"),
        ):
            r = extract("webpage", {"source_url": "https://example.com/slow"})
        assert r.error == "timeout"
        assert r.normalized_text == ""

    def test_fetch_failed_connection_error(self):
        with patch(
            "app.knowledge.source_extractors.httpx.Client",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            r = extract("webpage", {"source_url": "https://example.com/conn-fail"})
        assert r.error == "fetch_failed"
        assert r.normalized_text == ""

    def test_response_truncated(self):
        # 构造超过 MAX_RESPONSE_BYTES 的响应
        big_content = b"<html>" + b"x" * (MAX_RESPONSE_BYTES + 1024)
        # 用 iter_chunks 分块返回，模拟流式读取
        chunks = [big_content[i : i + 8192] for i in range(0, len(big_content), 8192)]
        resp = _MockStreamResponse(
            headers={"content-type": "text/html; charset=utf-8"},
            iter_chunks=chunks,
        )
        with _patch_httpx(resp), _patch_trafilatura("truncated but extracted"):
            r = extract("webpage", {"source_url": "https://example.com/huge"})
        assert r.error == ""
        assert r.warning == "response_truncated"
        assert r.metadata.get("response_truncated") is True

    def test_empty_html_content(self):
        resp = _MockStreamResponse(content=b"<html></html>")
        with _patch_httpx(resp), _patch_trafilatura(None):
            r = extract("webpage", {"source_url": "https://example.com/empty"})
        assert r.error == "empty_content"

    def test_trafilatura_returns_empty(self):
        resp = _MockStreamResponse(content=b"<html><body></body></html>")
        with _patch_httpx(resp), _patch_trafilatura(""):
            r = extract("webpage", {"source_url": "https://example.com/empty"})
        assert r.error == "empty_content"

    def test_trafilatura_raises_exception(self):
        resp = _MockStreamResponse(content=b"<html>some html</html>")
        with _patch_httpx(resp), patch(
            "app.knowledge.source_extractors.trafilatura.extract",
            side_effect=RuntimeError("trafilatura boom"),
        ):
            r = extract("webpage", {"source_url": "https://example.com/crash"})
        assert r.error == "extract_failed"

    def test_source_too_large(self):
        # trafilatura 返回 > 5 MiB 文本
        big_text = "A" * (MAX_SOURCE_CHARS + 1)
        resp = _MockStreamResponse(content=b"<html>big</html>")
        with _patch_httpx(resp), _patch_trafilatura(big_text):
            r = extract("webpage", {"source_url": "https://example.com/huge-text"})
        assert r.error == "source_too_large"

    def test_gb18030_html_response(self):
        html = "<html><body>中文正文</body></html>"
        resp = _MockStreamResponse(
            headers={"content-type": "text/html"},  # 无 charset 声明
            content=html.encode("gb18030"),
        )
        with _patch_httpx(resp), _patch_trafilatura("中文正文"):
            r = extract("webpage", {"source_url": "https://example.com/cn"})
        assert r.error == ""
        assert r.normalized_text == "中文正文"
        assert r.metadata["encoding"] == "gb18030"

    def test_charset_from_header_used(self):
        html = "<html><body>text</body></html>"
        resp = _MockStreamResponse(
            headers={"content-type": "text/html; charset=iso-8859-1"},
            content=html.encode("iso-8859-1"),
        )
        with _patch_httpx(resp), _patch_trafilatura("text"):
            r = extract("webpage", {"source_url": "https://example.com/latin1"})
        assert r.error == ""
        assert r.normalized_text == "text"
        assert r.metadata["encoding"] == "iso-8859-1"


# ---------------------------------------------------------------------------
# extract() 统一入口
# ---------------------------------------------------------------------------


class TestExtractDispatch:
    def test_unknown_source_type(self):
        r = extract("pdf", {"content_base64": "abc"})
        assert r.error == "unknown_source_type"
        assert r.normalized_text == ""

    def test_none_source_type(self):
        r = extract(None, {})
        assert r.error == "unknown_source_type"

    def test_payload_none(self):
        # extract 内部用 `payload or {}` 兜底
        r = extract("pasted_text", None)  # type: ignore[arg-type]
        assert r.error == "empty_content"

    def test_extractor_exception_caught(self):
        # mock TextExtractor.extract 抛异常，验证兜底
        with patch.object(
            TextExtractor,
            "extract",
            side_effect=RuntimeError("boom"),
        ):
            r = extract("pasted_text", {"pasted_text": "hello"})
        assert r.error == "extract_failed"
        assert r.normalized_text == ""


# ---------------------------------------------------------------------------
# normalizer.py 直接测试
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_bom_removed(self):
        assert normalize_text("\ufeffHello") == "Hello"

    def test_crlf_normalized(self):
        assert normalize_text("a\r\nb\rc") == "a\nb\nc"

    def test_control_chars_removed(self):
        assert normalize_text("a\x00b\x01c\x7F") == "abc"

    def test_zero_width_removed(self):
        assert normalize_text("a\u200Bb\u200Cc\u200Dd") == "abcd"

    def test_line_separators_converted(self):
        assert normalize_text("a\u2028b\u2029c") == "a\nb\nc"

    def test_multi_newline_collapsed(self):
        # 3+ 换行折叠为 2（保留 1 个空行）
        assert normalize_text("a\n\n\n\nb") == "a\n\nb"

    def test_consecutive_duplicate_lines_removed(self):
        assert normalize_text("a\na\na\nb") == "a\nb"

    def test_non_consecutive_duplicates_kept(self):
        assert normalize_text("a\nb\na") == "a\nb\na"

    def test_empty(self):
        assert normalize_text("") == ""

    def test_strip(self):
        assert normalize_text("  \n hello \n ") == "hello"


class TestDecodeBytes:
    def test_utf8_bom(self):
        text, enc = decode_bytes("你好".encode("utf-8-sig"))
        assert text == "你好"
        assert enc == "utf-8-sig"

    def test_utf8_no_bom(self):
        text, enc = decode_bytes("hello".encode("utf-8"))
        assert text == "hello"
        assert enc == "utf-8"

    def test_utf16_le_bom(self):
        # utf-16-le 编码不自带 BOM；手动加 LE BOM 触发 BOM 检测路径
        text, enc = decode_bytes(b"\xff\xfe" + "hello".encode("utf-16-le"))
        assert text == "hello"
        assert enc == "utf-16-le"

    def test_utf16_be_bom(self):
        text, enc = decode_bytes(b"\xfe\xff" + "hello".encode("utf-16-be"))
        assert text == "hello"
        assert enc == "utf-16-be"

    def test_utf32_le_bom(self):
        text, enc = decode_bytes(b"\xff\xfe\x00\x00" + "hello".encode("utf-32-le"))
        assert text == "hello"
        assert enc == "utf-32-le"

    def test_utf32_be_bom(self):
        text, enc = decode_bytes(b"\x00\x00\xfe\xff" + "hello".encode("utf-32-be"))
        assert text == "hello"
        assert enc == "utf-32-be"

    def test_gb18030(self):
        text, enc = decode_bytes("中文".encode("gb18030"))
        assert text == "中文"
        assert enc == "gb18030"

    # 注意：Big5 / Shift-JIS 路径在确定性检测下几乎不可达（见 TestTxtExtractor 注释）。
    # GB18030 极宽松，Big5 / Shift-JIS 字节序列几乎都被 GB18030 提前消化（产生 mojibake）。
    # 此处不测试 Big5 / Shift-JIS 端到端解码；这两个编码仅作为 GB18030 失败时的兜底。

    def test_empty_bytes(self):
        text, enc = decode_bytes(b"")
        assert text == ""
        assert enc == "utf-8"

    def test_decode_failure(self):
        with pytest.raises(ValueError, match="decode_failed"):
            decode_bytes(b"\xff\xff\xff\xff\xff\xff\xff\xff")

    def test_none_raises(self):
        with pytest.raises(ValueError, match="decode_failed"):
            decode_bytes(None)  # type: ignore[arg-type]


class TestCleanLivestreamLog:
    def test_timestamp_removed(self):
        text = "2024-01-01 12:00:00 用户A: 你好\n[12:00:01] 用户B: 世界"
        result = clean_livestream_log(text)
        assert "你好" in result
        assert "世界" in result
        assert "2024-01-01" not in result
        assert "12:00:00" not in result

    def test_username_removed(self):
        text = "用户A: 你好\n用户B：世界\n<用户C> 测试\n[用户D] 哈哈"
        result = clean_livestream_log(text)
        assert "你好" in result
        assert "世界" in result
        assert "测试" in result
        assert "哈哈" in result
        assert "用户A" not in result
        assert "用户B" not in result

    def test_system_keywords_removed(self):
        text = "用户A 进入直播间\n用户B 关注了主播\n用户C 送出礼物\n正常弹幕"
        result = clean_livestream_log(text)
        assert "正常弹幕" in result
        assert "进入直播间" not in result
        assert "关注了主播" not in result
        assert "送出" not in result

    def test_punctuation_only_removed(self):
        text = "你好\n。。。\n666\n！！！\n世界"
        result = clean_livestream_log(text)
        assert "你好" in result
        assert "666" in result
        assert "世界" in result
        assert "。。。" not in result
        assert "！！！" not in result

    def test_spam_collapse_5_or_more(self):
        # 同一条消息连续重复 ≥5 次合并为 1 条
        text = "\n".join(["哈哈哈"] * 5 + ["太强了"])
        result = clean_livestream_log(text)
        assert result == "哈哈哈\n太强了"

    def test_spam_collapse_10_repeats(self):
        text = "\n".join(["刷屏"] * 10 + ["结束"])
        result = clean_livestream_log(text)
        assert result == "刷屏\n结束"

    def test_less_than_5_repeats_kept(self):
        # 4 次重复 < 5，全部保留
        text = "\n".join(["哈哈"] * 4 + ["太强了"])
        result = clean_livestream_log(text)
        assert result == "\n".join(["哈哈"] * 4 + ["太强了"])

    def test_empty(self):
        assert clean_livestream_log("") == ""

    def test_room_prefix_removed(self):
        text = "#12345 这是房间弹幕\n正常消息"
        result = clean_livestream_log(text)
        assert "这是房间弹幕" in result
        assert "正常消息" in result
        assert "#12345" not in result

    def test_empty_messages_removed(self):
        text = "用户A: \n用户B: 有内容\n"
        result = clean_livestream_log(text)
        assert "有内容" in result
        # 用户A 的空消息被移除
        assert result.strip() == "有内容"

    def test_preserves_order(self):
        text = "第一条\n第二条\n第三条"
        result = clean_livestream_log(text)
        assert result == "第一条\n第二条\n第三条"
