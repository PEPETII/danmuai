"""Read-only provider rules API for web settings UI."""

from __future__ import annotations

from app.model_providers import provider_rules_for_api, resolve_provider_for_ui


def register_provider_routes(app) -> None:
    @app.get("/api/provider-rules")
    def provider_rules():
        return provider_rules_for_api()

    @app.get("/api/provider-rules/resolve")
    def provider_rules_resolve(endpoint: str = "", api_mode: str = ""):
        return resolve_provider_for_ui(endpoint, api_mode)
