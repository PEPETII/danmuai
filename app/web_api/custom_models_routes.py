"""自定义模型与 API 探测 Web API 路由注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header
from pydantic import BaseModel

from app.web_api import custom_models as cm_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class CustomModelPayload(BaseModel):
    name: str = ""
    model_ids: list[str] | None = None
    default_model_id: str = ""
    max_tokens: int | None = None
    mode: str = "doubao"
    endpoint: str = ""
    apiKey: str = ""
    description: str = ""
    provider: str = ""


class CustomModelProbePayload(CustomModelPayload):
    index: int = -1
    # W-CUSTOMMODEL-SCHEMA-002：probe 可指定具体 model_id；缺省取 default_model_id
    model_id: str = ""


class ProbePayload(BaseModel):
    api_endpoint: str = ""
    api_key: str = ""
    model: str = ""
    api_mode: str = ""


def register_custom_models_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/custom-models")
    def get_custom_models():
        return cm_api.list_custom_models(bridge.danmu_app)

    @app.post("/api/custom-models")
    @require_auth(check_token)
    def post_custom_model(
        body: CustomModelPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(cm_api.create_custom_model, bridge.danmu_app, body.model_dump())

    @app.put("/api/custom-models/{index}")
    @require_auth(check_token)
    def put_custom_model(
        index: int,
        body: CustomModelPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(cm_api.update_custom_model, bridge.danmu_app, index, body.model_dump())

    @app.delete("/api/custom-models/{index}")
    @require_auth(check_token)
    def delete_custom_model_route(
        index: int,
        authorization: str | None = Header(default=None),
    ):
        invoke_main(cm_api.delete_custom_model, bridge.danmu_app, index)
        return {"ok": True}

    @app.post("/api/custom-models/{index}/default")
    @require_auth(check_token)
    def set_default_custom_model(
        index: int,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(cm_api.set_default_custom_model, bridge.danmu_app, index)

    @app.post("/api/probe")
    @require_auth(check_token)
    def probe_api_connection_route(
        body: ProbePayload,
        authorization: str | None = Header(default=None),
    ):
        return bridge.danmu_app.probe_api_connection(
            api_endpoint=body.api_endpoint or "",
            api_key=body.api_key or "",
            model=body.model or "",
            api_mode=body.api_mode or "",
        )

    @app.post("/api/custom-models/probe")
    @require_auth(check_token)
    def probe_custom_model(
        body: CustomModelProbePayload,
        authorization: str | None = Header(default=None),
    ):
        payload = body.model_dump(exclude={"index"})
        resolved = cm_api.resolve_probe_credentials(bridge.danmu_app, payload, body.index)
        return bridge.danmu_app.probe_api_connection(
            api_endpoint=str(resolved.get("endpoint") or ""),
            api_key=str(resolved.get("apiKey") or ""),
            model=str(resolved.get("default_model_id") or ""),
            api_mode=str(resolved.get("mode") or ""),
        )
