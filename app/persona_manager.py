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
                "persona_model_bindings", json.dumps(bindings, ensure_ascii=False)
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

    # W-PERSONA-MODEL-BIND-001：人格 → 自定义模型档案 model_id 绑定
    # 独立键 persona_model_bindings，不进 custom_personae schema，零迁移；
    # 内置人格也能绑定。运行时 resolve_request_credentials_for_persona 读取。
    def get_model_bindings(self) -> dict:
        raw = self.config.get("persona_model_bindings", "{}")
        try:
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_model_binding(self, name: str) -> str:
        return (
            self.get_model_bindings().get(normalize_persona_name(name)) or ""
        ).strip()

    def set_model_binding(self, name: str, model_id: str) -> None:
        norm = normalize_persona_name(name)
        bindings = self.get_model_bindings()
        mid = (model_id or "").strip()
        if mid:
            bindings[norm] = mid
        else:
            bindings.pop(norm, None)
        self.config.set(
            "persona_model_bindings", json.dumps(bindings, ensure_ascii=False)
        )

    def pick_random(self) -> str:
        active = self.get_active()
        return random.choice(active) if active else self.DEFAULT_ACTIVE[0]
