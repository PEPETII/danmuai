"""Supabase credential resolution for backend PostgREST reads."""

import pytest

from app.bundle_paths import project_root
from app.supabase_config import SupabaseCredentials, get_supabase_credentials


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
