"""Model/provider selection helpers for Web config validation and status projection."""

from __future__ import annotations

from typing import Any

from app.model_catalog import (
    _CATALOG_BY_PROVIDER,
    is_catalog_model_for_provider,
)
from app.model_providers import (
    guess_provider_from_endpoint,
    is_model_config_complete,
    is_valid_endpoint,
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
    """Reject invalid global model + endpoint combinations before persisting."""
    mid = (model_id or "").strip()
    if not mid:
        raise ValueError(tr("config.error_model_id_required"))

    custom = _custom_model_by_id(custom_models, mid)
    if custom is not None and is_model_config_complete(custom):
        raise ValueError(tr("config.error_model_id_reserved_for_custom"))

    provider_id = infer_provider_id(api_endpoint, api_mode)
    if _provider_has_catalog(provider_id) and not is_catalog_model_for_provider(provider_id, mid):
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


def validate_web_config_patch(config, payload: dict[str, Any]) -> None:
    """Validate model selection for PUT /api/config (call before emit / set_batch)."""
    touches = {"model", "default_model_id", "api_endpoint", "api_mode"}
    if not touches.intersection(payload.keys()):
        return

    if "api_endpoint" in payload:
        endpoint_val = str(payload.get("api_endpoint", "")).strip()
        if endpoint_val and not is_valid_endpoint(endpoint_val):
            raise ValueError(tr("config.error_api_endpoint_invalid"))

    endpoint = str(payload.get("api_endpoint", config.get("api_endpoint", ""))).strip()
    api_mode = str(payload.get("api_mode", config.get("api_mode", "doubao")))
    model_id = str(
        payload.get("model")
        or payload.get("default_model_id")
        or config.get_default_model_id()
        or config.get("model", "")
    ).strip()

    if not model_id:
        if "model" in payload or "default_model_id" in payload:
            raise ValueError(tr("config.error_model_id_required"))
        return

    validate_global_model_selection(
        endpoint,
        api_mode,
        model_id,
        _custom_models_list(config),
    )


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
