"""Protected model/provider resolution facade for the Web console."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Body, Header, HTTPException

from app.model_catalog import lookup_catalog_model
from app.providers.capability_resolver import resolve_capabilities
from app.providers.endpoint_resolver import resolve_api_family
from app.providers.platform_registry import get_provider_definition
from app.providers.registry import guess_provider_from_endpoint, resolve_api_transport
from app.web_api.auth import require_auth


def _capabilities_dict(caps, *, model_capabilities_unknown: bool = False) -> dict:
    return {
        "transport": caps.transport,
        "vision": None if model_capabilities_unknown else caps.vision,
        "mic_audio": caps.mic_audio,
        "thinking_param": caps.thinking_param,
        "thinking_param_style": caps.thinking_param_style,
        "supports_thinking": caps.supports_thinking,
        "text_input": caps.text_input,
        "image_input": None if model_capabilities_unknown else caps.image_input,
        "audio_input": caps.audio_input,
        "video_input": caps.video_input,
        "file_input": caps.file_input,
        "structured_output": caps.structured_output,
    }


def _endpoint_profile(definition, endpoint: str, api_family: str | None) -> dict:
    profile = definition.endpoint if definition is not None else None
    return {
        "base_url": endpoint,
        "api_mode": getattr(profile, "api_mode", None),
        "api_family": api_family,
        "exact_hosts": list(getattr(profile, "exact_hosts", ())),
        "path_prefix": getattr(profile, "path_prefix", None),
        "path_join_policy": getattr(profile, "path_join_policy", None),
        "status": getattr(profile, "status", "unknown"),
    }


def register_model_resolve_routes(app, check_token) -> None:
    @app.post("/api/model-api/resolve")
    @require_auth(check_token)
    def resolve_model_api(
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        del authorization
        endpoint = payload.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise HTTPException(status_code=400, detail={"code": "invalid_endpoint", "message": "endpoint is required"})
        parsed = urlparse(endpoint.strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_endpoint", "message": "endpoint must be an HTTP(S) URL with a hostname"},
            )

        endpoint = endpoint.strip()
        provider_id = payload.get("provider_id") or guess_provider_from_endpoint(
            endpoint, payload.get("api_mode") or ""
        )
        definition = get_provider_definition(provider_id)
        if definition is None:
            raise HTTPException(status_code=400, detail={"code": "unknown_provider", "provider_id": provider_id})

        transport = resolve_api_transport(endpoint, payload.get("api_mode") or "")
        api_family = resolve_api_family(
            transport=transport,
            profile=definition.endpoint,
            api_family=payload.get("api_family"),
        )
        if api_family is None:
            raise HTTPException(status_code=400, detail={"code": "unknown_api_family"})

        model_id = payload.get("model_id") or ""
        catalog_model = lookup_catalog_model(model_id) if model_id else None
        caps = resolve_capabilities(
            model_id, endpoint, payload.get("api_mode") or "", provider_id=provider_id
        )
        warnings = []
        model_capabilities_unknown = bool(model_id and catalog_model is None)
        if model_capabilities_unknown:
            warnings.append("unknown_model")
        if catalog_model is not None and catalog_model.supports_vision is None:
            warnings.append("unknown_vision_capability")
        return {
            "provider": definition.to_api_dict(),
            "provider_id": definition.id,
            "api_family": api_family,
            "endpoint_profile": _endpoint_profile(definition, endpoint, api_family),
            "model": catalog_model.to_dict() if catalog_model is not None else None,
            "capabilities": _capabilities_dict(
                caps, model_capabilities_unknown=model_capabilities_unknown
            ),
            "warnings": warnings,
        }
