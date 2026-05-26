import sys
from types import SimpleNamespace

from app.hotkey import HotkeyManager


class FakeApp:
    def toggle(self):
        pass


def test_hotkey_noop_on_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    manager = HotkeyManager(FakeApp())

    manager.register("Ctrl+Shift+B")

    assert manager.hotkey_str == "ctrl+shift+b"
    assert manager._registered is False


def test_hotkey_uses_keyboard_backend_on_windows(monkeypatch):
    calls = []

    def add_hotkey(keys, callback):
        calls.append(("add", keys, callback))

    def remove_hotkey(keys):
        calls.append(("remove", keys))

    fake_keyboard = SimpleNamespace(add_hotkey=add_hotkey, remove_hotkey=remove_hotkey)
    monkeypatch.setitem(sys.modules, "keyboard", fake_keyboard)
    monkeypatch.setattr(sys, "platform", "win32")
    manager = HotkeyManager(FakeApp())

    manager.register("Ctrl+Shift+B")
    manager.unregister()

    assert calls[0][0:2] == ("add", "ctrl+shift+b")
    assert calls[1] == ("remove", "ctrl+shift+b")
