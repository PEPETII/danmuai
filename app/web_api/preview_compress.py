"""图像压缩预览路由：POST /api/preview/compress。

Web「设置→图像」页上传一张图片预览压缩后的 Base64 data URI；
max_width 1024 / quality 85 是运行时主链路截图压缩的默认值，本路由复用
``app.image_compress.compress_image_bytes`` 让用户看到压缩后效果再保存设置。

注册方式：``app.web_api.routes`` 调用 ``register_preview_compress_route(app, check_token)``。
"""

from __future__ import annotations

from typing import Callable

from fastapi import File, Form, Header, HTTPException, UploadFile
from PIL import UnidentifiedImageError

from app.config_defaults import DEFAULT_IMAGE_MAX_WIDTH
from app.image_compress import compress_image_bytes
from app.web_api.auth import require_auth


def register_preview_compress_route(app, check_token: Callable) -> None:
    """Module-level registration so UploadFile resolves under Python 3.14 + Pydantic v2."""

    @app.post("/api/preview/compress")
    @require_auth(check_token)
    async def preview_compress(
        file: UploadFile = File(...),
        max_width: int = Form(DEFAULT_IMAGE_MAX_WIDTH),
        quality: int = Form(85),
        authorization: str | None = Header(default=None),
    ):
        max_width = max(64, min(max_width, 4096))
        quality = max(1, min(quality, 95))
        data = await file.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="图片太大了，请换一张小一点的~")
        try:
            return compress_image_bytes(data, max_width=max_width, quality=quality)
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            raise HTTPException(status_code=400, detail=f"小助手读不懂这张图：{exc}") from exc
