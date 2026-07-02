"""Detect Microsoft Edge WebView2 runtime availability on Windows."""

from __future__ import annotations

import os
import sys
from pathlib import Path

WEBVIEW2_CLIENT_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_INSTALL_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

_REGISTRY_PATHS = (
    rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}",
    rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{WEBVIEW2_CLIENT_GUID}",
)


def _registry_has_webview2_client() -> bool:
    import winreg

    for path in _REGISTRY_PATHS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path):
                return True
        except OSError:
            continue
    return False


def _webview2_exe_exists() -> bool:
    program_dirs: list[Path] = []
    for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
        value = os.environ.get(env_name, "").strip()
        if value:
            program_dirs.append(Path(value))
    for base in program_dirs:
        matches = list(
            (base / "Microsoft" / "EdgeWebView" / "Application").glob("*/msedgewebview2.exe")
        )
        if matches:
            return True
    return False


def is_webview2_runtime_available() -> bool:
    """Return True when WebView2 is present or the platform does not require it."""
    if sys.platform != "win32":
        return True
    if _registry_has_webview2_client():
        return True
    return _webview2_exe_exists()
