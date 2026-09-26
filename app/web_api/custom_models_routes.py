"""自定义模型与 API 探测 Web API 路由注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api_probe import ProbeScopeViolation
from app.web_api import custom_models as cm_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class CustomModelPayload(BaseModel):
    """HTTP contract for custom model create/update; mirrors settings modal payload."""

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    # W-AUDIT-MODEL-IDENTITY-001：不可变档案身份；创建时由服务端分配（入参被忽略），
    # 更新 / 探测时用于精确定位档案（按 index 的定位仅作旧客端兼容）。
    profile_id: str = ""
    model_ids: list[str] | None = None
    model_names: dict[str, str] | None = None
    default_model_id: str = ""
    max_tokens: int | None = None
    temperature: float | None = None
    mode: str = "doubao"
    endpoint: str = ""
    apiKey: str = ""
    description: str = ""
    provider: str = ""
    supportsMic: bool = False
    thinking_effort: str = "off"


class CustomModelProbePayload(CustomModelPayload):
    index: int = -1
    # W-CUSTOMMODEL-SCHEMA-002：probe 可指定具体 model_id；缺省取 default_model_id
    model_id: str = ""
    stage: str = "text"


class ProbePayload(BaseModel):
    api_endpoint: str = ""
    api_key: str = ""
    model: str = ""
    api_mode: str = ""
    stage: str = "text"


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

    def _scope_violation(exc: ProbeScopeViolation) -> HTTPException:
        """W-AUDIT-PROBE-SECRET-001：凭据作用域越界是客户端错误，稳定映射为 400。"""
        return HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": exc.error_code,
                "detail": str(exc),
            },
        )

    @app.post("/api/probe")
    @require_auth(check_token)
    def probe_api_connection_route(
        body: ProbePayload,
        authorization: str | None = Header(default=None),
    ):
        try:
            return bridge.danmu_app.probe_api_connection(
                api_endpoint=body.api_endpoint or "",
                api_key=body.api_key or "",
                model=body.model or "",
                api_mode=body.api_mode or "",
                stage=body.stage or "text",
            )
        except ProbeScopeViolation as exc:
            raise _scope_violation(exc) from exc

    @app.post("/api/custom-models/probe")
    @require_auth(check_token)
    def probe_custom_model(
        body: CustomModelProbePayload,
        authorization: str | None = Header(default=None),
    ):
        payload = body.model_dump(exclude={"index"})
        try:
            # W-AUDIT-PROBE-PARITY-001：档案 probe 由 cm_api 单一路径执行——
            # 先按 profile_id 解析不可变凭据快照，再分阶段探测（含正式视觉流式
            # 与正式业务解析）；不再经通用 façade 丢掉档案参数。
            return cm_api.probe_custom_model(
                bridge.danmu_app, payload, body.index, body.stage or "text"
            )
        except ProbeScopeViolation as exc:
            raise _scope_violation(exc) from exc
