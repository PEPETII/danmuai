"""Global hotkey registration via ``keyboard`` library.

线程模型：
- ``keyboard.add_hotkey`` 回调在 ``keyboard`` 内部线程（不是主线程）；直接修改 Qt
  对象会抛「QObject: Cannot create children for a parent that is in a different thread」。
- 引入 ``_ToggleBridge(QObject) + pyqtSignal``：回调 emit signal，Qt 自动把
  signal 投递到 ``self.app`` 所在的主线程，再触发 ``app.toggle``。
- ``_registered_hotkey_str`` 记录最近一次成功注册的 key 串，``unregister`` 时按它反注册；
  **不**用 ``self._hotkey_str`` 是因为用户在中途 ``set_keys`` 后会改值，可能与实际注册串脱节。

约束：必须主线程构造；``register`` 失败（权限 / 被占用）只写日志，不抛。
"""

import keyboard
from PyQt6.QtCore import QObject, pyqtSignal

from app.logger import SanitizedLogger


def _normalize_hotkey(keys: str) -> str:
    return keys.lower().replace(" ", "")


class _ToggleBridge(QObject):
    toggle = pyqtSignal()


class HotkeyManager(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._hotkey_str = "ctrl+shift+b"
        self._registered = False
        self._registered_hotkey_str = ""
        self._bridge = _ToggleBridge()
        self._bridge.toggle.connect(self.app.toggle)

    def register(self, keys: str = ""):
        self.unregister()
        if keys:
            self._hotkey_str = _normalize_hotkey(keys)
        try:
            keyboard.add_hotkey(self._hotkey_str, self._bridge.toggle.emit)
            self._registered = True
            self._registered_hotkey_str = self._hotkey_str
        except Exception as e:  # boundary: keyboard hotkey platform API
            import traceback
            logger = SanitizedLogger()
            logger.warning(f"[Hotkey] registration failed: {e}\n{traceback.format_exc()}")

    def unregister(self):
        if self._registered and self._registered_hotkey_str:
            try:
                keyboard.remove_hotkey(self._registered_hotkey_str)
            except (OSError, RuntimeError):
                pass
        self._registered = False
        self._registered_hotkey_str = ""

    def set_keys(self, keys: str):
        hotkey = _normalize_hotkey(keys)
        if hotkey == self._hotkey_str:
            return
        self._hotkey_str = hotkey
        if self._registered:
            self.register()

    @property
    def hotkey_str(self) -> str:
        return self._hotkey_str
