"""W-AUDIT-MODEL-IDENTITY-001：模型档案不可变 ``profile_id`` 与旧数据迁移。

覆盖工单 §5.1 / §5.2 / §5.3 与 §6 验收标准；不依赖 Qt / Web 服务，直接驱动
``ConfigStore`` + ``PersonaManager`` + 请求规划链路。

迁移基线用"旧 shape 原始 DB 行"（无 ``profile_id``、密钥为 Fernet 密文）构造，
再通过重新打开 ``ConfigStore`` 触发启动期受控迁移，以模拟真实用户数据库。
"""

from __future__ import annotations

import json

import pytest
from app.ai_client_requests import resolve_request_credentials_for_persona
from app.config_store import ConfigStore
from app.config_store.storage_models import (
    invalidate_custom_models_cache_for_store,
    migrate_custom_model_identities_for_store,
)
from app.model_providers import (
    find_custom_model_profile,
    find_custom_model_profile_by_profile_id,
)
from app.model_selection import set_active_model_profile
from app.persona_manager import (
    PersonaManager,
    PersonaModelBindingError,
    resolve_persona_model_binding,
)
from app.providers.request_planner import GenerationRequest, plan_http_request

PLAINTEXT_KEY_A = "sk-profile-a-1234567890"
PLAINTEXT_KEY_B = "sk-profile-b-1234567890"


def _canonical_profile(
    *,
    model_id: str,
    endpoint: str,
    api_key: str,
    name: str = "",
    profile_id: str | None = None,
) -> dict:
    entry = {
        "name": name or f"Profile {model_id}",
        "model_ids": [model_id],
        "default_model_id": model_id,
        "max_tokens": 512,
        "mode": "openai-compatible",
        "endpoint": endpoint,
        "apiKey": api_key,
        "provider": "custom_openai",
    }
    if profile_id is not None:
        entry["profile_id"] = profile_id
    return entry


def _raw_custom_models_json(store: ConfigStore) -> str:
    row = store.conn.execute(
        "SELECT value FROM config WHERE key = ?", ("custom_models",)
    ).fetchone()
    assert row is not None
    return row[0]


def _seed_legacy_store(
    store: ConfigStore,
    models: list[dict],
    bindings: dict | None = None,
) -> str:
    """把"旧数据库"写进给定 store：档案无 ``profile_id``，apiKey 为 Fernet 密文。

    返回写入的原始 JSON，供"失败保持不变"断言复用。
    """
    assert store._fernet is not None, "cryptography 必须可用"
    encoded = []
    for model in models:
        entry = dict(model)
        entry.pop("profile_id", None)
        entry["apiKey"] = store._fernet.encrypt(entry["apiKey"].encode("utf-8")).decode("utf-8")
        encoded.append(entry)
    raw = json.dumps(encoded, ensure_ascii=False)
    store.set("custom_models", raw)
    invalidate_custom_models_cache_for_store(store)
    if bindings is not None:
        store.set("persona_model_bindings", json.dumps(bindings, ensure_ascii=False))
    return raw


def _read_bindings(store: ConfigStore) -> dict:
    return json.loads(store.get("persona_model_bindings", "{}"))


@pytest.fixture
def legacy_db(tmp_path):
    """旧数据库（两个档案共享同一上游模型名，其中一个带悬挂旧绑定）。"""
    db_path = tmp_path / "legacy.db"
    models = [
        _canonical_profile(
            model_id="shared-model",
            endpoint="https://api.openai.com/v1",
            api_key=PLAINTEXT_KEY_A,
            name="Profile A",
        ),
        _canonical_profile(
            model_id="shared-model",
            endpoint="https://api.deepseek.com/v1",
            api_key=PLAINTEXT_KEY_B,
            name="Profile B",
        ),
    ]
    store = ConfigStore(db_path=db_path)
    try:
        raw = _seed_legacy_store(store, models, bindings={"高压吐槽型": "shared-model"})
    finally:
        store.close()
    return db_path, raw


# ---------------------------------------------------------------------------
# §5.2 旧数据迁移
# ---------------------------------------------------------------------------


def test_migration_assigns_profile_ids_once_and_persists(legacy_db):
    db_path, raw_before = legacy_db
    store = ConfigStore(db_path=db_path)
    try:
        models = store.get_custom_models()
        profile_ids = [m.get("profile_id") for m in models]
        assert all(isinstance(pid, str) and pid for pid in profile_ids)
        assert len(set(profile_ids)) == len(profile_ids)
        # 已持久化到原始 DB 行
        raw_after = _raw_custom_models_json(store)
        assert raw_after != raw_before
        for pid in profile_ids:
            assert pid in raw_after
    finally:
        store.close()


def test_migration_is_stable_across_repeated_runs_and_restart(legacy_db):
    db_path, _raw = legacy_db
    store = ConfigStore(db_path=db_path)
    try:
        first = [m["profile_id"] for m in store.get_custom_models()]
        # 重复执行迁移：已稳定 → 无需改写
        assert migrate_custom_model_identities_for_store(store) is False
        assert [m["profile_id"] for m in store.get_custom_models()] == first
    finally:
        store.close()

    for _ in range(3):
        reopened = ConfigStore(db_path=db_path)
        try:
            assert [m["profile_id"] for m in reopened.get_custom_models()] == first
        finally:
            reopened.close()


def test_migration_keeps_api_key_encrypted_and_usable(legacy_db):
    db_path, _raw = legacy_db
    store = ConfigStore(db_path=db_path)
    try:
        raw = _raw_custom_models_json(store)
        assert PLAINTEXT_KEY_A not in raw
        assert PLAINTEXT_KEY_B not in raw
        keys = sorted(m["apiKey"] for m in store.get_custom_models())
        assert keys == sorted([PLAINTEXT_KEY_A, PLAINTEXT_KEY_B])
    finally:
        store.close()


def test_migration_leaves_ambiguous_legacy_binding_unresolved(legacy_db):
    """重复 ``default_model_id`` 的旧绑定不猜测首项，保留可诊断的 unresolved。"""
    db_path, _raw = legacy_db
    store = ConfigStore(db_path=db_path)
    try:
        assert _read_bindings(store) == {"高压吐槽型": "shared-model"}
        personae = PersonaManager(store)
        assert personae.describe_model_binding("高压吐槽型")["status"] == "unresolved"
        with pytest.raises(PersonaModelBindingError) as exc_info:
            resolve_persona_model_binding(store, "高压吐槽型")
        assert exc_info.value.code == "unresolved"
        assert PLAINTEXT_KEY_A not in str(exc_info.value)
    finally:
        store.close()


def test_migration_upgrades_unique_legacy_binding_to_versioned(tmp_path):
    db_path = tmp_path / "unique.db"
    models = [
        _canonical_profile(
            model_id="unique-model",
            endpoint="https://api.openai.com/v1",
            api_key=PLAINTEXT_KEY_A,
        )
    ]
    store = ConfigStore(db_path=db_path)
    try:
        _seed_legacy_store(store, models, bindings={"高压吐槽型": "unique-model"})
    finally:
        store.close()

    reopened = ConfigStore(db_path=db_path)
    try:
        profile_id = reopened.get_custom_models()[0]["profile_id"]
        parsed = _read_bindings(reopened)
        assert parsed == {
            "高压吐槽型": {"v": 1, "profile_id": profile_id, "model_id": "unique-model"}
        }
    finally:
        reopened.close()


def test_migration_failure_preserves_original_rows(legacy_db, monkeypatch):
    """原子失败：档案与绑定都保持原样，不出现"档案已变而引用只变一半"。"""
    db_path, raw_before = legacy_db
    store = ConfigStore(db_path=db_path)
    try:
        # 重新种回旧 shape（上面的 ConfigStore(...) 已经迁移过），再注入失败
        _seed_legacy_store(
            store,
            [
                _canonical_profile(
                    model_id="shared-model",
                    endpoint="https://api.openai.com/v1",
                    api_key=PLAINTEXT_KEY_A,
                ),
                _canonical_profile(
                    model_id="shared-model",
                    endpoint="https://api.deepseek.com/v1",
                    api_key=PLAINTEXT_KEY_B,
                ),
            ],
            bindings={"高压吐槽型": "shared-model"},
        )
        raw_reseeded = _raw_custom_models_json(store)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("injected migration failure")

        monkeypatch.setattr(store, "apply_web_save", _boom)
        assert migrate_custom_model_identities_for_store(store) is False
        assert _raw_custom_models_json(store) == raw_reseeded
        assert _read_bindings(store) == {"高压吐槽型": "shared-model"}
    finally:
        store.close()
    assert raw_before  # 旧基线快照确实非空（保留给"迁移前"证据）


# ---------------------------------------------------------------------------
# §5.1 档案身份：唯一主路径按 profile_id，模型名重复时歧义
# ---------------------------------------------------------------------------


def test_find_profile_is_ambiguous_on_duplicate_model_name(legacy_db):
    db_path, _raw = legacy_db
    store = ConfigStore(db_path=db_path)
    try:
        models = store.get_custom_models()
        # 上游模型名重复 → 按模型名查找返回歧义（None），不返回首项
        assert find_custom_model_profile(models, "shared-model") is None
        # 按 profile_id 精确命中
        for model in models:
            found = find_custom_model_profile_by_profile_id(models, model["profile_id"])
            assert found is model or found == model
    finally:
        store.close()


# ---------------------------------------------------------------------------
# §6 验收：重复模型名 + 不同 endpoint/key → 绑定后命中正确档案
# ---------------------------------------------------------------------------


def test_duplicate_model_profiles_share_the_selected_global_profile(tmp_path):
    db_path = tmp_path / "duplicate.db"
    models = [
        _canonical_profile(
            model_id="gpt-4o-mini",
            endpoint="https://api.openai.com/v1",
            api_key=PLAINTEXT_KEY_A,
            name="OpenAI profile",
        ),
        _canonical_profile(
            model_id="gpt-4o-mini",
            endpoint="https://api.deepseek.com/v1",
            api_key=PLAINTEXT_KEY_B,
            name="DeepSeek profile",
        ),
    ]
    store = ConfigStore(db_path=db_path)
    try:
        store.set_custom_models(models)
        profiles = store.get_custom_models()
        profile_a, profile_b = profiles[0], profiles[1]
        assert profile_a["profile_id"] != profile_b["profile_id"]

        personae = PersonaManager(store)
        personae.set_model_binding("甲方人格", profile_id=profile_a["profile_id"])
        personae.set_model_binding("乙方人格", profile_id=profile_b["profile_id"])
        assert personae.get_model_binding("甲方人格") == profile_a["profile_id"]
        assert personae.get_model_binding("乙方人格") == profile_b["profile_id"]

        set_active_model_profile(store, profile_b["profile_id"])
        creds_a = resolve_request_credentials_for_persona(store, "甲方人格")
        creds_b = resolve_request_credentials_for_persona(store, "乙方人格")
        assert creds_a is not None and creds_b is not None
        assert creds_a == creds_b
        assert creds_a[0] == "https://api.deepseek.com/v1"
        assert creds_a[1] == PLAINTEXT_KEY_B
        assert creds_b[0] == "https://api.deepseek.com/v1"
        assert creds_b[1] == PLAINTEXT_KEY_B
        # 上游模型标识仍正确传给 provider
        assert creds_a[2] == "gpt-4o-mini" == creds_b[2]

        planned_a = plan_http_request(
            GenerationRequest(
                purpose="visual_danmu",
                model_id=creds_a[2],
                endpoint=creds_a[0],
                api_key=creds_a[1],
                api_mode=creds_a[3],
            )
        )
        planned_b = plan_http_request(
            GenerationRequest(
                purpose="visual_danmu",
                model_id=creds_b[2],
                endpoint=creds_b[0],
                api_key=creds_b[1],
                api_mode=creds_b[3],
            )
        )
        assert planned_a.url.startswith("https://api.deepseek.com/")
        assert planned_b.url.startswith("https://api.deepseek.com/")
        assert planned_a.headers.get("Authorization") == f"Bearer {PLAINTEXT_KEY_B}"
        assert planned_b.headers.get("Authorization") == f"Bearer {PLAINTEXT_KEY_B}"
        assert planned_a.model_id == "gpt-4o-mini" == planned_b.model_id
    finally:
        store.close()


def test_personas_use_the_selected_global_profile(legacy_db):
    """人格绑定历史值不影响运行时；所有人格都使用当前全局档案。"""
    db_path, _raw = legacy_db
    store = ConfigStore(db_path=db_path)
    try:
        personae = PersonaManager(store)
        profiles = store.get_custom_models()
        set_active_model_profile(store, profiles[1]["profile_id"])
        assert personae.get_model_binding("未绑定的人格") == ""
        creds_a = resolve_request_credentials_for_persona(store, "未绑定的人格")
        creds_b = resolve_request_credentials_for_persona(store, "其它人格")
        assert creds_a is not None and creds_a == creds_b
        assert creds_a[0] == "https://api.deepseek.com/v1"
        assert creds_a[1] == PLAINTEXT_KEY_B
    finally:
        store.close()


def test_model_removed_from_historical_binding_does_not_change_global_runtime(tmp_path):
    """历史人格绑定失效时，运行时仍只按全局档案解析。"""
    store = ConfigStore(db_path=tmp_path / "removed.db")
    models = [
        _canonical_profile(
            model_id="first-model",
            endpoint="https://api.openai.com/v1",
            api_key=PLAINTEXT_KEY_A,
        ),
        _canonical_profile(
            model_id="bound-a",
            endpoint="https://api.deepseek.com/v1",
            api_key=PLAINTEXT_KEY_B,
        ),
    ]
    try:
        store.set_custom_models(models)
        profiles = store.get_custom_models()
        personae = PersonaManager(store)
        personae.set_model_binding(
            "高压吐槽型", model_id="bound-a", profile_id=profiles[1]["profile_id"]
        )
        set_active_model_profile(store, profiles[1]["profile_id"])
        # 从该档案移除被绑定的上游模型（保留档案身份）
        updated = dict(profiles[1])
        updated["model_ids"] = ["bound-b"]
        updated["default_model_id"] = "bound-b"
        store.set_custom_models([profiles[0], updated])

        creds = resolve_request_credentials_for_persona(store, "高压吐槽型")
        assert creds is not None
        assert creds[:3] == (
            "https://api.deepseek.com/v1",
            PLAINTEXT_KEY_B,
            "bound-b",
        )
    finally:
        store.close()
