"""Velopack update API and service — source mode contracts."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import update_service
from app.web_api.routes import register_web_routes
from tests.fakes import FakeConfig

_TEST_TOKEN = "Bearer test-token"


def _strict_check_token(authorization: str | None = None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    if authorization != _TEST_TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")


def _make_client():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()
    register_web_routes(app, bridge, _strict_check_token)
    return TestClient(app)


@pytest.fixture
def reset_update_state():
    with update_service._lock:
        update_service._state.clear()
        update_service._state.update(
            {
                "last_check": None,
                "pending_update": None,
                "last_error": None,
                "download_phase": "idle",
                "download_progress": 0,
                "package_size_bytes": 0,
                "download_thread": None,
            }
        )
    yield


def _mock_update_info(*, version="0.4.0", full_size=50_000_000, delta_sizes=None):
    info = MagicMock()
    full = MagicMock()
    full.Version = version
    full.Size = full_size
    info.TargetFullRelease = full
    if delta_sizes:
        info.DeltasToTarget = [MagicMock(Size=size) for size in delta_sizes]
    else:
        info.DeltasToTarget = []
    return info


_PROGRESS_FIELD_NAMES = (
    "download_phase",
    "download_progress",
    "package_size_bytes",
    "downloaded_bytes",
    "downloading",
)


def test_update_status_source_mode():
    st = update_service.get_status()
    d = st.to_dict()
    assert d["ok"] is True
    assert d["frozen"] is False
    assert d["current_version"]
    for key in _PROGRESS_FIELD_NAMES:
        assert key in d
    assert d["download_phase"] == "idle"
    assert d["downloading"] is False


def test_update_check_source_mode():
    st = update_service.check_for_updates()
    d = st.to_dict()
    assert d["frozen"] is False
    assert d["ok"] is False
    assert d["error"] == "not_frozen"


def test_update_check_frozen_mock():
    mock_mgr = MagicMock()
    mock_mgr.get_current_version.return_value = "0.3.0"
    mock_mgr.check_for_updates.return_value = None
    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            st = update_service.check_for_updates()
    assert st.ok is True
    assert st.update_available is False


def test_check_frozen_returns_package_size(reset_update_state):
    info = _mock_update_info(full_size=12_345_678)
    mock_mgr = MagicMock()
    mock_mgr.get_current_version.return_value = "0.3.0"
    mock_mgr.check_for_updates.return_value = info
    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            st = update_service.check_for_updates()
    assert st.ok is True
    assert st.update_available is True
    assert st.package_size_bytes == 12_345_678
    assert st.latest_version == "0.4.0"


def test_check_frozen_prefers_delta_package_size(reset_update_state):
    info = _mock_update_info(full_size=50_000_000, delta_sizes=[4_000_000, 1_000_000])
    mock_mgr = MagicMock()
    mock_mgr.get_current_version.return_value = "0.3.0"
    mock_mgr.check_for_updates.return_value = info
    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            st = update_service.check_for_updates()
    assert st.package_size_bytes == 5_000_000


def test_download_starts_background_and_reports_progress(reset_update_state):
    info = _mock_update_info(full_size=1_000_000)

    def fake_download(_update_info, progress_callback=None):
        if progress_callback:
            progress_callback(50)

    mock_mgr = MagicMock()
    mock_mgr.get_current_version.return_value = "0.3.0"
    mock_mgr.get_update_pending_restart.return_value = False
    mock_mgr.download_updates.side_effect = fake_download

    class ImmediateThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            if self._target:
                self._target(*self._args)

        def is_alive(self):
            return False

        def join(self, timeout=None):
            return None

    with update_service._lock:
        update_service._state["pending_update"] = info

    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            with patch("app.update_service.threading.Thread", ImmediateThread):
                started = update_service.download_updates(wait=True)

    assert started.ok is True
    assert started.download_ready is True
    assert started.download_phase == "ready"
    assert started.download_progress == 100
    assert started.downloaded_bytes == 1_000_000


def test_download_returns_in_progress_without_wait(reset_update_state):
    info = _mock_update_info(full_size=2_000_000)
    mock_mgr = MagicMock()
    mock_mgr.get_current_version.return_value = "0.3.0"
    mock_mgr.get_update_pending_restart.return_value = False

    class DeferredThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target = target
            self._args = args
            self._alive = False

        def start(self):
            self._alive = True

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            self._alive = False

    started_threads: list[DeferredThread] = []
    original_init = DeferredThread.__init__

    def tracking_init(self, target=None, args=(), daemon=None):
        original_init(self, target=target, args=args, daemon=daemon)
        started_threads.append(self)

    DeferredThread.__init__ = tracking_init

    with update_service._lock:
        update_service._state["pending_update"] = info
        update_service._state["download_phase"] = "idle"

    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            with patch("app.update_service.threading.Thread", DeferredThread):
                started = update_service.download_updates()

    assert started.ok is True
    assert started.downloading is True
    assert started.download_phase == "downloading"
    assert len(started_threads) == 1


def test_download_does_not_start_second_thread(reset_update_state):
    info = _mock_update_info(full_size=1_000_000)
    mock_mgr = MagicMock()
    mock_mgr.get_current_version.return_value = "0.3.0"
    mock_mgr.get_update_pending_restart.return_value = False

    started_threads: list[object] = []

    class DeferredThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target = target
            self._args = args
            self._alive = False

        def start(self):
            self._alive = True
            started_threads.append(self)

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            self._alive = False

    with update_service._lock:
        update_service._state["pending_update"] = info
        update_service._state["download_phase"] = "downloading"

    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            with patch("app.update_service.threading.Thread", DeferredThread):
                st = update_service.download_updates()

    assert st.downloading is True
    assert started_threads == []


def test_update_status_api_includes_progress_fields():
    client = _make_client()
    res = client.get("/api/update/status", headers={"Authorization": _TEST_TOKEN})
    assert res.status_code == 200
    body = res.json()
    for key in _PROGRESS_FIELD_NAMES:
        assert key in body


def test_update_channels_public_without_token():
    client = _make_client()
    res = client.get("/api/update/channels")
    assert res.status_code == 200
    body = res.json()
    assert "github_releases_url" in body
    assert "current_version" in body
    assert "latest_version" in body
    assert "update_available" in body
    assert "release_url" in body
    assert "feed_url" in body
    assert "message" in body
    assert "cache_state" in body
    assert "from_cache" in body
    assert "stale" in body
    assert "cache_age_sec" in body
    assert isinstance(body["update_available"], bool)
    assert isinstance(body["from_cache"], bool)
    assert isinstance(body["stale"], bool)


def test_update_channels_readonly_never_calls_velopack_check():
    from app import release_channels
    from app.web_api import update as update_api
    from app.supabase_app_updates import AppUpdateFetchResult, AppUpdateRemote

    remote = AppUpdateFetchResult(
        update=AppUpdateRemote(
            latest_version="0.4.0",
            release_url="https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe",
            message="",
        ),
        cache_state="fresh",
        cache_age_sec=0.0,
    )
    with patch.object(update_api, "fetch_app_update_result", return_value=remote):
        with patch.object(update_service, "get_status") as mock_status:
            with patch.object(update_service, "check_for_updates") as mock_check:
                client = _make_client()
                res = client.get("/api/update/channels")
    mock_status.assert_not_called()
    mock_check.assert_not_called()
    assert res.status_code == 200
    body = res.json()
    assert body["latest_version"] == "0.4.0"
    assert body["cache_state"] == "fresh"
    assert body["from_cache"] is False
    assert body["stale"] is False


@pytest.mark.parametrize("frozen", [False, True])
def test_update_channels_frozen_still_skips_velopack_check(frozen):
    from app.web_api import update as update_api
    from app.supabase_app_updates import AppUpdateFetchResult
    from app.version import __version__

    with patch.object(
        update_api,
        "fetch_app_update_result",
        return_value=AppUpdateFetchResult(update=None, cache_state="miss", cache_age_sec=None),
    ):
        with patch.object(update_service, "get_status") as mock_status:
            with patch.object(update_service, "check_for_updates") as mock_check:
                mock_status.return_value = update_service.UpdateStatus(
                    ok=True,
                    frozen=frozen,
                    current_version="0.3.0",
                )
                client = _make_client()
                res = client.get("/api/update/channels")
    mock_check.assert_not_called()
    assert res.status_code == 200
    body = res.json()
    assert body["latest_version"] == __version__
    assert body["cache_state"] == "miss"
    assert body["stale"] is False


def test_update_channels_exposes_stale_fallback_when_network_failed():
    from app.web_api import update as update_api
    from app.supabase_app_updates import AppUpdateFetchResult, AppUpdateRemote

    stale_remote = AppUpdateFetchResult(
        update=AppUpdateRemote(
            latest_version="0.4.1",
            release_url="https://updates.qiaoqiao.buzz/downloads/DanmuAI-Setup.exe",
            message="cached",
        ),
        cache_state="stale_fallback",
        cache_age_sec=42.5,
    )
    with patch.object(update_api, "fetch_app_update_result", return_value=stale_remote):
        client = _make_client()
        res = client.get("/api/update/channels")

    assert res.status_code == 200
    body = res.json()
    assert body["latest_version"] == "0.4.1"
    assert body["cache_state"] == "stale_fallback"
    assert body["from_cache"] is True
    assert body["stale"] is True
    assert body["cache_age_sec"] == 42.5


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/update/status"),
        ("post", "/api/update/check"),
        ("post", "/api/update/download"),
        ("post", "/api/update/restart"),
    ],
)
def test_update_routes_reject_missing_token(method, path):
    client = _make_client()
    res = getattr(client, method)(path)
    assert res.status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/update/status"),
        ("post", "/api/update/check"),
        ("post", "/api/update/download"),
        ("post", "/api/update/restart"),
    ],
)
def test_update_routes_reject_wrong_token(method, path):
    client = _make_client()
    res = getattr(client, method)(
        path,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/update/status"),
        ("post", "/api/update/check"),
        ("post", "/api/update/download"),
        ("post", "/api/update/restart"),
    ],
)
def test_update_routes_accept_valid_token(method, path):
    client = _make_client()
    res = getattr(client, method)(
        path,
        headers={"Authorization": _TEST_TOKEN},
    )
    assert res.status_code == 200
