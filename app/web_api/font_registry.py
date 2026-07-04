"""字体文件导入 / 列表 / 删除路由：POST /api/fonts/import + GET /api/fonts + DELETE /api/fonts/{sha256}。

W-FONT-002 配套：上传 .ttf/.otf 文件后由 ``app.font_registry`` 复制到
``%APPDATA%/DanmuAI/fonts/``，记入 config 的 ``imported_fonts`` JSON 数组。

注册方式：``app.web_api.routes`` 调用 ``register_font_registry_routes(app, bridge, check_token)``。
写操作（import / delete）经 ``WebConsoleBridge.invoke_on_main`` 回到主线程，避免 HTTP 线程
直接修改 Qt/文件系统。
"""

from __future__ import annotations

from fastapi import File, Header, HTTPException, Path, UploadFile

from app.web_api.auth import require_auth
from app.translations import tr
from app.web_console import MainThreadInvokeTimeout


def register_font_registry_routes(app, bridge, check_token) -> None:
    @app.post("/api/fonts/import")
    @require_auth(check_token)
    async def fonts_import(
        file: UploadFile = File(...),
        authorization: str | None = Header(default=None),
    ):
        data = await file.read()
        try:
            record = bridge.invoke_on_main(
                bridge.danmu_app.font_registry.import_bytes,
                data,
                file.filename or "uploaded.ttf",
            )
        except MainThreadInvokeTimeout as exc:
            raise HTTPException(status_code=504, detail=tr("common.mainThreadTimeout")) from exc
        except ValueError as exc:
            detail = str(exc)
            if detail == tr("fontRegistry.unavailable"):
                raise HTTPException(status_code=503, detail=detail) from exc
            raise HTTPException(status_code=400, detail=detail) from exc
        registry = bridge.danmu_app.font_registry
        return {"ok": True, **record, "families": registry.list_families()}

    @app.get("/api/fonts")
    @require_auth(check_token)
    def fonts_list(authorization: str | None = Header(default=None)):
        registry = bridge.danmu_app.font_registry
        return {
            "families": registry.list_families(),
            "imported": registry.list_imported(),
        }

    @app.delete("/api/fonts/{sha256}")
    @require_auth(check_token)
    def fonts_delete(
        sha256: str = Path(..., pattern=r"^[0-9a-f]{64}$"),
        authorization: str | None = Header(default=None),
    ):
        try:
            ok = bridge.invoke_on_main(bridge.danmu_app.font_registry.delete, sha256)
        except MainThreadInvokeTimeout as exc:
            raise HTTPException(status_code=504, detail=tr("common.mainThreadTimeout")) from exc
        except ValueError as exc:
            if str(exc) == tr("fontRegistry.unavailable"):
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            raise
        if not ok:
            raise HTTPException(status_code=404, detail=tr("fontRegistry.recordNotFound"))
        registry = bridge.danmu_app.font_registry
        return {"ok": True, "families": registry.list_families()}
