"""虚拟主播模型配置 Web API façade。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from main import DanmuApp


def get_model_config(app: "DanmuApp") -> dict[str, object]:
    return app.get_virtual_host_model_config()


def save_model_config(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, object]:
    return app.apply_virtual_host_model_config(payload)
