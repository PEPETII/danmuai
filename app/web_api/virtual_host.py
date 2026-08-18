"""虚拟主播模型配置 Web API façade。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from main import DanmuApp


def get_model_config(app: "DanmuApp") -> dict[str, object]:
    return app.get_virtual_host_model_config()


def save_model_config(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, object]:
    return app.apply_virtual_host_model_config(payload)


def get_settings(app: "DanmuApp") -> dict[str, object]:
    return app.get_virtual_host_settings()


def save_settings(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, object]:
    return app.apply_virtual_host_settings(payload)


def get_voice_status(app: "DanmuApp") -> dict[str, object]:
    return app.get_virtual_host_voice_status()


def get_speech_logs(app: "DanmuApp") -> dict[str, object]:
    return app.get_virtual_host_speech_logs()


def start_voice_session(app: "DanmuApp") -> dict[str, object]:
    return app.start_virtual_host_voice()


def stop_voice_session(app: "DanmuApp") -> dict[str, object]:
    return app.stop_virtual_host_voice()


def cancel_voice_session(app: "DanmuApp") -> dict[str, object]:
    return app.cancel_virtual_host_voice()
