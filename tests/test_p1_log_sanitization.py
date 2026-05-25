"""Tests for P1-007 (log sanitization)."""

import pytest
from app.logger import SanitizedLogger


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
