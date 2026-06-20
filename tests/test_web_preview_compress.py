"""Web API: POST /api/preview/compress (multipart UploadFile)."""

import io
from unittest.mock import MagicMock

import pytest
from app.web_api.routes import register_web_routes
from app.web_console import WebConsoleBridge
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

_TEST_TOKEN = "test-preview-token"


def _make_bridge():
    app = MagicMock()
    app.config = MagicMock()
    app.config.get_api_key.return_value = "sk-test"
    app.engine.running = False
    app.engine.get_dedup_profile_snapshot.return_value = None
    app.danmu_count = 0
    app.reply_buffer.size.return_value = 0
    app._visible_display_count.return_value = 0
    app._start_time = 0
    app._total_input_tokens = 0
    app._total_output_tokens = 0
    app.personae.get_active.return_value = []
    app.config.get_int.return_value = 0
    app._web_error_message = ""
    app._web_error_is_error = False
    app.window = None
    app.logger = MagicMock()
    return WebConsoleBridge(app)


def _check_token(authorization: str | None = None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要登录令牌")
    if authorization.removeprefix("Bearer ").strip() != _TEST_TOKEN:
        raise HTTPException(status_code=403, detail="令牌无效")


def _png_bytes(w: int = 400, h: int = 300) -> bytes:
    img = Image.new("RGB", (w, h), color=(40, 120, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def preview_client():
    api = FastAPI()
    register_web_routes(api, _make_bridge(), _check_token)
    return TestClient(api)


def test_preview_compress_returns_jpeg_data_url(preview_client):
    data = _png_bytes(1200, 800)
    res = preview_client.post(
        "/api/preview/compress",
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        files={"file": ("shot.png", data, "image/png")},
        data={"max_width": "768", "quality": "85"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["orig_w"] == 1200
    assert body["out_w"] <= 768
    assert body["preview_data_url"].startswith("data:image/jpeg;base64,")


def test_preview_compress_rejects_missing_token(preview_client):
    res = preview_client.post(
        "/api/preview/compress",
        files={"file": ("shot.png", _png_bytes(), "image/png")},
    )
    assert res.status_code == 401


def test_preview_compress_clamps_oversized_params(preview_client):
    """max_width and quality are clamped to safe upper bounds."""
    data = _png_bytes(1200, 800)
    res = preview_client.post(
        "/api/preview/compress",
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        files={"file": ("shot.png", data, "image/png")},
        data={"max_width": "999999", "quality": "100"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # max_width clamped to 4096; image is 1200px wide so output stays at 1200
    assert body["out_w"] == 1200


def test_preview_compress_clamps_zero_params(preview_client):
    """max_width=0 and quality=0 are clamped to minimum (64 and 1 respectively)."""
    data = _png_bytes(400, 300)
    res = preview_client.post(
        "/api/preview/compress",
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        files={"file": ("shot.png", data, "image/png")},
        data={"max_width": "0", "quality": "0"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # max_width clamped to 64; image is 400px wide so it resizes to 64
    assert body["out_w"] == 64
