"""扩展 FastAPI 路由：协议适配层，委托 DanmuApp 公开 façade 与 web_api 子模块。

线程模型：
- GET 路由：HTTP 线程直接执行（只读快照）
- PUT /api/config：经 save_config_requested.emit 异步信号到主线程
- 其他写路由：经 bridge.invoke_on_main（BlockingQueuedConnection）同步到主线程

边界约束：必须使用 DanmuApp 公开 façade，禁止访问内部私有属性：
- build_status_snapshot() / build_diagnostic_snapshot()
- apply_web_config_payload() / start() / stop()
- get/set_persona, get/set_custom_models, probe_model_config 等

/api/status 在 web_console 内注册，本文件不重复。
/api/diagnostics 必须 build_diagnostic_snapshot()，与 status 分离。
写操作需 Bearer；须经 bridge.invoke_on_main（勿在 HTTP 线程直接写 Config / emit config_changed）。
"""

from typing import TYPE_CHECKING, Callable
from urllib.parse import unquote

from fastapi import Header, HTTPException
from pydantic import BaseModel

from app.web_api import announcements_state
from app.web_api import app_update_state as app_update_state_api
from app.web_api import console_theme as console_theme_api
from app.web_api import custom_models as cm_api
from app.web_api import danmu_pool as pool_api
from app.web_api import danmu_read as read_api
from app.web_api import font_registry as font_registry_api  # W-FONT-002
from app.web_api import meme_barrage as meme_api
from app.web_api import mic_test as mic_test_api
from app.web_api import persona as persona_api
from app.web_api import pet as pet_api
from app.web_api.preview_compress import register_preview_compress_route

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


def register_web_routes(app, bridge: "WebConsoleBridge", check_token: Callable) -> None:
    register_preview_compress_route(app, check_token)

    class PersonaCreatePayload(BaseModel):
        name: str

    class PersonaSavePayload(BaseModel):
        system_custom: str = ""
        user_pt: str = ""

    class PersonaRollbackPayload(BaseModel):
        version: int

    class CustomModelPayload(BaseModel):
        name: str = ""
        modelId: str = ""
        mode: str = "doubao"
        endpoint: str = ""
        apiKey: str = ""
        description: str = ""
        provider: str = ""

    class CustomModelProbePayload(CustomModelPayload):
        index: int = -1

    class ActivePersonaePayload(BaseModel):
        active: list[str]

    class MicTestPayload(BaseModel):
        duration_sec: float = 3.0
        send_to_ai: bool = False

    class ProbePayload(BaseModel):
        api_endpoint: str = ""
        api_key: str = ""
        model: str = ""
        api_mode: str = "doubao"

    class DanmuPoolSettingsPayload(BaseModel):
        custom_enabled: bool | None = None
        min_on_screen: int | None = None

    class DanmuPoolCustomAppendPayload(BaseModel):
        text: str = ""
        items: list[str] | None = None

    class DanmuPoolCustomDeletePayload(BaseModel):
        texts: list[str]

    class MemeBarrageSettingsPayload(BaseModel):
        enabled: bool | None = None
        category: str | None = None
        tag: str | None = None
        display_mode: str | None = None
        collect_interval_sec: int | None = None
        collect_batch_size: int | None = None
        display_interval_sec: int | None = None
        display_batch_size: int | None = None

    class TestDanmuPayload(BaseModel):
        items: list[str]
        persona: str = "测试"

    class DanmuReadConfigPayload(BaseModel):
        enabled: bool | None = None
        interval_sec: int | None = None
        voice: str | None = None
        style_prompt: str | None = None
        api_key: str | None = None
        provider: str | None = None
        endpoint: str | None = None
        model_id: str | None = None
        custom_endpoint: str | None = None
        custom_model_id: str | None = None

    class DanmuReadProbePayload(BaseModel):
        api_key: str | None = None
        provider: str | None = None
        endpoint: str | None = None
        model_id: str | None = None
        custom_endpoint: str | None = None
        custom_model_id: str | None = None

    class AnnouncementsReadStatePayload(BaseModel):
        readIds: list[str] = []
        lastSeenMs: int = 0
        overviewBannerDismissedId: str = ""

    class AppUpdateStatePayload(BaseModel):
        dismissedLatestVersion: str = ""

    class ConsoleThemePayload(BaseModel):
        theme: str = "light"

    def _invoke_main(fn, *args, **kwargs):
        """写 API：经 WebConsoleBridge.invoke_on_main 在主线程执行。"""
        try:
            return bridge.invoke_on_main(fn, *args, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/diagnostics")
    def get_diagnostics(authorization: str | None = Header(default=None)):
        # 只读诊断；调度/timing 数据经 DanmuApp 公开入口，不读 _last_api_trigger_at 等私有字段
        check_token(authorization)
        return {
            "ok": True,
            "diagnostics": bridge.danmu_app.build_diagnostic_snapshot(),
        }

    @app.get("/api/announcements-read-state")
    def get_announcements_read_state():
        return announcements_state.get_from_config(bridge.danmu_app.config)

    @app.put("/api/announcements-read-state")
    def put_announcements_read_state(
        body: AnnouncementsReadStatePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        state = announcements_state.validate_payload(body.model_dump())
        _invoke_main(announcements_state.save_to_config, bridge.danmu_app.config, state)
        return {"ok": True}

    @app.get("/api/version")
    def get_app_version():
        from app.version import __version__

        return {"current_version": __version__}

    @app.get("/api/app-update-state")
    def get_app_update_state():
        return app_update_state_api.get_from_config(bridge.danmu_app.config)

    @app.put("/api/app-update-state")
    def put_app_update_state(
        body: AppUpdateStatePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        state = app_update_state_api.validate_payload(body.model_dump())
        _invoke_main(app_update_state_api.save_to_config, bridge.danmu_app.config, state)
        return {"ok": True}

    @app.get("/api/console-theme")
    def get_console_theme():
        return console_theme_api.get_from_config(bridge.danmu_app.config)

    @app.put("/api/console-theme")
    def put_console_theme(
        body: ConsoleThemePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        theme = console_theme_api.validate_payload(body.model_dump())
        _invoke_main(console_theme_api.save_to_config, bridge.danmu_app.config, theme)
        return {"ok": True, "theme": theme}

    @app.get("/api/personae/{name}/template")
    def get_persona_template(name: str):
        return read_api.safe_read_api(persona_api.get_template_detail, bridge.danmu_app, unquote(name))

    @app.get("/api/personae/{name}/versions")
    def get_persona_versions(name: str):
        return read_api.safe_read_api(persona_api.list_versions, bridge.danmu_app, unquote(name))

    @app.put("/api/personae/{name}/template")
    def put_persona_template(
        name: str,
        body: PersonaSavePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        _invoke_main(
            persona_api.save_template,
            bridge.danmu_app,
            unquote(name),
            body.system_custom,
            body.user_pt,
        )
        return {"ok": True}

    @app.post("/api/personae/{name}/rollback")
    def post_persona_rollback(
        name: str,
        body: PersonaRollbackPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return read_api.safe_read_api(persona_api.rollback_preview, bridge.danmu_app, unquote(name), body.version)

    @app.post("/api/personae")
    def post_persona(body: PersonaCreatePayload, authorization: str | None = Header(default=None)):
        check_token(authorization)
        return _invoke_main(persona_api.create_persona, bridge.danmu_app, body.name)

    @app.delete("/api/personae/{name}")
    def delete_persona(name: str, authorization: str | None = Header(default=None)):
        check_token(authorization)
        _invoke_main(persona_api.delete_persona, bridge.danmu_app, unquote(name))
        return {"ok": True}

    @app.post("/api/personae/{name}/restore")
    def restore_persona(name: str, authorization: str | None = Header(default=None)):
        check_token(authorization)
        return _invoke_main(persona_api.restore_builtin_default, bridge.danmu_app, unquote(name))

    # 活跃人格：经 invoke_on_main 在主线程调用 set_active_personae
    @app.put("/api/personae/active")
    def put_active_personae(
        body: ActivePersonaePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        if not body.active:
            raise HTTPException(status_code=400, detail="请至少选择一个人格")
        _invoke_main(bridge.danmu_app.set_active_personae, body.active)
        return {"ok": True}

    @app.get("/api/danmu-pool/meta")
    def get_danmu_pool_meta():
        return pool_api.get_meta(bridge.danmu_app)

    @app.put("/api/danmu-pool/settings")
    def put_danmu_pool_settings(
        body: DanmuPoolSettingsPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(pool_api.save_settings, bridge.danmu_app, body.model_dump(exclude_none=True))

    @app.get("/api/danmu-pool/custom")
    def get_danmu_pool_custom():
        return pool_api.list_custom(bridge.danmu_app)

    @app.post("/api/danmu-pool/custom")
    def post_danmu_pool_custom(
        body: DanmuPoolCustomAppendPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(pool_api.append_custom, bridge.danmu_app, body.model_dump(exclude_none=True))

    @app.delete("/api/danmu-pool/custom")
    def delete_danmu_pool_custom(
        body: DanmuPoolCustomDeletePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(pool_api.delete_custom, bridge.danmu_app, body.model_dump())

    @app.post("/api/test/danmu")
    def post_test_danmu(
        body: TestDanmuPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(bridge.danmu_app.inject_test_danmu_batch, body.items, persona_id=body.persona)

    @app.get("/api/meme-barrage/meta")
    def get_meme_barrage_meta():
        return meme_api.get_meta(bridge.danmu_app)

    @app.put("/api/meme-barrage/settings")
    def put_meme_barrage_settings(
        body: MemeBarrageSettingsPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(
            meme_api.save_settings,
            bridge.danmu_app,
            body.model_dump(exclude_none=True),
        )

    @app.get("/api/meme-barrage/tags")
    def get_meme_barrage_tags():
        return meme_api.get_tags()

    @app.post("/api/meme-barrage/clear")
    def post_meme_barrage_clear(
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(meme_api.clear_library, bridge.danmu_app)

    @app.get("/api/danmu-read/config")
    def get_danmu_read_config():
        return read_api.get_config(bridge.danmu_app)

    @app.put("/api/danmu-read/config")
    def put_danmu_read_config(
        body: DanmuReadConfigPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        payload = read_api.normalize_put_payload(body.model_dump(exclude_none=True))
        return _invoke_main(read_api.save_config, bridge.danmu_app, payload)

    @app.post("/api/danmu-read/probe")
    def post_danmu_read_probe(
        body: DanmuReadProbePayload | None = None,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        payload = body.model_dump(exclude_none=True) if body else {}
        return _invoke_main(read_api.run_probe, bridge.danmu_app, payload)

    @app.get("/api/custom-models")
    def get_custom_models():
        return cm_api.list_custom_models(bridge.danmu_app)

    @app.post("/api/custom-models")
    def post_custom_model(
        body: CustomModelPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(cm_api.create_custom_model, bridge.danmu_app, body.model_dump())

    @app.put("/api/custom-models/{index}")
    def put_custom_model(
        index: int,
        body: CustomModelPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(cm_api.update_custom_model, bridge.danmu_app, index, body.model_dump())

    @app.delete("/api/custom-models/{index}")
    def delete_custom_model_route(
        index: int,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        _invoke_main(cm_api.delete_custom_model, bridge.danmu_app, index)
        return {"ok": True}

    @app.post("/api/custom-models/{index}/default")
    def set_default_custom_model(
        index: int,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(cm_api.set_default_custom_model, bridge.danmu_app, index)

    @app.post("/api/probe")
    def probe_api_connection_route(
        body: ProbePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return bridge.danmu_app.probe_api_connection(
            api_endpoint=body.api_endpoint or "",
            api_key=body.api_key or "",
            model=body.model or "",
            api_mode=body.api_mode or "",
        )

    @app.post("/api/custom-models/probe")
    def probe_custom_model(
        body: CustomModelProbePayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        payload = body.model_dump(exclude={"index"})
        resolved = cm_api.resolve_probe_credentials(bridge.danmu_app, payload, body.index)
        return bridge.danmu_app.probe_api_connection(
            api_endpoint=str(resolved.get("endpoint") or ""),
            api_key=str(resolved.get("apiKey") or ""),
            model=str(resolved.get("modelId") or ""),
            api_mode=str(resolved.get("mode") or ""),
        )

    @app.post("/api/mic/test")
    def mic_test(
        body: MicTestPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(
            mic_test_api.run_mic_test,
            bridge.danmu_app,
            body.duration_sec,
            body.send_to_ai,
        )

    @app.post("/api/mic/test-send")
    def mic_test_send(
        body: MicTestPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(
            mic_test_api.run_mic_test,
            bridge.danmu_app,
            body.duration_sec,
            True,
        )

    @app.get("/api/capture-region")
    def get_capture_region():
        return bridge.danmu_app.get_capture_region_status()

    @app.post("/api/capture-region/select")
    def post_capture_region_select(
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        current = bridge.danmu_app.get_capture_region_status()
        if current.get("selection_state") == "selecting":
            return {"ok": True, "selection_state": "selecting"}
        bridge.region_select_requested.emit()
        return {"ok": True, "selection_state": "selecting"}

    @app.post("/api/capture-region/reset")
    def post_capture_region_reset(
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        bridge.region_reset_requested.emit()
        return {"ok": True}

    class PetSettingsPayload(BaseModel):
        enabled: bool | None = None
        visible: bool | None = None
        asset_source: str | None = None
        asset_path: str | None = None
        scale: float | None = None
        opacity: float | None = None
        always_on_top: bool | None = None
        click_through: bool | None = None
        position_x: int | None = None
        position_y: int | None = None
        command_box_enabled: bool | None = None
        command_ttl_sec: int | None = None
        command_apply_count: int | None = None

    class PetCommandPayload(BaseModel):
        text: str = ""

    @app.get("/api/pet/settings")
    def get_pet_settings():
        return pet_api.get_settings(bridge.danmu_app)

    @app.post("/api/pet/settings")
    def post_pet_settings(
        body: PetSettingsPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        raw = body.model_dump(exclude_none=True)
        payload = {
            "pet_enabled": raw.get("enabled"),
            "pet_asset_source": raw.get("asset_source"),
            "pet_asset_path": raw.get("asset_path"),
            "pet_scale": raw.get("scale"),
            "pet_opacity": raw.get("opacity"),
            "pet_always_on_top": raw.get("always_on_top"),
            "pet_click_through": raw.get("click_through"),
            "pet_position_x": raw.get("position_x"),
            "pet_position_y": raw.get("position_y"),
            "pet_command_box_enabled": raw.get("command_box_enabled"),
            "pet_command_ttl_sec": raw.get("command_ttl_sec"),
            "pet_command_apply_count": raw.get("command_apply_count"),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return _invoke_main(pet_api.save_settings, bridge.danmu_app, payload)

    @app.post("/api/pet/show")
    def post_pet_show(authorization: str | None = Header(default=None)):
        check_token(authorization)
        return _invoke_main(pet_api.show_pet, bridge.danmu_app)

    @app.post("/api/pet/hide")
    def post_pet_hide(authorization: str | None = Header(default=None)):
        check_token(authorization)
        return _invoke_main(pet_api.hide_pet, bridge.danmu_app)

    @app.post("/api/pet/close")
    def post_pet_close(authorization: str | None = Header(default=None)):
        check_token(authorization)
        return _invoke_main(pet_api.close_pet, bridge.danmu_app)

    @app.post("/api/pet/command")
    def post_pet_command(
        body: PetCommandPayload,
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        return _invoke_main(pet_api.submit_command, bridge.danmu_app, body.text)

    @app.get("/api/pet/status")
    def get_pet_status():
        return pet_api.get_status(bridge.danmu_app)

    font_registry_api.register_font_registry_routes(app, bridge, check_token)  # W-FONT-002


def register_diagnostics_sse_route(app, diagnostics_hub, bridge, check_token) -> None:
    """注册 /api/diagnostics/events SSE 端点。

    推送初始 hello 事件、初始诊断快照，随后每 2.5 秒推送更新快照。
    与 /api/diagnostics GET 一致，需要鉴权（通过 query 参数 token 传递）。
    """
    import asyncio
    import json
    import time

    from fastapi.responses import StreamingResponse

    @app.get("/api/diagnostics/events")
    async def diagnostics_events(token: str | None = None):
        # SSE 端点通过 query 参数传递 Token（EventSource 不支持自定义 headers）
        check_token(token)
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        diagnostics_hub.register(queue)

        async def event_stream():
            try:
                # 推送初始 hello 事件
                hello = json.dumps(
                    {"event": "hello", "ts": time.time()},
                    ensure_ascii=False,
                )
                yield f"event: hello\ndata: {hello}\n\n"

                # 推送初始诊断快照
                snapshot = bridge.danmu_app.build_diagnostic_snapshot()
                snapshot_data = json.dumps(snapshot, ensure_ascii=False)
                yield f"event: diagnostic_snapshot\ndata: {snapshot_data}\n\n"

                # 每 2.5 秒推送更新快照
                while True:
                    await asyncio.sleep(2.5)
                    snapshot = bridge.danmu_app.build_diagnostic_snapshot()
                    snapshot_data = json.dumps(snapshot, ensure_ascii=False)
                    yield f"event: diagnostic_snapshot\ndata: {snapshot_data}\n\n"
            finally:
                diagnostics_hub.unregister(queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
