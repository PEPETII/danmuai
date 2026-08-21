"""Model/provider selection helpers for Web config validation and status projection.

职责：
- ``infer_provider_id`` / ``resolve_active_*``：根据模型档案推断当前 provider。
- ``validate_model_selection_for_save``：保存前校验 endpoint 协议。
- 状态投影：``project_*`` 函数供 ``StatusSnapshotBuilder`` 使用，避免路由层直接读 model 配置。

约束：本模块**不**触达 Qt、不调主链路函数；可在 HTTP 线程安全调用。
"""

from __future__ import annotations

from typing import Any

from app.model_catalog import _CATALOG_BY_PROVIDER
from app.model_providers import (
    find_custom_model_profile,
    guess_provider_from_endpoint,
    is_model_config_complete,
    is_valid_endpoint,
    normalize_endpoint,
    resolve_active_model_id,
)
from app.translations import tr


def infer_provider_id(api_endpoint: str, api_mode: str = "") -> str:
    """Infer provider preset id from a model profile endpoint and mode."""
    return guess_provider_from_endpoint(api_endpoint, api_mode)


def _custom_model_by_id(custom_models: list[Any], model_id: str) -> dict[str, Any] | None:
    return find_custom_model_profile(custom_models, model_id)


def catalog_display_name(provider_id: str, model_id: str) -> str | None:
    platform = _CATALOG_BY_PROVIDER.get((provider_id or "").strip())
    if platform is None:
        return None
    for model in platform.models:
        if model.id == model_id:
            return model.name
    return None


def _custom_models_list(config) -> list[Any]:
    if not hasattr(config, "get_custom_models"):
        return []
    return config.get_custom_models()


def _uses_complete_custom_model(config, model_id: str) -> bool:
    """True when active model uses a complete custom profile (own endpoint/key)."""
    mid = (model_id or "").strip()
    if not mid:
        return False
    custom = _custom_model_by_id(_custom_models_list(config), mid)
    return custom is not None and is_model_config_complete(custom)


def visual_api_endpoint_issue(config) -> str | None:
    """Return user-facing error if the active custom_models profile lacks a valid endpoint.

    W-GLOBAL-VISUAL-APIKEY-REMOVE-001: legacy global api_endpoint fallback removed.
    Returns error_api_endpoint_required when no complete custom_models profile exists.
    """
    model_id = resolve_active_model_id(config)
    if _uses_complete_custom_model(config, model_id):
        custom = _custom_model_by_id(_custom_models_list(config), model_id)
        endpoint = normalize_endpoint((custom or {}).get("endpoint", ""))
        if not is_valid_endpoint(endpoint):
            return tr("config.error_api_endpoint_invalid")
        return None
    return tr("config.error_api_endpoint_required")


def validate_web_config_patch(config, payload: dict[str, Any]) -> None:
    """Validate independent model settings for PUT /api/config.

    W-GLOBAL-VISUAL-APIKEY-REMOVE-001: removed legacy global api_endpoint/api_mode
    validation and validate_global_model_selection call. Visual model selection is
    now derived from the first custom_models profile and is not validated here.
    """
    touches = {"mic_api_endpoint", "mic_api_mode", "mic_use_visual_model"}
    if not touches.intersection(payload.keys()):
        return

    mic_use_visual = str(
        payload.get("mic_use_visual_model", config.get("mic_use_visual_model", "1"))
    ).strip()
    if mic_use_visual in ("0", "false", "no", "off"):
        mic_endpoint = str(
            payload.get("mic_api_endpoint", config.get("mic_api_endpoint", ""))
        ).strip()
        if not mic_endpoint:
            raise ValueError(tr("config.error_api_endpoint_required"))
        if not is_valid_endpoint(mic_endpoint):
            raise ValueError(tr("config.error_api_endpoint_invalid"))


def resolve_model_status(config) -> dict[str, Any]:
    """Read-only model projection for /api/status and export_config."""
    active_model_id = resolve_active_model_id(config)
    custom_models = _custom_models_list(config)
    custom_entry = _custom_model_by_id(custom_models, active_model_id)
    if custom_entry is not None:
        endpoint = normalize_endpoint(custom_entry.get("endpoint") or "")
        api_mode = custom_entry.get("mode", "doubao")
        provider_id = (custom_entry.get("provider") or "").strip() or infer_provider_id(
            endpoint, api_mode
        )
    else:
        endpoint = ""
        api_mode = ""
        provider_id = ""
    uses_custom = bool(custom_entry is not None and is_model_config_complete(custom_entry))

    display_name = active_model_id or ""
    model_source = "unknown"

    if not active_model_id:
        model_source = "unknown"
    elif custom_entry is not None:
        model_source = "custom"
        display_name = (custom_entry.get("name") or "").strip() or active_model_id

    return {
        "active_model_id": active_model_id,
        "inferred_provider_id": provider_id,
        "model_display_name": display_name,
        "uses_custom_credentials": uses_custom,
        "model_source": model_source,
        "provider_model_mismatch": False,
    }
