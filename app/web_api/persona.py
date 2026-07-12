"""人格/模板 Web 逻辑；由 routes 调用，写配置经 DanmuApp/ConfigStore 既有入口。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/personae``：列出内置 + 自定义人格清单。
- ``GET /api/personae/{name}``：返回 ``system_pt`` + ``user_pt``（中文/英文按当前语言）。
- ``POST/PUT /api/personae``：写入自定义人格；落 ``custom_personae`` JSON 字符串。
- ``DELETE /api/personae/{name}``：删除自定义人格；同步从 ``active_personae`` 剔除。

与 ``PersonaManager`` 的关系：本模块只做 Web 入参与出参转换，业务逻辑全部委托
``app.personae.PersonaManager``；不直接读写 ConfigStore 内部字段。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.persona_builtin import BUILTIN_PERSONAE, normalize_persona_name, validate_persona_name
from app.persona_contract import (
    append_live_topic_to_system_pt,
    append_nickname_to_system_pt,
    ensure_reply_contract,
    get_reply_contract,
    strip_reply_contract,
    strip_system_style,
)
from app.persona_manager import PersonaManager
from app.persona_display import default_user_prompt
from app.templates import TemplateManager
from app.translations import Translator, tr

if TYPE_CHECKING:
    from main import DanmuApp


def _default_user_pt_for_save(name: str) -> str:
    if name in BUILTIN_PERSONAE:
        prompt = BUILTIN_PERSONAE[name]
        if Translator.get_language() == "en":
            return prompt["user_en"]
        return prompt["user_zh"]
    return default_user_prompt()


def _system_custom_for_display(system_pt: str) -> str:
    return strip_reply_contract(system_pt)


def _resolve_user_pt_for_save(name: str, user_pt: str, existing_user: str) -> str:
    if (user_pt or "").strip():
        return user_pt
    if (existing_user or "").strip():
        return existing_user
    return _default_user_pt_for_save(name)


def get_template_detail(app: "DanmuApp", name: str) -> dict[str, Any]:
    personae: PersonaManager = app.personae
    templates: TemplateManager = app.templates

    from app.persona_builtin import normalize_persona_name

    name = normalize_persona_name(name)
    if name not in personae.list():
        raise ValueError(tr("persona.notFound"))

    is_builtin = name in BUILTIN_PERSONAE

    system_pt, user_pt = personae.get_prompt(name)
    if not system_pt:
        system_pt, user_pt = templates.load(name)

    # 完整提示词预览：含契约 + 风格 + 自定义 + 昵称 + 主题（与 main.py 实际发送一致）
    system_pt_full = append_nickname_to_system_pt(system_pt, app.config)
    system_pt_full = append_live_topic_to_system_pt(system_pt_full, app.config)

    return {
        "id": name,
        "label": personae.get_display_name(name),
        "builtin": is_builtin,
        "editable": not is_builtin,
        "system_editable": True,
        "can_save": True,
        "system_custom": _system_custom_for_display(system_pt),
        "user_pt": user_pt or default_user_prompt(),
        "reply_contract": get_reply_contract(app.config),
        "system_pt_full": system_pt_full,
    }


def list_versions(app: "DanmuApp", name: str) -> list[dict[str, Any]]:
    from app.persona_builtin import normalize_persona_name

    name = normalize_persona_name(name)
    return app.templates.versions(name)


def save_template(app: "DanmuApp", name: str, system_custom: str, user_pt: str, label: str = "") -> None:
    from app.persona_builtin import normalize_persona_name

    name = normalize_persona_name(name)

    _, existing_user = app.templates.load(name)
    user_pt = _resolve_user_pt_for_save(name, user_pt, existing_user)

    custom = strip_system_style((system_custom or "").strip())
    if custom:
        full_system = ensure_reply_contract(custom, app.config)
    elif name in BUILTIN_PERSONAE:
        prompt = BUILTIN_PERSONAE[name]
        if Translator.get_language() == "en":
            base = prompt["system_en"]
        else:
            base = prompt["system_zh"]
        full_system = ensure_reply_contract(base, app.config)
    else:
        full_system = ensure_reply_contract("", app.config)

    app.personae.save_custom(name, full_system, user_pt)
    app.personae.save_display_name(name, label)
    app.templates.save(name, full_system, user_pt)
    app.config_changed.emit()


def rollback_preview(app: "DanmuApp", name: str, version: int) -> dict[str, Any]:
    from app.persona_builtin import normalize_persona_name

    name = normalize_persona_name(name)
    system_pt, user_pt = app.templates.load(name, version)
    return {
        "system_custom": _system_custom_for_display(system_pt),
        "user_pt": user_pt or default_user_prompt(),
        "version": version,
    }


def create_persona(app: "DanmuApp", name: str) -> dict[str, Any]:
    from app.persona_builtin import normalize_persona_name, validate_persona_name

    name = normalize_persona_name(validate_persona_name(name))
    if name in app.personae.list():
        raise ValueError(tr("persona.alreadyExists"))

    user_pt = default_user_prompt()
    full_system = ensure_reply_contract("", app.config)
    app.personae.save_custom(name, full_system, user_pt)
    app.templates.save(name, full_system, user_pt)
    app.config_changed.emit()
    return {"id": name, "label": app.personae.get_display_name(name)}


def delete_persona(app: "DanmuApp", name: str) -> None:
    from app.persona_builtin import normalize_persona_name

    name = normalize_persona_name(name)
    if name in BUILTIN_PERSONAE:
        raise ValueError(tr("persona.builtinCannotDelete"))
    app.personae.delete_custom(name)
    app.config_changed.emit()


def restore_builtin_default(app: "DanmuApp", name: str) -> dict[str, Any]:
    from app.persona_builtin import normalize_persona_name

    name = normalize_persona_name(name)
    if name not in BUILTIN_PERSONAE:
        raise ValueError(tr("persona.onlyBuiltinCanRestore"))

    app.personae.delete_custom(name)
    app.config_changed.emit()
    prompt = BUILTIN_PERSONAE[name]
    if Translator.get_language() == "en":
        system_pt = ensure_reply_contract(prompt["system_en"], app.config)
        user_pt = prompt["user_en"]
    else:
        system_pt = ensure_reply_contract(prompt["system_zh"], app.config)
        user_pt = prompt["user_zh"]
    return {
        "system_custom": _system_custom_for_display(system_pt),
        "user_pt": user_pt,
    }
