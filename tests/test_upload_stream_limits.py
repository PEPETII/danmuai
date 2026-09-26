from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.web_api import custom_css_routes
from app.web_api import font_registry as font_routes
from app.web_api.upload_limits import (
    UploadSizeLimitExceeded,
    read_upload_with_limit,
    reject_upload_if_too_large,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _ChunkedUpload:
    def __init__(self, data: bytes, *, size: int | None = None) -> None:
        self._data = data
        self._offset = 0
        self.size = size
        self.read_sizes: list[int] = []
        self.returned_bytes = 0

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            size = len(self._data) - self._offset
        end = min(self._offset + size, len(self._data))
        chunk = self._data[self._offset : end]
        self._offset = end
        self.returned_bytes += len(chunk)
        return chunk


def test_bounded_reader_reassembles_cross_chunk_css_attack_before_validation():
    payload = b".card{background:url(//example.com/a.png)}"
    upload = _ChunkedUpload(payload)

    data = asyncio.run(
        read_upload_with_limit(
            upload,
            limit=len(payload),
            detail="too large",
            chunk_size=3,
        )
    )

    assert data == payload
    assert len(upload.read_sizes) > 2
    assert upload.returned_bytes == len(payload)


@pytest.mark.parametrize("length", [3, 4])
def test_bounded_reader_accepts_below_and_at_limit(length):
    upload = _ChunkedUpload(b"x" * length)

    assert asyncio.run(
        read_upload_with_limit(upload, limit=4, detail="too large", chunk_size=2)
    ) == b"x" * length


def test_bounded_reader_stops_after_limit_plus_one_byte():
    limit = 7
    upload = _ChunkedUpload(b"x" * (limit + 10))

    with pytest.raises(UploadSizeLimitExceeded, match="too large"):
        asyncio.run(
            read_upload_with_limit(upload, limit=limit, detail="too large", chunk_size=4)
        )

    assert upload.returned_bytes == limit + 1


def test_content_length_shortcut_rejects_without_reading_when_part_size_unknown():
    upload = _ChunkedUpload(b"safe", size=None)

    with pytest.raises(UploadSizeLimitExceeded, match="too large"):
        reject_upload_if_too_large(
            upload,
            content_length=5,
            limit=4,
            detail="too large",
        )

    assert upload.read_sizes == []


def _css_client(service, monkeypatch, *, limit: int = 32):
    monkeypatch.setattr(custom_css_routes.custom_css, "MAX_CUSTOM_CSS_BYTES", limit)
    app = FastAPI()
    bridge = SimpleNamespace(danmu_app=SimpleNamespace(config=object()))

    def invoke_main(fn, *args):
        return fn(*args)

    custom_css_routes.register_custom_css_routes(
        app,
        bridge,
        lambda _authorization=None: None,
        invoke_main,
    )
    monkeypatch.setattr(custom_css_routes.custom_css, "import_custom_css_bytes", service)
    return TestClient(app)


def test_css_route_rejects_oversize_before_existing_service(monkeypatch):
    service = MagicMock()
    client = _css_client(service, monkeypatch, limit=4)

    response = client.post(
        "/api/floating-panel/custom-css/import",
        files={"file": ("too-large.css", b"12345", "text/css")},
    )

    assert response.status_code == 413
    service.assert_not_called()


@pytest.mark.parametrize("length", [3, 4])
def test_css_route_accepts_below_and_at_service_limit(monkeypatch, length):
    service = MagicMock(return_value={"file_name": "ok.css", "name": "ok.css"})
    client = _css_client(service, monkeypatch, limit=4)

    response = client.post(
        "/api/floating-panel/custom-css/import",
        files={"file": ("ok.css", b"x" * length, "text/css")},
    )

    assert response.status_code == 200
    service.assert_called_once()


def test_css_route_passes_one_reassembled_payload_to_existing_service(monkeypatch):
    payload = b".x{background:url(//example.com/a.png)}"
    service = MagicMock(side_effect=ValueError("blocked by CSS safety validation"))
    client = _css_client(service, monkeypatch, limit=len(payload) + 4)
    monkeypatch.setattr(custom_css_routes, "UPLOAD_READ_CHUNK_SIZE", 3, raising=False)

    response = client.post(
        "/api/floating-panel/custom-css/import",
        files={"file": ("attack.css", payload, "text/css")},
    )

    assert response.status_code == 400
    service.assert_called_once()
    assert service.call_args.args[1] == payload


def _font_client(service, monkeypatch, *, limit: int = 32):
    monkeypatch.setattr(font_routes.font_registry_service, "MAX_FILE_BYTES", limit)
    service.list_families.return_value = ["ImportedFont"]
    app = FastAPI()
    registry = SimpleNamespace(
        import_bytes=service.import_bytes,
        list_families=service.list_families,
    )

    def invoke_on_main(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    bridge = SimpleNamespace(
        danmu_app=SimpleNamespace(font_registry=registry),
        invoke_on_main=invoke_on_main,
    )
    font_routes.register_font_registry_routes(
        app,
        bridge,
        lambda _authorization=None: None,
    )
    return TestClient(app)


def test_font_route_rejects_oversize_before_existing_service(monkeypatch):
    service = MagicMock()
    client = _font_client(service, monkeypatch, limit=4)

    response = client.post(
        "/api/fonts/import",
        files={"file": ("too-large.ttf", b"12345", "font/ttf")},
    )

    assert response.status_code == 413
    service.import_bytes.assert_not_called()


@pytest.mark.parametrize("length", [3, 4])
def test_font_route_accepts_below_and_at_service_limit(monkeypatch, length):
    service = MagicMock()
    service.import_bytes.return_value = {
        "sha256": "a" * 64,
        "family": "ImportedFont",
        "original_name": "ok.ttf",
        "size": length,
    }
    client = _font_client(service, monkeypatch, limit=4)

    response = client.post(
        "/api/fonts/import",
        files={"file": ("ok.ttf", b"x" * length, "font/ttf")},
    )

    assert response.status_code == 200
    service.import_bytes.assert_called_once_with(b"x" * length, "ok.ttf")
