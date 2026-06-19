"""Release channel config and API."""

from unittest.mock import patch

import pytest
from app import release_channels
from app.release_channels import R2_LATEST_INSTALLER_URL, UPDATE_FEED_URL
from app.supabase_app_updates import AppUpdateRemote, clear_app_update_cache
from app.velopack_config import UPDATE_FEED_URL as VPK_FEED_URL
from app.version import __version__
from app.web_api import update as update_api_mod
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_app_update_cache():
    clear_app_update_cache()
    yield
    clear_app_update_cache()


def test_release_channels_constants():
    d = release_channels.to_dict()
    assert d["github_releases_url"] == "https://github.com/PEPETII/danmuai/releases"
    assert d["quark_url"] == "https://pan.quark.cn/s/33bc4f23d1df"
    assert "夸克" in d["quark_share_text"]
    assert d["baidu_url"] == "https://pan.baidu.com/s/18GiqaUhpBw8w96-PpHU9Gw"
    assert d["baidu_extract_code"] == "1234"
    assert d["r2_latest_installer_url"] == R2_LATEST_INSTALLER_URL
    assert UPDATE_FEED_URL == VPK_FEED_URL


_METADATA_KEYS = (
    "current_version",
    "latest_version",
    "update_available",
    "release_url",
    "feed_url",
    "message",
    "github_releases_url",
    "quark_url",
    "quark_share_text",
    "baidu_url",
    "baidu_extract_code",
    "r2_latest_installer_url",
)


def test_build_update_metadata_returns_all_keys():
    meta = release_channels.build_update_metadata(current_version="0.3.0")
    for key in _METADATA_KEYS:
        assert key in meta


def test_resolve_published_update_uses_supabase_row():
    remote = AppUpdateRemote(
        latest_version="0.4.0",
        release_url="https://example.com/DanmuAI-Setup.exe",
        message="Security patch",
    )
    with patch.object(release_channels, "fetch_app_update", return_value=remote):
        latest, release_url, message = release_channels.resolve_published_update()
    assert latest == "0.4.0"
    assert release_url == "https://example.com/DanmuAI-Setup.exe"
    assert message == "Security patch"


def test_resolve_published_update_offline_fallback_matches_local_version():
    with patch.object(release_channels, "fetch_app_update", return_value=None):
        latest, release_url, message = release_channels.resolve_published_update()
    assert latest == __version__
    assert release_url == R2_LATEST_INSTALLER_URL
    assert message == ""


@pytest.mark.parametrize(
    "current,remote_latest,expected",
    [
        ("0.2.0", "0.4.0", True),
        ("0.4.0", "0.4.0", False),
        ("0.5.0", "0.4.0", False),
    ],
)
def test_build_update_metadata_update_available(current, remote_latest, expected):
    remote = AppUpdateRemote(
        latest_version=remote_latest,
        release_url=R2_LATEST_INSTALLER_URL,
        message="",
    )
    with patch.object(release_channels, "fetch_app_update", return_value=remote):
        meta = release_channels.build_update_metadata(current_version=current)
    assert meta["update_available"] is expected
    assert meta["latest_version"] == remote_latest


def test_build_update_metadata_offline_no_false_prompt():
    with patch.object(release_channels, "fetch_app_update", return_value=None):
        meta = release_channels.build_update_metadata(current_version=__version__)
    assert meta["latest_version"] == __version__
    assert meta["update_available"] is False


def test_release_channels_api_route():
    remote = AppUpdateRemote(
        latest_version="0.4.0",
        release_url=R2_LATEST_INSTALLER_URL,
        message="",
    )
    api = FastAPI()

    @api.get("/api/update/channels")
    def _channels():
        return update_api_mod.get_release_channels()

    with patch.object(release_channels, "fetch_app_update", return_value=remote):
        client = TestClient(api)
        res = client.get("/api/update/channels")
    assert res.status_code == 200
    body = res.json()
    for key in _METADATA_KEYS:
        assert key in body
    assert body["latest_version"] == "0.4.0"
    assert body["github_releases_url"].startswith("https://github.com/")
    assert body["baidu_extract_code"] == "1234"
    assert body["feed_url"] == UPDATE_FEED_URL


def test_get_update_channels_never_calls_velopack_check():
    from app import update_service

    with patch.object(release_channels, "fetch_app_update", return_value=None):
        with patch.object(update_service, "get_status") as mock_status:
            with patch.object(update_service, "check_for_updates") as mock_check:
                payload = update_api_mod.get_update_channels()
    mock_status.assert_not_called()
    mock_check.assert_not_called()
    assert payload["latest_version"] == __version__
