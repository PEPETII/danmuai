"""网页 extractor 的逐跳 redirect SSRF 回归测试。

所有 HTTP 响应都由本地 mock client 提供；DNS 也在测试内固定到公开测试地址，
因此不会访问真实 loopback、私网、metadata、云地址或外部网页。
"""
from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from app.knowledge import source_extractors
from app.knowledge.source_extractors import MAX_REDIRECTS, MAX_RESPONSE_BYTES, extract


class _MockStreamResponse:
    def __init__(
        self,
        *,
        url: str,
        status_code: int,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
        iter_chunks: list[bytes] | None = None,
    ):
        self.url = url
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content
        self._iter_chunks = iter_chunks

    @property
    def charset_encoding(self) -> str | None:
        content_type = self.headers.get("content-type", "")
        if "charset=" not in content_type:
            return None
        return content_type.split("charset=", 1)[1].split(";", 1)[0].strip()

    def iter_bytes(self, chunk_size: int = 8192):
        if self._iter_chunks is not None:
            yield from self._iter_chunks
            return
        for offset in range(0, len(self._content), chunk_size):
            yield self._content[offset : offset + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RedirectClient:
    def __init__(self, routes: dict[str, _MockStreamResponse], **kwargs):
        self.routes = routes
        self.kwargs = kwargs
        self.calls: list[tuple[str, str]] = []

    def stream(self, method: str, url: str):
        self.calls.append((method, url))
        if url not in self.routes:
            raise AssertionError(f"unexpected mocked request: {method} {url}")
        return self.routes[url]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_getaddrinfo(host: str, port, *args, **kwargs):
    if host in {"public.test", "final.test"}:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 0),
            )
        ]
    raise socket.gaierror(host)


@pytest.fixture
def no_real_dns():
    with patch.object(
        source_extractors.socket,
        "getaddrinfo",
        side_effect=_fake_getaddrinfo,
    ):
        yield


@pytest.mark.parametrize(
    "redirect_location, expected_error",
    [
        ("http://127.0.0.1/private", "ssrf_blocked"),
        ("http://10.0.0.1/private", "ssrf_blocked"),
        ("http://169.254.169.254/latest/meta-data", "ssrf_blocked"),
        ("file:///etc/passwd", "unsupported_scheme"),
        ("http://[::1", "invalid_url"),
    ],
)
def test_redirect_target_is_validated_before_request(
    no_real_dns,
    redirect_location: str,
    expected_error: str,
):
    source_url = "https://public.test/start"
    client = _RedirectClient(
        {
            source_url: _MockStreamResponse(
                url=source_url,
                status_code=302,
                headers={"Location": redirect_location},
            )
        }
    )

    with patch.object(source_extractors.httpx, "Client", return_value=client):
        result = extract("webpage", {"source_url": source_url})

    assert result.error == expected_error
    assert result.metadata["redirect_url"] == redirect_location
    assert client.calls == [("GET", source_url)]


def test_allowed_redirects_are_checked_each_hop_and_final_url_is_recorded(no_real_dns):
    source_url = "https://public.test/start"
    middle_url = "https://public.test/middle"
    final_url = "https://final.test/article"
    client = _RedirectClient(
        {
            source_url: _MockStreamResponse(
                url=source_url,
                status_code=302,
                headers={"Location": "/middle"},
            ),
            middle_url: _MockStreamResponse(
                url=middle_url,
                status_code=307,
                headers={"Location": final_url},
            ),
            final_url: _MockStreamResponse(
                url=final_url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"<html><body>article</body></html>",
            ),
        }
    )

    def make_client(**kwargs):
        client.kwargs = kwargs
        return client

    with (
        patch.object(source_extractors.httpx, "Client", side_effect=make_client),
        patch.object(source_extractors.trafilatura, "extract", return_value="article"),
    ):
        result = extract("webpage", {"source_url": source_url})

    assert result.error == ""
    assert result.normalized_text == "article"
    assert result.metadata["url"] == source_url
    assert result.metadata["final_url"] == final_url
    assert client.calls == [
        ("GET", source_url),
        ("GET", middle_url),
        ("GET", final_url),
    ]
    assert client.kwargs["follow_redirects"] is False
    assert client.kwargs["max_redirects"] == MAX_REDIRECTS


def test_blocked_final_response_url_is_rejected(no_real_dns):
    source_url = "https://public.test/start"
    client = _RedirectClient(
        {
            source_url: _MockStreamResponse(
                url="http://127.0.0.1/final",
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"should not be extracted",
            )
        }
    )

    with patch.object(source_extractors.httpx, "Client", return_value=client):
        result = extract("webpage", {"source_url": source_url})

    assert result.error == "ssrf_blocked"
    assert result.metadata["final_url"] == "http://127.0.0.1/final"
    assert client.calls == [("GET", source_url)]


def test_redirect_limit_is_enforced_before_next_request(no_real_dns):
    source_url = "https://public.test/start"
    hop1_url = "https://public.test/hop1"
    hop2_url = "https://public.test/hop2"
    hop3_url = "https://public.test/hop3"
    client = _RedirectClient(
        {
            source_url: _MockStreamResponse(
                url=source_url,
                status_code=302,
                headers={"Location": hop1_url},
            ),
            hop1_url: _MockStreamResponse(
                url=hop1_url,
                status_code=302,
                headers={"Location": hop2_url},
            ),
            hop2_url: _MockStreamResponse(
                url=hop2_url,
                status_code=302,
                headers={"Location": hop3_url},
            ),
        }
    )

    with (
        patch.object(source_extractors, "MAX_REDIRECTS", 2),
        patch.object(source_extractors.httpx, "Client", return_value=client),
    ):
        result = extract("webpage", {"source_url": source_url})

    assert result.error == "redirect_limit_exceeded"
    assert result.metadata["redirect_count"] == 2
    assert client.calls == [
        ("GET", source_url),
        ("GET", hop1_url),
        ("GET", hop2_url),
    ]


def test_final_response_size_limit_remains_streamed_after_redirect(no_real_dns):
    source_url = "https://public.test/start"
    final_url = "https://final.test/large"
    large_content = b"<html>" + b"x" * (MAX_RESPONSE_BYTES + 1)
    client = _RedirectClient(
        {
            source_url: _MockStreamResponse(
                url=source_url,
                status_code=302,
                headers={"Location": final_url},
            ),
            final_url: _MockStreamResponse(
                url=final_url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                iter_chunks=[large_content[:8192], large_content[8192:]],
            ),
        }
    )

    with (
        patch.object(source_extractors.httpx, "Client", return_value=client),
        patch.object(
            source_extractors.trafilatura,
            "extract",
            return_value="truncated article",
        ),
    ):
        result = extract("webpage", {"source_url": source_url})

    assert result.error == ""
    assert result.warning == "response_truncated"
    assert result.metadata["response_truncated"] is True
    assert result.metadata["final_url"] == final_url
