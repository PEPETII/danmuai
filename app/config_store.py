"""SQLite 配置存储：内存缓存 + WAL 并发读 + Fernet 加密 API Key。

设计要点：
- **%APPDATA%/DanmuAI/config.db** 持久化；**%APPDATA%/DanmuAI/.key** 为 Fernet 对称密钥。
- **密钥丢失或 .key 被删/损坏后重新生成**：旧 api_key_encrypted 无法解密，等同不可恢复（须重新填写 Key）。
- **向后兼容**：无 cryptography 时退化为 base64 存 api_key_encoded（仅编码非加密）；有 Fernet 后写入 encrypted 并删除 encoded。
- **WAL + busy_timeout**：允许多读者与单写者共存，写路径用 _write_lock 串行化避免 cache/DB 不一致。
- **set_batch**：显式事务，commit 成功后才更新 _cache，失败 rollback。

调用方：DanmuApp、ConfigService.apply_web_payload、各模块读配置。

存储边界：新业务模块禁止继续共享 ConfigStore 的 SQLite 连接；历史/模板等应经既有门面访问，见 docs/phase1-boundary-rules.md。
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
    from cryptography.fernet import Fernet
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

from base64 import b64decode, b64encode

from app.translations import tr

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



def _restrict_key_file_permissions(path: Path):
    """Set file permissions so only the owner can read/write (best-effort)."""
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


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

    def get_startup_notice(self) -> str:
        """首装会话返回本地化引导文案；密钥丢失时返回告警文案；否则为空。"""
        if self.is_first_run:
            return tr("config.startup_notice")
        if self._key_regenerated:
            return tr("config.key_lost_notice")
        return ""

    def _init_fernet(self):
        """加载或生成 %APPDATA%/DanmuAI/.key；校验失败则换新 key（旧密文永久不可读）。"""
        if not _HAS_CRYPTO:
            logger.warning(tr("config.crypto_missing"))
            return None
        if self._key_file.exists():
            key = self._key_file.read_bytes()
            try:
                f = Fernet(key)
                # Verify key is valid by a dummy round-trip
                f.decrypt(f.encrypt(b"test"))
                return f
            except Exception:
                logger.warning(
                    tr("config.crypto_key_regenerated")
                )
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
        with self._write_lock:
            try:
                self.conn.execute("REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
                self.conn.commit()
                self._cache[key] = value
            except sqlite3.OperationalError as e:
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
        """
        if self._closed:
            logger.warning("ConfigStore.set_batch() called after close(), write skipped")
            return
        changed = {k: v for k, v in items.items() if self._cache.get(k) != v}
        if not changed:
            return
        with self._write_lock:
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
            except sqlite3.OperationalError as e:
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
        if _HAS_CRYPTO and self._fernet:
            encrypted = self._fernet.encrypt(key.encode("utf-8")).decode("utf-8")
            pairs.append((encrypted_key, encrypted))
            if encoded_key in self._cache:
                keys_to_delete.append(encoded_key)
            return
        logger.warning(tr("config.insecure_store"))
        pairs.append((encoded_key, b64encode(key.encode("utf-8")).decode("utf-8")))

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
            except sqlite3.OperationalError as e:
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
        if encrypted and _HAS_CRYPTO and self._fernet:
            try:
                plaintext = self._fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8")
                return self._cache_decrypted_secret(encrypted_key, encoded_key, plaintext)
            except Exception:
                logger.warning(tr("config.decrypt_failed"))
        if not encoded:
            return self._cache_decrypted_secret(encrypted_key, encoded_key, "")
        try:
            plaintext = b64decode(encoded).decode("utf-8")
        except Exception:
            return self._cache_decrypted_secret(encrypted_key, encoded_key, "")
        # W-MEDLOW-004：安装 cryptography 后首次读取 legacy base64 时自动升级为 Fernet。
        if _HAS_CRYPTO and self._fernet and not encrypted:
            try:
                self._encrypted_set(encrypted_key, encoded_key, plaintext)
            except Exception as exc:
                logger.warning(
                    "config key auto-upgrade failed key=%s error=%s",
                    encrypted_key,
                    type(exc).__name__,
                )
        elif encrypted_key == "api_key_encrypted" and _HAS_CRYPTO and self._fernet is None:
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
            except sqlite3.OperationalError as e:
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
        if not value or not _HAS_CRYPTO or not self._fernet:
            return False
        if len(value) < 57 or not value.startswith("gAAAAA"):
            return False
        return True

    def _encrypt_custom_model_api_key(self, key: str) -> str:
        """Encrypt custom-model apiKey with the same Fernet key as api_key_encrypted."""
        if not key:
            return ""
        if _HAS_CRYPTO and self._fernet:
            return self._fernet.encrypt(key.encode("utf-8")).decode("utf-8")
        logger.warning(tr("config.insecure_store"))
        return b64encode(key.encode("utf-8")).decode("utf-8")

    def _resolve_custom_model_api_key(self, stored: str) -> tuple[str, bool]:
        """Return (plaintext apiKey, needs_encryption_upgrade)."""
        if not stored:
            return "", False
        if self._looks_like_fernet_token(stored):
            try:
                return self._fernet.decrypt(stored.encode("utf-8")).decode("utf-8"), False
            except Exception:
                pass
        try:
            decoded = b64decode(stored).decode("utf-8")
        except Exception:
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
            except Exception:
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
        except Exception:
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
            try:
                self.conn.execute(
                    "REPLACE INTO system_flags (key, value) VALUES (?, ?)",
                    (key, value),
                )
                self.conn.commit()
            except sqlite3.OperationalError as e:
                self.conn.rollback()
                logger.error(
                    "set_flag failed key=%s error=%s", key, type(e).__name__
                )
                raise

    def _maybe_migrate_legacy_api_to_custom_models(self) -> bool:
        """W-LEGACY-MIGRATE-003: 启动期把 legacy 顶栏 API 字段迁移到默认 custom_models 档案。

        触发条件（全部 AND）：
            1. ``system_flags.legacy_api_migrated_v1`` 不为 ``"true"``
            2. ``cfg.api_key`` 非空且非 ``MASKED_API_KEY``
            3. ``get_custom_models()`` 返回空（无任何档案）

        迁移动作：
            - 推断 provider（``guess_provider_from_endpoint`` 失败兜底 ``custom_openai``）
            - 推断 mode（doubao provider → ``doubao``；其他 → ``openai-compatible``）
            - 写入一条默认档案 dict（含 model_ids / default_model_id / max_tokens）
            - 调 ``set_default_model_selection(config, default_model_id)``
            - 写标志位 ``legacy_api_migrated_v1 = "true"``

        兜底（仅置标志位 true，不插档案、不改默认）：
            - api_key 为空 / MASKED / 解密异常
            - 已有 custom_models 档案（保护用户数据）

        异常容错：迁移过程中任一步失败 → 不置标志位 → 下次启动重试；
        记录 ``reason=legacy_migrate_failed`` 日志。

        Returns:
            True 表示执行了迁移或标志位已 true（无需再迁移）；
            False 表示异常失败（下次启动重试）。
        """
        try:
            # 1. 标志位已 true → 直接 return（幂等保证）
            if self.get_flag("legacy_api_migrated_v1") == "true":
                return True

            # 2. 读取 cfg.api_key（解密可能抛异常）
            try:
                api_key = self.get_api_key()
            except Exception as exc:  # noqa: BLE001 — 解密异常需兜底
                logger.warning(
                    "legacy api migrate skipped: api_key decrypt failed",
                    extra={"reason": "legacy_migrate_failed", "error": str(exc)},
                )
                self.set_flag("legacy_api_migrated_v1", "true")
                return True

            # 3. 空 key / MASKED 兜底：仅置标志位 true
            from app.application.config_service import MASKED_API_KEY

            if not api_key or api_key == MASKED_API_KEY:
                self.set_flag("legacy_api_migrated_v1", "true")
                return True

            # 4. 已有档案兜底：保护用户数据，仅置标志位 true
            existing_models = self.get_custom_models()
            if existing_models:
                self.set_flag("legacy_api_migrated_v1", "true")
                return True

            # 5. 推断 provider（失败兜底 custom_openai）
            from app.model_providers import guess_provider_from_endpoint

            endpoint = self.get("api_endpoint", "")
            api_mode = self.get("api_mode", "")
            provider = (
                guess_provider_from_endpoint(endpoint, api_mode) or "custom_openai"
            )

            # 6. 推断 mode（按 provider 简化判断）
            mode = "doubao" if provider == "doubao" else "openai-compatible"

            # 7. 构造默认档案 dict
            cfg_model = self.get("model", "")
            model_ids = [cfg_model] if cfg_model else []
            default_model_id = cfg_model or ""
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

            # 8. 写入档案（set_custom_models 会触发缓存失效）
            self.set_custom_models([profile])

            # 9. 调 set_default_model_selection 维护 default_model_id + legacy model 双写
            if default_model_id:
                from app.application.config_service import set_default_model_selection

                set_default_model_selection(self, default_model_id)

            # 10. 写标志位 true（幂等保证：下次启动不再迁移）
            self.set_flag("legacy_api_migrated_v1", "true")

            logger.info(
                "legacy api migrated to default custom model profile",
                extra={
                    "reason": "legacy_migrate_done",
                    "provider": provider,
                    "model_id": default_model_id,
                },
            )
            return True
        except Exception as exc:  # noqa: BLE001 — 顶层容错，下次重试
            logger.warning(
                "legacy api migrate failed",
                extra={"reason": "legacy_migrate_failed", "error": str(exc)},
            )
            return False

    def close(self):
        self._closed = True
        try:
            self.conn.close()
        except sqlite3.ProgrammingError:
            pass
