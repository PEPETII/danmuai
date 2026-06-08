"""FastAPI / uvicorn 运行时组装：路由注册、静态文件挂载、生命周期管理。

线程模型：run_uvicorn_locked() 在非主线程执行（由 WebConsoleServer.start 启动），
内部 asyncio 事件循环处理所有 HTTP/WebSocket 请求。
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from app.bundle_paths import append_frozen_log, is_frozen
from app.startup_trace import log_startup
from app.web_console_session_auth import enforce_session_authorization
from app.web_console_support import (
    enumerate_screens,
    export_config,
    extract_config_payload,
    resolve_screens_for_api,
    save_config_via_bridge,
)
from app.web_console_ws import register_websocket_routes


def run_uvicorn_locked(server) -> None:
    bridge = server.bridge
    try:
        import uvicorn
        from fastapi import Body, FastAPI, Header, HTTPException, WebSocketDisconnect
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
        from starlette.routing import WebSocketRoute
    except ImportError as exc:
        msg = (
            f"Web console dependencies missing: {exc}. "
            "Install with: pip install fastapi \"uvicorn[standard]>=0.32.0\""
        )
        bridge.danmu_app.logger.error(msg)
        append_frozen_log(msg)
        return

    log_startup("uvicorn.import.done")

    ws_impl = "websockets"
    try:
        import websockets  # noqa: F401
    except ImportError:
        ws_impl = "auto"
        bridge.danmu_app.logger.warning(
            "未安装 websockets，/ws/status、/ws/logs 可能无法连接；"
            "HTTP API 仍可用。请运行: pip install \"uvicorn[standard]>=0.32.0\""
        )
    token = server.token

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        server._loop = asyncio.get_running_loop()
        bridge.set_event_loop(server._loop)
        server.diagnostics_hub.set_loop(server._loop)
        server.live_overlay_hub.set_loop(server._loop)
        try:
            yield
        finally:
            server._ready.clear()
            server.startup_ok = False

    app = FastAPI(
        title="DanmuAI Web Console",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    def _check_token(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="需要登录令牌")
        if authorization.removeprefix("Bearer ").strip() != token:
            raise HTTPException(status_code=403, detail="令牌无效")

    @app.get("/api/session")
    def read_console_session(
        host: str | None = Header(default=None),
        origin: str | None = Header(default=None),
        referer: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ):
        # W-SEC-001：bug-audit/bug-03.md 缺陷 1 修复。
        # 拒绝无同源 loopback 握手 / 无正确 token 的调用，避免任意本机进程零成本拿 Bearer Token。
        enforce_session_authorization(
            authorization=authorization,
            origin=origin,
            referer=referer,
            host=host,
            expected_token=token,
        )
        host = (host or "").strip()
        base_url = f"http://{host}" if host else server.base_url
        return {"token": token, "base_url": base_url}

    @app.get("/api/status")
    def status():
        return asdict(bridge.refresh_status())

    @app.get("/api/logs/recent")
    def logs_recent(since_ts: float = 0.0):
        return {"items": bridge.list_recent_logs(since_ts)}

    @app.get("/api/config")
    def get_config():
        return export_config(bridge.danmu_app.config)

    @app.get("/api/config/defaults")
    def get_config_defaults():
        from app.config_defaults import export_web_config_defaults

        return export_web_config_defaults()

    @app.get("/api/personae")
    def list_personae():
        from app.personae import BUILTIN_PERSONAE, persona_display_name

        names = bridge.danmu_app.personae.list()
        active = set(bridge.danmu_app.personae.get_active())
        return {
            "items": [
                {
                    "id": name,
                    "label": persona_display_name(name),
                    "active": name in active,
                    "builtin": name in BUILTIN_PERSONAE,
                }
                for name in names
            ],
            "active": bridge.danmu_app.personae.get_active(),
        }

    @app.get("/api/screens")
    def screens():
        return resolve_screens_for_api(bridge.cached_screens, enumerate_screens())

    @app.get("/api/meta")
    def meta():
        cfg = bridge.danmu_app.config
        return {
            "ui_mode": "web",
            "hotkey": cfg.get("hotkey", "Ctrl+Shift+B"),
            "language": cfg.get("language", ""),
            "screens": resolve_screens_for_api(bridge.cached_screens, enumerate_screens()),
        }

    @app.get("/api/providers")
    def providers():
        from app.model_providers import PROVIDERS

        return [
            {
                "id": provider.id,
                "label": provider.label_zh,
                "default_endpoint": provider.default_endpoint,
                "mode": provider.mode,
                "hint": provider.model_id_hint_zh,
            }
            for provider in PROVIDERS
        ]

    @app.get("/api/model-catalog")
    def model_catalog():
        from app.model_catalog import list_platform_catalogs

        return {"platforms": list_platform_catalogs()}

    @app.api_route("/api/config", methods=["PUT", "POST"])
    def save_config(
        body: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
    ):
        _check_token(authorization)
        try:
            data = extract_config_payload(body)
            from app.model_selection import validate_web_config_patch

            validate_web_config_patch(bridge.danmu_app.config, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = save_config_via_bridge(bridge, data)
        if result.get("ok"):
            return {"ok": True}
        status_code = 504 if result.get("error") == "save_timeout" else 500
        return JSONResponse(status_code=status_code, content=result)

    @app.post("/api/start")
    def api_start(authorization: str | None = Header(default=None)):
        _check_token(authorization)
        bridge.start_requested.emit()
        return {"ok": True}

    @app.post("/api/stop")
    def api_stop(authorization: str | None = Header(default=None)):
        _check_token(authorization)
        bridge.stop_requested.emit()
        return {"ok": True}

    @app.post("/api/toggle")
    def api_toggle(authorization: str | None = Header(default=None)):
        _check_token(authorization)
        bridge.toggle_requested.emit()
        return {"ok": True}

    from app.web_api.live_overlay import register_live_overlay_routes
    from app.web_api.routes import register_diagnostics_sse_route, register_web_routes

    register_web_routes(app, bridge, _check_token)
    register_live_overlay_routes(
        app,
        server.live_overlay_hub,
        server.base_url,
        _check_token,
    )
    register_diagnostics_sse_route(app, server.diagnostics_hub, bridge, _check_token)
    register_websocket_routes(app, bridge, token, WebSocketRoute, WebSocketDisconnect)

    @app.get("/")
    def index():
        index_path = server.static_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="index.html missing")
        return FileResponse(index_path)

    if server.static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(server.static_dir)), name="static")

    config_kwargs: dict[str, Any] = {
        "host": server.host,
        "port": server.port,
        "log_level": "warning",
        "access_log": False,
        "ws": ws_impl,
    }
    if is_frozen():
        config_kwargs["loop"] = "asyncio"
        config_kwargs["http"] = "h11"
    if is_frozen() or sys.stderr is None:
        from app.web_console import _prepare_stdio_for_uvicorn

        _prepare_stdio_for_uvicorn()
        config_kwargs["log_config"] = None
    config = uvicorn.Config(app, **config_kwargs)
    append_frozen_log(
        f"uvicorn Config ready host={server.host} port={server.port} "
        f"frozen={is_frozen()} static={server.static_dir} ws={ws_impl}"
    )

    class _DanmuWebUvicornServer(uvicorn.Server):
        def __init__(self, cfg, owner):
            super().__init__(cfg)
            self._owner = owner

        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                self._owner._on_uvicorn_started()

    server._server = _DanmuWebUvicornServer(config, server)

    if is_frozen() and sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        append_frozen_log("uvicorn serve() starting")
        asyncio.run(server._server.serve())
        append_frozen_log("uvicorn serve() exited")
    except SystemExit:
        if not server._ready.is_set():
            server._bind_failed.set()
            msg = (
                f"Web 控制台端口 {server.host}:{server.port} 绑定失败。"
                "请关闭占用该端口的进程后重启 DanmuAI。"
            )
            bridge.danmu_app.logger.error(msg)
            append_frozen_log(msg)
    except OSError as exc:
        server._bind_failed.set()
        msg = (
            f"Web 控制台端口 {server.host}:{server.port} 绑定失败: {exc}。"
            "请关闭占用该端口的进程后重启 DanmuAI。"
        )
        bridge.danmu_app.logger.error(msg)
        append_frozen_log(msg)
    except Exception as exc:
        import traceback

        server._bind_failed.set()
        detail = traceback.format_exc()
        bridge.danmu_app.logger.error(f"Web 控制台线程异常退出: {exc!r}")
        append_frozen_log(f"Web console thread crashed (serve):\n{detail}")
