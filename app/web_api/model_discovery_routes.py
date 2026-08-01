"""Protected Web API for one-shot account model discovery."""

from __future__ import annotations

from typing import Callable

from fastapi import Header
from pydantic import BaseModel, Field

from app.providers.model_discovery import discover_models
from app.web_api.auth import require_auth

MAX_TTL_SECONDS = 3600.0


class ModelDiscoveryPayload(BaseModel):
    provider_id: str = Field(min_length=1)
    endpoint: str | None = None
    api_key: str = ""
    ttl_seconds: float = Field(default=300.0, ge=0, le=MAX_TTL_SECONDS)


def _serialize(result) -> dict:
    return {
        "status": result.status,
        "discovery_kind": result.discovery_kind,
        "source": result.source,
        "source_url": result.source_url,
        "request_url": result.request_url,
        "verified_at": result.verified_at,
        "fetched_at": result.fetched_at,
        "warnings": list(result.warnings),
        "models": [model.to_dict() for model in result.models],
    }


def register_model_discovery_routes(app, check_token: Callable) -> None:
    @app.post("/api/model-discovery")
    @require_auth(check_token)
    def post_model_discovery(
        body: ModelDiscoveryPayload,
        authorization: str | None = Header(default=None),
    ):
        result = discover_models(
            body.provider_id,
            body.api_key,
            endpoint=body.endpoint,
            ttl_seconds=body.ttl_seconds,
        )
        return _serialize(result)
