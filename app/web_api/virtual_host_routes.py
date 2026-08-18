"""虚拟主播模型选择 Web API 路由。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Body, Header, HTTPException
from pydantic import BaseModel

from app.web_api import virtual_host as virtual_host_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class VirtualHostSettingsPatch(BaseModel):
    dialogue_enabled: bool | None = None
    danmu_adapter_enabled: bool | None = None


class VirtualHostPersonaPatch(BaseModel):
    system_prompt: str | None = None
    voice_dialogue_prompt: str | None = None


def register_virtual_host_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/virtual-host/models")
    def get_virtual_host_models():
        return invoke_main(virtual_host_api.get_model_config, bridge.danmu_app)

    @app.put("/api/virtual-host/models")
    @require_auth(check_token)
    def put_virtual_host_models(
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        del authorization
        try:
            return invoke_main(virtual_host_api.save_model_config, bridge.danmu_app, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    @app.get("/api/virtual-host/settings")
    def get_virtual_host_settings():
        return invoke_main(virtual_host_api.get_settings, bridge.danmu_app)

    @app.put("/api/virtual-host/settings")
    @require_auth(check_token)
    def put_virtual_host_settings(
        payload: VirtualHostSettingsPatch,
        authorization: str | None = Header(default=None),
    ):
        del authorization
        try:
            return invoke_main(
                virtual_host_api.save_settings,
                bridge.danmu_app,
                payload.model_dump(exclude_unset=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/virtual-host/voice/status")
    def get_virtual_host_voice_status():
        return invoke_main(virtual_host_api.get_voice_status, bridge.danmu_app)

    @app.get("/api/virtual-host/speech-logs")
    def get_virtual_host_speech_logs():
        return invoke_main(virtual_host_api.get_speech_logs, bridge.danmu_app)

    @app.post("/api/virtual-host/voice/start")
    @require_auth(check_token)
    def post_virtual_host_voice_start(
        authorization: str | None = Header(default=None),
    ):
        del authorization
        try:
            return invoke_main(virtual_host_api.start_voice_session, bridge.danmu_app)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/virtual-host/voice/stop")
    @require_auth(check_token)
    def post_virtual_host_voice_stop(
        authorization: str | None = Header(default=None),
    ):
        del authorization
        try:
            return invoke_main(virtual_host_api.stop_voice_session, bridge.danmu_app)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/virtual-host/voice/cancel")
    @require_auth(check_token)
    def post_virtual_host_voice_cancel(
        authorization: str | None = Header(default=None),
    ):
        del authorization
        try:
            return invoke_main(virtual_host_api.cancel_voice_session, bridge.danmu_app)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/virtual-host/persona")
    def get_virtual_host_persona():
        return invoke_main(virtual_host_api.get_persona_config, bridge.danmu_app)

    @app.put("/api/virtual-host/persona")
    @require_auth(check_token)
    def put_virtual_host_persona(
        payload: VirtualHostPersonaPatch | None = Body(default=None),
        reset: bool = False,
        authorization: str | None = Header(default=None),
    ):
        del authorization
        try:
            patch = payload.model_dump(exclude_unset=True) if payload is not None else {}
            return invoke_main(
                virtual_host_api.save_persona_config,
                bridge.danmu_app,
                patch,
                reset=reset,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
