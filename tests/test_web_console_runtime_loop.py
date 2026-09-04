"""Windows uvicorn loop: source python main.py must use SelectorEventLoop."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from app.web_console_runtime import (
    run_uvicorn_asyncio,
    should_use_windows_selector_event_loop,
    windows_uvicorn_loop_factory,
)


def test_should_use_windows_selector_event_loop_only_on_win32():
    assert should_use_windows_selector_event_loop("win32") is True
    assert should_use_windows_selector_event_loop("linux") is False
    assert should_use_windows_selector_event_loop("darwin") is False


def test_run_uvicorn_locked_uses_loop_factory_without_frozen_gate():
    src = Path("app/web_console_runtime.py").read_text(encoding="utf-8")
    assert "run_uvicorn_asyncio(server._server.serve())" in src
    assert "set_event_loop_policy" not in src
    assert 'if is_frozen() and sys.platform == "win32":' not in src


@pytest.mark.skipif(sys.platform != "win32", reason="Selector vs Proactor is a Windows distinction")
def test_windows_uvicorn_loop_factory_is_selector_not_proactor():
    loop = windows_uvicorn_loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
        assert not isinstance(loop, asyncio.ProactorEventLoop)
    finally:
        loop.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Proactor 10054 only exists on Windows")
def test_run_uvicorn_asyncio_win32_uses_selector_loop():
    seen: dict[str, object] = {}

    async def _probe() -> None:
        loop = asyncio.get_running_loop()
        seen["is_selector"] = isinstance(loop, asyncio.SelectorEventLoop)
        seen["is_proactor"] = isinstance(loop, asyncio.ProactorEventLoop)

    run_uvicorn_asyncio(_probe(), platform="win32")
    assert seen["is_selector"] is True
    assert seen["is_proactor"] is False


@pytest.mark.skipif(sys.platform != "win32", reason="Default loop type is platform-specific")
def test_run_uvicorn_asyncio_non_windows_keeps_default_factory():
    seen: dict[str, object] = {}

    async def _probe() -> None:
        loop = asyncio.get_running_loop()
        seen["is_proactor"] = isinstance(loop, asyncio.ProactorEventLoop)

    run_uvicorn_asyncio(_probe(), platform="linux")
    assert seen["is_proactor"] is True
