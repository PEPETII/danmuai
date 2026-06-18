"""Provider registry, capabilities, and OpenAI-compat adapters."""



from app.providers.adapters.default_openai import DefaultOpenAIAdapter
from app.providers.adapters.mimo import MimoOpenAIAdapter
from app.providers.capabilities import (
    ProviderCapabilities,
    get_capabilities,
    get_capabilities_for_endpoint,
)
from app.providers.registry import (
    HOST_ENTRIES,
    guess_provider_from_endpoint,
    is_minimax_endpoint,
    match_host_entry,
    provider_extra_headers,
    resolve_api_transport,
)

_DEFAULT_ADAPTER = DefaultOpenAIAdapter()

_MIMO_ADAPTER = MimoOpenAIAdapter()





def get_openai_adapter(endpoint: str, api_mode: str = "") -> DefaultOpenAIAdapter | MimoOpenAIAdapter:

    provider_id = guess_provider_from_endpoint(endpoint, api_mode)

    if provider_id == "mimo":

        return _MIMO_ADAPTER

    return _DEFAULT_ADAPTER





__all__ = [

    "HOST_ENTRIES",

    "ProviderCapabilities",

    "get_capabilities",

    "get_capabilities_for_endpoint",

    "get_openai_adapter",

    "guess_provider_from_endpoint",

    "is_minimax_endpoint",

    "match_host_entry",

    "provider_extra_headers",

    "resolve_api_transport",

]

