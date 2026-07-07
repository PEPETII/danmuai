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

    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 分支 B 应清空全局三字段
    assert store2.get_api_key() == "", "分支 B 建档后应清空全局 api_key"
    assert store2.get("api_endpoint") == "", "分支 B 建档后应清空全局 api_endpoint"
    assert store2.get("api_mode") == "", "分支 B 建档后应清空全局 api_mode"

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
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 分支 B 应清空全局三字段
    assert store2.get_api_key() == "", "分支 B 建档后应清空全局 api_key"
    assert store2.get("api_endpoint") == "", "分支 B 建档后应清空全局 api_endpoint"
    assert store2.get("api_mode") == "", "分支 B 建档后应清空全局 api_mode"
    store2.close()


def test_clean_migration_empty_model_yields_empty_model_ids(tmp_path):
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: cfg.model 为空 → 凭证不完整，走分支 C：
    不创建档案，不清空全局 api_key，置标志位 true。"""
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
    # 分支 C：凭证不完整（缺 model）→ 不创建档案
    assert len(models) == 0, "分支 C：model 为空时不应创建档案"
    assert store2.get_flag("legacy_api_migrated_v1") == "true"
    # 分支 C：不清空全局 api_key
    assert store2.get_api_key() == "sk-empty-model-1234567890", (
        "分支 C：model 为空时不应清空 api_key"
    )
    assert store2.get("api_endpoint") == "https://api.example.com/v1", (
        "分支 C：model 为空时不应清空 api_endpoint"
    )
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
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 第一次迁移已清空全局三字段，第二次仍为空
    assert store.get_api_key() == "", "幂等：第二次调用后全局 api_key 仍应为空"
    assert store.get("api_endpoint") == "", "幂等：第二次调用后全局 api_endpoint 仍应为空"
    assert store.get("api_mode") == "", "幂等：第二次调用后全局 api_mode 仍应为空"

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
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 重启后全局 api_key 仍为空（已被清空）
    assert store2.get_api_key() == "", "重启后全局 api_key 应仍为空"
    store2.close()


# --- 情形 3：DB 空但标志位 true ---

def test_empty_db_with_flag_true_does_not_migrate(tmp_path):
    """情形 3：DB 已被清空（custom_models 为空）但标志位 true → 不迁移；
    档案数仍为 0。"""
    db_path = tmp_path / "config.db"
    # 首次创建：api_key 为空 → 快速秒退，不置标志位（W-GLOBAL-VISUAL-APIKEY-REMOVE-001）
    store1 = ConfigStore(db_path=db_path)
    assert store1.get_flag("legacy_api_migrated_v1") is None, "api_key 为空时快速秒退，不置标志位"
    assert len(store1.get_custom_models()) == 0
    # 手动置标志位，模拟"之前已尝试过清理"的场景
    store1.set_flag("legacy_api_migrated_v1", "true")
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
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 分支 C 语义——标志位 true + api_key 非空 → 不清理
    assert store2.get_api_key() == "sk-after-flag-true-1234567890", (
        "分支 C：标志位已 true 时不应清空 api_key"
    )
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
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 分支 A——存在完整档案时应清空全局三字段
    assert store.get_api_key() == "", "分支 A：存在完整档案时应清空全局 api_key"
    assert store.get("api_endpoint") == "", "分支 A：存在完整档案时应清空全局 api_endpoint"
    assert store.get("api_mode") == "", "分支 A：存在完整档案时应清空全局 api_mode"
    store.close()


# --- 情形 5：api_key 为空 / MASKED / 解密失败 ---

def test_empty_api_key_only_sets_flag(tmp_path):
    """情形 5a：cfg.api_key 为空 → 快速秒退，不创建档案，不置标志位。"""
    db_path = tmp_path / "config.db"
    # 首次创建：api_key 为空
    store = ConfigStore(db_path=db_path)
    # 设置 endpoint/model 但不设置 api_key
    store.set("api_endpoint", "https://api.example.com/v1")
    store.set("model", "some-model")

    # 清除标志位（首次创建时 fast-path 不置标志位）
    _clear_legacy_flag(db_path)

    # 调用迁移：api_key 为空 → 快速秒退，不置标志位
    assert store._maybe_migrate_legacy_api_to_custom_models() is True
    assert len(store.get_custom_models()) == 0, "api_key 为空时不应创建档案"
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: api_key 为空时快速秒退，不置标志位
    assert store.get_flag("legacy_api_migrated_v1") is None, "api_key 为空时快速秒退，不置标志位"
    # 快速秒退不清空 endpoint/model
    assert store.get("api_endpoint") == "https://api.example.com/v1", (
        "api_key 为空时不应清空 api_endpoint"
    )
    assert store.get("model") == "some-model", "api_key 为空时不应清空 model"
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
    """情形 5c：api_key 解密失败（密钥丢失/损坏）→ get_api_key() 返回空字符串，
    安全网走 fast-path 秒退，不创建档案，不置标志位。

    说明：get_api_key() 内部捕获解密异常并返回 ""，不向上抛出。
    W-GLOBAL-VISUAL-APIKEY-REMOVE-001: fast-path 语义——api_key 为空 → return True，不置标志位。
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
    # 清除标志位
    _clear_legacy_flag(db_path)

    # 调用迁移：get_api_key() 解密失败返回 "" → fast-path 秒退
    result = store2._maybe_migrate_legacy_api_to_custom_models()
    assert result is True, "fast-path 秒退应返回 True"
    assert len(store2.get_custom_models()) == 0, "解密失败时不应创建档案"
    # fast-path 不置标志位（api_key 视为空）
    assert store2.get_flag("legacy_api_migrated_v1") is None, "fast-path 不置标志位"
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


# --- W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 安全网分支 A / C 专项 ---


def test_safety_net_branch_a_cleans_global_when_complete_profile_exists(tmp_path):
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001 分支 A：
    已有完整 custom_models 档案 + 全局 api_key 残留 → 清空全局三字段，不新建档案。"""
    db_path = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db_path)
    # 写入完整 custom_models 档案
    profile = {
        "name": "Existing Profile",
        "provider": "custom_openai",
        "mode": "openai-compatible",
        "endpoint": "https://api.existing.example.com/v1",
        "apiKey": "sk-existing-profile-1234567890",
        "model_ids": ["existing-model"],
        "default_model_id": "existing-model",
        "max_tokens": 512,
        "supportsMic": False,
        "description": "",
    }
    store1.set_custom_models([profile])
    set_default_model_selection(store1, "existing-model")
    # 写入全局残留（模拟历史遗留）
    store1.set_api_key("sk-legacy-residual-1234567890")
    store1.set("api_endpoint", "https://legacy.example.com/v1")
    store1.set("api_mode", "openai")
    store1.close()

    # 清除标志位（首次创建时已被置 true）
    _clear_legacy_flag(db_path)

    # 新建 store 触发安全网
    store2 = ConfigStore(db_path=db_path)

    # 断言：档案数仍为 1（未被覆盖，未新增）
    models = store2.get_custom_models()
    assert len(models) == 1, "分支 A：不应新增档案"
    assert models[0]["name"] == "Existing Profile", "分支 A：已有档案不应被覆盖"
    assert models[0]["apiKey"] == "sk-existing-profile-1234567890"

    # 断言：全局三字段已清空
    assert store2.get_api_key() == "", "分支 A：应清空全局 api_key"
    assert store2.get("api_endpoint") == "", "分支 A：应清空全局 api_endpoint"
    assert store2.get("api_mode") == "", "分支 A：应清空全局 api_mode"

    # 断言：标志位已置 true
    assert store2.get_flag("legacy_api_migrated_v1") == "true"

    # 断言：default_model_id 不变
    assert store2.get_default_model_id() == "existing-model"
    store2.close()


def test_safety_net_branch_c_incomplete_creds_does_not_clean(tmp_path):
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001 分支 C：
    api_key 非空但 endpoint 缺失 → 不清空，置标志位，下次启动跳过。"""
    db_path = tmp_path / "config.db"
    store1 = ConfigStore(db_path=db_path)
    # 只写 api_key，不写 endpoint/model（凭证不完整）
    store1.set_api_key("sk-incomplete-creds-1234567890")
    store1.close()

    # 清除标志位（首次创建时已被置 true）
    _clear_legacy_flag(db_path)

    # 新建 store 触发安全网
    store2 = ConfigStore(db_path=db_path)

    # 断言：分支 C → 不清空 api_key，置标志位
    assert store2.get_api_key() == "sk-incomplete-creds-1234567890", (
        "分支 C：api_key 不应被清空"
    )
    assert store2.get("api_endpoint") == "", "分支 C：api_endpoint 原本就为空"
    assert store2.get_flag("legacy_api_migrated_v1") == "true", "分支 C：应置标志位 true"
    assert len(store2.get_custom_models()) == 0, "分支 C：不应创建档案"
    store2.close()

    # 再次重启：标志位已 true → 跳过，api_key 仍非空
    store3 = ConfigStore(db_path=db_path)
    assert store3.get_api_key() == "sk-incomplete-creds-1234567890", (
        "分支 C 重启后：api_key 应仍非空（标志位 true 跳过）"
    )
    assert store3.get_flag("legacy_api_migrated_v1") == "true"
    store3.close()


# --- W-LEGACY-MIGRATE-ATOMIC-001: 原子写入与失败回滚 ---


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


def test_branch_b_migration_single_commit(tmp_path):
    """W-LEGACY-MIGRATE-ATOMIC-001: 分支 B 迁移单次 commit。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    _seed_legacy_config(
        store,
        api_key="sk-atomic-commit-1234567890",
        endpoint="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-1-6-vision-32k-250115",
        max_tokens=512,
    )
    _clear_legacy_flag(db_path)

    counting = _CommitCountingConn(store.conn)
    store.conn = counting
    result = store._maybe_migrate_legacy_api_to_custom_models()

    assert result is True
    assert counting.commit_call_count == 1
    assert len(store.get_custom_models()) == 1
    assert store.get_api_key() == ""
    assert store.get("api_endpoint") == ""
    assert store.get("api_mode") == ""
    assert store.get_flag("legacy_api_migrated_v1") == "true"
    store.close()


def test_branch_b_migration_rollback_on_failure_restart_consistent(tmp_path):
    """W-LEGACY-MIGRATE-ATOMIC-001: 分支 B commit 失败全回滚，重启后重试成功。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    original_key = "sk-rollback-retry-1234567890"
    _seed_legacy_config(
        store,
        api_key=original_key,
        endpoint="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seed-1-6-vision-32k-250115",
        max_tokens=512,
    )
    _clear_legacy_flag(db_path)
    inner = store.conn

    class _FailingConn:
        def execute(self, sql, params=()):
            raise sqlite3.OperationalError("disk I/O error")

        def executemany(self, sql, seq_of_parameters):
            raise sqlite3.OperationalError("disk I/O error")

        def commit(self):
            return inner.commit()

        def rollback(self):
            return inner.rollback()

        def close(self):
            return inner.close()

    store.conn = _FailingConn()
    result = store._maybe_migrate_legacy_api_to_custom_models()

    assert result is False
    store.conn = inner
    assert len(store.get_custom_models()) == 0, "半迁移：custom_models 不应落库"
    assert store.get_api_key() == original_key, "半迁移：全局 api_key 应保留"
    assert store.get("api_endpoint") == "https://ark.cn-beijing.volces.com/api/v3"
    assert store.get_flag("legacy_api_migrated_v1") is None, "失败时不应置标志位"
    store.close()

    store2 = ConfigStore(db_path=db_path)
    assert len(store2.get_custom_models()) == 1
    assert store2.get_api_key() == ""
    assert store2.get_flag("legacy_api_migrated_v1") == "true"
    assert store2.get_default_model_id() == "doubao-seed-1-6-vision-32k-250115"
    store2.close()


def test_branch_a_migration_rollback_on_failure(tmp_path):
    """W-LEGACY-MIGRATE-ATOMIC-001: 分支 A commit 失败时 profile 与全局 key 均不变。"""
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    profile = {
        "name": "Existing Profile",
        "provider": "custom_openai",
        "mode": "openai-compatible",
        "endpoint": "https://api.existing.example.com/v1",
        "apiKey": "sk-existing-profile-1234567890",
        "model_ids": ["existing-model"],
        "default_model_id": "existing-model",
        "max_tokens": 512,
        "supportsMic": False,
        "description": "",
    }
    store.set_custom_models([profile])
    set_default_model_selection(store, "existing-model")
    legacy_key = "sk-legacy-residual-1234567890"
    store.set_api_key(legacy_key)
    store.set("api_endpoint", "https://legacy.example.com/v1")
    store.set("api_mode", "openai")
    _clear_legacy_flag(db_path)
    inner = store.conn

    class _FailingConn:
        def execute(self, sql, params=()):
            raise sqlite3.OperationalError("disk I/O error")

        def executemany(self, sql, seq_of_parameters):
            raise sqlite3.OperationalError("disk I/O error")

        def commit(self):
            return inner.commit()

        def rollback(self):
            return inner.rollback()

        def close(self):
            return inner.close()

    store.conn = _FailingConn()
    result = store._maybe_migrate_legacy_api_to_custom_models()

    assert result is False
    store.conn = inner
    models = store.get_custom_models()
    assert len(models) == 1
    assert models[0]["name"] == "Existing Profile"
    assert models[0]["apiKey"] == "sk-existing-profile-1234567890"
    assert store.get_api_key() == legacy_key
    assert store.get("api_endpoint") == "https://legacy.example.com/v1"
    assert store.get_flag("legacy_api_migrated_v1") is None
    store.close()
