"""Persona / template operations for the web console."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.personae import (
    BUILTIN_PERSONAE,
    PersonaManager,
    default_user_prompt,
    ensure_reply_contract,
    get_reply_contract,
    strip_reply_contract,
)
from app.templates import TemplateManager
from app.translations import Translator

if TYPE_CHECKING:
    from main import DanmuApp


def get_template_detail(app: "DanmuApp", name: str) -> dict[str, Any]:
    personae: PersonaManager = app.personae
    templates: TemplateManager = app.templates

    from app.personae import normalize_persona_name, persona_display_name

    name = normalize_persona_name(name)
    if name not in personae.list():
        raise ValueError("人格不存在")

    is_builtin = name in BUILTIN_PERSONAE

    system_pt, user_pt = personae.get_prompt(name)
    if not system_pt:
        system_pt, user_pt = templates.load(name)

    return {
        "id": name,
        "label": persona_display_name(name),
        "builtin": is_builtin,
        "editable": not is_builtin,
        "system_editable": True,
        "can_save": True,
        "system_custom": strip_reply_contract(system_pt),
        "user_pt": user_pt or default_user_prompt(),
        "reply_contract": get_reply_contract(app.config),
    }


def list_versions(app: "DanmuApp", name: str) -> list[dict[str, Any]]:
    from app.personae import normalize_persona_name

    name = normalize_persona_name(name)
    return app.templates.versions(name)


def save_template(app: "DanmuApp", name: str, system_custom: str, user_pt: str) -> None:
    from app.personae import normalize_persona_name

    name = normalize_persona_name(name)
    reply_contract = get_reply_contract(app.config)

    _, existing_user = app.templates.load(name)
    if not (user_pt or "").strip():
        user_pt = existing_user or default_user_prompt()

    custom = (system_custom or "").strip()
    if custom:
        full_system = f"{reply_contract} {custom}".strip()
    elif name in BUILTIN_PERSONAE:
        prompt = BUILTIN_PERSONAE[name]
        if Translator.get_language() == "en":
            base = prompt["system_en"]
        else:
            base = prompt["system_zh"]
        full_system = ensure_reply_contract(base, app.config)
    else:
        full_system = reply_contract

    app.personae.save_custom(name, full_system, user_pt)
    app.templates.save(name, full_system, user_pt)
    app.config_changed.emit()


def rollback_preview(app: "DanmuApp", name: str, version: int) -> dict[str, Any]:
    from app.personae import normalize_persona_name

    name = normalize_persona_name(name)
    system_pt, user_pt = app.templates.load(name, version)
    return {
        "system_custom": strip_reply_contract(system_pt),
        "user_pt": user_pt or default_user_prompt(),
        "version": version,
    }


def create_persona(app: "DanmuApp", name: str) -> dict[str, Any]:
    from app.personae import normalize_persona_name, persona_display_name

    name = normalize_persona_name(name.strip())
    if not name:
        raise ValueError("请输入人格名称")
    if name in app.personae.list():
        raise ValueError("人格名称已存在")

    contract = get_reply_contract(app.config)
    user_pt = default_user_prompt()
    app.personae.save_custom(name, contract, user_pt)
    app.templates.save(name, contract, user_pt)
    app.config_changed.emit()
    return {"id": name, "label": persona_display_name(name)}


def delete_persona(app: "DanmuApp", name: str) -> None:
    from app.personae import normalize_persona_name

    name = normalize_persona_name(name)
    if name in BUILTIN_PERSONAE:
        raise ValueError("内置人格不可删除")
    app.personae.delete_custom(name)
    app.config_changed.emit()


def restore_builtin_default(app: "DanmuApp", name: str) -> dict[str, Any]:
    from app.personae import normalize_persona_name

    name = normalize_persona_name(name)
    if name not in BUILTIN_PERSONAE:
        raise ValueError("仅内置人格可恢复默认")

    app.personae.delete_custom(name)
    app.config_changed.emit()
    prompt = BUILTIN_PERSONAE[name]
    if Translator.get_language() == "en":
        system_custom = prompt["system_en"]
        user_pt = prompt["user_en"]
    else:
        system_custom = prompt["system_zh"]
        user_pt = prompt["user_zh"]
    return {
        "system_custom": system_custom,
        "user_pt": user_pt,
    }
