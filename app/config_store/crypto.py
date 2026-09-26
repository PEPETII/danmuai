"""ConfigStore 子包：Fernet 加密、密钥管理与自定义模型 shape 迁移辅助。

从原 ``app/config_store.py`` 拆分而来；本模块仅含不依赖 ConfigStore 实例状态的
独立函数与异常类。密钥丢失 / 损坏恢复策略见 ``storage.py`` 模块 docstring。
"""
import logging
import os
import subprocess
import uuid
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
MASKED_CUSTOM_MODEL_API_KEY = "********"


class CustomModelApiKeyConflictError(ValueError):
    """Raised when apiKey and api_key carry different non-empty values."""


def read_custom_model_api_key(entry: dict | None) -> str:
    """Return trimmed apiKey value, accepting legacy ``api_key`` alias."""
    if not isinstance(entry, dict):
        return ""
    return (entry.get("apiKey") or entry.get("api_key") or "").strip()


def assert_custom_model_api_key_aliases_consistent(entry: dict) -> None:
    """Reject payloads that supply conflicting apiKey/api_key values."""
    if not isinstance(entry, dict):
        return
    canonical = str(entry.get("apiKey") or "").strip()
    snake = str(entry.get("api_key") or "").strip()
    if canonical and snake and canonical != snake:
        raise CustomModelApiKeyConflictError(
            tr("custom_model.error_api_key_conflict")
        )


def normalize_custom_model_api_key_aliases(entry: dict) -> dict:
    """Collapse ``api_key`` into canonical ``apiKey`` and strip the alias field."""
    assert_custom_model_api_key_aliases_consistent(entry)
    resolved = read_custom_model_api_key(entry)
    if resolved or "apiKey" in entry or "api_key" in entry:
        entry["apiKey"] = resolved
    entry.pop("api_key", None)
    return entry


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
    return normalize_custom_model_api_key_aliases(entry)


# W-CUSTOMMODEL-SCHEMA-002 别名；测试与既有 import 仍可用。
_migrate_custom_model_shape = canonicalize_custom_model_profile


# --- W-AUDIT-MODEL-IDENTITY-001：不可变模型档案身份 + 人格绑定版本化 -------------
#
# ``profile_id`` 是每个 custom_models 档案的持久化、不可编辑身份，允许两个档案
# 共享同一上游 ``default_model_id``（模型名只是发给 provider 的标识，不唯一）。
# 生成只发生在受控迁移 / 创建写入路径；读取路径绝不随机生成，否则会在重启或
# 重复读取时漂移。

PROFILE_ID_FIELD = "profile_id"
PROFILE_ID_PREFIX = "cmp_"

# 人格 → 模型档案绑定版本化结构：{"v": 1, "profile_id": ..., "model_id": ...}
PERSONA_BINDING_VERSION = 1


def new_custom_model_profile_id(used: set[str] | None = None) -> str:
    """生成一个新的、非空且未被占用的模型档案身份。"""
    taken = used if used is not None else set()
    while True:
        candidate = f"{PROFILE_ID_PREFIX}{uuid.uuid4().hex}"
        if candidate not in taken:
            return candidate


def read_custom_model_profile_id(entry: dict | None) -> str:
    """返回档案的规范化 ``profile_id``；缺失 / 非字符串 / 空白时返回空串。"""
    if not isinstance(entry, dict):
        return ""
    value = entry.get(PROFILE_ID_FIELD)
    if not isinstance(value, str):
        return ""
    return value.strip()


def custom_model_profile_id_type_error(entry: dict | None) -> bool:
    """``profile_id`` 存在但类型错误（非字符串且非 None）时为 True，用于诊断。"""
    if not isinstance(entry, dict) or PROFILE_ID_FIELD not in entry:
        return False
    return entry.get(PROFILE_ID_FIELD) is not None and not isinstance(
        entry.get(PROFILE_ID_FIELD), str
    )


def duplicate_custom_model_profile_ids(models) -> set[str]:
    """返回在档案列表中重复出现的 ``profile_id`` 集合（歧义身份）。"""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for entry in models or []:
        pid = read_custom_model_profile_id(entry)
        if not pid:
            continue
        if pid in seen:
            duplicates.add(pid)
        seen.add(pid)
    return duplicates


def profile_ids_by_versioned_model_id(models) -> dict[str, list[str]]:
    """``default_model_id`` → 拥有该模型名的 ``profile_id`` 列表（仅含有效身份）。"""
    index: dict[str, list[str]] = {}
    for entry in models or []:
        if not isinstance(entry, dict):
            continue
        pid = read_custom_model_profile_id(entry)
        mid = str(entry.get("default_model_id") or "").strip()
        if not pid or not mid:
            continue
        index.setdefault(mid, []).append(pid)
    return index


def build_persona_model_binding(profile_id: str, model_id: str) -> dict:
    """构造版本化人格绑定结构（至少含 ``profile_id`` / ``model_id``）。"""
    return {
        "v": PERSONA_BINDING_VERSION,
        "profile_id": str(profile_id or "").strip(),
        "model_id": str(model_id or "").strip(),
    }


def parse_persona_model_binding(value) -> dict | None:
    """解析版本化绑定；非版本化（旧字符串 / 其他类型）返回 ``None``。"""
    if not isinstance(value, dict):
        return None
    profile_id = value.get("profile_id")
    model_id = value.get("model_id")
    profile_id = profile_id.strip() if isinstance(profile_id, str) else ""
    model_id = model_id.strip() if isinstance(model_id, str) else ""
    if not profile_id:
        return None
    return {"profile_id": profile_id, "model_id": model_id}


def legacy_persona_model_binding_model_id(value) -> str:
    """旧绑定（模型名字符串）解析为 model_id；其他类型返回空串。"""
    return value.strip() if isinstance(value, str) else ""


def migrate_persona_model_bindings(
    bindings: dict,
    profile_ids_by_model_id: dict[str, list[str]] | None,
) -> tuple[dict, bool]:
    """把旧人格绑定字符串迁移为版本化结构。

    规则（工单 §5.2）：仅当旧字符串 **唯一匹配** 一个档案的 ``default_model_id``
    时才自动迁移；零匹配或多匹配不猜测首项，保留原始字符串作为可诊断的
    unresolved 状态，等待用户在 UI 重新选择。已是版本化结构的绑定原样保留。
    """
    index = profile_ids_by_model_id or {}
    result: dict = {}
    changed = False
    for persona, value in (bindings or {}).items():
        parsed = parse_persona_model_binding(value)
        if parsed is not None:
            result[persona] = dict(value)
            continue
        legacy_model_id = legacy_persona_model_binding_model_id(value)
        if not legacy_model_id:
            result[persona] = value
            continue
        matches = index.get(legacy_model_id, [])
        if len(matches) == 1:
            result[persona] = build_persona_model_binding(matches[0], legacy_model_id)
            changed = True
        else:
            result[persona] = value
    return result, changed



class ConfigStoreCryptoUnavailableError(ConfigError):
    """Sensitive config cannot be stored without Fernet."""
