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
弹幕池 CRUD 重新导出于 ``app.config_store.pool``，烂梗库 CRUD 实现位于 ``app.config_store.storage_meme``，
custom_models 与 API Key 读写实现位于 ``app.config_store.storage_models``，
system_flags 与 legacy API 迁移实现位于 ``app.config_store.storage_legacy``。
``_HAS_CRYPTO`` 通过 ``_cs_pkg._HAS_CRYPTO``
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

from app.config_migrations import run_pending
from app.translations import Translator, tr

# 通过包属性访问 _HAS_CRYPTO，使 patch("app.config_store._HAS_CRYPTO", ...) 生效。
# 详见模块 docstring。
import app.config_store as _cs_pkg

from app.config_store.crypto import (
    ConfigStoreCryptoUnavailableError,
    _backup_corrupted_key_file,
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
            affected = self._unreadable_encrypted_field_names()
            if affected:
                sep = "、" if Translator.get_language() == "zh" else ", "
                keys_text = sep.join(affected)
                if self._key_backup_path is not None:
                    return tr("config.key_lost_notice_with_backup_specific").format(
                        keys=keys_text, backup_path=self._key_backup_path
                    )
                return tr("config.key_lost_notice_specific").format(keys=keys_text)
            # key 重新生成但无受影响字段 → 退回通用文案
            if self._key_backup_path is not None:
                return tr("config.key_lost_notice_with_backup").format(
                    backup_path=self._key_backup_path
                )
            return tr("config.key_lost_notice")
        return ""

    def _unreadable_encrypted_field_names(self) -> list[str]:
        """BUG-015: key 重新生成后，返回仍残留密文但已无法解密的字段本地化名列表。"""
        fields = [
            ("api_key_encrypted", "config.key_name.api_key"),
            ("mic_api_key_encrypted", "config.key_name.mic_api_key"),
            ("tts_api_key_encrypted", "config.key_name.tts_api_key"),
        ]
        return [tr(label) for cache_key, label in fields if self._cache.get(cache_key)]

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
        # BUG-016: close 后写操作必须抛 RuntimeError 而非静默跳过，避免并发 close 竞态丢写无错误反馈。
        if self._closed:
            raise RuntimeError(f"ConfigStore.set({key!r}) called after close()")
        self._reject_insecure_encoded_write(key, value)
        with self._write_lock:
            if self._closed:
                raise RuntimeError(f"ConfigStore.set({key!r}) called after close()")
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
            raise RuntimeError("ConfigStore.set_batch() called after close()")
        changed = {k: v for k, v in items.items() if self._cache.get(k) != v}
        if not changed:
            return
        with self._write_lock:
            if self._closed:
                raise RuntimeError("ConfigStore.set_batch() called after close()")
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
        from app.config_store.storage_models import _encode_custom_models_json

        return _encode_custom_models_json(self, models)

    def _queue_secret_write(
        self,
        encrypted_key: str,
        encoded_key: str,
        key: str,
        pairs: list[tuple[str, str]],
        keys_to_delete: list[str],
    ) -> None:
        from app.config_store.storage_models import _queue_secret_write

        _queue_secret_write(
            self, encrypted_key, encoded_key, key, pairs, keys_to_delete
        )

    def apply_web_save(
        self,
        *,
        items: dict[str, str] | None = None,
        api_key: str | None = None,
        mic_api_key: str | None = None,
        custom_models: list[dict] | None = None,
        flags: dict[str, str] | None = None,
    ) -> None:
        from app.config_store.storage_models import apply_web_save_for_store

        apply_web_save_for_store(
            self,
            items=items,
            api_key=api_key,
            mic_api_key=mic_api_key,
            custom_models=custom_models,
            flags=flags,
        )

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
        from app.config_store.storage_models import _secret_fingerprint

        return _secret_fingerprint(self, encrypted_key, encoded_key)

    def _invalidate_secret_cache(self, encrypted_key: str) -> None:
        from app.config_store.storage_models import invalidate_secret_cache_for_store

        invalidate_secret_cache_for_store(self, encrypted_key)

    def _cache_decrypted_secret(
        self, encrypted_key: str, encoded_key: str, plaintext: str
    ) -> str:
        from app.config_store.storage_models import _cache_decrypted_secret

        return _cache_decrypted_secret(self, encrypted_key, encoded_key, plaintext)

    def _encrypted_get(self, encrypted_key: str, encoded_key: str) -> str:
        from app.config_store.storage_models import encrypted_get_for_store

        return encrypted_get_for_store(self, encrypted_key, encoded_key)

    def _encrypted_set(self, encrypted_key: str, encoded_key: str, key: str) -> None:
        from app.config_store.storage_models import encrypted_set_for_store

        encrypted_set_for_store(self, encrypted_key, encoded_key, key)

    def get_api_key(self) -> str:
        from app.config_store.storage_models import get_api_key_for_store

        return get_api_key_for_store(self)

    def set_api_key(self, key: str):
        from app.config_store.storage_models import set_api_key_for_store

        set_api_key_for_store(self, key)

    def get_tts_api_key(self) -> str:
        from app.config_store.storage_models import get_tts_api_key_for_store

        return get_tts_api_key_for_store(self)

    def set_tts_api_key(self, key: str) -> None:
        from app.config_store.storage_models import set_tts_api_key_for_store

        set_tts_api_key_for_store(self, key)

    def get_mic_api_key(self) -> str:
        from app.config_store.storage_models import get_mic_api_key_for_store

        return get_mic_api_key_for_store(self)

    def set_mic_api_key(self, key: str) -> None:
        from app.config_store.storage_models import set_mic_api_key_for_store

        set_mic_api_key_for_store(self, key)

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
        from app.config_store.storage_models import invalidate_custom_models_cache_for_store

        invalidate_custom_models_cache_for_store(self)

    def _looks_like_fernet_token(self, value: str) -> bool:
        from app.config_store.storage_models import _looks_like_fernet_token

        return _looks_like_fernet_token(self, value)

    def _encrypt_custom_model_api_key(self, key: str) -> str:
        from app.config_store.storage_models import _encrypt_custom_model_api_key

        return _encrypt_custom_model_api_key(self, key)

    def _resolve_custom_model_api_key(self, stored: str) -> tuple[str, bool]:
        from app.config_store.storage_models import _resolve_custom_model_api_key

        return _resolve_custom_model_api_key(self, stored)

    def get_custom_models(self) -> list:
        from app.config_store.storage_models import get_custom_models_for_store

        return get_custom_models_for_store(self)

    def set_custom_models(self, models: list):
        from app.config_store.storage_models import set_custom_models_for_store

        set_custom_models_for_store(self, models)

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

    def _conn_usable(self) -> bool:
        """False after close(); HTTP 退出竞态读库时避免 ProgrammingError。"""
        return not getattr(self, "_closed", False)

    # --- Meme barrage library (meme_barrage_library table) ---

    def meme_barrage_library_count(self) -> int:
        from app.config_store.storage_meme import meme_barrage_library_count_for_store

        return meme_barrage_library_count_for_store(self)

    def meme_barrage_library_clear(self) -> None:
        from app.config_store.storage_meme import meme_barrage_library_clear_for_store

        meme_barrage_library_clear_for_store(self)

    def meme_barrage_library_insert_many(
        self,
        items: list[tuple[str, str | None, int | None]],
        *,
        collected_at: float,
        max_rows: int,
    ) -> int:
        from app.config_store.storage_meme import meme_barrage_library_insert_many_for_store

        return meme_barrage_library_insert_many_for_store(
            self, items, collected_at=collected_at, max_rows=max_rows
        )

    def meme_barrage_library_all_texts(self) -> list[str]:
        from app.config_store.storage_meme import meme_barrage_library_all_texts_for_store

        return meme_barrage_library_all_texts_for_store(self)

    def meme_barrage_library_contains_text(self, text: str) -> bool:
        from app.config_store.storage_meme import meme_barrage_library_contains_text_for_store

        return meme_barrage_library_contains_text_for_store(self, text)

    def meme_barrage_library_fetch_batch(
        self, offset: int, limit: int
    ) -> tuple[list[str], int]:
        from app.config_store.storage_meme import meme_barrage_library_fetch_batch_for_store

        return meme_barrage_library_fetch_batch_for_store(self, offset, limit)

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
        from app.config_store.storage_legacy import get_flag_for_store

        return get_flag_for_store(self, key)

    def set_flag(self, key: str, value: str) -> None:
        from app.config_store.storage_legacy import set_flag_for_store

        set_flag_for_store(self, key, value)

    def _maybe_migrate_legacy_api_to_custom_models(self) -> bool:
        from app.config_store.storage_legacy import (
            maybe_migrate_legacy_api_to_custom_models_for_store,
        )

        return maybe_migrate_legacy_api_to_custom_models_for_store(self)

    def close(self):
        # BUG-005: 先等弹幕库写入结束（_pool_write_lock），再与配置写锁一起关闭连接。
        # BUG-016: conn.close() 必须在 _write_lock 内完成，否则并发 set/set_batch
        # 会在 close 出锁后、conn.close() 完成前拿到锁并走「静默跳过」分支丢写。
        with self._pool_write_lock:
            with self._write_lock:
                self._closed = True
                try:
                    self.conn.close()
                except sqlite3.ProgrammingError:
                    pass
        self._invalidate_formula_text_cache()
