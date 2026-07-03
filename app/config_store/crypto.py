"""ConfigStore 子包：Fernet 加密、密钥管理与自定义模型 shape 迁移辅助。

从原 ``app/config_store.py`` 拆分而来；本模块仅含不依赖 ConfigStore 实例状态的
独立函数与异常类。密钥丢失 / 损坏恢复策略见 ``storage.py`` 模块 docstring。
"""
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path

from app.errors import ConfigError
from app.translations import tr

logger = logging.getLogger(__name__)


def _restrict_key_file_permissions(path: Path) -> None:
    """Set file permissions so only the owner can read/write (best-effort)."""
    if os.name == "nt":
        username = os.environ.get("USERNAME", "")
        if not username:
            logger.warning(tr("config.key_acl_failed").format(path=path))
            return
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:F"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(tr("config.key_acl_failed").format(path=path))
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        logger.warning(tr("config.key_acl_failed").format(path=path))


def _backup_corrupted_key_file(key_dir: Path, raw_bytes: bytes) -> Path | None:
    """Best-effort backup of a corrupted .key before regeneration."""
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_path = key_dir / f".key.bak.{timestamp}"
    try:
        backup_path.write_bytes(raw_bytes)
        _restrict_key_file_permissions(backup_path)
        return backup_path
    except OSError as exc:
        logger.warning(
            tr("config.key_backup_failed").format(path=backup_path, error=exc)
        )
        return None


def _migrate_custom_model_shape(entry: dict) -> dict:
    """W-CUSTOMMODEL-SCHEMA-002: 将旧 shape（modelId 单值）迁移为新 shape（model_ids 数组 + default_model_id + max_tokens）。

    迁移规则：
    - 幂等：检测到 ``model_ids`` 已存在（list 类型）则跳过迁移，仅补齐 ``max_tokens``。
    - 旧 ``modelId`` 字段保留不删（兼容回滚）。
    - ``model_ids = [modelId]``（过滤空值；旧 modelId 也为空则 ``[]``）。
    - ``default_model_id = modelId``。
    - ``max_tokens`` 默认 512（与 ``app.main_helpers.resolve_danmu_max_output_tokens`` 下限一致）。

    不写回 DB；新 shape 在下次 ``set_custom_models`` 调用时自然持久化。
    """
    existing = entry.get("model_ids")
    if isinstance(existing, list):
        # 已迁移；补齐 max_tokens（防御性）
        if not isinstance(entry.get("max_tokens"), int):
            entry["max_tokens"] = 512
        return entry
    legacy_model_id = (entry.get("modelId") or "").strip()
    entry["model_ids"] = [legacy_model_id] if legacy_model_id else []
    entry["default_model_id"] = legacy_model_id
    if not isinstance(entry.get("max_tokens"), int):
        entry["max_tokens"] = 512
    return entry


class ConfigStoreCryptoUnavailableError(ConfigError):
    """Sensitive config cannot be stored without Fernet."""
