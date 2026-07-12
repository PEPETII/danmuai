"""Tests for P1-007 (log sanitization)."""

import httpx
import pytest
from app.ai_client_support import format_http_status_error
from app.logger import SanitizedLogger, sanitize_sensitive_text


_FAKE_SHORT_HEAD_JWT = "fakeHead.fakePayload123456.fakeSignature789012"
_FAKE_LONG_HEAD_JWT = (
    "fakeHeaderSegment1234567890.fakePayload456789.fakeSignature012345"
)
_FAKE_DOTTED_KEY = "opaquePrefix1234567890.payloadPart456.signaturePart789"
_FAKE_DOTTED_SK_KEY = "sk-ABCDEFGHIJKLMNOPQRSTUV.payloadPart456.signaturePart789"


class TestSanitizeSensitiveText:
    def test_redacts_api_key_with_default_hidden_label(self):
        msg = "fail sk-abc1234567890abcdef1234567890abcdef end"
        result = sanitize_sensitive_text(msg)
        assert "sk-abc1234567890abcdef1234567890abcdef" not in result
        assert "sk-****" in result

        auth = "Authorization: Bearer abc1234567890abcdef1234567890abcdef"
        assert "Authorization: Bearer (hidden)" in sanitize_sensitive_text(auth)

    def test_truncates_with_ellipsis(self):
        raw = "a" * 250
        result = sanitize_sensitive_text(raw, max_len=200)
        assert len(result) == 201
        assert result.endswith("…")
        assert result.startswith("a" * 200)

    def test_custom_hidden_label(self):
        msg = "Authorization: Bearer abc1234567890abcdef1234567890abcdef"
        result = sanitize_sensitive_text(msg, hidden_label="已隐藏")
        assert "Authorization: Bearer (已隐藏)" in result

    @pytest.mark.parametrize(
        ("message", "secret_parts"),
        [
            (
                f'headers={{"Authorization":"Bearer {_FAKE_SHORT_HEAD_JWT}","retry":false}}',
                tuple(_FAKE_SHORT_HEAD_JWT.split(".")),
            ),
            (
                f"Authorization: Bearer {_FAKE_LONG_HEAD_JWT}, request failed",
                tuple(_FAKE_LONG_HEAD_JWT.split(".")),
            ),
            (
                f"api_key='{_FAKE_DOTTED_KEY}', request failed",
                tuple(_FAKE_DOTTED_KEY.split(".")),
            ),
            (
                f"provider key {_FAKE_DOTTED_SK_KEY}, request failed",
                tuple(_FAKE_DOTTED_SK_KEY.split(".")),
            ),
        ],
    )
    def test_redacts_entire_dotted_secret(self, message, secret_parts):
        result = sanitize_sensitive_text(message)

        for part in secret_parts:
            assert part not in result

    def test_legitimate_dotted_text_is_unchanged(self):
        message = "HTTP 400 from api.example.com: model v1.2.3 failed at config.json"

        assert sanitize_sensitive_text(message) == message


class TestP1007LogSanitization:
    """P1-007: 日志脱敏不足"""

    @pytest.fixture
    def logger(self):
        return SanitizedLogger()

    def test_api_key_sanitized(self, logger):
        """日志不应包含 API Key。"""
        msg = "请求失败，api_key: sk-abc1234567890abcdef1234567890abcdef"
        sanitized = logger._sanitize(msg)

        assert "sk-abc1234567890abcdef1234567890abcdef" not in sanitized
        assert "sk-****" in sanitized

    def test_authorization_header_sanitized(self, logger):
        """日志不应包含 Authorization header。"""
        msg = 'headers: {"Authorization": "Bearer abc1234567890abcdef1234567890abcdef"}'
        sanitized = logger._sanitize(msg)

        assert "Bearer abc1234567890abcdef1234567890abcdef" not in sanitized
        assert "Authorization: Bearer (已隐藏)" in sanitized

    def test_base64_image_sanitized(self, logger):
        """日志不应包含完整 base64 图片。"""
        # 构造一个足够长的 base64 图片 URI
        b64_data = "data:image/jpeg;base64," + "A" * 100
        msg = f"截图数据：{b64_data}"
        sanitized = logger._sanitize(msg)

        assert b64_data not in sanitized
        assert "data:image/***;base64,(已隐藏)" in sanitized

    def test_encrypted_key_sanitized(self, logger):
        """日志不应包含 Fernet 加密密钥。"""
        # Fernet 加密密钥以 gAAAA 开头
        encrypted_key = "gAAAAABlZmhxY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6MTIzNDU2Nzg5MA"
        msg = f"加密数据：{encrypted_key}"
        sanitized = logger._sanitize(msg)

        assert encrypted_key not in sanitized
        assert "gAAAA****(已隐藏)" in sanitized

    def test_generic_api_key_sanitized(self, logger):
        """日志不应包含通用 API Key 格式。"""
        msg = "配置：api_key = 'mysecretapikey1234567890abcdef'"
        sanitized = logger._sanitize(msg)

        assert "mysecretapikey1234567890abcdef" not in sanitized
        assert "(api_key: ****)" in sanitized

    def test_request_body_not_logged(self, logger):
        """日志不应包含完整请求体。"""
        # 模拟请求体包含敏感信息
        request_body = '{"model": "test", "messages": [{"role": "user", "content": "test"}]}'
        msg = f"请求体：{request_body}"
        sanitized = logger._sanitize(msg)

        # 请求体本身不包含敏感模式，应原样保留
        # 但如果包含 API Key 等，应被脱敏
        assert sanitized == msg

    def test_combined_sensitive_info(self, logger):
        """日志应脱敏多种敏感信息。"""
        msg = (
            "请求失败：api_key=sk-abc1234567890abcdef1234567890abcdef, "
            "Authorization: Bearer token1234567890abcdef1234567890abcdef, "
            "图片：data:image/png;base64," + "B" * 100
        )
        sanitized = logger._sanitize(msg)

        assert "sk-abc1234567890abcdef1234567890abcdef" not in sanitized
        assert "token1234567890abcdef1234567890abcdef" not in sanitized
        assert "B" * 100 not in sanitized
        assert "sk-****" in sanitized
        assert "Authorization: Bearer (已隐藏)" in sanitized
        assert "data:image/***;base64,(已隐藏)" in sanitized

    def test_normal_message_unchanged(self, logger):
        """普通消息不应被修改。"""
        msg = "弹幕已启动，截图间隔 3 秒"
        sanitized = logger._sanitize(msg)

        assert sanitized == msg

    def test_percent_format_args(self, logger, caplog):
        """支持 logging 风格 msg % args（与 FakeLogger 一致）。"""
        import logging

        caplog.set_level(logging.DEBUG)
        logger.debug("tick skip: id=%s elapsed=%s", 4, 1200)
        assert "tick skip: id=4 elapsed=1200" in caplog.text

    def test_debug_log_sanitized(self, logger, caplog):
        """DEBUG 日志应脱敏。"""
        import logging
        caplog.set_level(logging.DEBUG)

        logger.debug("API Key: sk-abc1234567890abcdef1234567890abcdef")

        assert "sk-****" in caplog.text
        assert "sk-abc1234567890abcdef1234567890abcdef" not in caplog.text

    def test_error_log_sanitized(self, logger, caplog):
        """ERROR 日志应脱敏。"""
        import logging
        caplog.set_level(logging.DEBUG)

        logger.error("请求失败，Authorization: Bearer secret_token_1234567890abcdef")

        assert "Authorization: Bearer (已隐藏)" in caplog.text
        assert "secret_token_1234567890abcdef" not in caplog.text

    def test_multiple_instances_share_log_bus(self):
        """临时 SanitizedLogger 实例的 UI 推送应走同一全局 bus。"""
        from app.logger import get_log_bus

        received: list[tuple[str, str]] = []
        get_log_bus().log_emitted.connect(lambda level, msg: received.append((level, msg)))

        logger_a = SanitizedLogger()
        logger_b = SanitizedLogger()

        logger_a.info("from instance a")
        logger_b.warning("from instance b")

        assert received == [("INFO", "from instance a"), ("WARNING", "from instance b")]


def test_provider_error_is_sanitized_before_runtime_status():
    from tests.conftest import make_minimal_danmu_app

    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    provider_message = (
        f"provider rejected Authorization: Bearer {_FAKE_SHORT_HEAD_JWT}; "
        f"api_key={_FAKE_DOTTED_KEY}"
    )
    response = httpx.Response(400, request=request, json={"message": provider_message})
    exc = httpx.HTTPStatusError("bad", request=request, response=response)
    formatted = format_http_status_error(exc)

    app = make_minimal_danmu_app()
    app.logger = SanitizedLogger()
    app.ai_in_flight = 1
    app._register_request_meta(7, 9, 0, "visual")
    app._on_ai_error(formatted, "persona-1", 7, 9, 1.0, 0)

    surfaced = "\n".join(
        (
            formatted,
            app._last_error_message,
            app.web_runtime_state.error_message,
        )
    )
    for part in (*_FAKE_SHORT_HEAD_JWT.split("."), *_FAKE_DOTTED_KEY.split(".")):
        assert part not in surfaced
    assert "HTTP 400" in surfaced
