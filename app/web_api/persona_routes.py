"""人格 Web API 路由注册。

路由（由 ``app.web_api.routes`` 调用 ``register_persona_routes``）：
- ``GET/PUT /api/personae/{name}/template``：模板读写
- ``GET /api/personae/{name}/versions`` / ``POST .../rollback``：版本与回滚预览
- ``POST /api/personae`` / ``DELETE /api/personae/{name}`` / ``POST .../restore``：创建、删除、恢复内置
- ``PUT /api/personae/active``：活跃人格列表
- ``PUT /api/personae/{name}/model``：人格 → 模型档案绑定

写操作经 ``invoke_main``（``WebConsoleBridge.invoke_on_main`` 包装）回到主线程。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable
from urllib.parse import unquote

from fastapi import Header, HTTPException
from pydantic import BaseModel

from app.translations import tr
from app.web_api import danmu_read as read_api
from app.web_api import persona as persona_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class PersonaCreatePayload(BaseModel):
    name: str


class PersonaSavePayload(BaseModel):
    system_custom: str = ""
    user_pt: str = ""
    label: str = ""


class PersonaRollbackPayload(BaseModel):
    version: int


class ActivePersonaePayload(BaseModel):
    active: list[str]


class PersonaModelBindingPayload(BaseModel):
    # W-PERSONA-MODEL-BIND-001：人格 → 模型档案绑定（空串 = 清除，回退全局）
    model_id: str = ""


def register_persona_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/personae/{name}/template")
    def get_persona_template(name: str):
        return read_api.safe_read_api(persona_api.get_template_detail, bridge.danmu_app, unquote(name))

    @app.get("/api/personae/{name}/versions")
    def get_persona_versions(name: str):
        return read_api.safe_read_api(persona_api.list_versions, bridge.danmu_app, unquote(name))

    @app.put("/api/personae/{name}/template")
    @require_auth(check_token)
    def put_persona_template(
        name: str,
        body: PersonaSavePayload,
        authorization: str | None = Header(default=None),
    ):
        invoke_main(
            persona_api.save_template,
            bridge.danmu_app,
            unquote(name),
            body.system_custom,
            body.user_pt,
            body.label,
        )
        return {"ok": True}

    @app.post("/api/personae/{name}/rollback")
    @require_auth(check_token)
    def post_persona_rollback(
        name: str,
        body: PersonaRollbackPayload,
        authorization: str | None = Header(default=None),
    ):
        return read_api.safe_read_api(persona_api.rollback_preview, bridge.danmu_app, unquote(name), body.version)

    @app.post("/api/personae")
    @require_auth(check_token)
    def post_persona(body: PersonaCreatePayload, authorization: str | None = Header(default=None)):
        return invoke_main(persona_api.create_persona, bridge.danmu_app, body.name)

    @app.delete("/api/personae/{name}")
    @require_auth(check_token)
    def delete_persona(name: str, authorization: str | None = Header(default=None)):
        invoke_main(persona_api.delete_persona, bridge.danmu_app, unquote(name))
        return {"ok": True}

    @app.post("/api/personae/{name}/restore")
    @require_auth(check_token)
    def restore_persona(name: str, authorization: str | None = Header(default=None)):
        return invoke_main(persona_api.restore_builtin_default, bridge.danmu_app, unquote(name))

    # 活跃人格：经 invoke_on_main 在主线程调用 set_active_personae
    @app.put("/api/personae/active")
    @require_auth(check_token)
    def put_active_personae(
        body: ActivePersonaePayload,
        authorization: str | None = Header(default=None),
    ):
        if not body.active:
            raise HTTPException(status_code=400, detail=tr("persona.activeRequired"))
        invoke_main(bridge.danmu_app.set_active_personae, body.active)
        return {"ok": True}

    # W-PERSONA-MODEL-BIND-001：人格 → 模型档案绑定（空串清除，回退全局"使用"模型）
    @app.put("/api/personae/{name}/model")
    @require_auth(check_token)
    def put_persona_model(
        name: str,
        body: PersonaModelBindingPayload,
        authorization: str | None = Header(default=None),
    ):
        invoke_main(
            bridge.danmu_app.set_persona_model_binding,
            unquote(name),
            body.model_id or "",
        )
        return {"ok": True}
