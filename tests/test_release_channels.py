"""Release channel config and API."""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import release_channels, update_service
from app.release_channels import (
    LATEST_PUBLISHED_VERSION,
    R2_LATEST_INSTALLER_URL,
    UPDATE_FEED_URL,
)
from app.velopack_config import UPDATE_FEED_URL as VPK_FEED_URL
from app.web_api import update as update_api_mod


def test_release_channels_constants():
    d = release_channels.to_dict()
    assert d["github_releases_url"] == "https://github.com/PEPETII/danmuai/releases"
    assert d["quark_url"] == "https://pan.quark.cn/s/33bc4f23d1df"
    assert "夸克" in d["quark_share_text"]
    assert d["baidu_url"] == "https://pan.baidu.com/s/18GiqaUhpBw8w96-PpHU9Gw"
    assert d["baidu_extract_code"] == "1234"
    assert d["r2_latest_installer_url"] == R2_LATEST_INSTALLER_URL
    assert d["r2_latest_installer_url"] == (
        "https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe"
    )
    assert LATEST_PUBLISHED_VERSION
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


@pytest.mark.parametrize(
    "current,expected",
    [
        ("0.2.0", True),
        ("0.3.1", False),
        ("0.4.0", False),
    ],
)
def test_build_update_metadata_update_available(current, expected):
    meta = release_channels.build_update_metadata(current_version=current)
    assert meta["update_available"] is expected
    assert meta["latest_version"] == LATEST_PUBLISHED_VERSION


def test_build_update_metadata_merges_velopack_when_newer():
    vp = update_service.UpdateStatus(
        ok=True,
        frozen=True,
        current_version="0.3.0",
        latest_version="0.4.0",
        update_available=True,
    )
    meta = release_channels.build_update_metadata(
        current_version="0.3.0",
        velopack_status=vp,
    )
    assert meta["latest_version"] == "0.4.0"
    assert meta["update_available"] is True


def test_release_channels_api_route():
    api = FastAPI()

    @api.get("/api/update/channels")
    def _channels():
        return update_api_mod.get_release_channels()

    client = TestClient(api)
    res = client.get("/api/update/channels")
    assert res.status_code == 200
    body = res.json()
    for key in _METADATA_KEYS:
        assert key in body
    assert body["github_releases_url"].startswith("https://github.com/")
    assert body["baidu_extract_code"] == "1234"
    assert body["r2_latest_installer_url"] == R2_LATEST_INSTALLER_URL
    assert body["feed_url"] == UPDATE_FEED_URL


@pytest.mark.parametrize("frozen", [False, True])
def test_get_update_channels_never_calls_velopack_check(frozen):
    with patch.object(update_service, "get_status") as mock_status:
        with patch.object(update_service, "check_for_updates") as mock_check:
            mock_status.return_value = update_service.UpdateStatus(
                ok=True,
                frozen=frozen,
                current_version="0.3.0",
            )
            payload = update_api_mod.get_update_channels()
    mock_status.assert_not_called()
    mock_check.assert_not_called()
    assert payload["latest_version"] == LATEST_PUBLISHED_VERSION
