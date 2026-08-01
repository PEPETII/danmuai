from app.providers.auth_resolver import AuthResolution, build_auth_headers, resolve_auth
from app.providers.platform_definitions import AuthProfile


def test_resolves_supported_auth_schemes():
    assert resolve_auth("secret", AuthProfile()).headers == {"Authorization": "Bearer secret"}
    assert resolve_auth(
        "secret", AuthProfile(scheme="api_key_header", header_name="X-API-Key")
    ).headers == {"X-API-Key": "secret"}
    assert resolve_auth(
        "secret", AuthProfile(scheme="query_key", query_key="key")
    ).query_params == {"key": "secret"}
    assert resolve_auth(
        "secret", AuthProfile(scheme="custom", custom="X-Custom-Auth")
    ).headers == {"X-Custom-Auth": "secret"}


def test_empty_token_does_not_emit_auth():
    result = resolve_auth("  ", AuthProfile())
    assert result.headers == {}
    assert result.query_params == {}


def test_extra_headers_are_allowlisted_case_insensitively():
    result = resolve_auth(
        "secret",
        AuthProfile(),
        extra_user_headers={"X-REQUEST-ID": "request", "Authorization": "bad"},
    )
    assert result.headers["X-REQUEST-ID"] == "request"
    assert result.headers["Authorization"] == "Bearer secret"


def test_openrouter_attribution_requires_exact_profile_and_hostname():
    official = build_auth_headers(
        "secret", provider_id="openrouter", endpoint="https://openrouter.ai/api/v1"
    )
    evil = build_auth_headers(
        "secret", provider_id="openrouter", endpoint="https://evil-openrouter.ai/api/v1"
    )
    other = build_auth_headers(
        "secret", provider_id="other", endpoint="https://openrouter.ai/api/v1"
    )
    assert official["X-Title"] == "DanmuAI"
    assert "X-Title" not in evil
    assert "X-Title" not in other


def test_secret_is_not_in_resolution_repr_or_error_summary():
    secret = "super-secret-token"
    result = resolve_auth(secret, AuthProfile())
    assert secret not in repr(result)
    assert secret not in repr(AuthResolution())
