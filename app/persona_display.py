"""Persona 显示名与默认 user prompt 辅助。"""

from __future__ import annotations

import json

from app.persona_builtin import PERSONA_NAME_KEYS, normalize_persona_name
from app.translations import tr


def persona_display_name(name: str) -> str:
    normalized = normalize_persona_name(name)
    key = PERSONA_NAME_KEYS.get(normalized)
    return tr(key) if key else normalized


def get_persona_custom_label(name: str, config) -> str | None:
    """从 config 的 persona_labels JSON 映射中读取自定义显示名称。"""
    normalized = normalize_persona_name(name)
    raw = config.get("persona_labels", "{}")
    try:
        labels = json.loads(raw)
        if isinstance(labels, dict):
            return labels.get(normalized)
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def persona_display_name_with_config(name: str, config) -> str:
    """优先返回用户自定义的显示名称，否则 fallback 到翻译或原始名。"""
    custom = get_persona_custom_label(name, config)
    if custom:
        return custom
    return persona_display_name(name)


def default_user_prompt() -> str:
    return tr("template.default_user_prompt")


__all__ = [
    "default_user_prompt",
    "get_persona_custom_label",
    "persona_display_name",
    "persona_display_name_with_config",
]
