"""Floating-panel custom CSS file and template routes."""

from __future__ import annotations

from typing import Callable

from fastapi import File, Header, HTTPException, Path, UploadFile

from app import floating_panel_custom_css as custom_css
from app.translations import tr
from app.web_api.auth import require_auth
from app.web_console import MainThreadInvokeTimeout


def register_custom_css_routes(
    app,
    bridge,
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/floating-panel/custom-css/templates")
    @require_auth(check_token)
    def custom_css_templates(authorization: str | None = Header(default=None)):
        return {"templates": custom_css.custom_css_templates()}

    @app.get("/api/floating-panel/custom-css")
    @require_auth(check_token)
    def custom_css_list(authorization: str | None = Header(default=None)):
        return {"files": custom_css.list_custom_css_files(bridge.danmu_app.config)}

    @app.get("/api/floating-panel/custom-css/{file_name}")
    @require_auth(check_token)
    def custom_css_read(
        file_name: str = Path(..., min_length=1, max_length=255),
        authorization: str | None = Header(default=None),
    ):
        try:
            name = custom_css.normalize_custom_css_file_name(file_name)
            if not name:
                raise ValueError("CSS 文件名无效")
            return {
                "file_name": name,
                "css": custom_css.read_custom_css(bridge.danmu_app.config, name),
            }
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="CSS 文件不存在") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/floating-panel/custom-css/import")
    @require_auth(check_token)
    async def custom_css_import(
        file: UploadFile = File(...),
        authorization: str | None = Header(default=None),
    ):
        data = await file.read()
        try:
            record = invoke_main(
                custom_css.import_custom_css_bytes,
                bridge.danmu_app.config,
                data,
                file.filename or "uploaded.css",
            )
        except MainThreadInvokeTimeout as exc:
            raise HTTPException(status_code=504, detail=tr("common.mainThreadTimeout")) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, **record}

    @app.post("/api/floating-panel/custom-css/open-folder")
    @require_auth(check_token)
    def custom_css_open_folder(authorization: str | None = Header(default=None)):
        try:
            return invoke_main(custom_css.open_custom_css_directory, bridge.danmu_app.config)
        except MainThreadInvokeTimeout as exc:
            raise HTTPException(status_code=504, detail=tr("common.mainThreadTimeout")) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="无法打开 CSS 文件夹") from exc
