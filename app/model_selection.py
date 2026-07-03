"""Model/provider selection helpers for Web config validation and status projection.

职责：
- ``infer_provider_id`` / ``resolve_active_*``：根据 endpoint/model 推断当前 provider。
- ``set_default_model_selection``：双写「默认视觉模型」到 ``default_model_id`` + 自定义模型列表，
  Web 端切换默认模型调用此函数。
- ``validate_model_selection_for_save``：保存前校验 endpoint 协议，目录仅用于识别明确跨平台误选。
- 状态投影：``project_*`` 函数供 ``StatusSnapshotBuilder`` 使用，避免路由层直接读 model 配置。

约束：本模块**不**触达 Qt、不调主链路函数；可在 HTTP 线程安全调用。
"""

from __future__ import annotations

from typing import Any

from app.model_catalog import (
    _CATALOG_BY_PROVIDER,
    catalog_provider_ids_for_model,
    is_catalog_model_for_provider,
)
from app.model_providers import (
    guess_provider_from_endpoint,
    is_model_config_complete,
    is_valid_endpoint,
    normalize_endpoint,
    provider_label,
    resolve_active_model_id,
)
from app.translations import tr


def infer_provider_id(api_endpoint: str, api_mode: str = "") -> str:
    """Infer provider preset id from global endpoint and API mode."""
    return guess_provider_from_endpoint(api_endpoint, api_mode)


def _custom_model_by_id(custom_models: list[Any], model_id: str) -> dict[str, Any] | None:
    mid = (model_id or "").strip()
    if not mid:
        return None
    for entry in custom_models:
        if not isinstance(entry, dict):
            continue
        if (entry.get("modelId") or "").strip() == mid:
            return entry
    return None


def _provider_has_catalog(provider_id: str) -> bool:
    return (provider_id or "").strip() in _CATALOG_BY_PROVIDER


def catalog_display_name(provider_id: str, model_id: str) -> str | None:
    platform = _CATALOG_BY_PROVIDER.get((provider_id or "").strip())
    if platform is None:
        return None
    for model in platform.models:
        if model.id == model_id:
            return model.name
    return None


def validate_global_model_selection(
    api_endpoint: str,
    api_mode: str,
    model_id: str,
    custom_models: list[Any],
) -> None:
    """Reject invalid global model + endpoint combinations before persisting.

    Deprecated (W-GLOBAL-VISUAL-APIKEY-REMOVE-001): kept for unit test coverage;
    no longer called from validate_web_config_patch. Visual credentials must
    come from a complete custom_models profile.
    """
    mid = (model_id or "").strip()
    if not mid:
        raise ValueError(tr("config.error_model_id_required"))

    custom = _custom_model_by_id(custom_models, mid)
    if custom is not None and is_model_config_complete(custom):
        raise ValueError(tr("config.error_model_id_reserved_for_custom"))

    provider_id = infer_provider_id(api_endpoint, api_mode)
    catalog_provider_ids = catalog_provider_ids_for_model(mid)
    if catalog_provider_ids and provider_id not in catalog_provider_ids:
        label = provider_label(provider_id, "zh")
        raise ValueError(
            tr("config.error_provider_model_mismatch").format(
                provider=label,
                model_id=mid,
            )
        )


def _custom_models_list(config) -> list[Any]:
    if not hasattr(config, "get_custom_models"):
        return []
    return config.get_custom_models()


def _uses_complete_custom_model(config, model_id: str) -> bool:
    """True when active model uses a complete custom profile (own endpoint/key)."""
    mid = (model_id or "").strip()
    if not mid:
        return False
    default_id = (config.get_default_model_id() or "").strip()
    if default_id != mid:
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
    """Validate model selection for PUT /api/config (call before emit / set_batch).

    W-GLOBAL-VISUAL-APIKEY-REMOVE-001: removed legacy global api_endpoint/api_mode
    validation and validate_global_model_selection call. Visual credentials must
    come from a complete custom_models profile.
    """
    touches = {
        "model",
        "default_model_id",
        "mic_api_endpoint",
        "mic_api_mode",
        "mic_use_visual_model",
    }
    if not touches.intersection(payload.keys()):
        return

    model_id = str(
        payload.get("model")
        or payload.get("default_model_id")
        or config.get_default_model_id()
        or config.get("model", "")
    ).strip()

    if model_id:
        # 视觉凭证必须来自完整 custom_models 档案；不再校验全局 api_endpoint/api_mode
        if not _uses_complete_custom_model(config, model_id):
            raise ValueError(tr("config.error_model_id_required"))
    elif "model" in payload or "default_model_id" in payload:
        raise ValueError(tr("config.error_model_id_required"))

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
    endpoint = (config.get("api_endpoint") or "").strip()
    api_mode = config.get("api_mode", "doubao")
    active_model_id = resolve_active_model_id(config)
    provider_id = infer_provider_id(endpoint, api_mode)
    custom_models = _custom_models_list(config)
    default_id = (config.get_default_model_id() or "").strip()

    custom_entry = _custom_model_by_id(custom_models, active_model_id)
    uses_custom = bool(
        custom_entry is not None
        and default_id == active_model_id
        and is_model_config_complete(custom_entry)
    )

    display_name = active_model_id or ""
    model_source = "unknown"

    if not active_model_id:
        model_source = "unknown"
    elif uses_custom:
        model_source = "custom"
        display_name = (custom_entry.get("name") or "").strip() or active_model_id
    elif _provider_has_catalog(provider_id) and is_catalog_model_for_provider(
        provider_id, active_model_id
    ):
        model_source = "catalog"
        display_name = catalog_display_name(provider_id, active_model_id) or active_model_id
    else:
        model_source = "freeform"

    mismatch = bool(
        active_model_id
        and _provider_has_catalog(provider_id)
        and not uses_custom
        and not is_catalog_model_for_provider(provider_id, active_model_id)
    )

    return {
        "active_model_id": active_model_id,
        "inferred_provider_id": provider_id,
        "model_display_name": display_name,
        "uses_custom_credentials": uses_custom,
        "model_source": model_source,
        "provider_model_mismatch": mismatch,
    }
