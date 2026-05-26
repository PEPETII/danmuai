import sys

from PyQt6.QtCore import QObject, pyqtSignal

from app.logger import SanitizedLogger


class _ToggleBridge(QObject):
    toggle = pyqtSignal()


class HotkeyManager(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._hotkey_str = "ctrl+shift+b"
        self._registered = False
        self._backend = self._load_backend()
        self._backend_warning_logged = False
        self._bridge = _ToggleBridge()
        self._bridge.toggle.connect(self.app.toggle)

    def _load_backend(self):
        if sys.platform != "win32":
            return None
        try:
            import keyboard
        except Exception:
            return None
        return keyboard

    def register(self, keys: str = ""):
        self.unregister()
        if keys:
            self._hotkey_str = keys.lower().replace("ctrl+shift+", "ctrl+shift+")
        if self._backend is None:
            if not self._backend_warning_logged:
                logger = SanitizedLogger()
                logger.info(
                    "[Hotkey] global hotkey disabled on this platform; use tray or Web controls"
                )
                self._backend_warning_logged = True
            return
        try:
            self._backend.add_hotkey(self._hotkey_str, self._bridge.toggle.emit)
            self._registered = True
        except Exception as e:
            import traceback
            logger = SanitizedLogger()
            logger.warning(f"[Hotkey] registration failed: {e}\n{traceback.format_exc()}")

    def unregister(self):
        if self._registered:
            try:
                self._backend.remove_hotkey(self._hotkey_str)
            except Exception:
                pass
            self._registered = False

    def set_keys(self, keys: str):
        hotkey = keys.lower().replace(" ", "")
        if hotkey == self._hotkey_str:
            return
        self._hotkey_str = hotkey
        if self._registered:
            self.register()

    @property
    def hotkey_str(self) -> str:
        return self._hotkey_str
