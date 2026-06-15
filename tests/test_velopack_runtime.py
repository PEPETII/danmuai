"""Velopack startup hook — source mode must skip."""

import sys
from unittest.mock import MagicMock, patch

import pytest


def test_run_startup_apply_skips_when_not_frozen():
    from app.velopack_runtime import run_startup_apply_if_needed

    with patch.object(sys, "frozen", False, create=True):
        run_startup_apply_if_needed()


def test_run_startup_apply_calls_velopack_when_frozen():
    from app import velopack_runtime

    mock_app = MagicMock()
    velopack_mod = MagicMock(App=MagicMock(return_value=mock_app))
    with patch.object(sys, "frozen", True, create=True):
        with patch.dict("sys.modules", {"velopack": velopack_mod}):
            with patch("app.startup_trace.log_startup"):
                velopack_runtime.run_startup_apply_if_needed()
    mock_app.run.assert_called_once()
    mock_app.on_before_uninstall_fast_callback.assert_called_once()


def test_run_startup_apply_skips_on_import_error_when_frozen():
    import builtins

    from app import velopack_runtime

    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "velopack":
            raise ImportError("no velopack")
        return real_import(name, *args, **kwargs)

    with patch.object(sys, "frozen", True, create=True):
        with patch("builtins.__import__", side_effect=_import):
            with patch("app.startup_trace.log_startup") as log:
                velopack_runtime.run_startup_apply_if_needed()
    assert any("velopack.skip" in str(c) for c in log.call_args_list)
