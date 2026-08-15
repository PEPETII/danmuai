"""ConfigStore schema 迁移注册表（轻量，非框架）。

现有 per-key 懒迁移（_resolve_custom_model_api_key / _migrate_custom_model_shape）
保留为运行期回退；本模块仅负责启动期 schema_version 推进。

W-SCHEMA-MIGRATION-FOUNDATION-001：当前 MIGRATIONS 为空，仅建立版本追踪基线，
零行为回归。后续新增 schema 变更时用 @register(version, name) 装饰器加迁移函数，
迁移函数接收已开事务的 conn，需自行保证幂等（CREATE TABLE IF NOT EXISTS 等）。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

_TTS_GENERIC_API_KEY_PROVIDERS = frozenset(
    {"mimo", "dashscope", "minimax", "doubao"}
)

# (version, name, fn(conn)) —— fn 在已开连接内运行，需幂等。
MIGRATIONS: List[Tuple[int, str, Callable[["sqlite3.Connection"], None]]] = []


def register(version: int, name: str):
    """装饰器：注册一个 schema 迁移函数。

    Args:
        version: 正整数 schema 版本；迁移按 version 升序运行。
        name: 人类可读名称，仅用于日志。

    Returns:
        装饰器，原函数原样返回。
    """

    def deco(fn: Callable[["sqlite3.Connection"], None]) -> Callable:
        MIGRATIONS.append((version, name, fn))
        return fn

    return deco


def run_pending(conn: "sqlite3.Connection") -> int:
    """在已开连接内运行未应用的迁移；返回最终 schema_version。幂等。

    调用方需在已开连接后调用（ConfigStore.__init__ 已开连接 + PRAGMA 已设置）。
    不自行 commit；依赖调用方或 SQLite 自动提交（ConfigStore 用 autocommit 默认行为）。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        # 首次初始化：写入 schema_version=0 基线
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", "0"),
        )
        current = 0
    else:
        current = int(row[0])
    for version, name, fn in sorted(MIGRATIONS, key=lambda m: m[0]):
        if version <= current:
            continue
        logger.info("config.schema_migration running v%s %s", version, name)
        fn(conn)
        conn.execute(
            "REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(version)),
        )
    return max([current] + [m[0] for m in MIGRATIONS])


def migrate_legacy_tts_credentials(store) -> bool:
    """将旧单一 TTS key 幂等迁移到明确的 provider/api_key 槽位。

    旧字段只迁入对应 provider 的 ``api_key`` 槽位，绝不复制或猜测为
    Doubao 的 ``app_id``/``access_token``；未知 provider 保留旧值。
    """
    from app.config_defaults import DEFAULT_TTS_PROVIDER, TTS_SECRET_PROVIDER_ALIASES

    legacy_raw = bool(
        store.get("tts_api_key_encrypted", "")
        or store.get("tts_api_key_encoded", "")
    )
    if not legacy_raw:
        return False

    raw_provider = str(store.get("tts_provider", "") or "").strip().lower()
    provider = (
        DEFAULT_TTS_PROVIDER
        if not raw_provider
        else TTS_SECRET_PROVIDER_ALIASES.get(raw_provider)
    )
    if provider not in _TTS_GENERIC_API_KEY_PROVIDERS:
        return False

    legacy_value = store.get_tts_api_key()
    # 密文无法解密时保留旧行，交给既有 key-loss 处理，不以空读结果销毁。
    if not legacy_value:
        return False

    target_raw = store.get(f"tts_secret:{provider}:api_key", "")
    target_value = store.get_tts_secret(provider, "api_key")
    if target_raw and not target_value:
        return False

    try:
        if not target_value:
            store.set_tts_secret(provider, "api_key", legacy_value)
        from app.config_store.storage_models import delete_legacy_tts_api_key_for_store

        delete_legacy_tts_api_key_for_store(store)
    except Exception as exc:  # noqa: BLE001 - startup migration retries next launch
        logger.warning(
            "config.tts_secret_migration_failed provider=%s error=%s",
            provider,
            type(exc).__name__,
        )
        return False
    return True


__all__ = ["MIGRATIONS", "migrate_legacy_tts_credentials", "register", "run_pending"]
