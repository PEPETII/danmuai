"""Web 控制台主题偏好：config.db 字符串键，不影响主链路运行态。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/console-theme``：返回当前主题 ``{theme: "light" | "dark"}``。
- ``PUT /api/console-theme``：写入用户偏好（仅 light/dark，其他值归一化到 dark）。

本模块**仅**处理 Web UI 偏好，不影响 Overlay / FloatingPanel 等 Qt 渲染；
Overlay 主题由 ``app.overlay`` 的颜色常量决定，与 Web 控制台主题解耦。
"""

from __future__ import annotations

from fastapi import HTTPException

from app.translations import tr

CONSOLE_THEME_KEY = "console_theme"
DEFAULT_CONSOLE_THEME = "dark"
_VALID_THEMES = frozenset({"light", "dark"})


def normalize_theme(value: object) -> str:
    if isinstance(value, str) and value.strip().lower() == "light":
        return "light"
    return DEFAULT_CONSOLE_THEME


def get_from_config(config) -> dict[str, str]:
    raw = config.get(CONSOLE_THEME_KEY, default=DEFAULT_CONSOLE_THEME)
    return {"theme": normalize_theme(raw)}


def save_to_config(config, theme: str) -> None:
    config.set(CONSOLE_THEME_KEY, normalize_theme(theme))


def validate_payload(body: dict) -> str:
    theme = body.get("theme", DEFAULT_CONSOLE_THEME)
    if theme is None:
        theme = DEFAULT_CONSOLE_THEME
    if not isinstance(theme, str):
        raise HTTPException(status_code=400, detail=tr("validation.themeMustBeString"))
    normalized = theme.strip().lower()
    if normalized not in _VALID_THEMES:
        raise HTTPException(status_code=400, detail=tr("validation.themeMustBeLightOrDark"))
    return normalized
