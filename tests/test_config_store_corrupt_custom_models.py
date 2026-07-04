import pytest
from app.config_store import ConfigStore


_CORRUPT_VALUES = [
    ("truncated_json", '{"name":"a"'),
    ("bom_prefix", "\ufeff[]"),
    ("chinese_quotes", "[\"name\":\"模型\"]"),
    ("not_json", "not-json-at-all"),
    ("number_instead_of_list", "123"),
]


@pytest.mark.parametrize("_id,value", _CORRUPT_VALUES, ids=[v[0] for v in _CORRUPT_VALUES])
def test_get_custom_models_returns_empty_on_corrupt_data(tmp_path, _id, value):
    """Inject malformed JSON into custom_models field and assert graceful fallback."""
    db = tmp_path / "config.db"
    store = ConfigStore(db_path=db)
    store.conn.execute(
        "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
        ("custom_models", value),
    )
    store.conn.commit()
    # Invalidate cache so get_custom_models reads from DB again
    store._invalidate_custom_models_cache()

    result = store.get_custom_models()
    assert result == []

    store.close()


# ── BUG-015: 启动提示应指明具体失效的加密字段 ──────────────────────


def test_startup_notice_lists_specific_unreadable_field(tmp_path):
    """BUG-015: key 重新生成后，启动提示应列出具体失效字段（视觉模型 API Key）。"""
    from cryptography.fernet import Fernet

    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    # 用真实 Fernet 加密一段密文，模拟旧 key 下的密文
    old_fernet = Fernet(Fernet.generate_key())
    encrypted_value = old_fernet.encrypt(b"old_api_key").decode()
    store.conn.execute(
        "REPLACE INTO config (key, value) VALUES (?, ?)",
        ("api_key_encrypted", encrypted_value),
    )
    store.conn.commit()
    store.close()

    # 损坏 .key 文件，让重新打开时触发 key 重新生成
    key_file = db_path.parent / ".key"
    key_file.write_bytes(b"not-a-valid-fernet-key")

    store2 = ConfigStore(db_path=db_path)
    assert store2._key_regenerated is True
    notice = store2.get_startup_notice()
    assert "视觉模型 API Key" in notice
    store2.close()


def test_startup_notice_lists_mic_field_only(tmp_path):
    """BUG-015: 仅 mic_api_key_encrypted 残留时，提示只含麦克风字段，不含视觉模型字段。"""
    from cryptography.fernet import Fernet

    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    old_fernet = Fernet(Fernet.generate_key())
    mic_encrypted = old_fernet.encrypt(b"old_mic_key").decode()
    store.conn.execute(
        "REPLACE INTO config (key, value) VALUES (?, ?)",
        ("mic_api_key_encrypted", mic_encrypted),
    )
    store.conn.commit()
    store.close()

    key_file = db_path.parent / ".key"
    key_file.write_bytes(b"corrupted-key-bytes")

    store2 = ConfigStore(db_path=db_path)
    assert store2._key_regenerated is True
    notice = store2.get_startup_notice()
    assert "麦克风 API Key" in notice
    assert "视觉模型 API Key" not in notice
    store2.close()


def test_startup_notice_falls_back_when_no_encrypted_field(tmp_path):
    """BUG-015: key 损坏但无任何加密字段时，退回通用文案（不含具体字段名）。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    # 不写任何 _encrypted 字段，但让 is_first_run=False
    store.set("some_normal_key", "some_value")
    store.close()

    key_file = db_path.parent / ".key"
    key_file.write_bytes(b"corrupted-key-bytes")

    store2 = ConfigStore(db_path=db_path)
    assert store2._key_regenerated is True
    notice = store2.get_startup_notice()
    # 退回通用文案，不应含 specific 变体的「请重新填写：」结构
    assert "请重新填写：" not in notice
    # 通用 key_lost_notice 应该非空
    assert notice != ""
    store2.close()
