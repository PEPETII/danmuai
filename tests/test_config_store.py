from app.config_store import ConfigStore


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
    assert store.get("freshness") == "medium"
    assert store.get("eviction_mode") == "natural"
    assert store.get("hotkey") == "Ctrl+Shift+B"
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


def test_missing_config_file_has_friendly_notice(tmp_path):
    db_path = tmp_path / "fresh" / "config.db"
    store = ConfigStore(db_path=db_path)

    assert store.is_first_run is True
    assert "未找到配置文件" in store.get_startup_notice()

    store.close()

    store2 = ConfigStore(db_path=db_path)
    assert store2.is_first_run is False
    assert store2.get_startup_notice() == ""
    store2.close()
