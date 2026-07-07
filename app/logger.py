import logging
import re
import sys

from PyQt6.QtCore import QObject, pyqtSignal

from app.bundle_paths import app_log_path, is_frozen
from app.translations import tr

API_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
BASE64_IMAGE_PATTERN = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]{100,}")
BASE64_AUDIO_PATTERN = re.compile(r"data:audio/[^;]+;base64,[A-Za-z0-9+/=]{100,}")
AUTH_HEADER_PATTERN = re.compile(r"Authorization['\"]?\s*[:=]\s*['\"]?Bearer\s+[A-Za-z0-9_-]{20,}['\"]?", re.IGNORECASE)
ENCRYPTED_KEY_PATTERN = re.compile(r"gAAAA[A-Za-z0-9_-]{50,}")
GENERIC_API_KEY_PATTERN = re.compile(r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_-]{20,}", re.IGNORECASE)

_log_bus: "LogEmitBus | None" = None


class LogEmitBus(QObject):
    """全局日志 UI 推送总线；所有 SanitizedLogger 实例经此发射 log_emitted。"""

    log_emitted = pyqtSignal(str, str)  # level, message


def _log_bus_is_alive(bus: "LogEmitBus | None") -> bool:
    if bus is None:
        return False
    try:
        from PyQt6 import sip

        return not sip.isdeleted(bus)
    except Exception:
        return True


def get_log_bus() -> LogEmitBus:
    global _log_bus
    if not _log_bus_is_alive(_log_bus):
        _log_bus = LogEmitBus()
    return _log_bus


def _log_formatter() -> logging.Formatter:
    return logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")


def _has_console_handler(handlers: list[logging.Handler]) -> bool:
    return any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in handlers
    )


def _has_file_handler(handlers: list[logging.Handler]) -> bool:
    return any(isinstance(handler, logging.FileHandler) for handler in handlers)


def _ensure_stream_handler() -> logging.Logger:
    logger = logging.getLogger("DanmuAI")
    logger.setLevel(logging.DEBUG)
    formatter = _log_formatter()
    if sys.stderr is not None and not _has_console_handler(logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    if (is_frozen() or sys.stderr is None) and not _has_file_handler(logger.handlers):
        try:
            path = app_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(path, encoding="utf-8", mode="a")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            pass
    return logger


def sanitize_log_message(msg: str) -> str:
    """与 SanitizedLogger._sanitize 相同规则；供 append_frozen_log 等无 logger 实例路径复用。"""
    msg = API_KEY_PATTERN.sub("sk-****", msg)
    msg = BASE64_IMAGE_PATTERN.sub(f"data:image/***;base64,({tr('common.hidden')})", msg)
    msg = BASE64_AUDIO_PATTERN.sub(f"data:audio/***;base64,({tr('common.hidden')})", msg)
    msg = AUTH_HEADER_PATTERN.sub(f"Authorization: Bearer ({tr('common.hidden')})", msg)
    msg = ENCRYPTED_KEY_PATTERN.sub(f"gAAAA****({tr('common.hidden')})", msg)
    msg = GENERIC_API_KEY_PATTERN.sub("(api_key: ****)", msg)
    return msg


class SanitizedLogger:
    def __init__(self):
        self.logger = _ensure_stream_handler()

    @property
    def log_emitted(self):
        return get_log_bus().log_emitted

    @staticmethod
    def _format_msg(msg: str, args: tuple) -> str:
        if not args:
            return msg
        try:
            return msg % args
        except Exception:
            return f"{msg} {args!r}"

    def _sanitize(self, msg: str) -> str:
        return sanitize_log_message(msg)

    def _emit(self, level: str, msg: str, *args) -> None:
        safe = self._sanitize(self._format_msg(msg, args))
        getattr(self.logger, level.lower())(safe)
        get_log_bus().log_emitted.emit(level.upper(), safe)

    def debug(self, msg: str, *args):
        self._emit("debug", msg, *args)

    def info(self, msg: str, *args):
        self._emit("info", msg, *args)

    def warning(self, msg: str, *args):
        self._emit("warning", msg, *args)

    def error(self, msg: str, *args):
        self._emit("error", msg, *args)
