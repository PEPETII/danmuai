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
import random

from app.config_store import ConfigStore
from app.persona_builtin import (
    BUILTIN_PERSONAE,
    BUILTIN_PERSONA_PINNED_FIRST,
    builtin_personae_names,
    normalize_persona_name,
)
from app.persona_contract import ensure_reply_contract
from app.translations import tr

_REMOVED_PERSONAE = frozenset({
    "阿静",
    "测试",
    "专业分析型",
    "路人惊讶型",
    "搞笑玩梗型",
    "捧场活跃型",
    "轻度吐槽型",
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
        "测试1",
        "测试2",
        "测试3",
        "吐槽型",
        "傲娇型",
        "腹黑型",
    ]
    _ACTIVE_VERSION = 7

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
            if version < 7:
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
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                self._custom = {normalize_persona_name(name): value for name, value in loaded.items()}
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

    def pick_random(self) -> str:
        active = self.get_active()
        return random.choice(active) if active else self.DEFAULT_ACTIVE[0]
