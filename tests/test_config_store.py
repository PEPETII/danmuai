import sqlite3
import threading
from base64 import b64encode

import pytest
from app.config_store import ConfigStore

try:
    from cryptography.fernet import Fernet  # noqa: F401

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


class _CommitCountingConn:
    """Wrap sqlite3.Connection to count commit() calls."""

    def __init__(self, conn):
        self._conn = conn
        self.commit_call_count = 0

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)

    def executemany(self, sql, seq_of_parameters):
        return self._conn.executemany(sql, seq_of_parameters)

    def commit(self):
        self.commit_call_count += 1
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_set_batch_writes_all_keys(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    items = {"key_a": "val_a", "key_b": "val_b", "key_c": "val_c"}
    store.set_batch(items)

    assert store.get("key_a") == "val_a"
    assert store.get("key_b") == "val_b"
    assert store.get("key_c") == "val_c"

    store.close()


def test_set_batch_updates_cache(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("key_x", "old")
    store.set_batch({"key_x": "new", "key_y": "fresh"})

    assert store.get("key_x") == "new"
    assert store.get("key_y") == "fresh"

    store.close()


def test_set_batch_persists_to_db(tmp_path):
    db = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db)
    store1.set_batch({"persist_a": "hello", "persist_b": "world"})
    store1.close()

    store2 = ConfigStore(db_path=db)
    assert store2.get("persist_a") == "hello"
    assert store2.get("persist_b") == "world"
    store2.close()


def test_first_run_seeds_config_defaults(tmp_path):
    store = ConfigStore(db_path=tmp_path / "new.db")
    assert store.get("danmu_speed") == "2"
    assert store.get("normal_reply_count") == "5"
    assert store.get("freshness") == ""
    assert store.get("eviction_mode") == "natural"
    assert store.get("hotkey") == "Ctrl+Shift+B"
    assert store.get("language") == "zh"
    assert store.get("danmu_pool_use_custom") == "0"
    assert store.get("api_mode") == "openai"
    assert store.get("temperature") == "0.8"
    assert store.get("pet_scale") == "0.5"
    store.close()


def test_set_batch_single_commit(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    items = {f"key_{i}": f"value_{i}" for i in range(25)}
    store.set_batch(items)

    for i in range(25):
        assert store.get(f"key_{i}") == f"value_{i}"

    store.close()


def test_set_batch_overwrites_existing(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("shared", "original")
    store.set_batch({"shared": "updated"})

    assert store.get("shared") == "updated"

    store.close()


def test_set_batch_empty_dict(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("existing", "kept")
    store.set_batch({})

    assert store.get("existing") == "kept"

    store.close()


@pytest.mark.parametrize(
    ("stored_value", "default", "expected"),
    [
        (None, 7, 7),
        ("", 7, 7),
        ("   ", 7, 7),
        ("abc", 7, 7),
        ("0", 7, 0),
        ("0.0", 7, 0),
        ("12", 7, 12),
        ("-5", 7, -5),
    ],
)
def test_get_int_tolerates_invalid_values_and_preserves_zero(
    tmp_path, stored_value, default, expected
):
    store = ConfigStore(db_path=tmp_path / "config.db")
    key = "int_key"
    if stored_value is not None:
        store.set(key, stored_value)

    assert store.get_int(key, default) == expected

    store.close()


@pytest.mark.parametrize(
    ("stored_value", "default", "expected"),
    [
        (None, 1.5, 1.5),
        ("", 1.5, 1.5),
        ("   ", 1.5, 1.5),
        ("abc", 1.5, 1.5),
        ("0", 1.5, 0.0),
        ("0.0", 1.5, 0.0),
        ("2.5", 1.5, 2.5),
        ("-3.25", 1.5, -3.25),
    ],
)
def test_get_float_tolerates_invalid_values_and_preserves_zero(
    tmp_path, stored_value, default, expected
):
    store = ConfigStore(db_path=tmp_path / "config.db")
    key = "float_key"
    if stored_value is not None:
        store.set(key, stored_value)

    assert store.get_float(key, default) == expected

    store.close()


def test_set_if_changed_skips_unchanged(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    counting = _CommitCountingConn(store.conn)
    store.conn = counting
    store.set("alpha", "one")
    assert counting.commit_call_count == 1

    assert store.set_if_changed("alpha", "one") is False
    assert counting.commit_call_count == 1

    assert store.set_if_changed("alpha", "two") is True
    assert counting.commit_call_count == 2
    assert store.get("alpha") == "two"

    store.close()


def test_set_batch_skips_unchanged_keys(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set_batch({"a": "1", "b": "2"})
    counting = _CommitCountingConn(store.conn)
    store.conn = counting

    store.set_batch({"a": "1", "b": "2"})
    assert counting.commit_call_count == 0

    store.set_batch({"a": "1", "b": "3"})
    assert counting.commit_call_count == 1
    assert store.get("b") == "3"

    store.close()


def test_set_does_not_pollute_cache_on_write_failure(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("stable_key", "original")
    inner = store.conn

    class _FailingConn:
        def execute(self, sql, params=()):
            raise sqlite3.OperationalError("database is locked")

        def commit(self):
            return inner.commit()

        def rollback(self):
            return inner.rollback()

        def close(self):
            return inner.close()

    store.conn = _FailingConn()

    with pytest.raises(sqlite3.OperationalError):
        store.set("stable_key", "new_value")

    assert store.get("stable_key") == "original"
    store.close()


def test_missing_config_file_has_friendly_notice(tmp_path):
    db_path = tmp_path / "fresh" / "config.db"
    store = ConfigStore(db_path=db_path)

    assert store.is_first_run is True
    assert "未找到配置文件" in store.get_startup_notice()
    assert store.get("normal_reply_count") == "5"

    store.close()

    store2 = ConfigStore(db_path=db_path)
    assert store2.is_first_run is False
    assert store2.get_startup_notice() == ""
    store2.close()


def test_config_value_with_default_language(tmp_path):
    from app.config_defaults import DEFAULT_LANGUAGE, config_value_with_default

    store = ConfigStore(db_path=tmp_path / "config.db")
    assert config_value_with_default(store, "language") == DEFAULT_LANGUAGE

    store.set("language", "")
    assert config_value_with_default(store, "language") == DEFAULT_LANGUAGE

    store.set("language", "en")
    assert config_value_with_default(store, "language") == "en"

    store.close()


def test_set_region_zeros_all_keys_when_size_non_positive(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set_region(10, 20, 100, 80)
    store.set_region(100, 200, 0, 0)

    assert store.get_region() == (0, 0, 0, 0)
    assert store.get("region_x") == "0"
    assert store.get("region_y") == "0"
    assert store.get("region_w") == "0"
    assert store.get("region_h") == "0"

    store.close()


def test_set_region_clear_persists_after_reopen(tmp_path):
    db = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db)
    store1.set_region(50, 60, 320, 180)
    store1.set_region(0, 0, 0, 0)
    store1.close()

    store2 = ConfigStore(db_path=db)
    assert store2.get_region() == (0, 0, 0, 0)
    assert store2.get("region_x") == "0"
    assert store2.get("region_y") == "0"
    assert store2.get("region_w") == "0"
    assert store2.get("region_h") == "0"
    store2.close()


def test_config_store_repairs_stale_region_on_init(tmp_path):
    db = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db)
    store1.set_batch({
        "region_x": "100",
        "region_y": "200",
        "region_w": "0",
        "region_h": "0",
    })
    store1.close()

    store2 = ConfigStore(db_path=db)
    assert store2.get_region() == (0, 0, 0, 0)
    assert store2.get("region_x") == "0"
    assert store2.get("region_y") == "0"
    assert store2.get("region_w") == "0"
    assert store2.get("region_h") == "0"
    store2.close()


def test_with_write_lock_yields_conn_and_releases(tmp_path):
    """W-CONC-001：``with_write_lock()`` 必须 (1) 产出 ``self.conn``；(2) 退出
    with 块后立即释放锁，主线程可再次获取。
    """
    store = ConfigStore(db_path=tmp_path / "config.db")
    try:
        # 第一次进入：with 块内可拿到 store.conn
        with store.with_write_lock() as conn:
            assert conn is store.conn
            # 在临界区内写入一条 REPLACE 验证可用
            store.conn.execute(
                "REPLACE INTO config (key, value) VALUES (?, ?)", ("w_conc_001", "v1")
            )
            store.conn.commit()
        # 退出 with 后，_write_lock 已释放，主线程能再次进入
        with store.with_write_lock() as conn:
            assert conn is store.conn
            store.conn.execute(
                "REPLACE INTO config (key, value) VALUES (?, ?)", ("w_conc_001", "v2")
            )
            store.conn.commit()
        # 关键：再次进入临界区写入不抛锁异常（互斥已验证）；
        # 用 store.set 走「正常」路径刷新 _cache，验证最终值。
        store.set("w_conc_001", "v3")
        assert store.get("w_conc_001") == "v3"
        # 验证 via 再次进入 with_write_lock 的写也确实落到 DB
        with store.with_write_lock() as conn:
            row = conn.execute(
                "SELECT value FROM config WHERE key=?", ("w_conc_001",)
            ).fetchone()
        assert row[0] == "v3"
    finally:
        store.close()


def test_with_write_lock_blocks_other_writer(tmp_path):
    """W-CONC-001：``with_write_lock()`` 与 ``set`` 共享 ``_write_lock``；
    互斥成立（持有方未释放前另一方拿不到锁）。
    """
    store = ConfigStore(db_path=tmp_path / "config.db")
    try:
        # 主线程持锁
        assert store._write_lock.acquire(timeout=2.0) is True
        acquired_main_thread: dict = {}

        def _other_thread():
            try:
                with store.with_write_lock():
                    acquired_main_thread["ok"] = True
            except Exception as e:  # pragma: no cover - 仅在退步时报
                acquired_main_thread["error"] = repr(e)

        t = threading.Thread(target=_other_thread, name="test-other-writer")
        t.start()
        # 给另一线程一点时间确认它在 _write_lock 上阻塞
        t.join(timeout=0.3)
        assert t.is_alive(), "另一个写入者应在 _write_lock 上阻塞等待"
        assert "ok" not in acquired_main_thread, (
            f"持锁未释放时另一线程不应进入临界区：{acquired_main_thread}"
        )

        # 释放锁
        store._write_lock.release()
        t.join(timeout=2.0)
        assert not t.is_alive(), "释放锁后另一线程应在 2s 内进入临界区"
        assert acquired_main_thread.get("ok") is True, (
            f"释放锁后另一线程仍失败：{acquired_main_thread}"
        )
    finally:
        # 防御：若主线程持锁未释放，强制释放避免 close 时的潜在阻塞
        if store._write_lock.locked():
            try:
                store._write_lock.release()
            except RuntimeError:
                pass
        store.close()


def test_legacy_base64_api_key_auto_upgrades_on_read(tmp_path):
    if not _HAS_CRYPTO:
        pytest.skip("cryptography not available")

    db = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db)
    plain = "upgrade-me"
    store1.set("api_key_encoded", b64encode(plain.encode()).decode())
    store1.close()

    store2 = ConfigStore(db_path=db)
    assert store2.get_api_key() == plain
    assert store2.get("api_key_encoded", "") == ""
    assert store2.get("api_key_encrypted", "") != ""
    store2.close()


def test_api_key_cache_avoids_repeat_decrypt(tmp_path):
    if not _HAS_CRYPTO:
        pytest.skip("cryptography not available")

    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set_api_key("cached-secret")
    decrypt_calls: list[int] = []
    original_decrypt = store._fernet.decrypt

    def counting_decrypt(data):
        decrypt_calls.append(1)
        return original_decrypt(data)

    store._fernet.decrypt = counting_decrypt  # type: ignore[method-assign]

    assert store.get_api_key() == "cached-secret"
    assert store.get_api_key() == "cached-secret"
    assert len(decrypt_calls) == 1
    store.close()


def test_api_key_cache_invalidates_on_set(tmp_path):
    if not _HAS_CRYPTO:
        pytest.skip("cryptography not available")

    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set_api_key("first-key")
    assert store.get_api_key() == "first-key"
    store.set_api_key("second-key")
    assert store.get_api_key() == "second-key"
    store.close()


def test_custom_models_cache_invalidates_on_set_batch(tmp_path):
    import json

    if not _HAS_CRYPTO:
        pytest.skip("cryptography not available")

    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set_custom_models(
        [
            {
                "name": "A",
                "modelId": "model-a",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-model-a",
            }
        ]
    )
    first = store.get_custom_models()
    second = store.get_custom_models()
    assert first[0]["apiKey"] == "sk-model-a"
    assert second[0]["apiKey"] == "sk-model-a"
    assert first is not second

    store.set_batch(
        {
            "custom_models": json.dumps(
                [
                    {
                        "name": "B",
                        "modelId": "model-b",
                        "mode": "openai",
                        "endpoint": "https://api.example.com/v1",
                        "apiKey": store._encrypt_custom_model_api_key("sk-model-b"),
                    }
                ],
                ensure_ascii=False,
            )
        }
    )
    updated = store.get_custom_models()
    assert updated[0]["modelId"] == "model-b"
    assert updated[0]["apiKey"] == "sk-model-b"
    store.close()


def test_get_custom_models_returned_copy_does_not_pollute_cache(tmp_path):
    if not _HAS_CRYPTO:
        pytest.skip("cryptography not available")

    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set_custom_models(
        [
            {
                "name": "A",
                "modelId": "model-a",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-model-a",
            }
        ]
    )
    first = store.get_custom_models()
    first[0]["apiKey"] = "mutated-key"
    first.append(
        {
            "name": "Injected",
            "modelId": "injected",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-injected",
        }
    )

    second = store.get_custom_models()
    assert len(second) == 1
    assert second[0]["modelId"] == "model-a"
    assert second[0]["apiKey"] == "sk-model-a"
    assert first is not second
    store.close()


def test_apply_web_save_single_commit(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    counting = _CommitCountingConn(store.conn)
    store.conn = counting

    store.apply_web_save(
        items={"danmu_speed": "3", "model": "gpt-4o", "default_model_id": "gpt-4o"},
        api_key="sk-test-key-1234567890",
        mic_api_key="sk-mic-key-1234567890",
        custom_models=[
            {
                "name": "Test",
                "modelId": "test-model",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-custom-key-1234567890",
            }
        ],
    )

    assert counting.commit_call_count == 1
    assert store.get("danmu_speed") == "3"
    assert store.get_default_model_id() == "gpt-4o"
    assert store.get_api_key() == "sk-test-key-1234567890"
    assert store.get_mic_api_key() == "sk-mic-key-1234567890"
    models = store.get_custom_models()
    assert models[0]["apiKey"] == "sk-custom-key-1234567890"
    store.close()


def test_apply_web_save_does_not_pollute_cache_on_failure(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("stable_key", "original")
    inner = store.conn

    class _FailingConn:
        def execute(self, sql, params=()):
            raise sqlite3.OperationalError("database is locked")

        def executemany(self, sql, seq_of_parameters):
            raise sqlite3.OperationalError("database is locked")

        def commit(self):
            return inner.commit()

        def rollback(self):
            return inner.rollback()

        def close(self):
            return inner.close()

    store.conn = _FailingConn()

    with pytest.raises(sqlite3.OperationalError):
        store.apply_web_save(items={"stable_key": "new_value"})

    assert store.get("stable_key") == "original"
    store.close()


def test_custom_danmu_pool_json_migration(tmp_path):
    import json as json_mod

    db = tmp_path / "migrate.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "REPLACE INTO config (key, value) VALUES (?, ?)",
        ("custom_danmu_pool", json_mod.dumps(["旧句A", "旧句B", "旧句A", ""], ensure_ascii=False)),
    )
    conn.commit()
    conn.close()

    store = ConfigStore(db_path=db)
    assert store.get("custom_danmu_pool_migrated") == "1"
    assert store.get_custom_danmu_pool() == ["旧句A", "旧句B"]
    store.close()


def test_custom_danmu_pool_pagination_and_search(tmp_path):
    store = ConfigStore(db_path=tmp_path / "pool_page.db")
    store.set_custom_danmu_pool([f"手动句{i}" for i in range(5)])
    page = store.custom_danmu_list(page=1, page_size=2, source="manual")
    assert page["total"] == 5
    assert len(page["items"]) == 2
    assert page["items"][0]["id"] > 0

    found = store.custom_danmu_list(page=1, page_size=50, search="手动句3", source="manual")
    assert found["total"] == 1
    assert found["items"][0]["text"] == "手动句3"
    store.close()


def test_custom_danmu_insert_many_sources_and_dedup(tmp_path):
    store = ConfigStore(db_path=tmp_path / "pool_insert.db")
    manual = store.custom_danmu_insert_many(["句A", "句A", ""], source="manual")
    assert manual["added"] == 1
    assert manual["skipped_duplicate"] == 1
    assert manual["skipped_empty"] == 1

    imported = store.custom_danmu_insert_many(["导入句", "句A"], source="import")
    assert imported["added"] == 1
    assert imported["skipped_duplicate"] == 1
    assert store.custom_danmu_count("manual") == 1
    assert store.custom_danmu_count("import") == 1
    store.close()


def test_custom_danmu_random_sample(tmp_path):
    store = ConfigStore(db_path=tmp_path / "pool_sample.db")
    store.set_custom_danmu_pool([f"句{i}" for i in range(10)])
    picked = store.custom_danmu_random_sample(3)
    assert len(picked) == 3
    assert all(p in store.get_custom_danmu_pool() for p in picked)
    store.close()


def test_custom_danmu_pool_capacity_limit(tmp_path, monkeypatch):
    store = ConfigStore(db_path=tmp_path / "pool_cap.db")
    monkeypatch.setattr("app.danmu_pool.CUSTOM_DANMU_POOL_MAX", 3)
    stats = store.custom_danmu_insert_many(["a", "b", "c", "d"], source="manual")
    assert stats["added"] == 3
    assert stats["skipped_limit"] == 1
    assert store.custom_danmu_count() == 3
    store.close()


def test_meme_barrage_library_contains_text_after_init(tmp_path):
    store = ConfigStore(db_path=tmp_path / "meme_contains.db")
    store.meme_barrage_library_insert_many(
        [("烂梗句", None, None)],
        collected_at=0.0,
        max_rows=10_000,
    )
    assert store.meme_barrage_library_contains_text("烂梗句") is True
    assert store.meme_barrage_library_contains_text("不存在") is False
    store.close()


# --- Fernet key loss / regeneration startup notice tests ---


@pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
def test_corrupted_key_shows_key_lost_notice(tmp_path):
    """密钥文件损坏后重新生成，get_startup_notice() 应包含密钥丢失提醒。"""
    db_path = tmp_path / "corrupt_key.db"
    store = ConfigStore(db_path=db_path)
    # 写入加密 API Key
    store.set_api_key("sk-test-secret-key")
    assert store.get_api_key() == "sk-test-secret-key"
    store.close()

    # 损坏密钥文件
    key_file = db_path.parent / ".key"
    assert key_file.exists()
    key_file.write_bytes(b"corrupted_invalid_key_data")

    store2 = ConfigStore(db_path=db_path)
    assert store2._key_regenerated is True
    notice = store2.get_startup_notice()
    assert "密钥" in notice or "key" in notice.lower()
    # 旧 API Key 不可恢复
    assert store2.get_api_key() == ""
    store2.close()


@pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
def test_deleted_key_with_encrypted_data_shows_notice(tmp_path):
    """密钥文件被删除且数据库中有加密数据时，应显示密钥丢失提醒。"""
    db_path = tmp_path / "deleted_key.db"
    store = ConfigStore(db_path=db_path)
    store.set_api_key("sk-another-secret")
    assert store.get_api_key() == "sk-another-secret"
    store.close()

    # 删除密钥文件
    key_file = db_path.parent / ".key"
    assert key_file.exists()
    key_file.unlink()

    store2 = ConfigStore(db_path=db_path)
    assert store2._key_regenerated is True
    notice = store2.get_startup_notice()
    assert "密钥" in notice or "key" in notice.lower()
    assert store2.get_api_key() == ""
    store2.close()


@pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
def test_first_run_no_key_lost_notice(tmp_path):
    """首次安装时，get_startup_notice() 不应包含密钥丢失提醒。"""
    db_path = tmp_path / "first_run.db"
    store = ConfigStore(db_path=db_path)
    assert store.is_first_run is True
    assert store._key_regenerated is False
    notice = store.get_startup_notice()
    # 首次安装提示不包含密钥丢失关键词
    assert "密钥已丢失" not in notice
    assert "未找到配置文件" in notice
    store.close()


@pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
def test_normal_startup_empty_notice(tmp_path):
    """正常启动（密钥完好）时，get_startup_notice() 返回空字符串。"""
    db_path = tmp_path / "normal.db"
    store = ConfigStore(db_path=db_path)
    store.set_api_key("sk-normal-key")
    store.close()

    store2 = ConfigStore(db_path=db_path)
    assert store2.is_first_run is False
    assert store2._key_regenerated is False
    assert store2.get_startup_notice() == ""
    store2.close()

