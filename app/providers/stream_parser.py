"""Stream response parsing facade (Batch 3).

Delegates to existing OpenAI / Doubao stream modules; centralizes parser selection.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import httpx

from app.providers.capabilities import ProviderCapabilities
from app.providers.endpoint_resolver import API_FAMILY_OPENAI_CHAT, API_FAMILY_OPENAI_RESPONSES


def parser_id_for_api_family(api_family: str) -> str:
    if api_family == API_FAMILY_OPENAI_RESPONSES:
        return "doubao_responses_sse"
    if api_family == API_FAMILY_OPENAI_CHAT:
        return "openai_chat_sse"
    return "openai_chat_sse"


def usage_normalizer_id_for_caps(caps: ProviderCapabilities) -> str:
    return caps.usage_token_style or "openai"


def consume_openai_chat_stream(
    lines: Iterable[Any],
    *,
    adapter,
    caps: ProviderCapabilities,
    deadline_at: float | None = None,
    first_content_timeout: float | None = None,
    started_at: float | None = None,
    stopping: Callable[[], bool] | None = None,
    endpoint: str = "",
    url: str = "",
):
    from app.openai_chat_stream import consume_openai_sse_lines

    return consume_openai_sse_lines(
        lines,
        adapter=adapter,
        caps=caps,
        deadline_at=deadline_at,
        first_content_timeout=first_content_timeout,
        started_at=started_at,
        stopping=stopping,
        endpoint=endpoint,
        url=url,
    )


def stream_openai_chat_request(
    http_client: httpx.Client,
    url: str,
    headers: dict,
    data: dict,
    *,
    adapter,
    caps: ProviderCapabilities,
    endpoint: str = "",
    deadline_at: float | None = None,
    first_content_timeout: float | None = None,
    started_at: float | None = None,
    stopping: Callable[[], bool] | None = None,
):
    from app.openai_chat_stream import stream_openai_chat

    return stream_openai_chat(
        http_client,
        url,
        headers,
        data,
        endpoint=endpoint,
        api_mode="",
        deadline_at=deadline_at,
        first_content_timeout=first_content_timeout,
        started_at=started_at,
        stopping=stopping,
    )
