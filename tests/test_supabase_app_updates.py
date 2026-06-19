"""Supabase app_updates reader for backend update metadata."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from app.supabase_app_updates import (
    AppUpdateFetchResult,
    AppUpdateRemote,
    clear_app_update_cache,
    fetch_app_update,
    fetch_app_update_result,
)
from app.supabase_config import SupabaseCredentials


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_app_update_cache()
    yield
    clear_app_update_cache()


def test_fetch_app_update_parses_enabled_row():
    creds = SupabaseCredentials(
        url="https://example.supabase.co",
        anon_key="anon-test-key",
    )
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = [
        {
            "latest_version": "0.4.0",
            "release_url": "https://updates.example/DanmuAI-Setup.exe",
            "enabled": True,
            "message": "New build",
            "updated_at": "2026-06-13T00:00:00Z",
        }
    ]
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response

    with patch("app.supabase_app_updates.get_supabase_credentials", return_value=creds):
        with patch("app.supabase_app_updates.httpx.Client", return_value=client):
            row = fetch_app_update(force_refresh=True)

    assert row == AppUpdateRemote(
        latest_version="0.4.0",
        release_url="https://updates.example/DanmuAI-Setup.exe",
        message="New build",
    )
    client.get.assert_called_once()
    called_url = client.get.call_args.args[0]
    assert called_url.startswith("https://example.supabase.co/rest/v1/app_updates")
    assert "enabled=eq.true" in called_url


def test_fetch_app_update_result_marks_fresh_after_remote_success():
    creds = SupabaseCredentials(
        url="https://example.supabase.co",
        anon_key="anon-test-key",
    )
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = [
        {
            "latest_version": "0.4.0",
            "release_url": "https://updates.example/DanmuAI-Setup.exe",
            "enabled": True,
            "message": "New build",
            "updated_at": "2026-06-13T00:00:00Z",
        }
    ]
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response

    with patch("app.supabase_app_updates.get_supabase_credentials", return_value=creds):
        with patch("app.supabase_app_updates.httpx.Client", return_value=client):
            result = fetch_app_update_result(force_refresh=True)

    assert result == AppUpdateFetchResult(
        update=AppUpdateRemote(
            latest_version="0.4.0",
            release_url="https://updates.example/DanmuAI-Setup.exe",
            message="New build",
        ),
        cache_state="fresh",
        cache_age_sec=0.0,
    )


def test_fetch_app_update_returns_none_when_unconfigured():
    with patch("app.supabase_app_updates.get_supabase_credentials", return_value=None):
        assert fetch_app_update(force_refresh=True) is None


def test_fetch_app_update_result_returns_cache_hit_within_ttl():
    creds = SupabaseCredentials(url="https://example.supabase.co", anon_key="key")
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = [
        {
            "latest_version": "0.4.0",
            "release_url": "https://updates.example/setup.exe",
            "enabled": True,
            "message": "",
            "updated_at": "2026-06-13T00:00:00Z",
        }
    ]
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response

    with patch("app.supabase_app_updates.get_supabase_credentials", return_value=creds):
        with patch("app.supabase_app_updates.httpx.Client", return_value=client):
            first = fetch_app_update_result(force_refresh=True)
            second = fetch_app_update_result()

    assert first.update is not None
    assert first.cache_state == "fresh"
    assert second.update == first.update
    assert second.cache_state == "cache_hit"
    assert second.cache_age_sec is not None
    assert second.cache_age_sec >= 0.0
    assert client.get.call_count == 1


def test_fetch_app_update_uses_cache_until_force_refresh():
    creds = SupabaseCredentials(url="https://example.supabase.co", anon_key="key")
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = [
        {
            "latest_version": "0.4.0",
            "release_url": "https://updates.example/setup.exe",
            "enabled": True,
            "message": "",
            "updated_at": "2026-06-13T00:00:00Z",
        }
    ]
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = response

    with patch("app.supabase_app_updates.get_supabase_credentials", return_value=creds):
        with patch("app.supabase_app_updates.httpx.Client", return_value=client):
            first = fetch_app_update(force_refresh=True)
            second = fetch_app_update()
            third = fetch_app_update(force_refresh=True)

    assert first is not None
    assert second == first
    assert third is not None
    assert client.get.call_count == 2


def test_fetch_app_update_result_returns_stale_fallback_on_http_error():
    creds = SupabaseCredentials(url="https://example.supabase.co", anon_key="key")
    ok_response = MagicMock()
    ok_response.raise_for_status = MagicMock()
    ok_response.json.return_value = [
        {
            "latest_version": "0.4.0",
            "release_url": "https://updates.example/setup.exe",
            "enabled": True,
            "message": "",
            "updated_at": "2026-06-13T00:00:00Z",
        }
    ]
    client_ok = MagicMock()
    client_ok.__enter__.return_value = client_ok
    client_ok.get.return_value = ok_response

    client_fail = MagicMock()
    client_fail.__enter__.return_value = client_fail
    client_fail.get.side_effect = httpx.ConnectError("offline")

    with patch("app.supabase_app_updates.get_supabase_credentials", return_value=creds):
        with patch("app.supabase_app_updates.httpx.Client", return_value=client_ok):
            cached = fetch_app_update_result(force_refresh=True)
        with patch("app.supabase_app_updates.httpx.Client", return_value=client_fail):
            stale = fetch_app_update_result(force_refresh=True)

    assert cached.update is not None
    assert stale.update == cached.update
    assert stale.cache_state == "stale_fallback"
    assert stale.cache_age_sec is not None
    assert stale.cache_age_sec >= 0.0


def test_fetch_app_update_result_returns_miss_when_http_error_without_cache():
    creds = SupabaseCredentials(url="https://example.supabase.co", anon_key="key")
    client_fail = MagicMock()
    client_fail.__enter__.return_value = client_fail
    client_fail.get.side_effect = httpx.ConnectError("offline")

    with patch("app.supabase_app_updates.get_supabase_credentials", return_value=creds):
        with patch("app.supabase_app_updates.httpx.Client", return_value=client_fail):
            result = fetch_app_update_result(force_refresh=True)

    assert result == AppUpdateFetchResult(
        update=None,
        cache_state="miss",
        cache_age_sec=None,
    )
