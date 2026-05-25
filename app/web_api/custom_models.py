"""Custom model list operations for the web console."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.model_providers import is_model_config_complete, validate_model_config

if TYPE_CHECKING:
    from main import DanmuApp

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
    if key == MASKED_KEY and existing:
        return existing.get("apiKey", "")
    if key:
        return key
    return ""


def _normalize_payload(payload: dict, existing: dict | None = None, app: "DanmuApp | None" = None) -> dict:
    return {
        "name": (payload.get("name") or "").strip(),
        "modelId": (payload.get("modelId") or payload.get("model_id") or "").strip(),
        "mode": (payload.get("mode") or "doubao").strip(),
        "endpoint": (payload.get("endpoint") or "").strip(),
        "apiKey": _resolve_api_key(payload, existing, app),
        "description": (payload.get("description") or "").strip(),
        "provider": (payload.get("provider") or "").strip(),
    }


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
        raise ValueError("模型索引无效")

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
        raise ValueError("模型索引无效")

    removed = models.pop(index)
    app.config.set_custom_models(models)
    default_id = app.config.get_default_model_id()
    if removed.get("modelId") == default_id:
        fallback = models[0].get("modelId", "") if models else app.config.get("model", "")
        if fallback:
            app.config.set_default_model_id(fallback)
            app.config.set("model", fallback)
    app.config_changed.emit()


def set_default_custom_model(app: "DanmuApp", index: int) -> dict:
    models = app.config.get_custom_models()
    if index < 0 or index >= len(models):
        raise ValueError("模型索引无效")

    model_id = models[index].get("modelId", "")
    if not model_id:
        raise ValueError("模型 ID 为空")

    app.config.set_default_model_id(model_id)
    app.config.set("model", model_id)
    app.config_changed.emit()
    return {"default_model_id": model_id}
