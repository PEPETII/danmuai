"""SQLite 配置存储：内存缓存 + WAL 并发读 + Fernet 加密 API Key。

设计要点：
- **%APPDATA%/DanmuAI/config.db** 持久化；**%APPDATA%/DanmuAI/.key** 为 Fernet 对称密钥。
- **密钥丢失或 .key 被删/损坏后重新生成**：旧 api_key_encrypted 无法解密，等同不可恢复（须重新填写 Key）。
- **密钥损坏时 best-effort 备份**：校验失败生成新 key 前，将旧 `.key` 写入 `.key.bak.<timestamp>`（不保证可恢复密文）。
- **敏感写入 fail-closed**：无 cryptography / Fernet 时拒绝新写入 API Key（抛 ``ConfigStoreCryptoUnavailableError``）。
- **读取向后兼容**：仍可只读解码 legacy ``api_key_encoded``（base64，非加密）；有 Fernet 后写入 encrypted 并删除 encoded。
- **WAL + busy_timeout**：允许多读者与单写者共存，写路径用 _write_lock 串行化避免 cache/DB 不一致。
- **set_batch**：显式事务，commit 成功后才更新 _cache，失败 rollback。

调用方：DanmuApp、ConfigService.apply_web_payload、各模块读配置。

存储边界：新业务模块禁止继续共享 ConfigStore 的 SQLite 连接；历史/模板等应经既有门面访问，见 docs/phase1-boundary-rules.md。

注：本模块自原 ``app/config_store.py`` 拆分而来；加密辅助函数位于 ``app.config_store.crypto``，
弹幕池 CRUD 重新导出于 ``app.config_store.pool``。``_HAS_CRYPTO`` 通过 ``_cs_pkg._HAS_CRYPTO``
以属性访问形式读取，确保 ``unittest.mock.patch("app.config_store._HAS_CRYPTO", ...)``
能影响 ConfigStore 方法行为（见测试 test_p1_key_encryption / test_p1_sqlite_concurrency / test_config_store）。
"""
import json
import logging
import math
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTO = True
except ImportError:
    Fernet = None  # type: ignore[misc, assignment]
    InvalidToken = ValueError  # type: ignore[misc, assignment]
    _HAS_CRYPTO = False

from base64 import b64decode, b64encode

from app.config_migrations import run_pending
from app.translations import tr

# 通过包属性访问 _HAS_CRYPTO，使 patch("app.config_store._HAS_CRYPTO", ...) 生效。
# 详见模块 docstring。
import app.config_store as _cs_pkg

from app.config_store.crypto import (
    ConfigStoreCryptoUnavailableError,
    _backup_corrupted_key_file,
    _migrate_custom_model_shape,
    _restrict_key_file_permissions,
)

logger = logging.getLogger(__name__)

_SENSITIVE_CONFIG_KEYS = frozenset(
    {
        "api_key_encrypted",
        "mic_api_key_encrypted",
        "tts_api_key_encrypted",
        "custom_models",
        "api_key",
    }
)


def _redact_config_value_for_log(key: str, value: str) -> str:
    if key in _SENSITIVE_CONFIG_KEYS or "encrypted" in key.lower() or key.endswith("_key"):
        return "***"
    if len(value) > 120:
        return f"{value[:40]}…({len(value)} chars)"
    return value


CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "DanmuAI"
CONFIG_FILE = CONFIG_DIR / "config.db"
_KEY_FILE = CONFIG_DIR / ".key"
# Python 3.12 默认 cached_statements=128；显式放大以覆盖 meme/custom 池等高频查询变体。
_SQLITE_CACHED_STATEMENTS = 256


class ConfigStore:
    """应用配置与 API Key 的 SQLite 门面；读走内存 _cache，写持 _write_lock。"""

    def __init__(self, db_path: Path = CONFIG_FILE):
        self.is_first_run = not db_path.exists()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._key_file = db_path.parent / ".key"
        # 连接级 statement cache（sqlite3 内置）；不手写 prepared statement、不长期持有 cursor。
        self.conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            cached_statements=_SQLITE_CACHED_STATEMENTS,
        )
        # WAL：读不阻塞写、写不阻塞读；Web/主线程并发读配置时减少 database is locked
        # 选择原因：主线程读配置 + HTTP 线程写配置并发场景，WAL 比 DELETE 模式更适合
        self.conn.execute("PRAGMA journal_mode=WAL")
        # 写冲突时等待最多 5s 而非立即失败（与 _write_lock 双保险）
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._init_db()
        # W-SCHEMA-MIGRATION-FOUNDATION-001：启动期 schema 版本追踪（当前 MIGRATIONS 为空 = no-op）
        self._schema_version = run_pending(self.conn)
        self._cache: dict[str, str] = {}
        self._load_cache()
        # 所有 REPLACE/commit 串行化，保证 _cache 与 DB 同事务一致
        self._write_lock = threading.Lock()
        # 弹幕库写操作独立锁，与配置读写互不阻塞
        self._pool_write_lock = threading.Lock()
        self._closed = False
        # W-FP-V2-002：须在 seed 之前写回，避免 seed 先落 danmu_render_mode=scrolling 盖掉遗留 display_mode
        self._migrate_legacy_display_mode_to_render_mode()
        self._migrate_legacy_image_max_width()
        if self.is_first_run or not self.get("danmu_speed"):
            from app.config_defaults import seed_config_defaults

            seed_config_defaults(self)
            self._load_cache()
        self._key_regenerated = False
        self._key_backup_path: Path | None = None
        self._fernet = self._init_fernet()
        # W-PERF-MED-001：解密明文与 custom_models 解析结果指纹缓存（进程内驻留至配置变更）
        self._decrypted_secret_cache: dict[str, str] = {}
        self._decrypted_secret_fp: dict[str, tuple[str, str]] = {}
        self._custom_models_cache: list[dict] | None = None
        self._custom_models_fp: str | None = None
        # W-PERF-STARTUP-001：非关键迁移延迟到主线程空闲时执行，减少启动阻塞
        self._pending_deferred_migrations = True
        # W-LEGACY-MIGRATE-003：启动期自动迁移 legacy API 配置到默认 custom_models 档案
        # 必须在 _fernet / _cache / _custom_models_cache 初始化之后调用；
        # 迁移函数自身有异常容错，不会再抛异常。
        self._maybe_migrate_legacy_api_to_custom_models()

    @property
    def schema_version(self) -> int:
        """当前 DB schema 版本（W-SCHEMA-MIGRATION-FOUNDATION-001）。"""
        return self._schema_version

    def _migrate_legacy_image_max_width(self) -> None:
        from app.config_defaults import migrate_legacy_image_max_width

        migrate_legacy_image_max_width(self)

    def _migrate_legacy_display_mode_to_render_mode(self) -> None:
        # W-FP-V2-002：遗留 display_mode（overlay/floating_panel/both）→ danmu_render_mode 写回
        from app.config_defaults import migrate_legacy_display_mode_to_render_mode

        migrate_legacy_display_mode_to_render_mode(self)

    def _normalize_legacy_display_mode(self) -> None:
        from app.application.config_service import normalize_legacy_display_mode

        legacy_mode = str(self.get("danmu_display_mode", ""))
        items = {"danmu_display_mode": legacy_mode}
        normalize_legacy_display_mode(items)
        normalized_mode = str(items.get("danmu_display_mode", "")).strip().lower()
        if normalized_mode and normalized_mode != legacy_mode.strip().lower():
            self.set("danmu_display_mode", normalized_mode)

    def run_deferred_migrations(self) -> None:
        """执行启动时延迟的迁移/修复操作，由主线程空闲时调用（W-PERF-STARTUP-001）。"""
        if not self._pending_deferred_migrations:
            return
        self._pending_deferred_migrations = False
        self._repair_stale_region_if_needed()
        self._normalize_legacy_display_mode()
        from app.danmu_pool import migrate_custom_danmu_pool_json

        migrate_custom_danmu_pool_json(self)

    @property
    def secrets_storage_available(self) -> bool:
        return bool(_cs_pkg._HAS_CRYPTO and self._fernet)

    def get_startup_notice(self) -> str:
        """首装会话返回本地化引导文案；crypto 不可用或密钥丢失时返回告警文案；否则为空。"""
        if self.is_first_run:
            notice = tr("config.startup_notice")
            if not self.secrets_storage_available:
                notice = f"{notice}\n\n{tr('config.crypto_startup_notice')}"
            return notice
        if not self.secrets_storage_available:
            return tr("config.crypto_startup_notice")
        if self._key_regenerated:
            if self._key_backup_path is not None:
                return tr("config.key_lost_notice_with_backup").format(
                    backup_path=self._key_backup_path
                )
            return tr("config.key_lost_notice")
        return ""

    def _reject_insecure_encoded_write(self, key: str, value: str) -> None:
        if key.endswith("_encoded") and value and not self.secrets_storage_available:
            message = tr("config.crypto_write_blocked")
            logger.error(message)
            raise ConfigStoreCryptoUnavailableError(message)

    def _init_fernet(self):
        """加载或生成 %APPDATA%/DanmuAI/.key；校验失败则换新 key（旧密文永久不可读）。"""
        if not _cs_pkg._HAS_CRYPTO:
            logger.warning(tr("config.crypto_missing"))
            return None
        if self._key_file.exists():
            key = self._key_file.read_bytes()
            try:
                f = Fernet(key)
                # Verify key is valid by a dummy round-trip
                f.decrypt(f.encrypt(b"test"))
                return f
            except (ValueError, InvalidToken, OSError):
                self._key_backup_path = _backup_corrupted_key_file(
                    self._key_file.parent, key
                )
                if self._key_backup_path is not None:
                    logger.warning(
                        tr("config.crypto_key_regenerated").format(
                            backup_path=self._key_backup_path
                        )
                    )
                else:
                    logger.warning(tr("config.crypto_key_regenerated_no_backup"))
                # Key corrupted, generate a new one (old encrypted data becomes unreadable)
                self._key_regenerated = True
                pass
        # Key file missing — check if encrypted data exists that's now unreadable
        if not self._key_file.exists() and not self.is_first_run:
            has_encrypted = bool(
                self._cache.get("api_key_encrypted")
                or self._cache.get("mic_api_key_encrypted")
                or self._cache.get("tts_api_key_encrypted")
            )
            if has_encrypted:
                self._key_regenerated = True
        key = Fernet.generate_key()
        self._key_file.write_bytes(key)
        _restrict_key_file_permissions(self._key_file)
        return Fernet(key)

    def _init_db(self):
        self.conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                          "time TEXT, persona TEXT, content TEXT, image BLOB, round INT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS templates (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                          "name TEXT, version INT, system_pt TEXT, user_pt TEXT, created_at TEXT)")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS session_runs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "started_at REAL NOT NULL, "
            "ended_at REAL NOT NULL, "
            "model TEXT NOT NULL DEFAULT '', "
            "input_tokens INTEGER NOT NULL DEFAULT 0, "
            "output_tokens INTEGER NOT NULL DEFAULT 0, "
            "danmu_count INTEGER NOT NULL DEFAULT 0)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS meme_barrage_library ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "text TEXT NOT NULL UNIQUE, "
            "source_tag TEXT, "
            "remote_id INTEGER, "
            "collected_at REAL NOT NULL)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS custom_danmu_pool_entries ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "text TEXT NOT NULL UNIQUE, "
            "source TEXT NOT NULL DEFAULT 'manual', "
            "enabled INTEGER NOT NULL DEFAULT 1, "
            "created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL, "
            "use_count INTEGER NOT NULL DEFAULT 0)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_custom_danmu_pool_source_id "
            "ON custom_danmu_pool_entries(source, id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_custom_danmu_pool_text "
            "ON custom_danmu_pool_entries(text)"
        )
        # W-LEGACY-MIGRATE-003：独立 system_flags 表存一次性迁移标志位，
        # 避免与 custom_models JSON shape 校验冲突（方案 B）。
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS system_flags (key TEXT PRIMARY KEY, value TEXT)"
        )
        self.conn.commit()

    def _load_cache(self):
        rows = self.conn.execute("SELECT key, value FROM config").fetchall()
        self._cache = {k: v for k, v in rows}

    # --- 通用配置读写 ---

    def get(self, key: str, default: str = "") -> str:
        if self._closed:
            logger.warning("ConfigStore.get(%s) called after close(), returning cached value", key)
        return self._cache.get(key, default)

    def set(self, key: str, value: str):
        """单键写入：commit 成功后再更新 _cache（与 set_batch 一致，失败不污染缓存）。"""
        if self._closed:
            logger.warning("ConfigStore.set(%s) called after close(), write skipped", key)
            return
        self._reject_insecure_encoded_write(key, value)
        with self._write_lock:
            if self._closed:
                logger.warning("ConfigStore.set(%s) called after close(), write skipped", key)
                return
            try:
                self.conn.execute("REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
                self.conn.commit()
                self._cache[key] = value
            except sqlite3.DatabaseError as e:
                self.conn.rollback()
                safe_value = _redact_config_value_for_log(key, value)
                logger.error(
                    tr("config.write_failed").format(key=key, value=safe_value, error=e)
                )
                raise

    def set_if_changed(self, key: str, value: str) -> bool:
        """单键写入；值与缓存一致时跳过 DB 提交。返回 True 表示已写入。"""
        if self._cache.get(key) == value:
            return False
        self.set(key, value)
        return True

    def set_batch(self, items: dict[str, str]):
        """批量写入：单事务内多条 REPLACE，失败 rollback 且不改 _cache。

        Web PUT /api/config 一次提交多键，避免半写入导致 UI 与运行时状态不一致。
        与缓存相同的键会被跳过，减少无意义 WAL 提交。

        锁作用域 = 单次 ``executemany + commit``。典型 Web 保存（≤20 键）持锁
        <5ms；万键批（如自定义弹幕池走 ``set_custom_danmu_pool_for_store``，已走
        diff-based 增量路径）不经过本方法。读路径走 ``_cache`` 不持 ``_write_lock``，
        故 Web GET 不被阻塞。现状可接受，非缺陷（W-INVOKE-OBSERV-001 评估）。
        """
        if self._closed:
            logger.warning("ConfigStore.set_batch() called after close(), write skipped")
            return
        changed = {k: v for k, v in items.items() if self._cache.get(k) != v}
        if not changed:
            return
        with self._write_lock:
            if self._closed:
                logger.warning("ConfigStore.set_batch() called after close(), write skipped")
                return
            try:
                pairs = list(changed.items())
                self.conn.executemany(
                    "REPLACE INTO config (key, value) VALUES (?, ?)",
                    pairs,
                )
                self.conn.commit()
                # Only update cache after successful commit
                for k, v in changed.items():
                    self._cache[k] = v
            except sqlite3.DatabaseError as e:
                self.conn.rollback()
                logger.error(tr("config.batch_write_failed").format(error=type(e).__name__))
                raise

    def _encode_custom_models_json(self, models: list) -> str:
        """Serialize custom models with encrypted apiKey fields (caller may hold write lock)."""
        encrypted: list[dict] = []
        for model in models:
            if not isinstance(model, dict):
                continue
            entry = dict(model)
            plain_key = (entry.get("apiKey") or "").strip()
            if plain_key:
                if self._looks_like_fernet_token(plain_key):
                    entry["apiKey"] = plain_key
                else:
                    entry["apiKey"] = self._encrypt_custom_model_api_key(plain_key)
            encrypted.append(entry)
        return json.dumps(encrypted, ensure_ascii=False)

    def _queue_secret_write(
        self,
        encrypted_key: str,
        encoded_key: str,
        key: str,
        pairs: list[tuple[str, str]],
        keys_to_delete: list[str],
    ) -> None:
        """Queue API key REPLACE/DELETE within an open transaction (caller holds _write_lock)."""
        if not self.secrets_storage_available:
            message = tr("config.crypto_write_blocked")
            logger.error(message)
            raise ConfigStoreCryptoUnavailableError(message)
        encrypted = self._fernet.encrypt(key.encode("utf-8")).decode("utf-8")
        pairs.append((encrypted_key, encrypted))
        if encoded_key in self._cache:
            keys_to_delete.append(encoded_key)

    def apply_web_save(
        self,
        *,
        items: dict[str, str] | None = None,
        api_key: str | None = None,
        mic_api_key: str | None = None,
        custom_models: list[dict] | None = None,
    ) -> None:
        """Web PUT /api/config 原子落库：普通键、API Key、custom_models 单次 commit。

        仅供 ConfigService.apply_web_payload 使用；失败 rollback 且不更新 _cache。
        """
        pairs: list[tuple[str, str]] = []
        keys_to_delete: list[str] = []
        invalidate_secrets: list[str] = []

        if items:
            pairs.extend(items.items())

        if api_key:
            self._queue_secret_write(
                "api_key_encrypted",
                "api_key_encoded",
                api_key,
                pairs,
                keys_to_delete,
            )
            invalidate_secrets.append("api_key_encrypted")

        if mic_api_key:
            self._queue_secret_write(
                "mic_api_key_encrypted",
                "mic_api_key_encoded",
                mic_api_key,
                pairs,
                keys_to_delete,
            )
            invalidate_secrets.append("mic_api_key_encrypted")

        if custom_models is not None:
            pairs.append(("custom_models", self._encode_custom_models_json(custom_models)))

        if not pairs and not keys_to_delete:
            return

        with self._write_lock:
            try:
                if pairs:
                    self.conn.executemany(
                        "REPLACE INTO config (key, value) VALUES (?, ?)",
                        pairs,
                    )
                for key in keys_to_delete:
                    self.conn.execute("DELETE FROM config WHERE key=?", (key,))
                self.conn.commit()
                for key, value in pairs:
                    self._cache[key] = value
                for key in keys_to_delete:
                    self._cache.pop(key, None)
            except sqlite3.DatabaseError as e:
                self.conn.rollback()
                logger.error(tr("config.batch_write_failed").format(error=type(e).__name__))
                raise

        for encrypted_key in invalidate_secrets:
            self._invalidate_secret_cache(encrypted_key)
        if custom_models is not None:
            self._invalidate_custom_models_cache()

    @contextmanager
    def with_write_lock(self):
        """Acquire the SQLite write lock for atomic conn operations (W-CONC-001).

        用于同包模块（``HistoryWriter`` 等）批量 ``executemany`` + ``commit``。
        与 ``set`` / ``set_batch`` 共享同一把 ``self._write_lock``，避免主线程
        持锁时后台线程 ``conn.executemany`` 抛 ``database is locked`` 永久丢数据。

        限制：
            - 仅供同包模块在 SQLite 写入临界区使用；**禁止** HTTP 线程、Web
              路由、其他包模块直接调用（会阻塞主线程 SET 路径）。
            - 进程内临界区（``threading.Lock``），不跨进程；多实例仍受
              ``SingleInstanceGuard`` 串行化。
            - 不可重入：同线程内嵌套调用会死锁。
        """
        with self._write_lock:
            yield self.conn

    @contextmanager
    def with_pool_write_lock(self):
        """Acquire the pool write lock for danmu_pool operations.

        与 ``_write_lock`` 独立，弹幕库写入不阻塞配置读写。
        仅供 ``app/danmu_pool.py`` 使用。

        限制：
            - 不可重入：同线程内嵌套调用会死锁。
            - 不可与 ``_write_lock`` 嵌套使用（会死锁）。
        """
        with self._pool_write_lock:
            yield self.conn

    @staticmethod
    def _normalize_numeric_text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    def get_int(self, key: str, default: int = 0) -> int:
        val = self._normalize_numeric_text(self.get(key, ""))
        if not val:
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            try:
                parsed = float(val)
            except (TypeError, ValueError):
                return default
            if not math.isfinite(parsed) or not parsed.is_integer():
                return default
            return int(parsed)

    def get_float(self, key: str, default: float = 0.0) -> float:
        val = self._normalize_numeric_text(self.get(key, ""))
        if not val:
            return default
        try:
            parsed = float(val)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(parsed):
            return default
        return parsed

    def get_json(self, key: str, default: list | dict | None = None) -> list | dict:
        val = self.get(key)
        if not val:
            return default or {}
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            logger.warning("config key=%s has invalid JSON, returning default", key)
            return default or {}

    def set_json(self, key: str, value: list | dict):
        self.set(key, json.dumps(value, ensure_ascii=False))

    # --- API Key (Fernet encrypted) ---

    def _secret_fingerprint(self, encrypted_key: str, encoded_key: str) -> tuple[str, str]:
        return (self.get(encrypted_key, ""), self.get(encoded_key, ""))

    def _invalidate_secret_cache(self, encrypted_key: str) -> None:
        self._decrypted_secret_cache.pop(encrypted_key, None)
        self._decrypted_secret_fp.pop(encrypted_key, None)

    def _cache_decrypted_secret(
        self, encrypted_key: str, encoded_key: str, plaintext: str
    ) -> str:
        self._decrypted_secret_cache[encrypted_key] = plaintext
        self._decrypted_secret_fp[encrypted_key] = self._secret_fingerprint(
            encrypted_key, encoded_key
        )
        return plaintext

    def _encrypted_get(self, encrypted_key: str, encoded_key: str) -> str:
        """读取加密或 legacy base64 编码的 API Key 明文（指纹缓存避免重复解密）。"""
        fp = self._secret_fingerprint(encrypted_key, encoded_key)
        if self._decrypted_secret_fp.get(encrypted_key) == fp:
            return self._decrypted_secret_cache[encrypted_key]

        encrypted, encoded = fp
        if encrypted and _cs_pkg._HAS_CRYPTO and self._fernet:
            try:
                plaintext = self._fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
                return self._cache_decrypted_secret(encrypted_key, encoded_key, plaintext)
            except (InvalidToken, ValueError, UnicodeDecodeError):
                logger.warning(tr("config.decrypt_failed"))
        if not encoded:
            return self._cache_decrypted_secret(encrypted_key, encoded_key, "")
        try:
            plaintext = b64decode(encoded).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return self._cache_decrypted_secret(encrypted_key, encoded_key, "")
        # W-MEDLOW-004：安装 cryptography 后首次读取 legacy base64 时自动升级为 Fernet。
        if _cs_pkg._HAS_CRYPTO and self._fernet and not encrypted:
            try:
                self._encrypted_set(encrypted_key, encoded_key, plaintext)
            except (ConfigStoreCryptoUnavailableError, ValueError, OSError, sqlite3.Error) as exc:
                logger.warning(
                    "config key auto-upgrade failed key=%s error=%s",
                    encrypted_key,
                    type(exc).__name__,
                )
        elif encoded and not encrypted and not self.secrets_storage_available:
            logger.warning(tr("config.insecure_read"))
        return self._cache_decrypted_secret(encrypted_key, encoded_key, plaintext)

    def _encrypted_set(self, encrypted_key: str, encoded_key: str, key: str) -> None:
        """写入 API Key：Fernet 加密或退化为 base64；持 _write_lock 保证 cache/DB 一致。"""
        pairs: list[tuple[str, str]] = []
        keys_to_delete: list[str] = []
        self._queue_secret_write(encrypted_key, encoded_key, key, pairs, keys_to_delete)
        with self._write_lock:
            try:
                if pairs:
                    self.conn.executemany(
                        "REPLACE INTO config (key, value) VALUES (?, ?)",
                        pairs,
                    )
                for delete_key in keys_to_delete:
                    self.conn.execute("DELETE FROM config WHERE key=?", (delete_key,))
                self.conn.commit()
                for storage_key, value in pairs:
                    self._cache[storage_key] = value
                for delete_key in keys_to_delete:
                    self._cache.pop(delete_key, None)
            except sqlite3.DatabaseError as e:
                self.conn.rollback()
                logger.error(tr("config.api_key_write_failed").format(error=type(e).__name__))
                raise
        self._invalidate_secret_cache(encrypted_key)

    def get_api_key(self) -> str:
        """读取明文 API Key：优先 Fernet 解密 api_key_encrypted，否则回退 base64 的 api_key_encoded。"""
        return self._encrypted_get("api_key_encrypted", "api_key_encoded")

    def set_api_key(self, key: str):
        """写入 API Key：有 Fernet 则加密存 api_key_encrypted 并清除旧 base64 行。"""
        self._encrypted_set("api_key_encrypted", "api_key_encoded", key)

    def get_tts_api_key(self) -> str:
        """读弹幕专用 TTS API Key（tts_api_key_encrypted）。"""
        return self._encrypted_get("tts_api_key_encrypted", "tts_api_key_encoded")

    def set_tts_api_key(self, key: str) -> None:
        """写入 TTS API Key（加密存储）。"""
        self._encrypted_set("tts_api_key_encrypted", "tts_api_key_encoded", key)

    def get_mic_api_key(self) -> str:
        """读麦克风专用 API Key（mic_api_key_encrypted）。"""
        return self._encrypted_get("mic_api_key_encrypted", "mic_api_key_encoded")

    def set_mic_api_key(self, key: str) -> None:
        """写入麦克风专用 API Key（加密存储）。"""
        self._encrypted_set("mic_api_key_encrypted", "mic_api_key_encoded", key)

    # --- 选区持久化 ---

    @staticmethod
    def _normalize_region(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        """无有效尺寸时四键一致归零（全屏 / 未选区）。"""
        if w <= 0 or h <= 0:
            return 0, 0, 0, 0
        return x, y, w, h

    def _repair_stale_region_if_needed(self) -> None:
        x = self.get_int("region_x", 0)
        y = self.get_int("region_y", 0)
        w = self.get_int("region_w", 0)
        h = self.get_int("region_h", 0)
        if (w <= 0 or h <= 0) and (x, y, w, h) != (0, 0, 0, 0):
            self.set_region(0, 0, 0, 0)

    def get_region(self) -> tuple[int, int, int, int]:
        x = self.get_int("region_x", 0)
        y = self.get_int("region_y", 0)
        w = self.get_int("region_w", 0)
        h = self.get_int("region_h", 0)
        return self._normalize_region(x, y, w, h)

    def set_region(self, x: int, y: int, w: int, h: int):
        x, y, w, h = self._normalize_region(x, y, w, h)
        self.set_batch({
            "region_x": str(x),
            "region_y": str(y),
            "region_w": str(w),
            "region_h": str(h),
        })

    # --- Custom model profiles (apiKey encrypted inline in JSON) ---

    def _invalidate_custom_models_cache(self) -> None:
        self._custom_models_cache = None
        self._custom_models_fp = None

    def _looks_like_fernet_token(self, value: str) -> bool:
        """Heuristic Fernet token check — avoids trial decrypt on hot path."""
        if not value or not _cs_pkg._HAS_CRYPTO or not self._fernet:
            return False
        if len(value) < 57 or not value.startswith("gAAAAA"):
            return False
        return True

    def _encrypt_custom_model_api_key(self, key: str) -> str:
        """Encrypt custom-model apiKey with the same Fernet key as api_key_encrypted."""
        if not key:
            return ""
        if not self.secrets_storage_available:
            message = tr("config.crypto_write_blocked")
            logger.error(message)
            raise ConfigStoreCryptoUnavailableError(message)
        return self._fernet.encrypt(key.encode("utf-8")).decode("utf-8")

    def _resolve_custom_model_api_key(self, stored: str) -> tuple[str, bool]:
        """Return (plaintext apiKey, needs_encryption_upgrade)."""
        if not stored:
            return "", False
        if self._looks_like_fernet_token(stored):
            try:
                return self._fernet.decrypt(stored.encode("utf-8")).decode("utf-8"), False
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
        return stored, bool(stored) and not self._looks_like_fernet_token(stored)

    def get_custom_models(self) -> list:
        """Return custom models with decrypted apiKey; upgrade legacy plaintext on read.

        W-CUSTOMMODEL-SCHEMA-002: 同时在返回前对每条档案做 shape 迁移
       （旧 ``modelId`` 单值 → 新 ``model_ids`` 数组 + ``default_model_id`` + ``max_tokens``）。
        迁移幂等、不写回 DB；新 shape 在下次 ``set_custom_models`` 调用时持久化。
        """
        raw = self.get("custom_models", "")
        if self._custom_models_cache is not None and raw == self._custom_models_fp:
            return [_migrate_custom_model_shape(dict(m)) for m in self._custom_models_cache]

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
                plain_key, needs_encrypt = self._resolve_custom_model_api_key(stored_key)
                entry["apiKey"] = plain_key
                if needs_encrypt:
                    needs_upgrade = True
            result.append(entry)
        if needs_upgrade:
            self.set_custom_models(result)
            raw = self.get("custom_models", "")
        self._custom_models_cache = result
        self._custom_models_fp = raw
        return [_migrate_custom_model_shape(dict(m)) for m in self._custom_models_cache]

    def set_custom_models(self, models: list):
        """Persist custom models; each apiKey is Fernet-encrypted before JSON serialization."""
        self.set("custom_models", self._encode_custom_models_json(models))
        self._invalidate_custom_models_cache()

    # --- Custom danmu pool (custom_danmu_pool_entries table) ---

    def custom_danmu_count(self, source: str | None = None) -> int:
        from app.danmu_pool import custom_danmu_count_for_store

        return custom_danmu_count_for_store(self, source)

    def custom_danmu_list(
        self,
        page: int = 1,
        page_size: int = 100,
        search: str = "",
        source: str | None = "manual",
    ) -> dict:
        from app.danmu_pool import custom_danmu_list_for_store

        return custom_danmu_list_for_store(self, page, page_size, search, source)

    def custom_danmu_insert_many(self, texts: list[str], source: str = "manual") -> dict[str, int]:
        from app.danmu_pool import custom_danmu_insert_many_for_store

        return custom_danmu_insert_many_for_store(self, texts, source)

    def custom_danmu_delete_ids(self, ids: list[int]) -> int:
        from app.danmu_pool import custom_danmu_delete_ids_for_store

        return custom_danmu_delete_ids_for_store(self, ids)

    def custom_danmu_delete_texts(self, texts: list[str]) -> int:
        from app.danmu_pool import custom_danmu_delete_texts_for_store

        return custom_danmu_delete_texts_for_store(self, texts)

    def custom_danmu_random_sample(self, count: int) -> list[str]:
        from app.danmu_pool import custom_danmu_random_sample_for_store

        return custom_danmu_random_sample_for_store(self, count)

    def custom_danmu_contains_text(self, text: str) -> bool:
        from app.danmu_pool import custom_danmu_contains_text_for_store

        return custom_danmu_contains_text_for_store(self, text)

    def custom_danmu_enabled_ids(self) -> list[int]:
        from app.danmu_pool import custom_danmu_enabled_ids_for_store

        return custom_danmu_enabled_ids_for_store(self)

    def custom_danmu_texts_by_ids(self, ids: list[int]) -> list[str]:
        from app.danmu_pool import custom_danmu_texts_by_ids_for_store

        return custom_danmu_texts_by_ids_for_store(self, ids)

    def get_custom_danmu_pool(self) -> list[str]:
        from app.danmu_pool import get_custom_danmu_pool_for_store

        return get_custom_danmu_pool_for_store(self)

    def set_custom_danmu_pool(self, items: list[str]) -> None:
        from app.danmu_pool import set_custom_danmu_pool_for_store

        set_custom_danmu_pool_for_store(self, items)

    def get_recent_history(self, limit: int = 30) -> list[str]:
        """Return the most recent `limit` history entries (oldest first)."""
        if not self._conn_usable():
            return []
        try:
            rows = self.conn.execute(
                "SELECT content FROM history ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [str(row[0]) for row in reversed(rows) if row and row[0]]
        except sqlite3.Error:
            return []

    # --- Meme barrage library (meme_barrage_library table) ---

    def _conn_usable(self) -> bool:
        """False after close(); HTTP 退出竞态读库时避免 ProgrammingError。"""
        return not getattr(self, "_closed", False)

    def meme_barrage_library_count(self) -> int:
        if not self._conn_usable():
            return 0
        try:
            row = self.conn.execute("SELECT COUNT(*) FROM meme_barrage_library").fetchone()
        except sqlite3.ProgrammingError:
            return 0
        if not row or row[0] is None:
            return 0
        return int(row[0])

    def meme_barrage_library_clear(self) -> None:
        with self._write_lock:
            self.conn.execute("DELETE FROM meme_barrage_library")
            self.conn.commit()
        self._invalidate_formula_text_cache()

    def meme_barrage_library_insert_many(
        self,
        items: list[tuple[str, str | None, int | None]],
        *,
        collected_at: float,
        max_rows: int,
    ) -> int:
        params = []
        for text, source_tag, remote_id in items:
            stripped = str(text).strip()
            if stripped:
                params.append((stripped, source_tag, remote_id, collected_at))
        if not params:
            return 0
        with self._write_lock:
            before = self.conn.total_changes
            self.conn.executemany(
                "INSERT OR IGNORE INTO meme_barrage_library "
                "(text, source_tag, remote_id, collected_at) VALUES (?, ?, ?, ?)",
                params,
            )
            added = self.conn.total_changes - before
            self._trim_meme_barrage_library_locked(max_rows)
            self.conn.commit()
        self._invalidate_formula_text_cache()
        return added

    def meme_barrage_library_all_texts(self) -> list[str]:
        """All meme library lines for formula-text cache warm-up (max LIBRARY_MAX_ROWS)."""
        if not self._conn_usable():
            return []
        try:
            from app.meme_barrage.store import LIBRARY_MAX_ROWS

            rows = self.conn.execute(
                "SELECT text FROM meme_barrage_library ORDER BY id ASC LIMIT ?",
                (LIBRARY_MAX_ROWS,),
            ).fetchall()
        except sqlite3.ProgrammingError:
            return []
        return [str(row[0]).strip() for row in rows if row and row[0] and str(row[0]).strip()]

    def meme_barrage_library_contains_text(self, text: str) -> bool:
        """True when text exactly matches a row in meme_barrage_library."""
        value = str(text).strip()
        if not value:
            return False
        if not self._conn_usable():
            return False
        try:
            row = self.conn.execute(
                "SELECT 1 FROM meme_barrage_library WHERE text = ? LIMIT 1",
                (value,),
            ).fetchone()
        except sqlite3.ProgrammingError:
            return False
        return row is not None

    def meme_barrage_library_fetch_batch(
        self, offset: int, limit: int
    ) -> tuple[list[str], int]:
        if limit <= 0:
            return [], offset
        total = self.meme_barrage_library_count()
        if total <= 0:
            return [], 0
        offset = int(offset) % total
        if not self._conn_usable():
            return [], offset
        try:
            rows = self.conn.execute(
                "SELECT text FROM meme_barrage_library ORDER BY id ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        except sqlite3.ProgrammingError:
            return [], offset
        texts = [str(row[0]) for row in rows if row and row[0]]
        next_offset = (offset + len(texts)) % total if total else 0
        return texts, next_offset

    def _trim_meme_barrage_library_locked(self, max_rows: int) -> None:
        count = self.conn.execute("SELECT COUNT(*) FROM meme_barrage_library").fetchone()
        total = 0 if not count or count[0] is None else int(count[0])
        if total <= max_rows:
            return
        excess = total - max_rows
        self.conn.execute(
            "DELETE FROM meme_barrage_library WHERE id IN ("
            "SELECT id FROM meme_barrage_library ORDER BY id ASC LIMIT ?"
            ")",
            (excess,),
        )
        self._invalidate_formula_text_cache()

    def _invalidate_formula_text_cache(self) -> None:
        from app.danmu_pool import invalidate_formula_text_cache

        invalidate_formula_text_cache(self)

    def get_default_model_id(self) -> str:
        model_id = self.get("default_model_id", "")
        if model_id:
            return model_id
        return self.get("model", "")

    def set_default_model_id(self, model_id: str):
        self.set("default_model_id", model_id)

    # --- System flags (one-shot migration markers, W-LEGACY-MIGRATE-003) ---

    def get_flag(self, key: str) -> str | None:
        """Read a system flag from ``system_flags`` table; returns None if missing.

        读操作不持 ``_write_lock``（WAL 模式下读不阻塞写）。close 后返回 None。
        """
        if not self._conn_usable():
            return None
        try:
            row = self.conn.execute(
                "SELECT value FROM system_flags WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.ProgrammingError:
            return None
        if not row:
            return None
        return row[0]

    def set_flag(self, key: str, value: str) -> None:
        """Write a system flag (REPLACE INTO);持 ``_write_lock`` 保证事务一致。

        注意：``_write_lock`` 是非可重入 ``threading.Lock``；本方法**不能**在
        已持 ``_write_lock`` 的临界区内调用（如 ``with_write_lock`` 内），
        否则会自死锁。
        """
        if self._closed:
            logger.warning(
                "ConfigStore.set_flag(%s) called after close(), write skipped", key
            )
            return
        with self._write_lock:
            if self._closed:
                logger.warning(
                    "ConfigStore.set_flag(%s) called after close(), write skipped", key
                )
                return
            try:
                self.conn.execute(
                    "REPLACE INTO system_flags (key, value) VALUES (?, ?)",
                    (key, value),
                )
                self.conn.commit()
            except sqlite3.DatabaseError as e:
                self.conn.rollback()
                logger.error(
                    "set_flag failed key=%s error=%s", key, type(e).__name__
                )
                raise

    def _maybe_migrate_legacy_api_to_custom_models(self) -> bool:
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
            # 1. 读取 cfg.api_key（解密可能抛异常）
            try:
                api_key = self.get_api_key()
            except Exception as exc:  # noqa: BLE001 — 解密异常需兜底
                logger.warning(
                    "legacy api cleanup skipped: api_key decrypt failed",
                    extra={"reason": "legacy_cleanup_failed", "error": str(exc)},
                )
                self.set_flag("legacy_api_migrated_v1", "true")
                return True

            # 2. 快速秒退：api_key 已空（已清空或从未设置）
            if not api_key:
                return True

            # 3. MASKED key 兜底：仅置标志位 true（测试残留或显示值，非真实 key）
            from app.application.config_service import MASKED_API_KEY

            if api_key == MASKED_API_KEY:
                self.set_flag("legacy_api_migrated_v1", "true")
                return True

            # 4. 标志位已 true + api_key 仍非空 → 分支 C 已命中过，不重试
            if self.get_flag("legacy_api_migrated_v1") == "true":
                return True

            # 5. 运行安全网
            from app.model_providers import (
                guess_provider_from_endpoint,
                is_model_config_complete,
            )

            existing_models = self.get_custom_models()

            # 分支 A：存在完整 custom_models 档案 → 清空全局三字段
            has_complete_profile = any(
                is_model_config_complete(entry) for entry in existing_models
            )
            if has_complete_profile:
                self.set_api_key("")
                self.set("api_endpoint", "")
                self.set("api_mode", "")
                self.set_flag("legacy_api_migrated_v1", "true")
                logger.info(
                    "legacy global api cleaned: complete profile exists",
                    extra={"reason": "legacy_cleanup_done", "branch": "A"},
                )
                return True

            # 分支 B/C：检查全局凭证是否完整
            endpoint = self.get("api_endpoint", "")
            cfg_model = self.get("model", "")

            if not endpoint or not cfg_model:
                # 分支 C：全局凭证不完整，无法建档
                logger.warning(
                    "legacy cleanup incomplete: missing endpoint or model",
                    extra={"reason": "legacy_cleanup_incomplete"},
                )
                self.set_flag("legacy_api_migrated_v1", "true")
                return True

            # 分支 B：全局凭证完整 → 自动建档 + 清空全局
            api_mode = self.get("api_mode", "")
            provider = (
                guess_provider_from_endpoint(endpoint, api_mode) or "custom_openai"
            )
            mode = "doubao" if provider == "doubao" else "openai-compatible"
            default_model_id = cfg_model
            model_ids = [cfg_model]
            max_tokens_raw = self.get("max_tokens", "512")
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

            self.set_custom_models([profile])

            from app.application.config_service import set_default_model_selection

            set_default_model_selection(self, default_model_id)

            # 清空全局三字段
            self.set_api_key("")
            self.set("api_endpoint", "")
            self.set("api_mode", "")
            self.set_flag("legacy_api_migrated_v1", "true")

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

    def close(self):
        with self._write_lock:
            self._closed = True
        self._invalidate_formula_text_cache()
        try:
            self.conn.close()
        except sqlite3.ProgrammingError:
            pass
