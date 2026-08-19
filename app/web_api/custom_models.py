"""自定义模型 CRUD；默认模型切换须复用 set_default_model_selection 双写规则。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/custom-models``：返回全部自定义模型，``apiKey`` 字段**掩码**为 ``MASKED_KEY``。
- ``POST /api/custom-models`` / ``PUT /api/custom-models/{id}``：写入前经
  ``validate_model_config`` 校验 name/model_ids/endpoint/apiKey 完整性。
- ``DELETE /api/custom-models/{id}``：删除后若 id 是默认模型，重置为「未设置默认」。

W-ARCH-MODEL-PROFILE-CANONICAL-004：公开契约含 canonical 字段
（``model_ids`` / ``default_model_id`` / ``max_tokens``）及档案级 ``temperature``；
legacy ``modelId`` 仅由持久化 adapter 在读取历史 JSON 时内部消费。

设计约束：GET 必须返回掩码 apiKey（防泄漏）；**不**在 ``web_api/custom_models.py`` 内
直接读 ``DanmuApp._config`` 私有字段，统一经 ``app.config`` 公开 façade。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.application.config_service import set_default_model_selection
from app.config_store.crypto import canonicalize_custom_model_profile
from app.model_providers import (
    is_model_config_complete,
    normalize_endpoint,
    normalize_mode,
    validate_model_config,
)
from app.model_selection import catalog_display_name
from app.translations import tr

if TYPE_CHECKING:
    from main import DanmuApp

# 掩码：前端拿到的 apiKey 都是这个常量；原始 key 只在写入时使用，不对外暴露
MASKED_KEY = "********"
THINKING_EFFORT_VALUES = ("off", "low", "medium", "high")
DEFAULT_TEMPERATURE = 0.8
TEMPERATURE_MIN = 0.0
TEMPERATURE_MAX = 2.0


def _coerce_temperature(raw) -> float | None:
    """Parse temperature; ``0`` is valid. Returns None when missing or invalid."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            value = float(text)
        except (TypeError, ValueError):
            return None
    if value < TEMPERATURE_MIN or value > TEMPERATURE_MAX:
        return None
    return value


def _global_temperature_fallback(app: "DanmuApp | None") -> float:
    if app is not None:
        return app.config.get_float("temperature", DEFAULT_TEMPERATURE)
    return DEFAULT_TEMPERATURE


def _normalize_description(payload: dict, existing: dict | None) -> str:
    if "description" in payload:
        return (payload.get("description") or "").strip()
    if existing is not None:
        return (existing.get("description") or "").strip()
    return ""


def _normalize_model_names(
    payload: dict,
    existing: dict | None,
    model_ids: list[str],
    default_model_id: str,
    provider: str,
) -> dict[str, str]:
    raw = payload.get("model_names")
    if isinstance(raw, dict):
        incoming = {
            str(key).strip(): str(value).strip()
            for key, value in raw.items()
            if str(key).strip()
        }
    elif existing is not None and isinstance(existing.get("model_names"), dict):
        incoming = {
            str(key).strip(): str(value).strip()
            for key, value in existing["model_names"].items()
            if str(key).strip()
        }
    else:
        incoming = {}

    profile_name = (payload.get("name") or "").strip()
    if not profile_name and existing is not None:
        profile_name = (existing.get("name") or "").strip()

    result: dict[str, str] = {}
    for mid in model_ids:
        name = incoming.get(mid, "").strip()
        if not name and mid == default_model_id and profile_name:
            name = profile_name
        if not name:
            catalog_name = catalog_display_name(provider, mid)
            name = (catalog_name or mid).strip()
        result[mid] = name
    return result


def _derive_profile_name(
    model_names: dict[str, str],
    default_model_id: str,
    model_ids: list[str],
) -> str:
    if default_model_id and model_names.get(default_model_id):
        return model_names[default_model_id]
    if model_ids:
        first = model_ids[0]
        return model_names.get(first, first)
    return ""


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
    model_id = (payload.get("default_model_id") or "").strip()
    if not model_id:
        return None
    for model in models:
        entry_id = (model.get("default_model_id") or "").strip()
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


def _normalize_thinking_effort(payload: dict, existing: dict | None) -> str:
    """Normalize the per-model thinking selector to its four public values."""
    if "thinking_effort" in payload:
        raw = payload.get("thinking_effort")
    elif existing is not None:
        raw = existing.get("thinking_effort")
    else:
        raw = None
    value = str(raw or "off").strip().lower()
    return value if value in THINKING_EFFORT_VALUES else "off"


def _normalize_temperature(
    payload: dict,
    existing: dict | None,
    app: "DanmuApp | None" = None,
) -> float:
    """Normalize per-model temperature; ``0`` is valid and must not be treated as missing."""
    if "temperature" in payload:
        coerced = _coerce_temperature(payload.get("temperature"))
        if coerced is not None:
            return coerced
    elif existing is not None and "temperature" in existing:
        coerced = _coerce_temperature(existing.get("temperature"))
        if coerced is not None:
            return coerced
    return _global_temperature_fallback(app)


def _assert_canonical_http_payload(payload: dict, existing: dict | None) -> None:
    """Reject legacy-only HTTP bodies that omit canonical ``model_ids``."""
    if isinstance(payload.get("model_ids"), list):
        return
    if existing is not None and isinstance(existing.get("model_ids"), list):
        return
    raise ValueError(tr("custom_model.error_model_id"))


def _merge_payload_for_canonicalization(payload: dict, existing: dict | None) -> dict:
    """HTTP 写入场景：按 payload vs existing 优先级合并字段，再交 adapter canonical 化。

    W-004：payload 侧不接受 legacy modelId；无 model_ids list 时仅从 existing 继承。
    """
    base = dict(existing) if existing else {}

    raw_ids = payload.get("model_ids")
    if isinstance(raw_ids, list):
        model_ids = [str(mid).strip() for mid in raw_ids if str(mid or "").strip()]
    elif existing and isinstance(existing.get("model_ids"), list):
        model_ids = [
            str(mid).strip() for mid in existing["model_ids"] if str(mid or "").strip()
        ]
    else:
        model_ids = []

    raw_default = (payload.get("default_model_id") or "").strip()
    if raw_default:
        default_model_id = raw_default
    elif model_ids:
        default_model_id = model_ids[0]
    elif existing:
        default_model_id = (existing.get("default_model_id") or "").strip()
    else:
        default_model_id = ""

    raw_mt = payload.get("max_tokens")
    if raw_mt is not None:
        try:
            max_tokens = int(raw_mt)
        except (TypeError, ValueError):
            max_tokens = 512
    elif existing is not None:
        existing_raw = existing.get("max_tokens")
        if isinstance(existing_raw, int):
            max_tokens = existing_raw
        elif existing_raw is not None:
            try:
                max_tokens = int(existing_raw)
            except (TypeError, ValueError):
                max_tokens = 512
        else:
            max_tokens = 512
    else:
        max_tokens = 512

    base["model_ids"] = model_ids
    base["default_model_id"] = default_model_id
    base["max_tokens"] = max_tokens
    return base


def _normalize_payload(payload: dict, existing: dict | None = None, app: "DanmuApp | None" = None) -> dict:
    canonical = canonicalize_custom_model_profile(
        _merge_payload_for_canonicalization(payload, existing)
    )
    default_model_id = canonical["default_model_id"]
    model_ids = canonical["model_ids"]
    provider = (payload.get("provider") or (existing or {}).get("provider") or "").strip()
    model_names = _normalize_model_names(
        payload,
        existing,
        model_ids,
        default_model_id,
        provider,
    )
    profile_name = _derive_profile_name(model_names, default_model_id, model_ids)
    if not profile_name:
        profile_name = (payload.get("name") or "").strip()
    if not profile_name and existing is not None:
        profile_name = (existing.get("name") or "").strip()
    return {
        "name": profile_name,
        "model_ids": model_ids,
        "model_names": model_names,
        "default_model_id": default_model_id,
        "max_tokens": canonical["max_tokens"],
        "mode": normalize_mode((payload.get("mode") or "doubao").strip()),
        "endpoint": normalize_endpoint((payload.get("endpoint") or "").strip()),
        "apiKey": _resolve_api_key(payload, existing, app),
        "description": _normalize_description(payload, existing),
        "provider": provider,
        "supportsMic": _normalize_supports_mic(payload, existing),
        "thinking_effort": _normalize_thinking_effort(payload, existing),
        "temperature": _normalize_temperature(payload, existing, app),
    }


def resolve_probe_credentials(app: "DanmuApp", payload: dict, index: int = -1) -> dict:
    """Resolve probe credentials the same way as save (masked key + endpoint normalization).

    probe 入参 ``{profile_index, model_id?}``；``model_id`` 缺省时取档案的
    ``default_model_id``。
    """
    models = list(app.config.get_custom_models())
    existing = _find_existing_model(models, payload, index)
    _assert_canonical_http_payload(payload, existing)
    resolved = _normalize_payload(payload, existing, app)
    probe_model_id = (payload.get("model_id") or "").strip()
    if probe_model_id:
        resolved["default_model_id"] = probe_model_id
    return resolved


def create_custom_model(app: "DanmuApp", payload: dict) -> dict:
    _assert_canonical_http_payload(payload, existing=None)
    model = _normalize_payload(payload, app=app)
    errors = validate_model_config(model)
    if errors:
        raise ValueError(tr(errors[0]))

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
    _assert_canonical_http_payload(payload, existing)
    model = _normalize_payload(payload, existing, app)
    errors = validate_model_config(model)
    if errors:
        raise ValueError(tr(errors[0]))

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
    removed_id = (removed.get("default_model_id") or "").strip()
    if removed_id == default_id:
        fallback = ""
        if models:
            fallback = (models[0].get("default_model_id") or "").strip()
        if not fallback:
            fallback = app.config.get("model", "")
        if fallback:
            set_default_model_selection(app.config, fallback)
    # W-PERSONA-MODEL-BIND-001：清除引用了被删模型的人格绑定，使其回退全局"使用"模型
    if removed_id:
        _purge_persona_model_bindings_for_model(app.config, removed_id)
        from app.virtual_host.model_config import purge_virtual_host_model_refs

        purge_virtual_host_model_refs(app.config, removed_id)
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

    model_id = (models[index].get("default_model_id") or "").strip()
    if not model_id:
        raise ValueError(tr("customModel.idEmpty"))

    set_default_model_selection(app.config, model_id)
    app.config_changed.emit()
    return {"default_model_id": model_id}
