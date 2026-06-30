"""W-LEGACY-MIGRATE-003: Legacy API 启动期自动迁移到默认 custom_models 档案测试。

覆盖 5 种情形：
1. 干净迁移：干净 DB + 旧 cfg 含有效 api_key，标志位未设 → 创建 1 条默认档案；
   default_model_id 指向新档案；标志位置 true
2. 幂等：标志位已为 true，重启 → 不重复迁移；档案数不变
3. DB 空但标志位 true：DB 已被清空但标志位 true → 不迁移；档案数仍为 0
4. DB 已有档案：DB 已有其他档案但标志位 false（被人为清空）→ 不迁移；
   档案数不变；标志位置 true
5. api_key 为空 / MASKED / 解密失败 → 不创建档案；仅置标志位 true

测试约定：
- 每个用例使用独立 tmp_path 隔离 DB
- 不依赖全量 pytest；只运行本文件
- 不修改 app/ 源码
"""

import sqlite3

import pytest

from app.application.config_service import MASKED_API_KEY, set_default_model_selection
from app.config_store import ConfigStore

try:
    from cryptography.fernet import Fernet  # noqa: F401

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


def _clear_legacy_flag(db_path) -> None:
    """直接用 sqlite3 删除 legacy_api_migrated_v1 标志位（绕过 ConfigStore）。"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM system_flags WHERE key = ?", ("legacy_api_migrated_v1",))
        conn.commit()
    finally:
        conn.close()


def _seed_legacy_config(store, *, api_key, endpoint, model, max_tokens) -> None:
    """通过 ConfigStore 公开 API 写入 legacy 顶栏配置。"""
    store.set_api_key(api_key)
    store.set("api_endpoint", endpoint)
    store.set("api_mode", "openai")
    store.set("model", model)
    store.set("max_tokens", str(max_tokens))


# --- 情形 1：干净迁移 ---

def test_clean_migration_creates_default_profile(tmp_path):
    """情形 1：干净 DB + 旧 cfg 含有效 api_key → 创建 1 条默认档案；
    default_model_id 指向新档案；标志位置 true。"""
    db_path = tmp_path / "config.db"

    # 第一步：创建 ConfigStore1，写入 legacy 顶栏配置（首次创建会触发迁移，
    # 但因为 api_key 为空，标志位会被置 true 且不创建档案）
    store1 = ConfigStore(db_path=db_path)
    _seed_legacy_config(
        store1,
        api_key="sk-clean-migrate-1234567890",
        endpoint="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-1-6-vision-32k-250115",
        max_tokens=512,
    )
    store1.close()

    # 第二步：人为清除标志位，模拟"未迁移"状态
    _clear_legacy_flag(db_path)

    # 第三步：重新创建 ConfigStore，触发迁移
    store2 = ConfigStore(db_path=db_path)

    # 验证：创建了 1 条默认档案
    models = store2.get_custom_models()
    assert len(models) == 1, f"期望 1 条档案，实际 {len(models)} 条"
    profile = models[0]
    assert profile["name"] == "Default (imported)"
    assert profile["provider"] == "doubao"
    assert profile["mode"] == "doubao"
    assert profile["endpoint"] == "https://ark.cn-beijing.volces.com/api/v3"
    # apiKey 解密后应等于原 api_key
    assert profile["apiKey"] == "sk-clean-migrate-1234567890"
    assert profile["model_ids"] == ["doubao-seed-1-6-vision-32k-250115"]
    assert profile["default_model_id"] == "doubao-seed-1-6-vision-32k-250115"
    assert profile["max_tokens"] == 512
    assert profile["supportsMic"] is False
    assert profile["description"] == ""

    # 验证：标志位已置 true
    assert store2.get_flag("legacy_api_migrated_v1") == "true"

    # 验证：default_model_id 指向新档案
    assert store2.get_default_model_id() == "doubao-seed-1-6-vision-32k-250115"
    assert store2.get("model") == "doubao-seed-1-6-vision-32k-250115"

    store2.close()


def test_clean_migration_unknown_endpoint_falls_back_to_custom_openai(tmp_path):
    """补充：未知 endpoint → provider 兜底 custom_openai，mode=openai-compatible。"""
    db_path = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db_path)
    _seed_legacy_config(
        store1,
        api_key="sk-unknown-endpoint-1234567890",
        endpoint="https://api.unknown-provider.example.com/v1",
        model="some-model-id",
        max_tokens=1024,
    )
    store1.close()
    _clear_legacy_flag(db_path)

    store2 = ConfigStore(db_path=db_path)
    models = store2.get_custom_models()
    assert len(models) == 1
    profile = models[0]
    assert profile["provider"] == "custom_openai"
    assert profile["mode"] == "openai-compatible"
    assert profile["max_tokens"] == 1024
    assert store2.get_flag("legacy_api_migrated_v1") == "true"
    store2.close()


def test_clean_migration_empty_model_yields_empty_model_ids(tmp_path):
    """补充：cfg.model 为空 → model_ids=[]，default_model_id=''，
    仍写入档案（占位），不调 set_default_model_selection。"""
    db_path = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db_path)
    _seed_legacy_config(
        store1,
        api_key="sk-empty-model-1234567890",
        endpoint="https://api.example.com/v1",
        model="",
        max_tokens=512,
    )
    store1.close()
    _clear_legacy_flag(db_path)

    store2 = ConfigStore(db_path=db_path)
    models = store2.get_custom_models()
    assert len(models) == 1
    profile = models[0]
    assert profile["model_ids"] == []
    assert profile["default_model_id"] == ""
    assert store2.get_flag("legacy_api_migrated_v1") == "true"
    store2.close()


# --- 情形 2：幂等 ---

def test_idempotent_migration_does_not_duplicate(tmp_path):
    """情形 2：标志位已为 true，再次调用迁移 → 不重复迁移；档案数不变。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    _seed_legacy_config(
        store,
        api_key="sk-idempotent-1234567890",
        endpoint="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-1-6-vision-32k-250115",
        max_tokens=512,
    )
    # 清除标志位并运行迁移，创建档案
    _clear_legacy_flag(db_path)
    assert store._maybe_migrate_legacy_api_to_custom_models() is True
    models_after_first = store.get_custom_models()
    assert len(models_after_first) == 1
    assert store.get_flag("legacy_api_migrated_v1") == "true"

    # 再次调用迁移：应直接 return，不创建第二条
    assert store._maybe_migrate_legacy_api_to_custom_models() is True
    models_after_second = store.get_custom_models()
    assert len(models_after_second) == 1, (
        f"幂等失败：第二次调用后档案数应为 1，实际 {len(models_after_second)}"
    )

    store.close()


def test_idempotent_across_restart(tmp_path):
    """情形 2 补充：重启后（新建 ConfigStore）仍不重复迁移。"""
    db_path = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db_path)
    _seed_legacy_config(
        store1,
        api_key="sk-restart-1234567890",
        endpoint="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-1-6-vision-32k-250115",
        max_tokens=512,
    )
    _clear_legacy_flag(db_path)
    assert store1._maybe_migrate_legacy_api_to_custom_models() is True
    assert len(store1.get_custom_models()) == 1
    store1.close()

    # 重启
    store2 = ConfigStore(db_path=db_path)
    assert len(store2.get_custom_models()) == 1, "重启后档案数应仍为 1"
    assert store2.get_flag("legacy_api_migrated_v1") == "true"
    store2.close()


# --- 情形 3：DB 空但标志位 true ---

def test_empty_db_with_flag_true_does_not_migrate(tmp_path):
    """情形 3：DB 已被清空（custom_models 为空）但标志位 true → 不迁移；
    档案数仍为 0。"""
    db_path = tmp_path / "config.db"
    # 首次创建：api_key 为空 → 标志位置 true，无档案
    store1 = ConfigStore(db_path=db_path)
    assert store1.get_flag("legacy_api_migrated_v1") == "true"
    assert len(store1.get_custom_models()) == 0
    store1.close()

    # 设置 api_key（模拟用户后来填了 key），但标志位已 true
    store2 = ConfigStore(db_path=db_path)
    store2.set_api_key("sk-after-flag-true-1234567890")
    store2.set("api_endpoint", "https://ark.cn-beijing.volces.com/api/v3")
    store2.set("model", "doubao-seed-1-6-vision-32k-250115")

    # 调用迁移：应直接 return（标志位 true），不创建档案
    assert store2._maybe_migrate_legacy_api_to_custom_models() is True
    assert len(store2.get_custom_models()) == 0, (
        "标志位已 true 时不应创建档案，即使 custom_models 为空"
    )
    assert store2.get_flag("legacy_api_migrated_v1") == "true"
    store2.close()


# --- 情形 4：DB 已有档案兜底 ---

def test_existing_profiles_protected_from_migration(tmp_path):
    """情形 4：DB 已有其他档案但标志位 false（被人为清空）→ 不迁移；
    档案数不变；标志位置 true。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    # 设置 legacy api_key
    _seed_legacy_config(
        store,
        api_key="sk-existing-1234567890",
        endpoint="https://api.example.com/v1",
        model="some-model",
        max_tokens=512,
    )
    # 用户已有一条自定义档案
    existing_profile = {
        "name": "User Custom",
        "provider": "custom_openai",
        "mode": "openai-compatible",
        "endpoint": "https://api.user.example.com/v1",
        "apiKey": "sk-user-custom-1234567890",
        "model_ids": ["user-model-1"],
        "default_model_id": "user-model-1",
        "max_tokens": 1024,
        "supportsMic": False,
        "description": "user-created",
    }
    store.set_custom_models([existing_profile])
    set_default_model_selection(store, "user-model-1")
    assert len(store.get_custom_models()) == 1

    # 人为清除标志位（模拟"被人为清空"）
    _clear_legacy_flag(db_path)

    # 调用迁移：应检测到已有档案，不覆盖，仅置标志位 true
    assert store._maybe_migrate_legacy_api_to_custom_models() is True
    models = store.get_custom_models()
    assert len(models) == 1, "已有档案时不应再插入新档案"
    assert models[0]["name"] == "User Custom", "已有档案不应被覆盖"
    assert models[0]["default_model_id"] == "user-model-1"
    assert store.get_flag("legacy_api_migrated_v1") == "true"
    # default_model_id 不应被迁移改动
    assert store.get_default_model_id() == "user-model-1"
    store.close()


# --- 情形 5：api_key 为空 / MASKED / 解密失败 ---

def test_empty_api_key_only_sets_flag(tmp_path):
    """情形 5a：cfg.api_key 为空 → 不创建档案；仅置标志位 true。"""
    db_path = tmp_path / "config.db"
    # 首次创建：api_key 为空
    store = ConfigStore(db_path=db_path)
    # 设置 endpoint/model 但不设置 api_key
    store.set("api_endpoint", "https://api.example.com/v1")
    store.set("model", "some-model")

    # 清除标志位（首次创建时已被置 true）
    _clear_legacy_flag(db_path)

    # 调用迁移：api_key 为空 → 仅置标志位 true
    assert store._maybe_migrate_legacy_api_to_custom_models() is True
    assert len(store.get_custom_models()) == 0, "api_key 为空时不应创建档案"
    assert store.get_flag("legacy_api_migrated_v1") == "true"
    store.close()


def test_masked_api_key_only_sets_flag(tmp_path):
    """情形 5b：cfg.api_key == MASKED_API_KEY → 不创建档案；仅置标志位 true。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    # 设置 endpoint/model + MASKED api_key
    store.set("api_endpoint", "https://api.example.com/v1")
    store.set("model", "some-model")
    # 直接写入 MASKED 值到 cache（绕过加密），模拟 Web GET 后回填场景
    # 注意：MASKED_API_KEY 不是真实 key，不会走加密路径
    store.set_api_key(MASKED_API_KEY)

    _clear_legacy_flag(db_path)

    # 调用迁移：api_key == MASKED → 仅置标志位 true
    assert store._maybe_migrate_legacy_api_to_custom_models() is True
    assert len(store.get_custom_models()) == 0, "api_key 为 MASKED 时不应创建档案"
    assert store.get_flag("legacy_api_migrated_v1") == "true"
    store.close()


@pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
def test_decrypt_failure_only_sets_flag(tmp_path):
    """情形 5c：api_key 解密失败（密钥丢失/损坏）→ 仅置标志位 true，不创建档案。

    模拟方式：写入有效 api_key 后，损坏 .key 文件，使 Fernet.decrypt 抛异常。
    """
    db_path = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db_path)
    store1.set_api_key("sk-real-key-1234567890")
    store1.set("api_endpoint", "https://api.example.com/v1")
    store1.set("model", "some-model")
    store1.close()

    # 损坏 .key 文件
    key_file = db_path.parent / ".key"
    assert key_file.exists()
    key_file.write_bytes(b"corrupted_invalid_key_data_for_test")

    # 重新打开：_init_fernet 会重新生成 key，旧 api_key_encrypted 不可解密
    store2 = ConfigStore(db_path=db_path)
    # 清除标志位（首次创建时已被置 true）
    _clear_legacy_flag(db_path)

    # 调用迁移：解密失败 → 仅置标志位 true
    result = store2._maybe_migrate_legacy_api_to_custom_models()
    assert result is True, "解密异常应被捕获，返回 True"
    assert len(store2.get_custom_models()) == 0, "解密失败时不应创建档案"
    assert store2.get_flag("legacy_api_migrated_v1") == "true"
    store2.close()


# --- 补充：system_flags 表基础测试 ---

def test_system_flags_table_created_on_init(tmp_path):
    """system_flags 表在 ConfigStore 初始化时自动创建。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)

    # 验证表存在
    row = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='system_flags'"
    ).fetchone()
    assert row is not None, "system_flags 表应已创建"
    assert row[0] == "system_flags"

    # 验证 get_flag 返回 None（无数据时）
    assert store.get_flag("nonexistent_key") is None
    store.close()


def test_set_flag_then_get_flag_roundtrip(tmp_path):
    """set_flag / get_flag 往返测试。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)

    store.set_flag("test_key", "test_value")
    assert store.get_flag("test_key") == "test_value"

    # REPLACE INTO 覆盖
    store.set_flag("test_key", "updated_value")
    assert store.get_flag("test_key") == "updated_value"

    # 持久化到 DB（重新打开）
    store.close()
    store2 = ConfigStore(db_path=db_path)
    assert store2.get_flag("test_key") == "updated_value"
    store2.close()


def test_get_flag_after_close_returns_none(tmp_path):
    """close 后 get_flag 返回 None，不抛异常。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    store.set_flag("persist_key", "persist_value")
    store.close()

    assert store._closed is True
    assert store.get_flag("persist_key") is None


def test_set_flag_after_close_does_not_raise(tmp_path):
    """close 后 set_flag 静默跳过，不抛异常。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    store.close()
    assert store._closed is True
    # 不应抛异常
    store.set_flag("after_close", "value")
    # 验证未写入
    store2 = ConfigStore(db_path=db_path)
    assert store2.get_flag("after_close") is None
    store2.close()
