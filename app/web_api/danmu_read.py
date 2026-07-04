"""读弹幕（MiMo TTS）专用 API；配置不经 PUT /api/config。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/danmu-read``：返回读弹幕配置（api_key 掩码）。
- ``PUT /api/danmu-read``：保存读弹幕配置（enabled/interval/voice/style_prompt/provider/endpoint/model_id/api_key）。
- ``POST /api/danmu-read/probe``：发送试听文本触发 TTS 合成 + 本地播放（不写入配置）。

注册方式：``app.web_api.routes`` 调用 ``register_danmu_read_routes(app, bridge, check_token)``。
所有写操作经 ``WebConsoleBridge.invoke_on_main`` 回到主线程，由 ``DanmuReadService.apply_config`` 落地。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from app.application.config_service import MASKED_API_KEY
from app.danmu_read_service import export_danmu_read_config
from app.translations import tr
from app.model_providers import normalize_endpoint
from app.tts_catalog import list_catalog_for_api
from app.tts_providers import (
    TTS_PROVIDER_DASHSCOPE_QWEN,
    TTS_PROVIDER_MIMO,
    _reject_removed_doubao_tts,
    normalize_tts_voice,
)

_UNSUPPORTED_CUSTOM_TTS_MSG = tr("tts.unsupportedCustom")
_UNSUPPORTED_DOUBAO_TTS_MSG = tr("tts.unsupportedDoubao")

if TYPE_CHECKING:
    from main import DanmuApp


def get_config(app: "DanmuApp") -> dict[str, object]:
    return export_danmu_read_config(app.config)


def get_catalog() -> dict[str, object]:
    return {"providers": list_catalog_for_api()}


def save_config(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, object]:
    try:
        return app.apply_danmu_read_config(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def run_probe(app: "DanmuApp", payload: dict[str, Any] | None = None) -> dict[str, object]:
    overrides = normalize_probe_payload(payload)
    return app.run_danmu_read_probe(**overrides)


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
    try:
        _reject_removed_doubao_tts(provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if provider == "custom_openai":
        raise HTTPException(status_code=400, detail=_UNSUPPORTED_CUSTOM_TTS_MSG)
    if endpoint and provider != TTS_PROVIDER_DASHSCOPE_QWEN:
        raise HTTPException(status_code=400, detail=_UNSUPPORTED_CUSTOM_TTS_MSG)


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
    if "api_key" in body:
        key = str(body.get("api_key") or "").strip()
        if key and key != MASKED_API_KEY:
            out["api_key"] = key
    if "provider" in body:
        out["provider"] = str(body.get("provider") or "").strip()
    if "endpoint" in body or "custom_endpoint" in body:
        out["endpoint"] = _pick_endpoint(body)
    if "model_id" in body or "custom_model_id" in body:
        out["model_id"] = _pick_model_id(body)
    return out


def normalize_probe_payload(payload: dict[str, Any] | None) -> dict[str, str | None]:
    overrides: dict[str, str | None] = {
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
    if "provider" in payload:
        provider = str(payload.get("provider") or "").strip()
        if provider in ("", "mimo", TTS_PROVIDER_MIMO):
            overrides["provider_override"] = ""
        elif provider == "doubao":
            raise HTTPException(status_code=400, detail=_UNSUPPORTED_DOUBAO_TTS_MSG)
        elif provider == TTS_PROVIDER_DASHSCOPE_QWEN:
            overrides["provider_override"] = provider
        else:
            raise HTTPException(status_code=400, detail=_UNSUPPORTED_CUSTOM_TTS_MSG)
    if "endpoint" in payload or "custom_endpoint" in payload:
        overrides["endpoint_override"] = _pick_endpoint(payload)
    if "model_id" in payload or "custom_model_id" in payload:
        overrides["model_id_override"] = _pick_model_id(payload)
    return overrides


def safe_read_api(fn, *args, **kwargs):
    """只读 API：可在 HTTP 线程直接调用（不写入 Config / 不 emit Qt 信号）。"""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
