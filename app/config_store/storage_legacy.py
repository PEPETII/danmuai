"""ConfigStore 子包：system_flags 读写与 legacy API 启动期迁移。

``ConfigStore`` 通过 ``storage.py`` 内薄委托方法调用本模块 ``*_for_store`` 函数；
锁语义不变：``set_flag`` 持 ``store._write_lock``，``get_flag`` 不持锁。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config_store.storage import ConfigStore

logger = logging.getLogger(__name__)


def get_flag_for_store(store: ConfigStore, key: str) -> str | None:
    """Read a system flag from ``system_flags`` table; returns None if missing."""
    if not store._conn_usable():
        return None
    try:
        row = store.conn.execute(
            "SELECT value FROM system_flags WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.ProgrammingError:
        return None
    if not row:
        return None
    return row[0]


def set_flag_for_store(store: ConfigStore, key: str, value: str) -> None:
    """Write a system flag (REPLACE INTO);持 ``_write_lock`` 保证事务一致。"""
    if store._closed:
        logger.warning(
            "ConfigStore.set_flag(%s) called after close(), write skipped", key
        )
        return
    with store._write_lock:
        if store._closed:
            logger.warning(
                "ConfigStore.set_flag(%s) called after close(), write skipped", key
            )
            return
        try:
            store.conn.execute(
                "REPLACE INTO system_flags (key, value) VALUES (?, ?)",
                (key, value),
            )
            store.conn.commit()
        except sqlite3.DatabaseError as e:
            store.conn.rollback()
            logger.error("set_flag failed key=%s error=%s", key, type(e).__name__)
            raise


def maybe_migrate_legacy_api_to_custom_models_for_store(store: ConfigStore) -> bool:
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 启动期安全网 + 一次性清空全局视觉凭证。

    每次启动运行，但快速秒退：
    - ``get_api_key()`` 为空 → 已清空，return True
    - ``get_api_key()`` 非空 + 标志位 true → 之前已尝试且无法清理（分支 C），return True
    - ``get_api_key()`` 非空 + 标志位非 true → 运行安全网：
      - 分支 A：存在完整 custom_models 档案 → 清空全局 ``api_key`` / ``api_endpoint`` / ``api_mode``
      - 分支 B：无完整档案但全局凭证完整（api_key + endpoint + model 均非空）→ 自动建档 + 清空全局
      - 分支 C：全局凭证不完整 → 记 warning，不清空，置标志位避免重复尝试

    保留 ``model`` 字段不动（双写兼容）；保留 ``max_tokens``（全局设置）。
    ``mic_api_key`` / ``tts_api_key`` / ``danmu_read_api_key`` 职责不同，不受影响。

    异常容错：迁移过程中任一步失败 → 不置标志位 → 下次启动重试。

    Returns:
        True 表示已完成或无需处理；False 表示异常失败（下次启动重试）。
    """
    try:
        try:
            api_key = store.get_api_key()
        except Exception as exc:  # noqa: BLE001 — 解密异常需兜底
            logger.warning(
                "legacy api cleanup skipped: api_key decrypt failed",
                extra={"reason": "legacy_cleanup_failed", "error": str(exc)},
            )
            set_flag_for_store(store, "legacy_api_migrated_v1", "true")
            return True

        if not api_key:
            return True

        from app.application.config_service import MASKED_API_KEY

        if api_key == MASKED_API_KEY:
            set_flag_for_store(store, "legacy_api_migrated_v1", "true")
            return True

        if get_flag_for_store(store, "legacy_api_migrated_v1") == "true":
            return True

        from app.model_providers import (
            guess_provider_from_endpoint,
            is_model_config_complete,
        )

        existing_models = store.get_custom_models()

        has_complete_profile = any(
            is_model_config_complete(entry) for entry in existing_models
        )
        if has_complete_profile:
            store.apply_web_save(
                items={"api_endpoint": "", "api_mode": ""},
                api_key="",
                flags={"legacy_api_migrated_v1": "true"},
            )
            logger.info(
                "legacy global api cleaned: complete profile exists",
                extra={"reason": "legacy_cleanup_done", "branch": "A"},
            )
            return True

        endpoint = store.get("api_endpoint", "")
        cfg_model = store.get("model", "")

        if not endpoint or not cfg_model:
            logger.warning(
                "legacy cleanup incomplete: missing endpoint or model",
                extra={"reason": "legacy_cleanup_incomplete"},
            )
            set_flag_for_store(store, "legacy_api_migrated_v1", "true")
            return True

        api_mode = store.get("api_mode", "")
        provider = guess_provider_from_endpoint(endpoint, api_mode) or "custom_openai"
        mode = "doubao" if provider == "doubao" else "openai-compatible"
        default_model_id = cfg_model
        model_ids = [cfg_model]
        max_tokens_raw = store.get("max_tokens", "512")
        try:
            max_tokens_int = int(max_tokens_raw) if max_tokens_raw else 512
        except (TypeError, ValueError):
            max_tokens_int = 512

        profile = {
            "name": "Default (imported)",
            "provider": provider,
            "mode": mode,
            "endpoint": endpoint,
            "apiKey": api_key,
            "model_ids": model_ids,
            "default_model_id": default_model_id,
            "max_tokens": max_tokens_int,
            "supportsMic": False,
            "description": "",
        }

        store.apply_web_save(
            items={
                "api_endpoint": "",
                "api_mode": "",
                "default_model_id": default_model_id,
                "model": default_model_id,
            },
            api_key="",
            custom_models=[profile],
            flags={"legacy_api_migrated_v1": "true"},
        )

        logger.info(
            "legacy api migrated to default custom model profile and global cleaned",
            extra={
                "reason": "legacy_cleanup_done",
                "branch": "B",
                "provider": provider,
                "model_id": default_model_id,
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001 — 顶层容错，下次重试
        logger.warning(
            "legacy api cleanup failed",
            extra={"reason": "legacy_cleanup_failed", "error": str(exc)},
        )
        return False
