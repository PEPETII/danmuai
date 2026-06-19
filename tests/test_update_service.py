"""update_service — thread-safety and source-mode contracts."""

from unittest.mock import MagicMock, patch

import pytest
from app import update_service


@pytest.fixture
def reset_state():
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


# ── get_status() source-mode ──────────────────────────────────────


def test_get_status_source_mode(reset_state):
    """In source (non-frozen) mode, get_status() returns ok=True, frozen=False."""
    with patch.object(update_service, "_is_frozen", return_value=False):
        st = update_service.get_status()
    assert st.ok is True
    assert st.frozen is False


# ── get_status() snapshot consistency ─────────────────────────────


def test_get_status_snapshot_consistency(reset_state):
    """get_status() must return a consistent snapshot: download_ready and
    update_available should never contradict each other."""
    info = MagicMock()
    info.target_version = "0.4.0"
    info.version = "0.4.0"

    with update_service._lock:
        update_service._state["pending_update"] = info
        update_service._state["download_phase"] = "idle"

    mock_mgr = MagicMock()
    mock_mgr.get_update_pending_restart.return_value = False
    mock_mgr.get_current_version.return_value = "0.3.3"

    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            st = update_service.get_status()

    # idle phase with pending_update → update_available=True, download_ready=False
    assert st.update_available is True
    assert st.download_ready is False


def test_get_status_download_ready_not_also_available(reset_state):
    """When download is ready, update_available should be False (not both True)."""
    info = MagicMock()
    info.target_version = "0.4.0"
    info.version = "0.4.0"

    with update_service._lock:
        update_service._state["pending_update"] = info
        update_service._state["download_phase"] = "ready"

    mock_mgr = MagicMock()
    mock_mgr.get_update_pending_restart.return_value = False
    mock_mgr.get_current_version.return_value = "0.3.3"

    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            st = update_service.get_status()

    # ready phase → download_ready=True, update_available=False
    assert st.download_ready is True
    assert st.update_available is False


# ── _enrich_status with snapshot ───────────────────────────────────


def test_enrich_status_with_explicit_snapshot(reset_state):
    """_enrich_status(snapshot=...) should use the provided snapshot
    instead of acquiring the lock again."""
    status = update_service.UpdateStatus(ok=True, frozen=True)
    snapshot = {
        "download_phase": "downloading",
        "download_progress": 42,
        "package_size_bytes": 1_000_000,
        "last_error": None,
    }
    result = update_service._enrich_status(status, snapshot)
    assert result.download_phase == "downloading"
    assert result.download_progress == 42
    assert result.downloading is True


def test_enrich_status_default_snapshot(reset_state):
    """_enrich_status() without snapshot should take a fresh snapshot via _take_snapshot."""
    with update_service._lock:
        update_service._state["download_phase"] = "idle"
        update_service._state["download_progress"] = 0
        update_service._state["package_size_bytes"] = 0
        update_service._state["last_error"] = None

    status = update_service.UpdateStatus(ok=True, frozen=True)
    result = update_service._enrich_status(status)
    assert result.download_phase == "idle"
    assert result.downloading is False
