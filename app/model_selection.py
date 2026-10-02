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
    custom_model_profile_identity,
    guess_provider_from_endpoint,
    is_model_config_complete,
    is_valid_endpoint,
    normalize_endpoint,
)
from app.translations import tr

ACTIVE_MODEL_PROFILE_ID_KEY = "active_model_profile_id"


def resolve_active_model_profile(config) -> dict[str, Any] | None:
    """Resolve the one global visual model profile without depending on persona.

    ``active_model_profile_id`` is the only persisted selector.  A missing or
    stale selector is resolved conservatively for legacy stores: first complete
    profile, otherwise the first profile, otherwise no profile.  Callers that
    need to persist that fallback should use :func:`ensure_active_model_profile`.
    """
    get_models = getattr(config, "get_custom_models", None)
    if not callable(get_models):
        return None
    models = [entry for entry in get_models() if isinstance(entry, dict)]
    getter = getattr(config, "get", None)
    active_id = (
        str(getter(ACTIVE_MODEL_PROFILE_ID_KEY, "") or "").strip()
        if callable(getter)
        else ""
    )
    if active_id:
        matches = [
            entry
            for entry in models
            if custom_model_profile_identity(entry) == active_id
        ]
        if len(matches) == 1:
            return matches[0]
    for entry in models:
        if is_model_config_complete(entry):
            return entry
    return models[0] if models else None


def get_active_model_profile_id(config) -> str:
    """Return the resolved global profile identity, never an upstream model id."""
    profile = resolve_active_model_profile(config)
    return custom_model_profile_identity(profile) if profile is not None else ""


def ensure_active_model_profile(config) -> str:
    """Persist the startup/upgrade fallback after profile identities are stable."""
    resolved_id = get_active_model_profile_id(config)
    getter = getattr(config, "get", None)
    current_id = (
        str(getter(ACTIVE_MODEL_PROFILE_ID_KEY, "") or "").strip()
        if callable(getter)
        else ""
    )
    if resolved_id != current_id and (resolved_id or current_id):
        setter = getattr(config, "set_if_changed", None)
        if callable(setter):
            setter(ACTIVE_MODEL_PROFILE_ID_KEY, resolved_id)
        else:
            config.set(ACTIVE_MODEL_PROFILE_ID_KEY, resolved_id)
    return resolved_id


def set_active_model_profile(config, profile_id: str) -> str:
    """Select a complete profile by immutable identity and persist it."""
    selected_id = str(profile_id or "").strip()
    models = [entry for entry in config.get_custom_models() if isinstance(entry, dict)]
    matches = [
        entry
        for entry in models
        if custom_model_profile_identity(entry) == selected_id
    ]
    if len(matches) != 1:
        raise ValueError(tr("customModel.profileUnknown"))
    selected = matches[0]
    if not is_model_config_complete(selected):
        raise ValueError(tr("custom_model.error_incomplete"))
    config.set(ACTIVE_MODEL_PROFILE_ID_KEY, selected_id)
    return selected_id


def infer_provider_id(api_endpoint: str, api_mode: str = "") -> str:
    """Infer provider preset id from a model profile endpoint and mode."""
    return guess_provider_from_endpoint(api_endpoint, api_mode)


def _active_custom_model(config) -> dict[str, Any] | None:
    """Return the one global visual profile used by all personas."""
    return resolve_active_model_profile(config)


def catalog_display_name(provider_id: str, model_id: str) -> str | None:
    platform = _CATALOG_BY_PROVIDER.get((provider_id or "").strip())
    if platform is None:
        return None
    for model in platform.models:
        if model.id == model_id:
            return model.name
    return None


def _uses_complete_custom_model(config, model_id: str) -> bool:
    """True when active model uses a complete custom profile (own endpoint/key)."""
    mid = (model_id or "").strip()
    if not mid:
        return False
    custom = _active_custom_model(config)
    if custom is None:
        return False
    if (custom.get("default_model_id") or "").strip() != mid:
        return False
    return is_model_config_complete(custom)


def visual_api_endpoint_issue(config) -> str | None:
    """Return user-facing error if the active custom_models profile lacks a valid endpoint.

    W-GLOBAL-VISUAL-APIKEY-REMOVE-001: legacy global api_endpoint fallback removed.
    Returns error_api_endpoint_required when no complete custom_models profile exists.
    """
    model_id = (
        str((_active_custom_model(config) or {}).get("default_model_id") or "").strip()
    )
    if _uses_complete_custom_model(config, model_id):
        custom = _active_custom_model(config)
        endpoint = normalize_endpoint((custom or {}).get("endpoint", ""))
        if not is_valid_endpoint(endpoint):
            return tr("config.error_api_endpoint_invalid")
        return None
    return tr("config.error_api_endpoint_required")


def validate_web_config_patch(config, payload: dict[str, Any]) -> None:
    """Validate independent model settings for PUT /api/config.

    W-GLOBAL-VISUAL-APIKEY-REMOVE-001: removed legacy global api_endpoint/api_mode
    validation and validate_global_model_selection call. Visual model selection is
    now derived from the active custom_models profile and is not validated here.
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
    custom_entry = _active_custom_model(config)
    active_model_id = (
        str(custom_entry.get("default_model_id") or "").strip()
        if custom_entry is not None
        else ""
    )
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
