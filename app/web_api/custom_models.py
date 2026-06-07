"""自定义模型 CRUD；默认模型切换须复用 set_default_model_selection 双写规则。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/custom-models``：返回全部自定义模型，``apiKey`` 字段**掩码**为 ``MASKED_KEY``。
- ``POST /api/custom-models`` / ``PUT /api/custom-models/{id}``：写入前经
  ``validate_model_config`` 校验 name/modelId/endpoint/apiKey 完整性。
- ``DELETE /api/custom-models/{id}``：删除后若 id 是默认模型，重置为「未设置默认」。

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
    model_id = (payload.get("modelId") or payload.get("model_id") or "").strip()
    if not model_id:
        return None
    for model in models:
        if (model.get("modelId") or "").strip() == model_id:
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


def _normalize_payload(payload: dict, existing: dict | None = None, app: "DanmuApp | None" = None) -> dict:
    return {
        "name": (payload.get("name") or "").strip(),
        "modelId": (payload.get("modelId") or payload.get("model_id") or "").strip(),
        "mode": normalize_mode((payload.get("mode") or "doubao").strip()),
        "endpoint": normalize_endpoint((payload.get("endpoint") or "").strip()),
        "apiKey": _resolve_api_key(payload, existing, app),
        "description": (payload.get("description") or "").strip(),
        "provider": (payload.get("provider") or "").strip(),
        "supportsMic": _normalize_supports_mic(payload, existing),
    }


def resolve_probe_credentials(app: "DanmuApp", payload: dict, index: int = -1) -> dict:
    """Resolve probe credentials the same way as save (masked key + endpoint normalization)."""
    models = list(app.config.get_custom_models())
    existing = _find_existing_model(models, payload, index)
    return _normalize_payload(payload, existing, app)


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
            set_default_model_selection(app.config, fallback)
    app.config_changed.emit()


def set_default_custom_model(app: "DanmuApp", index: int) -> dict:
    models = app.config.get_custom_models()
    if index < 0 or index >= len(models):
        raise ValueError("模型索引无效")

    model_id = models[index].get("modelId", "")
    if not model_id:
        raise ValueError("模型 ID 为空")

    set_default_model_selection(app.config, model_id)
    app.config_changed.emit()
    return {"default_model_id": model_id}
