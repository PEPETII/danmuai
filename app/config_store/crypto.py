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


_DEFAULT_MAX_TOKENS = 512


def _resolve_model_ids(entry: dict) -> list[str]:
    """从单条档案快照解析 model_ids；不伪造缺失的模型 ID。"""
    existing = entry.get("model_ids")
    if isinstance(existing, list):
        return [str(mid).strip() for mid in existing if str(mid or "").strip()]
    legacy = (entry.get("modelId") or entry.get("model_id") or "").strip()
    return [legacy] if legacy else []


def _resolve_default_model_id(entry: dict, model_ids: list[str]) -> str:
    """解析 default_model_id；新 shape 已含 model_ids list 时保留原 default_model_id。"""
    if isinstance(entry.get("model_ids"), list):
        raw = entry.get("default_model_id")
        if raw is None:
            return ""
        return str(raw).strip()
    legacy = (entry.get("modelId") or entry.get("model_id") or "").strip()
    if legacy:
        return legacy
    if model_ids:
        return model_ids[0]
    raw = entry.get("default_model_id")
    if raw is not None:
        return str(raw).strip()
    return ""


def _resolve_max_tokens(entry: dict) -> int:
    """解析 max_tokens；无效或缺失时默认 512。"""
    raw = entry.get("max_tokens")
    if isinstance(raw, int):
        return raw
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return _DEFAULT_MAX_TOKENS


def canonicalize_custom_model_profile(entry: dict) -> dict:
    """W-ARCH-MODEL-PROFILE-CANONICAL-001/004: 唯一 canonical 化入口。

    将旧持久化档案（仅 legacy ``modelId``）或已合并的写入快照规范为：
    ``model_ids``、``default_model_id``、``max_tokens``。

    幂等条件：
    - 输入已含 ``model_ids`` list → 不改变顺序与成员（仅 strip 空串）。
    - 已完整的 ``default_model_id`` / ``max_tokens`` 不被擅自改写。
    - 不修改 ``apiKey``、``name``、``endpoint`` 等业务字段。

    W-004：读取时可消费 legacy ``modelId`` / ``model_id``；返回对象不含 legacy 键。
    读路径在 ``get_custom_models()`` 内存中调用；写路径经 ``set_custom_models`` 或
    ``web_api.custom_models`` 合并 payload 后调用。
    """
    model_ids = _resolve_model_ids(entry)
    default_model_id = _resolve_default_model_id(entry, model_ids)
    max_tokens = _resolve_max_tokens(entry)
    entry["model_ids"] = model_ids
    entry["default_model_id"] = default_model_id
    entry["max_tokens"] = max_tokens
    entry.pop("modelId", None)
    entry.pop("model_id", None)
    return entry


# W-CUSTOMMODEL-SCHEMA-002 别名；测试与既有 import 仍可用。
_migrate_custom_model_shape = canonicalize_custom_model_profile


class ConfigStoreCryptoUnavailableError(ConfigError):
    """Sensitive config cannot be stored without Fernet."""
