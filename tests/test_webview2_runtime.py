"""Tests for WebView2 runtime detection."""

from unittest.mock import MagicMock

from app import webview2_runtime


def test_non_windows_skips_check(monkeypatch):
    monkeypatch.setattr(webview2_runtime.sys, "platform", "linux")
    assert webview2_runtime.is_webview2_runtime_available() is True


def test_windows_registry_hit(monkeypatch):
    monkeypatch.setattr(webview2_runtime.sys, "platform", "win32")
    monkeypatch.setattr(webview2_runtime, "_registry_has_webview2_client", lambda: True)
    monkeypatch.setattr(webview2_runtime, "_webview2_exe_exists", lambda: False)
    assert webview2_runtime.is_webview2_runtime_available() is True


def test_windows_exe_fallback(monkeypatch):
    monkeypatch.setattr(webview2_runtime.sys, "platform", "win32")
    monkeypatch.setattr(webview2_runtime, "_registry_has_webview2_client", lambda: False)
    monkeypatch.setattr(webview2_runtime, "_webview2_exe_exists", lambda: True)
    assert webview2_runtime.is_webview2_runtime_available() is True


def test_windows_missing_runtime(monkeypatch):
    monkeypatch.setattr(webview2_runtime.sys, "platform", "win32")
    monkeypatch.setattr(webview2_runtime, "_registry_has_webview2_client", lambda: False)
    monkeypatch.setattr(webview2_runtime, "_webview2_exe_exists", lambda: False)
    assert webview2_runtime.is_webview2_runtime_available() is False


def test_registry_open_success(monkeypatch):
    opened: list[str] = []

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_open_key(root, path):
        opened.append(path)
        if "WOW6432Node" in path:
            raise OSError("missing")
        return FakeKey()

    fake_winreg = MagicMock()
    fake_winreg.HKEY_LOCAL_MACHINE = 1
    fake_winreg.OpenKey = fake_open_key
    monkeypatch.setitem(__import__("sys").modules, "winreg", fake_winreg)
    assert webview2_runtime._registry_has_webview2_client() is True
    assert opened


def test_webview2_exe_glob(monkeypatch, tmp_path):
    exe = tmp_path / "Microsoft" / "EdgeWebView" / "Application" / "109.0.1518.78" / "msedgewebview2.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert webview2_runtime._webview2_exe_exists() is True
