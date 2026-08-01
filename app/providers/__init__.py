"""Provider registry, capabilities, and OpenAI-compat adapters."""

from app.providers.adapters.default_openai import DefaultOpenAIAdapter
from app.providers.adapters.mimo import MimoOpenAIAdapter
from app.providers.auth_resolver import build_auth_headers
from app.providers.capabilities import (
    ProviderCapabilities,
    get_capabilities,
    get_capabilities_for_endpoint,
)
from app.providers.capability_resolver import resolve_capabilities
from app.providers.endpoint_resolver import (
    API_FAMILY_OPENAI_CHAT,
    API_FAMILY_OPENAI_RESPONSES,
    extract_hostname,
    join_api_path,
)
from app.providers.registry import (
    HOST_ENTRIES,
    guess_provider_from_endpoint,
    is_minimax_endpoint,
    match_host_entry,
    provider_extra_headers,
    resolve_api_transport,
)
from app.providers.request_planner import GenerationRequest, PlannedHttpRequest, plan_http_request

_DEFAULT_ADAPTER = DefaultOpenAIAdapter()

_MIMO_ADAPTER = MimoOpenAIAdapter()





def get_openai_adapter(endpoint: str, api_mode: str = "") -> DefaultOpenAIAdapter | MimoOpenAIAdapter:

    provider_id = guess_provider_from_endpoint(endpoint, api_mode)

    if provider_id == "mimo":

        return _MIMO_ADAPTER

    return _DEFAULT_ADAPTER





__all__ = [
    "API_FAMILY_OPENAI_CHAT",
    "API_FAMILY_OPENAI_RESPONSES",
    "HOST_ENTRIES",
    "GenerationRequest",
    "PlannedHttpRequest",
    "ProviderCapabilities",
    "build_auth_headers",
    "extract_hostname",
    "get_capabilities",
    "get_capabilities_for_endpoint",
    "get_openai_adapter",
    "guess_provider_from_endpoint",
    "is_minimax_endpoint",
    "join_api_path",
    "match_host_entry",
    "plan_http_request",
    "provider_extra_headers",
    "resolve_api_transport",
    "resolve_capabilities",
]

