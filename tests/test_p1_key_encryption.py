"""
P1-002 / P1-003 测试：API Key 加密 fail-closed 与密钥损坏恢复

覆盖：
1. Fernet 不可用时拒绝写入敏感字段
2. legacy base64 只读回退与告警
3. Key 文件损坏时生成新密钥并警告
4. Key 文件丢失时生成新密钥
5. 解密失败时警告
"""

import logging
from base64 import b64encode
from unittest.mock import patch

import pytest
from app.config_store import (
    ConfigStore,
    ConfigStoreCryptoUnavailableError,
    _HAS_CRYPTO,
)


@pytest.fixture
def temp_config_dir(tmp_path):
    """创建临时配置目录"""
    config_dir = tmp_path / "DanmuAI"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def mock_no_crypto():
    """模拟 cryptography 不可用"""
    with patch("app.config_store._HAS_CRYPTO", False):
        yield


class TestP1002_CryptoFailClosed:
    """P1-002: cryptography 不可用时拒绝写入，legacy base64 仍可只读。"""

    def test_warning_when_cryptography_not_available_on_init(self, temp_config_dir, mock_no_crypto):
        """测试 cryptography 不可用时初始化发出警告"""
        with self._capture_logs() as log_messages:
            store = ConfigStore(db_path=temp_config_dir / "config.db")

        assert any("cryptography" in msg.lower() for msg in log_messages)
        assert not store.secrets_storage_available

    def test_set_api_key_raises_without_crypto(self, temp_config_dir, mock_no_crypto):
        """测试设置 API Key 时无 cryptography 应拒绝写入"""
        store = ConfigStore(db_path=temp_config_dir / "config.db")

        with pytest.raises(ConfigStoreCryptoUnavailableError):
            store.set_api_key("test-api-key-123")

    def test_warning_when_reading_base64_encoded_key(self, temp_config_dir, mock_no_crypto):
        """测试读取 legacy base64 编码的 API Key 时仍可解码并发出告警"""
        store = ConfigStore(db_path=temp_config_dir / "config.db")
        encoded = b64encode(b"test-api-key").decode()
        store.conn.execute(
            "REPLACE INTO config (key, value) VALUES (?, ?)",
            ("api_key_encoded", encoded),
        )
        store.conn.commit()
        store._cache["api_key_encoded"] = encoded
        store.close()

        with self._capture_logs() as log_messages:
            store2 = ConfigStore(db_path=temp_config_dir / "config.db")
            key = store2.get_api_key()

        assert key == "test-api-key"
        assert any("base64" in msg.lower() or "不安全" in msg for msg in log_messages)

    def test_startup_notice_when_crypto_unavailable(self, temp_config_dir, mock_no_crypto):
        store = ConfigStore(db_path=temp_config_dir / "config.db")
        notice = store.get_startup_notice()
        assert "cryptography" in notice.lower() or "加密" in notice

    def test_set_encoded_key_raises_without_crypto(self, temp_config_dir, mock_no_crypto):
        store = ConfigStore(db_path=temp_config_dir / "config.db")
        with pytest.raises(ConfigStoreCryptoUnavailableError):
            store.set("api_key_encoded", b64encode(b"secret").decode())

    @staticmethod
    def _capture_logs():
        """捕获日志的上下文管理器"""

        class LogCapture(logging.Handler):
            def __init__(self):
                super().__init__()
                self.messages = []

            def emit(self, record):
                self.messages.append(self.format(record))

        handler = LogCapture()
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger("app.config_store")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)

        class CaptureContext:
            def __enter__(self):
                return handler.messages

            def __exit__(self, *args):
                logger.removeHandler(handler)

        return CaptureContext()


class TestP1003_KeyFileCorruptionRecovery:
    """P1-003: Key 文件损坏或丢失时应有恢复提示"""

    def test_warning_when_key_file_corrupted(self, temp_config_dir):
        """测试 Key 文件损坏时发出警告并生成新密钥"""
        if not _HAS_CRYPTO:
            pytest.skip("cryptography not available")

        from cryptography.fernet import Fernet

        # 写入损坏的 key 文件
        key_file = temp_config_dir / ".key"
        key_file.write_bytes(b"this-is-not-a-valid-fernet-key")

        with self._capture_logs() as log_messages:
            store = ConfigStore(db_path=temp_config_dir / "config.db")

        # 应该有密钥损坏警告
        assert any("损坏" in msg or "corrupted" in msg.lower() for msg in log_messages)

        # 新 key 文件应该已生成
        assert key_file.exists()
        # 新生成的 key 应该有效
        key_bytes = key_file.read_bytes()
        f = Fernet(key_bytes)
        # 验证可以正常加解密
        encrypted = f.encrypt(b"test")
        decrypted = f.decrypt(encrypted)
        assert decrypted == b"test"

    def test_new_key_generated_when_missing(self, temp_config_dir):
        """测试 Key 文件丢失时生成新密钥"""
        if not _HAS_CRYPTO:
            pytest.skip("cryptography not available")

        from cryptography.fernet import Fernet

        # 确保 key 文件不存在
        key_file = temp_config_dir / ".key"
        if key_file.exists():
            key_file.unlink()

        store = ConfigStore(db_path=temp_config_dir / "config.db")

        # 新 key 文件应该已生成
        assert key_file.exists()

        # 新生成的 key 应该有效
        key_bytes = key_file.read_bytes()
        f = Fernet(key_bytes)
        encrypted = f.encrypt(b"test-data")
        assert f.decrypt(encrypted) == b"test-data"

    def test_no_crash_when_key_corrupted_and_reading_old_encrypted_data(self, temp_config_dir):
        """测试 Key 损坏后读取旧加密数据不会崩溃"""
        if not _HAS_CRYPTO:
            pytest.skip("cryptography not available")

        from cryptography.fernet import Fernet

        # 生成第一个密钥并加密存储 API Key
        key1 = Fernet.generate_key()
        key_file = temp_config_dir / ".key"
        key_file.write_bytes(key1)

        store1 = ConfigStore(db_path=temp_config_dir / "config.db")
        store1.set_api_key("original-secret-key")
        assert store1.get_api_key() == "original-secret-key"
        store1.close()

        # 损坏 key 文件
        key_file.write_bytes(b"corrupted-key-data")

        # 重新加载 - 不应该崩溃
        with self._capture_logs() as log_messages:
            store2 = ConfigStore(db_path=temp_config_dir / "config.db")

            # 旧加密数据应该无法读取（返回空）
            key = store2.get_api_key()
            assert key == ""  # 旧数据无法用新密钥解密

        # 应该有相关警告
        assert len(log_messages) > 0

    def test_decryption_failure_shows_clear_message(self, temp_config_dir):
        """测试解密失败时显示明确提示"""
        if not _HAS_CRYPTO:
            pytest.skip("cryptography not available")

        from cryptography.fernet import Fernet

        # 生成有效密钥
        key = Fernet.generate_key()
        key_file = temp_config_dir / ".key"
        key_file.write_bytes(key)

        store = ConfigStore(db_path=temp_config_dir / "config.db")

        # 手动写入无效的加密数据
        store.set("api_key_encrypted", "not-valid-encrypted-data")

        with self._capture_logs() as log_messages:
            result = store.get_api_key()

        # 应该返回空字符串
        assert result == ""

        # 应该有解密失败警告
        assert any("解密失败" in msg or "decrypt" in msg.lower() for msg in log_messages)

    def test_decrypt_failure_with_legacy_base64_keeps_old_key(self, temp_config_dir):
        """加密值损坏但 legacy base64 仍在时，应继续回退读取旧 key。"""
        if not _HAS_CRYPTO:
            pytest.skip("cryptography not available")

        store = ConfigStore(db_path=temp_config_dir / "config.db")
        store.set("api_key_encrypted", "not-valid-encrypted-data")
        store.set("api_key_encoded", "bGVnYWN5LXNlY3JldC1rZXk=")

        with self._capture_logs() as log_messages:
            result = store.get_api_key()

        assert result == "legacy-secret-key"
        assert any("解密失败" in msg or "decrypt" in msg.lower() for msg in log_messages)

    @staticmethod
    def _capture_logs():
        """捕获日志的上下文管理器"""

        class LogCapture(logging.Handler):
            def __init__(self):
                super().__init__()
                self.messages = []

            def emit(self, record):
                self.messages.append(self.format(record))

        handler = LogCapture()
        handler.setLevel(logging.WARNING)
        logger = logging.getLogger("app.config_store")
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)

        class CaptureContext:
            def __enter__(self):
                return handler.messages

            def __exit__(self, *args):
                logger.removeHandler(handler)

        return CaptureContext()
