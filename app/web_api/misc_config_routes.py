"""控制台杂项配置 Web API 路由（公告已读、更新提示、主题、语言、版本）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header
from pydantic import BaseModel

from app.web_api import announcements_state
from app.web_api import app_update_state as app_update_state_api
from app.web_api import console_theme as console_theme_api
from app.web_api import language as language_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class AnnouncementsReadStatePayload(BaseModel):
    readIds: list[str] = []
    lastSeenMs: int = 0
    overviewBannerDismissedId: str = ""


class AppUpdateStatePayload(BaseModel):
    dismissedLatestVersion: str = ""


class ConsoleThemePayload(BaseModel):
    theme: str = "light"


class LanguagePayload(BaseModel):
    language: str = "zh"


def register_misc_config_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/announcements-read-state")
    def get_announcements_read_state():
        return announcements_state.get_from_config(bridge.danmu_app.config)

    @app.put("/api/announcements-read-state")
    @require_auth(check_token)
    def put_announcements_read_state(
        body: AnnouncementsReadStatePayload,
        authorization: str | None = Header(default=None),
    ):
        state = announcements_state.validate_payload(body.model_dump())
        invoke_main(announcements_state.save_to_config, bridge.danmu_app.config, state)
        return {"ok": True}

    @app.get("/api/version")
    def get_app_version():
        from app.version import __version__

        return {"current_version": __version__}

    @app.get("/api/app-update-state")
    def get_app_update_state():
        return app_update_state_api.get_from_config(bridge.danmu_app.config)

    @app.put("/api/app-update-state")
    @require_auth(check_token)
    def put_app_update_state(
        body: AppUpdateStatePayload,
        authorization: str | None = Header(default=None),
    ):
        state = app_update_state_api.validate_payload(body.model_dump())
        invoke_main(app_update_state_api.save_to_config, bridge.danmu_app.config, state)
        return {"ok": True}

    @app.get("/api/console-theme")
    def get_console_theme():
        return console_theme_api.get_from_config(bridge.danmu_app.config)

    @app.put("/api/console-theme")
    @require_auth(check_token)
    def put_console_theme(
        body: ConsoleThemePayload,
        authorization: str | None = Header(default=None),
    ):
        theme = console_theme_api.validate_payload(body.model_dump())
        invoke_main(console_theme_api.save_to_config, bridge.danmu_app.config, theme)
        return {"ok": True, "theme": theme}

    @app.get("/api/language")
    def get_language():
        return language_api.get_from_config(bridge.danmu_app.config)

    @app.put("/api/language")
    @require_auth(check_token)
    def put_language(
        body: LanguagePayload,
        authorization: str | None = Header(default=None),
    ):
        language = language_api.validate_payload(body.model_dump())
        invoke_main(language_api.save_to_config, bridge.danmu_app.config, language)
        return {"ok": True, "language": language}

    # W-FP-STYLE-CONTRACT-001：只读样式预设；不要求写权限；HTTP 线程不写 ConfigStore
    @app.get("/api/floating-panel/style-presets")
    def get_floating_panel_style_presets():
        from app.floating_panel_style import style_presets_api_payload

        return style_presets_api_payload()
