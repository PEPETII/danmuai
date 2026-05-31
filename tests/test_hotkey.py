from unittest.mock import MagicMock, patch

from app.hotkey import HotkeyManager
from PyQt6.QtWidgets import QApplication


def _ensure_qapp():
    return QApplication.instance() or QApplication([])


def _make_manager():
    _ensure_qapp()
    app = MagicMock()
    return HotkeyManager(app)


@patch("app.hotkey.keyboard.remove_hotkey")
@patch("app.hotkey.keyboard.add_hotkey")
def test_set_keys_removes_old_registered_hotkey(add_hotkey, remove_hotkey):
    manager = _make_manager()
    manager.register()

    assert add_hotkey.call_count == 1
    assert add_hotkey.call_args.args[0] == "ctrl+shift+b"
    assert manager._registered_hotkey_str == "ctrl+shift+b"

    manager.set_keys("Ctrl+Shift+X")

    remove_hotkey.assert_called_once_with("ctrl+shift+b")
    assert add_hotkey.call_args_list[-1].args[0] == "ctrl+shift+x"
    assert manager._registered_hotkey_str == "ctrl+shift+x"
    assert manager.hotkey_str == "ctrl+shift+x"


@patch("app.hotkey.keyboard.remove_hotkey")
@patch("app.hotkey.keyboard.add_hotkey")
def test_register_unregister_pair(add_hotkey, remove_hotkey):
    manager = _make_manager()
    manager.register()

    add_hotkey.assert_called_once()
    assert manager._registered is True

    manager.unregister()

    remove_hotkey.assert_called_once_with("ctrl+shift+b")
    assert manager._registered is False
    assert manager._registered_hotkey_str == ""


@patch("app.hotkey.keyboard.remove_hotkey")
@patch("app.hotkey.keyboard.add_hotkey")
def test_register_failure_leaves_no_registered_hotkey(add_hotkey, remove_hotkey):
    add_hotkey.side_effect = RuntimeError("hook failed")
    manager = _make_manager()

    manager.register()

    assert manager._registered is False
    assert manager._registered_hotkey_str == ""
    remove_hotkey.assert_not_called()


@patch("app.hotkey.keyboard.remove_hotkey")
@patch("app.hotkey.keyboard.add_hotkey")
def test_set_keys_noop_when_unchanged(add_hotkey, remove_hotkey):
    manager = _make_manager()
    manager.register()
    add_hotkey.reset_mock()
    remove_hotkey.reset_mock()

    manager.set_keys("Ctrl+Shift+B")

    add_hotkey.assert_not_called()
    remove_hotkey.assert_not_called()
