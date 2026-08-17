"""读弹幕（MiMo TTS）专用 API；配置不经 PUT /api/config。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/danmu-read``：返回读弹幕配置（api_key 掩码）。
- ``PUT /api/danmu-read``：保存读弹幕配置（enabled/interval/voice/style_prompt/provider/endpoint/model_id/api_key）。
- ``POST /api/danmu-read/probe``：发送试听文本触发 TTS 合成 + 本地播放（不写入配置）。

注册方式：``app.web_api.routes`` 调用 ``register_danmu_read_routes(app, bridge, check_token)``。
所有写操作经 ``WebConsoleBridge.invoke_on_main`` 回到主线程，由 ``DanmuReadService.apply_config`` 落地。
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from app.application.config_service import MASKED_API_KEY
from app.danmu_read_service import export_danmu_read_config
from app.model_providers import normalize_endpoint
from app.translations import tr
from app.tts.config_credentials import stored_tts_credentials
from app.tts.types import descriptor_to_dict
from app.tts_catalog import list_catalog_for_api
from app.tts_providers import (
    TTS_PROVIDER_MIMO,
    canonical_tts_model_id,
    canonical_tts_provider_id,
    get_tts_manager,
    normalize_tts_voice,
    validate_custom_tts_fields,
)

_UNSUPPORTED_CUSTOM_TTS_MSG = tr("tts.unsupportedCustom")

if TYPE_CHECKING:
    from main import DanmuApp


def get_config(app: "DanmuApp") -> dict[str, object]:
    return export_danmu_read_config(app.config)


def get_catalog() -> dict[str, object]:
    return {"providers": list_catalog_for_api()}


def get_voices(
    app: "DanmuApp",
    provider_id: str,
    model_id: str,
    *,
    force_refresh: bool = False,
) -> dict[str, object]:
    provider = canonical_tts_provider_id(provider_id)
    model = canonical_tts_model_id(provider, model_id.strip())
    if not provider or not model:
        raise HTTPException(status_code=400, detail="provider and model_id are required")
    try:
        model_descriptor = get_tts_manager().catalog.require_model(provider, model)
        if model_descriptor.status != "active":
            raise HTTPException(
                status_code=400,
                detail=tr("tts.error.unsupportedModel").format(model=model),
            )
        credentials = stored_tts_credentials(app.config, provider)
        voices = get_tts_manager().list_voices(
            provider,
            model,
            credentials=credentials,
            force_refresh=force_refresh,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"voices": [descriptor_to_dict(voice) for voice in voices]}


def save_config(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, object]:
    try:
        return app.apply_danmu_read_config(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def run_probe(app: "DanmuApp", payload: dict[str, Any] | None = None) -> dict[str, object]:
    overrides = normalize_probe_payload(payload)
    optional = {
        key: overrides.pop(key)
        for key in (
            "voice_override",
            "style_prompt_override",
            "emotion_override",
            "speed_override",
            "pitch_override",
            "volume_override",
            "credentials_override",
        )
        if key in overrides
    }
    probe = app.run_danmu_read_probe
    try:
        parameters = inspect.signature(probe).parameters.values()
    except (TypeError, ValueError):
        parameters = ()
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )
    accepted_names = {parameter.name for parameter in parameters}
    if accepts_kwargs:
        overrides.update(optional)
    else:
        overrides.update(
            {key: value for key, value in optional.items() if key in accepted_names}
        )
    return probe(**overrides)


def _pick_endpoint(body: dict[str, Any]) -> str:
    raw = body.get("endpoint")
    if raw is None:
        raw = body.get("custom_endpoint")
    return normalize_endpoint(str(raw or ""))


def _pick_model_id(body: dict[str, Any]) -> str:
    raw = body.get("model_id")
    if raw is None:
        raw = body.get("custom_model_id")
    return str(raw or "").strip()


def _reject_unsupported_custom_tts_payload(body: dict[str, Any]) -> None:
    provider = str(body.get("provider") or "").strip()
    endpoint = _pick_endpoint(body) if ("endpoint" in body or "custom_endpoint" in body) else ""
    if provider == "custom_openai":
        raise HTTPException(status_code=400, detail=_UNSUPPORTED_CUSTOM_TTS_MSG)
    canonical_provider = canonical_tts_provider_id(provider)
    if provider and get_tts_manager().catalog.get_provider(canonical_provider) is None:
        raise HTTPException(
            status_code=400,
            detail=tr("tts.error.unsupportedPlatform").format(platform=provider),
        )
    if endpoint:
        raise HTTPException(status_code=400, detail=_UNSUPPORTED_CUSTOM_TTS_MSG)

    model_id = _pick_model_id(body) if ("model_id" in body or "custom_model_id" in body) else ""
    if provider and model_id:
        try:
            validate_custom_tts_fields(provider, "", model_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _pick_credentials(body: dict[str, Any]) -> dict[str, str]:
    raw = body.get("credentials")
    if not isinstance(raw, dict):
        return {}
    picked: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        stripped = value.strip()
        if stripped == MASKED_API_KEY:
            continue
        picked[str(key)] = stripped
    return picked


def normalize_put_payload(body: dict[str, Any]) -> dict[str, Any]:
    _reject_unsupported_custom_tts_payload(body)
    out: dict[str, Any] = {}
    if "enabled" in body:
        out["enabled"] = bool(body.get("enabled"))
    if "interval_sec" in body:
        out["interval_sec"] = body.get("interval_sec")
    provider = str(body.get("provider") or "").strip()
    model_id = _pick_model_id(body) if ("model_id" in body or "custom_model_id" in body) else ""
    if "voice" in body:
        eff_provider = provider or TTS_PROVIDER_MIMO
        if provider in ("", "mimo"):
            eff_provider = TTS_PROVIDER_MIMO
        out["voice"] = normalize_tts_voice(
            str(body.get("voice") or ""),
            provider=eff_provider,
            model_id=model_id,
        )
    if "style_prompt" in body:
        out["style_prompt"] = str(body.get("style_prompt") or "")
    if "emotion" in body:
        out["emotion"] = str(body.get("emotion") or "")
    for field in ("speed", "pitch", "volume"):
        if field in body and body[field] is not None:
            out[field] = float(body[field])
    if "api_key" in body:
        key = str(body.get("api_key") or "").strip()
        if key == MASKED_API_KEY:
            pass
        else:
            out["api_key"] = key
    if body.get("clear_credentials"):
        out["clear_credentials"] = True
    credentials = _pick_credentials(body)
    if credentials:
        out["credentials"] = credentials
        if "api_key" not in out and credentials.get("api_key"):
            out["api_key"] = credentials["api_key"]
    if "provider" in body:
        out["provider"] = str(body.get("provider") or "").strip()
    if "endpoint" in body or "custom_endpoint" in body:
        out["endpoint"] = _pick_endpoint(body)
    if "model_id" in body or "custom_model_id" in body:
        out["model_id"] = _pick_model_id(body)
    return out


def normalize_probe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    overrides: dict[str, Any] = {
        "api_key_override": None,
        "provider_override": None,
        "endpoint_override": None,
        "model_id_override": None,
    }
    if not payload:
        return overrides
    _reject_unsupported_custom_tts_payload(payload)
    raw = payload.get("api_key")
    if isinstance(raw, str):
        key = raw.strip()
        if key and key != MASKED_API_KEY:
            overrides["api_key_override"] = key
    credentials = _pick_credentials(payload)
    if credentials:
        overrides["credentials_override"] = credentials
        if overrides["api_key_override"] is None and credentials.get("api_key"):
            overrides["api_key_override"] = credentials["api_key"]
    if "provider" in payload:
        provider = str(payload.get("provider") or "").strip()
        if provider in ("", "mimo", TTS_PROVIDER_MIMO):
            overrides["provider_override"] = ""
        elif get_tts_manager().catalog.get_provider(canonical_tts_provider_id(provider)) is not None:
            overrides["provider_override"] = provider
    if "endpoint" in payload or "custom_endpoint" in payload:
        overrides["endpoint_override"] = _pick_endpoint(payload)
    if "model_id" in payload or "custom_model_id" in payload:
        overrides["model_id_override"] = _pick_model_id(payload)
    if "voice" in payload:
        overrides["voice_override"] = str(payload.get("voice") or "").strip()
    if "style_prompt" in payload:
        overrides["style_prompt_override"] = str(payload.get("style_prompt") or "")
    if "emotion" in payload:
        overrides["emotion_override"] = str(payload.get("emotion") or "")
    for field in ("speed", "pitch", "volume"):
        if field in payload and payload[field] is not None:
            overrides[f"{field}_override"] = float(payload[field])
    return overrides


def safe_read_api(fn, *args, **kwargs):
    """只读 API：可在 HTTP 线程直接调用（不写入 Config / 不 emit Qt 信号）。"""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
