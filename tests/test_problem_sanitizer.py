"""Tests for technical detail sanitizer."""

from app.problems.sanitizer import sanitize_context, sanitize_technical_detail


def test_sanitize_technical_detail_masks_api_key():
    raw = "Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz1234567890"
    cleaned = sanitize_technical_detail(raw)
    assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in cleaned
    assert "Authorization" in cleaned or "[REDACTED]" in cleaned


def test_sanitize_technical_detail_truncates_to_1000_chars():
    raw = "x" * 1500
    cleaned = sanitize_technical_detail(raw)
    assert len(cleaned) <= 1000


def test_sanitize_context_removes_sensitive_keys():
    context = sanitize_context(
        {
            "provider_id": "openai",
            "api_key": "sk-secret",
            "authorization": "Bearer token",
            "status_code": 401,
        }
    )
    assert context == {"provider_id": "openai", "status_code": 401}
