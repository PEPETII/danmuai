"""ConfigStore 子包：custom_models 档案与 API Key 加解密读写实现。

``ConfigStore`` 通过 ``storage.py`` 内薄委托方法调用本模块 ``*_for_store`` 函数；
锁语义不变：写路径持 ``store._write_lock``，读路径不持锁。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from base64 import b64decode
from typing import TYPE_CHECKING

try:
    from cryptography.fernet import InvalidToken
except ImportError:
    InvalidToken = ValueError  # type: ignore[misc, assignment]

import app.config_store as _cs_pkg
from app.config_store.crypto import (
    ConfigStoreCryptoUnavailableError,
    canonicalize_custom_model_profile,
)
from app.translations import tr

if TYPE_CHECKING:
    from app.config_store.storage import ConfigStore

logger = logging.getLogger(__name__)


def _secret_fingerprint(
    store: ConfigStore, encrypted_key: str, encoded_key: str
) -> tuple[str, str]:
    return (store.get(encrypted_key, ""), store.get(encoded_key, ""))


def invalidate_secret_cache_for_store(store: ConfigStore, encrypted_key: str) -> None:
    store._decrypted_secret_cache.pop(encrypted_key, None)
    store._decrypted_secret_fp.pop(encrypted_key, None)


def _cache_decrypted_secret(
    store: ConfigStore, encrypted_key: str, encoded_key: str, plaintext: str
) -> str:
    store._decrypted_secret_cache[encrypted_key] = plaintext
    store._decrypted_secret_fp[encrypted_key] = _secret_fingerprint(
        store, encrypted_key, encoded_key
    )
    return plaintext


def encrypted_get_for_store(
    store: ConfigStore, encrypted_key: str, encoded_key: str
) -> str:
    """读取加密或 legacy base64 编码的 API Key 明文（指纹缓存避免重复解密）。"""
    fp = _secret_fingerprint(store, encrypted_key, encoded_key)
    if store._decrypted_secret_fp.get(encrypted_key) == fp:
        return store._decrypted_secret_cache[encrypted_key]

    encrypted, encoded = fp
    if encrypted and _cs_pkg._HAS_CRYPTO and store._fernet:
        try:
            plaintext = store._fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
            return _cache_decrypted_secret(store, encrypted_key, encoded_key, plaintext)
        except (InvalidToken, ValueError, UnicodeDecodeError):
            logger.warning(tr("config.decrypt_failed"))
    if not encoded:
        return _cache_decrypted_secret(store, encrypted_key, encoded_key, "")
    try:
        plaintext = b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return _cache_decrypted_secret(store, encrypted_key, encoded_key, "")
    # W-MEDLOW-004：安装 cryptography 后首次读取 legacy base64 时自动升级为 Fernet。
    if _cs_pkg._HAS_CRYPTO and store._fernet and not encrypted:
        try:
            encrypted_set_for_store(store, encrypted_key, encoded_key, plaintext)
        except (ConfigStoreCryptoUnavailableError, ValueError, OSError, sqlite3.Error) as exc:
            logger.warning(
                "config key auto-upgrade failed key=%s error=%s",
                encrypted_key,
                type(exc).__name__,
            )
    elif encoded and not encrypted and not store.secrets_storage_available:
        logger.warning(tr("config.insecure_read"))
    return _cache_decrypted_secret(store, encrypted_key, encoded_key, plaintext)


def _queue_secret_write(
    store: ConfigStore,
    encrypted_key: str,
    encoded_key: str,
    key: str,
    pairs: list[tuple[str, str]],
    keys_to_delete: list[str],
) -> None:
    """Queue API key REPLACE/DELETE within an open transaction (caller holds _write_lock)."""
    if not store.secrets_storage_available:
        message = tr("config.crypto_write_blocked")
        logger.error(message)
        raise ConfigStoreCryptoUnavailableError(message)
    encrypted = store._fernet.encrypt(key.encode("utf-8")).decode("utf-8")
    pairs.append((encrypted_key, encrypted))
    if encoded_key in store._cache:
        keys_to_delete.append(encoded_key)


def encrypted_set_for_store(
    store: ConfigStore, encrypted_key: str, encoded_key: str, key: str
) -> None:
    """写入 API Key：Fernet 加密或退化为 base64；持 _write_lock 保证 cache/DB 一致。"""
    pairs: list[tuple[str, str]] = []
    keys_to_delete: list[str] = []
    _queue_secret_write(store, encrypted_key, encoded_key, key, pairs, keys_to_delete)
    with store._write_lock:
        try:
            if pairs:
                store.conn.executemany(
                    "REPLACE INTO config (key, value) VALUES (?, ?)",
                    pairs,
                )
            for delete_key in keys_to_delete:
                store.conn.execute("DELETE FROM config WHERE key=?", (delete_key,))
            store.conn.commit()
            for storage_key, value in pairs:
                store._cache[storage_key] = value
            for delete_key in keys_to_delete:
                store._cache.pop(delete_key, None)
        except sqlite3.DatabaseError as e:
            store.conn.rollback()
            logger.error(tr("config.api_key_write_failed").format(error=type(e).__name__))
            raise
    invalidate_secret_cache_for_store(store, encrypted_key)


def get_api_key_for_store(store: ConfigStore) -> str:
    """读取明文 API Key：优先 Fernet 解密 api_key_encrypted，否则回退 base64 的 api_key_encoded。"""
    return encrypted_get_for_store(store, "api_key_encrypted", "api_key_encoded")


def set_api_key_for_store(store: ConfigStore, key: str) -> None:
    """写入 API Key：有 Fernet 则加密存 api_key_encrypted 并清除旧 base64 行。"""
    encrypted_set_for_store(store, "api_key_encrypted", "api_key_encoded", key)


def get_tts_api_key_for_store(store: ConfigStore) -> str:
    """读弹幕专用 TTS API Key（tts_api_key_encrypted）。"""
    return encrypted_get_for_store(store, "tts_api_key_encrypted", "tts_api_key_encoded")


def set_tts_api_key_for_store(store: ConfigStore, key: str) -> None:
    """写入 TTS API Key（加密存储）。"""
    encrypted_set_for_store(store, "tts_api_key_encrypted", "tts_api_key_encoded", key)


def get_mic_api_key_for_store(store: ConfigStore) -> str:
    """读麦克风专用 API Key（mic_api_key_encrypted）。"""
    return encrypted_get_for_store(store, "mic_api_key_encrypted", "mic_api_key_encoded")


def set_mic_api_key_for_store(store: ConfigStore, key: str) -> None:
    """写入麦克风专用 API Key（加密存储）。"""
    encrypted_set_for_store(store, "mic_api_key_encrypted", "mic_api_key_encoded", key)


def _looks_like_fernet_token(store: ConfigStore, value: str) -> bool:
    """Heuristic Fernet token check — avoids trial decrypt on hot path."""
    if not value or not _cs_pkg._HAS_CRYPTO or not store._fernet:
        return False
    if len(value) < 57 or not value.startswith("gAAAAA"):
        return False
    return True


def _encrypt_custom_model_api_key(store: ConfigStore, key: str) -> str:
    """Encrypt custom-model apiKey with the same Fernet key as api_key_encrypted."""
    if not key:
        return ""
    if not store.secrets_storage_available:
        message = tr("config.crypto_write_blocked")
        logger.error(message)
        raise ConfigStoreCryptoUnavailableError(message)
    return store._fernet.encrypt(key.encode("utf-8")).decode("utf-8")


def _encode_custom_models_json(store: ConfigStore, models: list) -> str:
    """Serialize custom models with encrypted apiKey fields (caller may hold write lock)."""
    encrypted: list[dict] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        entry = dict(model)
        plain_key = (entry.get("apiKey") or "").strip()
        if plain_key:
            if _looks_like_fernet_token(store, plain_key):
                entry["apiKey"] = plain_key
            else:
                entry["apiKey"] = _encrypt_custom_model_api_key(store, plain_key)
        encrypted.append(entry)
    return json.dumps(encrypted, ensure_ascii=False)


def invalidate_custom_models_cache_for_store(store: ConfigStore) -> None:
    store._custom_models_cache = None
    store._custom_models_fp = None


def _resolve_custom_model_api_key(store: ConfigStore, stored: str) -> tuple[str, bool]:
    """Return (plaintext apiKey, needs_encryption_upgrade)."""
    if not stored:
        return "", False
    if _looks_like_fernet_token(store, stored):
        try:
            return store._fernet.decrypt(stored.encode("utf-8")).decode("utf-8"), False
        except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
            logger.debug(
                "config.fernet_decrypt_failed key=custom_model_api_key error=%r",
                exc,
            )
    try:
        decoded = b64decode(stored).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        logger.debug(
            "config.b64decode_failed key=custom_model_api_key error=%r",
            exc,
        )
        decoded = stored
    if decoded.startswith("sk-") or decoded.startswith("Bearer "):
        return decoded, True
    if stored.startswith("sk-") or stored.startswith("Bearer "):
        return stored, True
    return stored, bool(stored) and not _looks_like_fernet_token(store, stored)


def get_custom_models_for_store(store: ConfigStore) -> list:
    """Return custom models with decrypted apiKey; upgrade legacy plaintext on read.

    W-ARCH-MODEL-PROFILE-CANONICAL-001/004: 返回前对每条档案委托
    ``canonicalize_custom_model_profile`` 做内存 canonical 化（旧 ``modelId``
    → ``model_ids`` / ``default_model_id`` / ``max_tokens``，并剥离 legacy 键）。
    幂等、不写回 DB；新 shape 在下次 ``set_custom_models`` 调用时持久化。
    """
    raw = store.get("custom_models", "")
    if store._custom_models_cache is not None and raw == store._custom_models_fp:
        return [canonicalize_custom_model_profile(dict(m)) for m in store._custom_models_cache]

    if not raw:
        parsed = []
    else:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning(tr("config.custom_models_parse_failed"))
            parsed = []
    if not isinstance(parsed, list):
        return []
    result: list[dict] = []
    needs_upgrade = False
    for model in parsed:
        if not isinstance(model, dict):
            continue
        entry = dict(model)
        stored_key = (entry.get("apiKey") or "").strip()
        if stored_key:
            plain_key, needs_encrypt = _resolve_custom_model_api_key(store, stored_key)
            entry["apiKey"] = plain_key
            if needs_encrypt:
                needs_upgrade = True
        result.append(entry)
    if needs_upgrade:
        set_custom_models_for_store(store, result)
        raw = store.get("custom_models", "")
    store._custom_models_cache = result
    store._custom_models_fp = raw
    return [canonicalize_custom_model_profile(dict(m)) for m in store._custom_models_cache]


def set_custom_models_for_store(store: ConfigStore, models: list) -> None:
    """Persist custom models; each apiKey is Fernet-encrypted before JSON serialization.

    W-004: canonicalize before encode so persisted JSON never contains legacy modelId.
    """
    normalized = [
        canonicalize_custom_model_profile(dict(m))
        for m in models
        if isinstance(m, dict)
    ]
    store.set("custom_models", _encode_custom_models_json(store, normalized))
    invalidate_custom_models_cache_for_store(store)


def apply_web_save_for_store(
    store: ConfigStore,
    *,
    items: dict[str, str] | None = None,
    api_key: str | None = None,
    mic_api_key: str | None = None,
    custom_models: list[dict] | None = None,
    flags: dict[str, str] | None = None,
) -> None:
    """Web PUT /api/config 原子落库：普通键、API Key、custom_models、flags 单次 commit。

    仅供 ConfigService.apply_web_payload 与启动期 legacy 迁移使用；
    失败 rollback 且不更新 _cache。``api_key=""`` 表示清空全局视觉 key。
    """
    pairs: list[tuple[str, str]] = []
    keys_to_delete: list[str] = []
    invalidate_secrets: list[str] = []
    flag_pairs: list[tuple[str, str]] = list(flags.items()) if flags else []

    if items:
        pairs.extend(items.items())

    if api_key is not None:
        _queue_secret_write(
            store,
            "api_key_encrypted",
            "api_key_encoded",
            api_key,
            pairs,
            keys_to_delete,
        )
        invalidate_secrets.append("api_key_encrypted")

    if mic_api_key:
        _queue_secret_write(
            store,
            "mic_api_key_encrypted",
            "mic_api_key_encoded",
            mic_api_key,
            pairs,
            keys_to_delete,
        )
        invalidate_secrets.append("mic_api_key_encrypted")

    if custom_models is not None:
        pairs.append(("custom_models", _encode_custom_models_json(store, custom_models)))

    if not pairs and not keys_to_delete and not flag_pairs:
        return

    with store._write_lock:
        try:
            if pairs:
                store.conn.executemany(
                    "REPLACE INTO config (key, value) VALUES (?, ?)",
                    pairs,
                )
            for key in keys_to_delete:
                store.conn.execute("DELETE FROM config WHERE key=?", (key,))
            if flag_pairs:
                store.conn.executemany(
                    "REPLACE INTO system_flags (key, value) VALUES (?, ?)",
                    flag_pairs,
                )
            store.conn.commit()
            for key, value in pairs:
                store._cache[key] = value
            for key in keys_to_delete:
                store._cache.pop(key, None)
        except sqlite3.DatabaseError as e:
            store.conn.rollback()
            logger.error(tr("config.batch_write_failed").format(error=type(e).__name__))
            raise

    for encrypted_key in invalidate_secrets:
        invalidate_secret_cache_for_store(store, encrypted_key)
    if custom_models is not None:
        invalidate_custom_models_cache_for_store(store)
