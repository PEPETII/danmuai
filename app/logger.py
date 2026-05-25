import logging
import re

from PyQt6.QtCore import QObject, pyqtSignal

from app.translations import tr

API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
BASE64_IMAGE_PATTERN = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]{100,}")
BASE64_AUDIO_PATTERN = re.compile(r"data:audio/[^;]+;base64,[A-Za-z0-9+/=]{100,}")
AUTH_HEADER_PATTERN = re.compile(r"Authorization['\"]?\s*[:=]\s*['\"]?Bearer\s+[A-Za-z0-9_-]{20,}['\"]?", re.IGNORECASE)
ENCRYPTED_KEY_PATTERN = re.compile(r"gAAAA[A-Za-z0-9_-]{50,}")
GENERIC_API_KEY_PATTERN = re.compile(r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_-]{20,}", re.IGNORECASE)


class SanitizedLogger(QObject):
    log_emitted = pyqtSignal(str, str)  # level, message

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("DanmuAI")
        self.logger.setLevel(logging.DEBUG)
        if not any(isinstance(handler, logging.StreamHandler) for handler in self.logger.handlers):
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            self.logger.addHandler(handler)

    def _sanitize(self, msg: str) -> str:
        msg = API_KEY_PATTERN.sub("sk-****", msg)
        msg = BASE64_IMAGE_PATTERN.sub(f"data:image/***;base64,({tr('common.hidden')})", msg)
        msg = BASE64_AUDIO_PATTERN.sub(f"data:audio/***;base64,({tr('common.hidden')})", msg)
        msg = AUTH_HEADER_PATTERN.sub(f"Authorization: Bearer ({tr('common.hidden')})", msg)
        msg = ENCRYPTED_KEY_PATTERN.sub(f"gAAAA****({tr('common.hidden')})", msg)
        msg = GENERIC_API_KEY_PATTERN.sub("(api_key: ****)", msg)
        return msg

    def debug(self, msg: str):
        safe = self._sanitize(msg)
        self.logger.debug(safe)
        self.log_emitted.emit("DEBUG", safe)

    def info(self, msg: str):
        safe = self._sanitize(msg)
        self.logger.info(safe)
        self.log_emitted.emit("INFO", safe)

    def warning(self, msg: str):
        safe = self._sanitize(msg)
        self.logger.warning(safe)
        self.log_emitted.emit("WARNING", safe)

    def error(self, msg: str):
        safe = self._sanitize(msg)
        self.logger.error(safe)
        self.log_emitted.emit("ERROR", safe)
