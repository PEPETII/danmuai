from app.providers.auth_resolver import resolve_auth
from app.providers.platform_registry import list_provider_definitions
from app.providers.registry import HOST_ENTRIES, match_host_entry


def test_builtin_registry_endpoints_have_unique_exact_host_routes():
    fragments = [entry.fragment for entry in HOST_ENTRIES]

    assert len(fragments) == len(set(fragments))
    for definition in list_provider_definitions():
        if not definition.endpoint.default_url:
            continue
        entry = match_host_entry(definition.endpoint.default_url)
        assert entry is not None
        assert entry.provider_id == definition.id
        assert entry.transport == ("doubao" if definition.endpoint.api_mode == "doubao" else "openai")


def test_auth_resolution_keeps_secret_out_of_non_auth_metadata():
    secret = "sk-contract-secret-do-not-log"
    for definition in list_provider_definitions():
        resolved = resolve_auth(secret, definition.auth)
        assert secret in repr(resolved.headers) or secret in repr(resolved.query_params)
        assert secret not in repr(definition.to_export_dict())
        assert secret not in repr(definition.to_api_dict())


def test_openrouter_extra_headers_are_host_scoped():
    definitions = {item.id: item for item in list_provider_definitions()}
    openrouter = definitions["openrouter"]

    headers = dict(openrouter.auth.extra_headers)
    assert headers["X-Title"] == "DanmuAI"
    assert headers["HTTP-Referer"].startswith("https://")
    assert definitions["openai"].auth.extra_headers == ()
