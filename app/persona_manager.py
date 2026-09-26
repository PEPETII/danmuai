"""人格 CRUD + 持久化门面。

``PersonaManager`` 是 ``DanmuApp.personae`` 的实际类型，提供：
- 内置人格（``BUILTIN_PERSONAE``）的清单与中/英 prompt 获取。
- 自定义人格（``custom_personae``）的增删改查与持久化到 ``ConfigStore``。
- 活跃人格（``active_personae``）版本迁移：旧版人格（``阿静``/``测试``）会被自动剔除。
- 随机抽签：``pick_random`` 从活跃人格中均匀随机选一个作为本轮回复的 persona。

约束：本类不导入 Qt；可在主线程或 HTTP 线程安全调用（Dict / set 操作不修改 ConfigStore 以外的共享状态）。
"""

from __future__ import annotations

import json
import logging
import random

from app.config_store import ConfigStore
from app.config_store.crypto import (
    build_persona_model_binding,
    legacy_persona_model_binding_model_id,
    parse_persona_model_binding,
)
from app.model_providers import (
    custom_model_profile_identity,
    find_custom_model_profile_by_profile_id,
    find_custom_model_profiles_by_model_id,
    is_model_config_complete,
)
from app.persona_builtin import (
    BUILTIN_PERSONA_PINNED_FIRST,
    BUILTIN_PERSONAE,
    builtin_personae_names,
    normalize_persona_name,
)
from app.persona_contract import (
    ensure_reply_contract,
    strip_reply_contract,
    strip_system_style,
)
from app.translations import tr

logger = logging.getLogger(__name__)

PERSONA_MODEL_BINDINGS_KEY = "persona_model_bindings"


class PersonaModelBindingError(ValueError):
    """W-AUDIT-MODEL-IDENTITY-001：显式人格模型绑定无法解析。

    只在人格**显式绑定**失效时抛出（悬挂 / 歧义 / 档案不完整 / 所选模型被移除）；
    未绑定人格仍按产品默认使用首个档案，不经过本异常。错误信息不含任何密钥。
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _persona_custom_body(system_pt: str) -> str:
    return strip_system_style(strip_reply_contract(system_pt))


def _builtin_default_system_custom(name: str, lang: str, config: ConfigStore) -> str:
    prompt = BUILTIN_PERSONAE[name]
    key = "system_en" if lang == "en" else "system_zh"
    return _persona_custom_body(ensure_reply_contract(prompt[key], config))


def _builtin_default_user_prompt(name: str, lang: str) -> str:
    prompt = BUILTIN_PERSONAE[name]
    key = "user_en" if lang == "en" else "user_zh"
    return (prompt[key] or "").strip()


def _is_builtin_lang_default_system(
    stored_system_pt: str,
    name: str,
    lang: str,
    config: ConfigStore,
) -> bool:
    expected = _builtin_default_system_custom(name, lang, config)
    actual = _persona_custom_body(stored_system_pt)
    return actual == expected


def _is_builtin_lang_default_user(stored_user: str, name: str, lang: str) -> bool:
    if not (stored_user or "").strip():
        return True
    return (stored_user or "").strip() == _builtin_default_user_prompt(name, lang)

_REMOVED_PERSONAE = frozenset({
    "阿静",
    "测试",
    "专业分析型",
    "路人惊讶型",
    "搞笑玩梗型",
    "捧场活跃型",
    "轻度吐槽型",
    # W-PERSONA-TRIM-002: non-default built-ins removed from personae_builtin.json
    "测试4",
    "文艺型",
    "技术型",
    "萌系型",
    "中二型",
    "治愈型",
    "毒舌型",
    "元气型",
    "社恐型",
    "团战解说型",
    "测试2",
})


def _custom_model_list(config) -> list[dict]:
    getter = getattr(config, "get_custom_models", None)
    if not callable(getter):
        return []
    return [m for m in getter() if isinstance(m, dict)]


def _model_ids_of(profile: dict) -> list[str]:
    return [
        str(mid).strip()
        for mid in (profile.get("model_ids") or [])
        if str(mid or "").strip()
    ]


def describe_persona_model_binding(raw_value, models: list[dict]) -> dict:
    """诊断一条人格模型绑定的当前状态（不含密钥）。

    返回 ``{"status", "profile_id", "model_id"}``；``status`` 取值：

    - ``unbound``：没有绑定（产品默认 → 首个档案）。
    - ``ok``：显式绑定可解析到唯一档案且所选模型仍属于该档案。
    - ``unresolved``：旧字符串绑定零匹配或多匹配，无法唯一确定（不猜测首项）。
    - ``profile_missing``：绑定的 ``profile_id`` 已不存在（悬挂）。
    - ``profile_incomplete``：绑定档案缺少 endpoint/key/model。
    - ``model_removed``：所选 ``model_id`` 已不属于该档案。
    """
    if raw_value is None or raw_value == "" or raw_value == {}:
        return {"status": "unbound", "profile_id": "", "model_id": ""}
    parsed = parse_persona_model_binding(raw_value)
    if parsed is None:
        legacy_model_id = legacy_persona_model_binding_model_id(raw_value)
        if not legacy_model_id:
            return {"status": "unbound", "profile_id": "", "model_id": ""}
        matches = find_custom_model_profiles_by_model_id(models, legacy_model_id)
        if len(matches) == 1:
            return {
                "status": "ok",
                "profile_id": custom_model_profile_identity(matches[0]),
                "model_id": legacy_model_id,
            }
        return {"status": "unresolved", "profile_id": "", "model_id": legacy_model_id}

    profile_id = parsed["profile_id"]
    model_id = parsed["model_id"]
    profile = find_custom_model_profile_by_profile_id(models, profile_id)
    if profile is None:
        return {"status": "profile_missing", "profile_id": profile_id, "model_id": model_id}
    if not is_model_config_complete(profile):
        return {"status": "profile_incomplete", "profile_id": profile_id, "model_id": model_id}
    if model_id and model_id not in _model_ids_of(profile):
        return {"status": "model_removed", "profile_id": profile_id, "model_id": model_id}
    return {"status": "ok", "profile_id": profile_id, "model_id": model_id}


_BINDING_ERROR_TRANSLATION_KEYS = {
    "unresolved": "persona.modelBindingUnresolved",
    "profile_missing": "persona.modelBindingProfileMissing",
    "profile_incomplete": "persona.modelBindingProfileIncomplete",
    "model_removed": "persona.modelBindingModelRemoved",
}


def persona_model_binding_message(status: str) -> str:
    """把绑定诊断状态翻译为面向用户的提示（``ok`` / ``unbound`` 返回空串）。

    与运行时 ``PersonaModelBindingError`` 复用同一组翻译键，保证 UI 提示与请求
    失败信息一致；文案不含任何密钥。
    """
    key = _BINDING_ERROR_TRANSLATION_KEYS.get(status)
    return tr(key) if key else ""


def resolve_persona_model_binding(config, persona_id: str) -> tuple[dict, str] | None:
    """解析显式人格绑定的档案与上游模型。

    返回 ``(profile, model_id)``；未绑定返回 ``None``（调用方回退首个档案）。
    显式绑定失效时抛 :class:`PersonaModelBindingError`，绝不静默换到首档案。
    """
    persona_name = normalize_persona_name(persona_id)
    if not persona_name:
        return None
    raw = config.get(PERSONA_MODEL_BINDINGS_KEY, "{}")
    try:
        loaded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        loaded = {}
    if not isinstance(loaded, dict):
        return None
    if persona_name not in loaded:
        return None
    models = _custom_model_list(config)
    status = describe_persona_model_binding(loaded.get(persona_name), models)
    if status["status"] == "unbound":
        return None
    if status["status"] != "ok":
        key = _BINDING_ERROR_TRANSLATION_KEYS.get(
            status["status"], "persona.modelBindingUnresolved"
        )
        raise PersonaModelBindingError(status["status"], tr(key))
    profile = find_custom_model_profile_by_profile_id(models, status["profile_id"])
    if profile is None:
        raise PersonaModelBindingError(
            "profile_missing", tr("persona.modelBindingProfileMissing")
        )
    model_id = status["model_id"] or str(profile.get("default_model_id") or "").strip()
    return profile, model_id


def purge_model_bindings_for_profile(
    config,
    profile_id: str,
    model_id: str,
    remaining_models: list[dict],
) -> None:
    """删除某个模型档案后，只清理指向该档案的人格绑定（W-AUDIT-MODEL-IDENTITY-001）。

    - 版本化绑定按不可变 ``profile_id`` 精确匹配清理，不受重复 ``default_model_id``
      影响（删除重复名之一不会波及另一档案的绑定）。
    - 旧字符串绑定按模型名匹配，但**仅当没有剩余档案仍拥有该模型名时**才清理；
      否则保留（删除其中一个重复名后，旧绑定可能因此变得可唯一解析）。
    - 持久化失败不抛错（不阻断模型删除）；运行时解析仍会再校验一次作为双保险。
    """
    raw = config.get(PERSONA_MODEL_BINDINGS_KEY, "{}")
    try:
        bindings = json.loads(raw) if isinstance(raw, str) else {}
    except (ValueError, TypeError):
        bindings = {}
    if not isinstance(bindings, dict) or not bindings:
        return
    pid = (profile_id or "").strip()
    mid = (model_id or "").strip()
    remaining_model_ids = {
        str(model.get("default_model_id") or "").strip()
        for model in remaining_models or []
        if isinstance(model, dict) and str(model.get("default_model_id") or "").strip()
    }
    changed = False
    for persona_name, value in list(bindings.items()):
        parsed = parse_persona_model_binding(value)
        if parsed is not None:
            if pid and parsed["profile_id"] == pid:
                bindings.pop(persona_name, None)
                changed = True
            continue
        legacy_model_id = legacy_persona_model_binding_model_id(value)
        if not legacy_model_id or legacy_model_id != mid:
            continue
        if mid not in remaining_model_ids:
            bindings.pop(persona_name, None)
            changed = True
    if changed:
        config.set(PERSONA_MODEL_BINDINGS_KEY, json.dumps(bindings, ensure_ascii=False))


class PersonaManager:
    """人格管理器：内置 + 自定义 + 活跃集合。

    关键属性：
    - ``_custom``：内存缓存的自定义人格字典，首次 ``_load_custom`` 时从 ``custom_personae`` 字符串读入。
    - ``_ACTIVE_VERSION``：活跃人格 schema 版本号；启动时 ``_migrate_active_personae`` 检查并迁移。
    - ``_REMOVED_PERSONAE``：被弃用的人格名（``阿静``、``测试``），迁移时自动剔除。

    线程安全：主线程构造 + 主线程/HTTP 线程读取；自定义人格写入后需 ``save_custom`` 显式持久化。
    """

    _TEST_DEFAULT_ACTIVE = BUILTIN_PERSONA_PINNED_FIRST
    DEFAULT_ACTIVE = [
        "高压吐槽型",
        "熬夜陪看型",
        "阴阳锐评型",
        "抽象玩梗型",
        "测试1",
        "测试3",
        "吐槽型",
        "傲娇型",
        "腹黑型",
    ]
    _ACTIVE_VERSION = 11

    def __init__(self, config: ConfigStore):
        self.config = config
        self._custom: dict = {}
        self._migrate_active_personae()
        self._purge_removed_personae()

    def _merge_test_default_active(self, names: list[str]) -> list[str]:
        filtered = self._filter_removed_active(names)
        return list(self._TEST_DEFAULT_ACTIVE) + [
            name for name in filtered if name not in self._TEST_DEFAULT_ACTIVE
        ]

    def _migrate_active_personae(self):
        version = self.config.get_int("active_personae_version", 0)
        if version < self._ACTIVE_VERSION:
            if version < 2:
                self.config.set_json("active_personae", self.DEFAULT_ACTIVE)
            elif version < 5:
                active = self.config.get_json("active_personae", self.DEFAULT_ACTIVE)
                merged = self._merge_test_default_active(active if isinstance(active, list) else [])
                self.config.set_json("active_personae", merged)
            if version < 6:
                active = self.config.get_json("active_personae", self.DEFAULT_ACTIVE)
                filtered = self._filter_removed_active(active if isinstance(active, list) else [])
                self.config.set_json("active_personae", filtered)
            if version < 9:
                self.config.set_json("active_personae", self.DEFAULT_ACTIVE)
            self.config.set("active_personae_version", str(self._ACTIVE_VERSION))

    def _filter_removed_active(self, names: list[str]) -> list[str]:
        filtered = [
            normalize_persona_name(name)
            for name in names
            if name and normalize_persona_name(name) not in _REMOVED_PERSONAE
        ]
        return filtered or list(self.DEFAULT_ACTIVE)

    def _filter_pickable_active(self, names: list[str]) -> list[str]:
        valid = set(self.list())
        return [
            normalize_persona_name(name)
            for name in names
            if name and normalize_persona_name(name) in valid
        ]

    def _purge_removed_personae(self):
        active = self.config.get_json("active_personae", None)
        if isinstance(active, list):
            filtered = self._filter_removed_active(active)
            if filtered != active:
                self.config.set_json("active_personae", filtered)

        custom = self._load_custom()
        removed = [name for name in custom if name in _REMOVED_PERSONAE]
        if removed:
            for name in removed:
                custom.pop(name, None)
            self._custom = custom
            self.config.set("custom_personae", json.dumps(custom, ensure_ascii=False))

    def list(self) -> list[str]:
        builtin_set = set(BUILTIN_PERSONAE.keys())
        custom = [name for name in self._load_custom_names() if name not in builtin_set]
        return builtin_personae_names() + custom

    def get_prompt(self, name: str) -> tuple[str, str]:
        from app.translations import Translator

        normalized = normalize_persona_name(name)
        custom = self._load_custom()
        if normalized in custom:
            prompt = custom[normalized]
            system_pt = (prompt.get("system_pt") or "").strip()
            if system_pt:
                lang = Translator.get_language()
                if normalized in BUILTIN_PERSONAE:
                    other_lang = "en" if lang == "zh" else "zh"
                    if _is_builtin_lang_default_system(
                        system_pt, normalized, other_lang, self.config
                    ):
                        builtin = BUILTIN_PERSONAE[normalized]
                        sys_key = "system_en" if lang == "en" else "system_zh"
                        user_key = "user_en" if lang == "en" else "user_zh"
                        stored_user = (prompt.get("user_pt") or "").strip()
                        if not stored_user or _is_builtin_lang_default_user(
                            stored_user, normalized, other_lang
                        ):
                            user_pt = builtin[user_key]
                        else:
                            user_pt = stored_user
                        return (
                            ensure_reply_contract(builtin[sys_key], self.config),
                            user_pt,
                        )
                user_pt = prompt.get("user_pt") or tr("template.default_user_prompt")
                return ensure_reply_contract(system_pt, self.config), user_pt

        if normalized in BUILTIN_PERSONAE:
            prompt = BUILTIN_PERSONAE[normalized]
            if Translator.get_language() == "en":
                return ensure_reply_contract(prompt["system_en"], self.config), prompt["user_en"]
            return ensure_reply_contract(prompt["system_zh"], self.config), prompt["user_zh"]
        return "", ""

    def get_active(self) -> list[str]:
        names = self.config.get_json("active_personae", self.DEFAULT_ACTIVE)
        normalized = self._filter_removed_active(names if isinstance(names, list) else [])
        pickable = self._filter_pickable_active(normalized)
        return pickable or list(self.DEFAULT_ACTIVE)

    def set_active(self, names: list[str]):
        normalized = self._filter_removed_active([normalize_persona_name(name) for name in names if name])
        self.config.set_json("active_personae", normalized)

    def _load_custom_names(self) -> list[str]:
        return list(self._load_custom().keys())

    def _load_custom(self) -> dict:
        if not self._custom:
            raw = self.config.get("custom_personae", "{}")
            try:
                loaded = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                logger.exception("custom_personae JSON 损坏，重置为空")
                self._custom = {}
            else:
                if isinstance(loaded, dict):
                    self._custom = {
                        normalize_persona_name(name): value for name, value in loaded.items()
                    }
                else:
                    self._custom = {}
        return self._custom

    def save_custom(self, name: str, system_pt: str, user_pt: str):
        custom = self._load_custom()
        custom[normalize_persona_name(name)] = {"system_pt": system_pt, "user_pt": user_pt}
        self._custom = custom
        self.config.set("custom_personae", json.dumps(custom, ensure_ascii=False))

    def delete_custom(self, name: str):
        norm = normalize_persona_name(name)
        custom = self._load_custom()
        custom.pop(norm, None)
        self._custom = custom
        self.config.set("custom_personae", json.dumps(custom, ensure_ascii=False))

        raw = self.config.get_json("active_personae", None)
        if isinstance(raw, list):
            pruned = [n for n in raw if n and normalize_persona_name(n) != norm]
            if len(pruned) != len(raw):
                self.set_active(pruned)

        # W-PERSONA-MODEL-BIND-001：删除自定义人格时同步清除其模型绑定，避免悬挂引用
        bindings = self.get_model_bindings()
        if norm in bindings:
            bindings.pop(norm, None)
            self.config.set(
                PERSONA_MODEL_BINDINGS_KEY, json.dumps(bindings, ensure_ascii=False)
            )

    def get_display_name(self, name: str) -> str:
        from app.persona_display import persona_display_name_with_config

        return persona_display_name_with_config(name, self.config)

    def save_display_name(self, name: str, label: str) -> None:
        norm = normalize_persona_name(name)
        raw = self.config.get("persona_labels", "{}")
        try:
            labels = json.loads(raw)
            if not isinstance(labels, dict):
                labels = {}
        except (json.JSONDecodeError, TypeError):
            labels = {}
        if label and label.strip():
            labels[norm] = label.strip()
        else:
            labels.pop(norm, None)
        self.config.set("persona_labels", json.dumps(labels, ensure_ascii=False))

    # W-PERSONA-MODEL-BIND-001：人格 → 自定义模型档案绑定
    # 独立键 persona_model_bindings，不进 custom_personae schema，零迁移；
    # 内置人格也能绑定。运行时 resolve_persona_model_binding 读取。
    #
    # W-AUDIT-MODEL-IDENTITY-001：绑定值升级为版本化结构
    # （``{"v": 1, "profile_id": ..., "model_id": ...}``），身份由不可变 profile_id
    # 决定；旧模型名字符串仅在唯一匹配时迁移，否则保留为可诊断的 unresolved。
    def get_model_bindings(self) -> dict:
        raw = self.config.get(PERSONA_MODEL_BINDINGS_KEY, "{}")
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_model_binding(self, name: str) -> str:
        """人格绑定的引用值：版本化 → ``profile_id``；旧字符串 → ``model_id``。

        人格页模型下拉以 ``profile_id`` 作为 option value，因此这里返回当前身份
        合同下的引用值；未绑定时为空串。
        """
        raw = self.get_model_bindings().get(normalize_persona_name(name))
        if raw is None:
            return ""
        parsed = parse_persona_model_binding(raw)
        if parsed is not None:
            return parsed["profile_id"]
        return legacy_persona_model_binding_model_id(raw)

    def get_model_binding_model_id(self, name: str) -> str:
        """人格绑定的上游模型标识（发给 provider 的 ``model_id``）。"""
        raw = self.get_model_bindings().get(normalize_persona_name(name))
        if raw is None:
            return ""
        parsed = parse_persona_model_binding(raw)
        if parsed is not None:
            return parsed["model_id"]
        return legacy_persona_model_binding_model_id(raw)

    def describe_model_binding(self, name: str) -> dict:
        """当前人格绑定的诊断状态（供 Web API / UI 显示是否需重新选择）。"""
        raw = self.get_model_bindings().get(normalize_persona_name(name))
        return describe_persona_model_binding(raw, self._custom_models())

    def set_model_binding(
        self, name: str, model_id: str = "", profile_id: str = ""
    ) -> None:
        """写入人格 → 模型档案绑定。

        - ``profile_id`` 非空：按不可变身份绑定；档案不存在 / 所选模型不属于该档案
          时抛 :class:`PersonaModelBindingError`（错误提示不含密钥）。
        - 仅有 ``model_id``（兼容旧调用 / 批量切换）：唯一匹配一个档案时升级为
          版本化绑定；零匹配或多匹配时保留原始字符串（不猜测首项）。
        - 两者皆空：清除绑定，回退首个档案。
        """
        norm = normalize_persona_name(name)
        bindings = self.get_model_bindings()
        pid = (profile_id or "").strip()
        mid = (model_id or "").strip()
        if pid:
            models = self._custom_models()
            profile = find_custom_model_profile_by_profile_id(models, pid)
            if profile is None:
                raise PersonaModelBindingError(
                    "profile_unknown", tr("persona.modelBindingProfileUnknown")
                )
            allowed = _model_ids_of(profile)
            if not mid:
                mid = str(profile.get("default_model_id") or "").strip()
            elif mid not in allowed:
                raise PersonaModelBindingError(
                    "model_removed", tr("persona.modelBindingModelRemoved")
                )
            bindings[norm] = build_persona_model_binding(pid, mid)
        elif mid:
            matches = find_custom_model_profiles_by_model_id(self._custom_models(), mid)
            matched_profile_id = (
                custom_model_profile_identity(matches[0]) if len(matches) == 1 else ""
            )
            if matched_profile_id:
                bindings[norm] = build_persona_model_binding(matched_profile_id, mid)
            else:
                # 零匹配 / 多匹配 / 档案缺身份：保留旧字符串（可诊断的 unresolved），
                # 不猜测首项，也不写入空的 profile_id 造出伪版本化绑定。
                bindings[norm] = mid
        else:
            bindings.pop(norm, None)
        self.config.set(
            PERSONA_MODEL_BINDINGS_KEY, json.dumps(bindings, ensure_ascii=False)
        )

    def _custom_models(self) -> list[dict]:
        return _custom_model_list(self.config)

    def pick_random(self) -> str:
        active = self.get_active()
        return random.choice(active) if active else self.DEFAULT_ACTIVE[0]
