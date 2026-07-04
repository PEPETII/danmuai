"""自定义模型 CRUD；默认模型切换须复用 set_default_model_selection 双写规则。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/custom-models``：返回全部自定义模型，``apiKey`` 字段**掩码**为 ``MASKED_KEY``。
- ``POST /api/custom-models`` / ``PUT /api/custom-models/{id}``：写入前经
  ``validate_model_config`` 校验 name/model_ids/endpoint/apiKey 完整性。
- ``DELETE /api/custom-models/{id}``：删除后若 id 是默认模型，重置为「未设置默认」。

W-CUSTOMMODEL-SCHEMA-002：每条档案支持 1:N（``model_ids: list[str]`` +
``default_model_id: str`` + ``max_tokens: int``）；旧 ``modelId`` 字段保留兜底。

设计约束：GET 必须返回掩码 apiKey（防泄漏）；**不**在 ``web_api/custom_models.py`` 内
直接读 ``DanmuApp._config`` 私有字段，统一经 ``app.config`` 公开 façade。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.application.config_service import set_default_model_selection
from app.model_providers import (
    is_model_config_complete,
    normalize_endpoint,
    normalize_mode,
    validate_model_config,
)
from app.translations import tr

if TYPE_CHECKING:
    from main import DanmuApp

# 掩码：前端拿到的 apiKey 都是这个常量；原始 key 只在写入时使用，不对外暴露
MASKED_KEY = "********"


def _mask_model(model: dict) -> dict:
    out = dict(model)
    if out.get("apiKey"):
        out["apiKey"] = MASKED_KEY
    return out


def list_custom_models(app: "DanmuApp") -> dict[str, Any]:
    models = app.config.get_custom_models()
    return {
        "items": [
            {**_mask_model(m), "complete": is_model_config_complete(m)}
            for m in models
        ],
        "default_model_id": app.config.get_default_model_id(),
    }


def _resolve_api_key(payload: dict, existing: dict | None, app: "DanmuApp") -> str:
    key = (payload.get("apiKey") or payload.get("api_key") or "").strip()
    if key == MASKED_KEY:
        # Masked key means "keep stored key" only when editing an existing entry.
        return (existing.get("apiKey", "") if existing else "")
    if key:
        return key
    return ""


def _find_existing_model(models: list[dict], payload: dict, index: int) -> dict | None:
    if 0 <= index < len(models):
        return models[index]
    # W-CUSTOMMODEL-SCHEMA-002：优先按 default_model_id 匹配，保留 modelId 兜底
    model_id = (
        payload.get("default_model_id")
        or payload.get("modelId")
        or payload.get("model_id")
        or ""
    )
    model_id = (model_id or "").strip()
    if not model_id:
        return None
    for model in models:
        entry_id = (
            (model.get("default_model_id") or model.get("modelId") or "").strip()
        )
        if entry_id == model_id:
            return model
    return None


def _normalize_supports_mic(payload: dict, existing: dict | None) -> bool:
    if "supportsMic" in payload:
        value = payload.get("supportsMic")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if existing is not None:
        return bool(existing.get("supportsMic"))
    return False


def _normalize_model_ids(payload: dict, existing: dict | None) -> list[str]:
    """W-CUSTOMMODEL-SCHEMA-002：解析 model_ids 数组。

    优先级：payload.model_ids > payload.modelId > existing.model_ids > existing.modelId。
    payload 的 modelId 优先于 existing确保 probe 场景下用户新填的 modelId 生效。
    """
    raw = payload.get("model_ids")
    if isinstance(raw, list):
        return [str(mid).strip() for mid in raw if str(mid or "").strip()]
    # payload 没有 model_ids → 优先从 payload 的 legacy modelId 兜底
    legacy = (payload.get("modelId") or payload.get("model_id") or "").strip()
    if legacy:
        return [legacy]
    # payload 既没有 model_ids 也没有 modelId → 从 existing 兜底（update 场景保留已有值）
    if existing and isinstance(existing.get("model_ids"), list):
        return [str(mid).strip() for mid in existing["model_ids"] if str(mid or "").strip()]
    if existing:
        legacy_existing = (existing.get("modelId") or existing.get("model_id") or "").strip()
        if legacy_existing:
            return [legacy_existing]
    return []


def _normalize_default_model_id(payload: dict, existing: dict | None, model_ids: list[str]) -> str:
    """W-CUSTOMMODEL-SCHEMA-002：解析 default_model_id。

    优先级：payload.default_model_id > model_ids[0] > payload.modelId > existing。
    """
    raw = (payload.get("default_model_id") or "").strip()
    if raw:
        return raw
    # payload 没有 default_model_id → 优先从 model_ids[0] 兜底
    if model_ids:
        return model_ids[0]
    # model_ids 也为空 → 从 payload 的 legacy modelId 兜底
    legacy = (payload.get("modelId") or payload.get("model_id") or "").strip()
    if legacy:
        return legacy
    # payload 完全没有 model 信息 → 从 existing 兜底（update 场景保留已有值）
    if existing:
        existing_default = (existing.get("default_model_id") or "").strip()
        if existing_default:
            return existing_default
        return (existing.get("modelId") or existing.get("model_id") or "").strip()
    return ""


def _normalize_max_tokens(payload: dict, existing: dict | None) -> int:
    """W-CUSTOMMODEL-SCHEMA-002：解析 max_tokens；缺省时取 existing 或 512。"""
    raw = payload.get("max_tokens")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 512
    if existing is not None:
        existing_raw = existing.get("max_tokens")
        if isinstance(existing_raw, int):
            return existing_raw
        if existing_raw is not None:
            try:
                return int(existing_raw)
            except (TypeError, ValueError):
                pass
    return 512


def _normalize_payload(payload: dict, existing: dict | None = None, app: "DanmuApp | None" = None) -> dict:
    model_ids = _normalize_model_ids(payload, existing)
    default_model_id = _normalize_default_model_id(payload, existing, model_ids)
    max_tokens = _normalize_max_tokens(payload, existing)
    return {
        "name": (payload.get("name") or "").strip(),
        # W-CUSTOMMODEL-SCHEMA-002：保留旧 modelId 字段与 default_model_id 同值（兼容回滚）
        "modelId": default_model_id,
        "model_ids": model_ids,
        "default_model_id": default_model_id,
        "max_tokens": max_tokens,
        "mode": normalize_mode((payload.get("mode") or "doubao").strip()),
        "endpoint": normalize_endpoint((payload.get("endpoint") or "").strip()),
        "apiKey": _resolve_api_key(payload, existing, app),
        "description": (payload.get("description") or "").strip(),
        "provider": (payload.get("provider") or "").strip(),
        "supportsMic": _normalize_supports_mic(payload, existing),
    }


def resolve_probe_credentials(app: "DanmuApp", payload: dict, index: int = -1) -> dict:
    """Resolve probe credentials the same way as save (masked key + endpoint normalization).

    W-CUSTOMMODEL-SCHEMA-002：probe 入参 ``{profile_index, model_id?}``；
    ``model_id`` 缺省时取档案的 ``default_model_id``。
    """
    models = list(app.config.get_custom_models())
    existing = _find_existing_model(models, payload, index)
    resolved = _normalize_payload(payload, existing, app)
    # W-CUSTOMMODEL-SCHEMA-002：若入参指定 model_id，则探测该具体 model_id
    probe_model_id = (payload.get("model_id") or "").strip()
    if probe_model_id:
        resolved["modelId"] = probe_model_id
        resolved["default_model_id"] = probe_model_id
    return resolved


def create_custom_model(app: "DanmuApp", payload: dict) -> dict:
    model = _normalize_payload(payload, app=app)
    errors = validate_model_config(model)
    if errors:
        raise ValueError(errors[0])

    models = list(app.config.get_custom_models())
    models.append(model)
    app.config.set_custom_models(models)
    app.config_changed.emit()
    return {"index": len(models) - 1, "item": _mask_model(model)}


def update_custom_model(app: "DanmuApp", index: int, payload: dict) -> dict:
    models = list(app.config.get_custom_models())
    if index < 0 or index >= len(models):
        raise ValueError(tr("customModel.indexInvalid"))

    existing = models[index]
    model = _normalize_payload(payload, existing, app)
    errors = validate_model_config(model)
    if errors:
        raise ValueError(errors[0])

    models[index] = model
    app.config.set_custom_models(models)
    app.config_changed.emit()
    return {"index": index, "item": _mask_model(model)}


def delete_custom_model(app: "DanmuApp", index: int) -> None:
    models = list(app.config.get_custom_models())
    if index < 0 or index >= len(models):
        raise ValueError(tr("customModel.indexInvalid"))

    removed = models.pop(index)
    app.config.set_custom_models(models)
    default_id = app.config.get_default_model_id()
    # W-CUSTOMMODEL-SCHEMA-002：优先读 default_model_id，保留 modelId 兜底
    removed_id = (removed.get("default_model_id") or removed.get("modelId") or "").strip()
    if removed_id == default_id:
        fallback = ""
        if models:
            fallback = (models[0].get("default_model_id") or models[0].get("modelId") or "").strip()
        if not fallback:
            fallback = app.config.get("model", "")
        if fallback:
            set_default_model_selection(app.config, fallback)
    # W-PERSONA-MODEL-BIND-001：清除引用了被删模型的人格绑定，使其回退全局"使用"模型
    if removed_id:
        _purge_persona_model_bindings_for_model(app.config, removed_id)
    app.config_changed.emit()


def _purge_persona_model_bindings_for_model(config, model_id: str) -> None:
    """删除 model_id 对应档案后，清理 persona_model_bindings 中所有引用它的绑定。

    幂等；解析失败不抛错（不阻断模型删除）；运行时 resolve_request_credentials_for_persona
    仍会再校验一次，作为双保险。
    """
    import json as _json

    raw = config.get("persona_model_bindings", "{}")
    try:
        bindings = _json.loads(raw) if isinstance(raw, str) else {}
    except (ValueError, TypeError):
        bindings = {}
    if not isinstance(bindings, dict) or not bindings:
        return
    changed = False
    for pname, mid in list(bindings.items()):
        if (mid or "").strip() == model_id:
            bindings.pop(pname, None)
            changed = True
    if changed:
        config.set(
            "persona_model_bindings", _json.dumps(bindings, ensure_ascii=False)
        )


def set_default_custom_model(app: "DanmuApp", index: int) -> dict:
    models = app.config.get_custom_models()
    if index < 0 or index >= len(models):
        raise ValueError(tr("customModel.indexInvalid"))

    # W-CUSTOMMODEL-SCHEMA-002：优先读 default_model_id，保留 modelId 兜底
    model_id = (models[index].get("default_model_id") or models[index].get("modelId") or "").strip()
    if not model_id:
        raise ValueError(tr("customModel.idEmpty"))

    set_default_model_selection(app.config, model_id)
    app.config_changed.emit()
    return {"default_model_id": model_id}
