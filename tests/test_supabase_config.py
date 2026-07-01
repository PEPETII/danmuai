"""Supabase credential resolution for backend PostgREST reads."""

import pytest
from app.bundle_paths import project_root
from app.supabase_config import (
    SupabaseCredentials,
    _parse_supabase_config_js,
    get_supabase_credentials,
)


def test_parse_local_supabase_config_js_when_present():
    path = project_root() / "web" / "static" / "supabase-config.js"
    if not path.is_file():
        pytest.skip("supabase-config.js not present")
    creds = get_supabase_credentials()
    assert creds is not None
    assert isinstance(creds, SupabaseCredentials)
    assert creds.url.startswith("https://")
    assert creds.anon_key


def test_env_vars_override_config_file(monkeypatch):
    monkeypatch.setenv("DANMU_SUPABASE_URL", "https://env.example.supabase.co")
    monkeypatch.setenv("DANMU_SUPABASE_ANON_KEY", "env-anon-key")
    creds = get_supabase_credentials()
    assert creds is not None
    assert creds.url == "https://env.example.supabase.co"
    assert creds.anon_key == "env-anon-key"


def test_parse_js_empty_anon_key_returns_none():
    js = """
    window.DANMU_SUPABASE = {
      url: 'https://example.supabase.co',
      anonKey: '',
    };
    """
    assert _parse_supabase_config_js(js) is None


def test_parse_js_placeholder_returns_none():
    js = """
    window.DANMU_SUPABASE = {
      url: 'https://YOUR_PROJECT_REF.supabase.co',
      anonKey: 'some-key',
    };
    """
    assert _parse_supabase_config_js(js) is None


def test_get_credentials_partial_env_url_only_returns_none(monkeypatch):
    monkeypatch.setattr(
        "app.supabase_config.get_env",
        lambda name: "https://partial.example.supabase.co" if name == "DANMU_SUPABASE_URL" else "",
    )
    monkeypatch.setattr(
        "app.supabase_config.resource_path",
        lambda *parts: project_root() / "web" / "static" / "nonexistent-supabase-config.js",
    )
    assert get_supabase_credentials() is None


def test_get_credentials_partial_env_key_only_returns_none(monkeypatch):
    monkeypatch.setattr(
        "app.supabase_config.get_env",
        lambda name: "only-key" if name == "DANMU_SUPABASE_ANON_KEY" else "",
    )
    monkeypatch.setattr(
        "app.supabase_config.resource_path",
        lambda *parts: project_root() / "web" / "static" / "nonexistent-supabase-config.js",
    )
    assert get_supabase_credentials() is None


def test_get_credentials_empty_env_no_file(monkeypatch):
    monkeypatch.setattr(
        "app.supabase_config.get_env",
        lambda name: "",
    )
    monkeypatch.setattr(
        "app.supabase_config.resource_path",
        lambda *parts: project_root() / "web" / "static" / "nonexistent-supabase-config.js",
    )
    assert get_supabase_credentials() is None
