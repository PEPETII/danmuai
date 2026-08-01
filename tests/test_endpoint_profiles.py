from app.providers.endpoint_resolver import (
    API_FAMILY_ANTHROPIC_MESSAGES,
    API_FAMILY_OPENAI_CHAT,
    API_FAMILY_OPENAI_RESPONSES,
    hostname_matches,
    join_api_path,
    resolve_api_family,
)
from app.providers.platform_definitions import EndpointProfile


def test_profiles_join_paths_and_serialize_metadata():
    profile = EndpointProfile("https://x.test/v1beta/openai", "openai-compatible", api_family=API_FAMILY_OPENAI_CHAT)
    assert join_api_path(profile.default_url, profile.api_family) == "https://x.test/v1beta/openai/chat/completions"
    assert profile.path_join_policy == "preserve_base_path"


def test_join_supports_anthropic_and_strips_only_complete_suffix():
    assert join_api_path("https://x.test/v1", API_FAMILY_ANTHROPIC_MESSAGES) == "https://x.test/v1/messages"
    assert join_api_path("https://x.test/api/v3/chat/completions", API_FAMILY_OPENAI_RESPONSES) == "https://x.test/api/v3/responses"
    assert join_api_path("https://x.test/v1/messages-extra", API_FAMILY_OPENAI_CHAT).endswith("/v1/messages-extra/chat/completions")


def test_query_fragment_are_profile_controlled_and_unknown_is_safe():
    profile = EndpointProfile("https://x.test/v1?key=1#frag", "openai-compatible", api_family=API_FAMILY_OPENAI_RESPONSES, preserve_query=True, preserve_fragment=True)
    assert join_api_path(profile.default_url, profile.api_family, profile=profile) == "https://x.test/v1/responses?key=1#frag"
    assert join_api_path("https://x.test/v1", "unknown") is None
    assert resolve_api_family(transport="unknown") is None


def test_family_explicit_metadata_precedes_transport_and_host_attacks_rejected():
    assert resolve_api_family(transport="doubao", api_family=API_FAMILY_ANTHROPIC_MESSAGES) == API_FAMILY_ANTHROPIC_MESSAGES
    assert hostname_matches("openrouter.ai", "https://openrouter.ai:443/v1")
    assert not hostname_matches("openrouter.ai", "https://evil-openrouter.ai/v1")
    assert not hostname_matches("openrouter.ai", "https://openrouter.ai.evil.test/v1")
