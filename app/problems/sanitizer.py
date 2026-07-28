"""Sanitize technical problem details before exposing them in status snapshots."""

from __future__ import annotations

from app.logger import sanitize_sensitive_text

TECHNICAL_DETAIL_MAX_LEN = 1000

_SENSITIVE_CONTEXT_KEYS = frozenset({
    "api_key",
    "authorization",
    "session_token",
    "cookie",
    "raw_request_body",
    "image_data_uri",
})


def sanitize_technical_detail(text: str, *, max_len: int = TECHNICAL_DETAIL_MAX_LEN) -> str:
    cleaned = sanitize_sensitive_text(str(text or "").strip(), max_len=max_len)
    if len(cleaned) > max_len:
        return cleaned[:max_len]
    return cleaned


def sanitize_context(context: dict | None) -> dict:
    if not context:
        return {}
    safe: dict = {}
    for key, value in context.items():
        key_text = str(key)
        if key_text.lower() in _SENSITIVE_CONTEXT_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key_text] = value
        elif isinstance(value, (list, tuple)):
            safe[key_text] = [
                item
                for item in value
                if isinstance(item, (str, int, float, bool)) or item is None
            ]
    return safe
