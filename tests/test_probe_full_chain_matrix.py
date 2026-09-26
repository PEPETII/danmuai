"""W-AUDIT-PROBE-PARITY-001：完整阶段链的本地假 HTTP/SSE 服务矩阵。

覆盖 5+2 种假服务行为（无真实 provider、无真实 API key）：
- ``text_only``：只有 /models 与非流式文本可用，流式（视觉）端点 404。
- ``vision_reject``：流式端点显式 400 拒绝视觉负载。
- ``malformed_sse``：流式 200 但只返回无法解析的行（无内容、无 [DONE]）。
- ``empty_sse``：流式 200 但只有 ``data: [DONE]``。
- ``reasoning_only_sse``：只有 reasoning_content，没有可见正文。
- ``filtered_items``：合法 SSE，但业务信封全是不可上屏占位内容。
- ``legal_sse``：合法视觉流式响应，可形成有效业务候选。

断言 contract：
- 只有 ``business_parse`` 通过才 ``complete=True``；
- 阶段失败返回稳定 ``stage`` / ``error_category`` / warnings；
- ``vision_stream`` 请求体含图片 + system/user + stream + 档案参数。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from app.api_probe import probe_connection
from app.providers.model_discovery import clear_discovery_cache

_PROBE_MODEL = "matrix-vision-model"
_VIRTUAL_KEY = "sk-virtual-matrix-key"
_PROFILE_PARAMS = {"temperature": 0.3, "thinking_effort": "low", "max_tokens": 768}


def _sse(*chunks: str) -> bytes:
    body = "".join(f"data: {chunk}\n\n" for chunk in chunks)
    return body.encode("utf-8")


def _content_chunk(text: str) -> str:
    return json.dumps({"choices": [{"delta": {"content": text}}]})


class _MatrixHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "legal_sse"
    upstream_requests: list[dict] = []

    def log_message(self, *_args):  # noqa: A003 - silence test server
        return

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server contract
        if self.path.endswith("/models"):
            payload = json.dumps({"data": [{"id": _PROBE_MODEL}]}).encode("utf-8")
            self._send(200, payload)
            return
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):  # noqa: N802 - http.server contract
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = {}
        self.upstream_requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "body": body,
            }
        )
        streaming = bool(body.get("stream"))
        has_image = "image_url" in raw.decode("utf-8", "replace") or "input_image" in raw.decode(
            "utf-8", "replace"
        )
        mode = self.mode
        # 文本-only / 视觉拒绝：任何携带图片的请求都被拒绝（无论流式与否）。
        if mode == "text_only" and has_image:
            self._send(404, b'{"error":"no streaming endpoint"}')
            return
        if mode == "vision_reject" and has_image:
            self._send(400, b'{"error":"image input not supported"}')
            return
        if not streaming:
            self._send(
                200,
                json.dumps({"choices": [{"message": {"content": "pong"}}]}).encode("utf-8"),
            )
            return
        if mode == "malformed_sse":
            self._send(200, b"this-is-not-a-sse-frame\n\nstill not json\n\n", "text/event-stream")
            return
        if mode == "empty_sse":
            self._send(200, _sse("[DONE]"), "text/event-stream")
            return
        if mode == "reasoning_only_sse":
            chunk = json.dumps({"choices": [{"delta": {"reasoning_content": "thinking..."}}]})
            self._send(200, _sse(chunk, "[DONE]"), "text/event-stream")
            return
        if mode == "filtered_items":
            self._send(
                200,
                _sse(_content_chunk('{"comments": ["comment 1", ":"]}'), "[DONE]"),
                "text/event-stream",
            )
            return
        # legal_sse
        self._send(
            200,
            _sse(
                _content_chunk('{"comments": ["这条弹幕来自假服务", "第二条有效候选"]}'),
                "[DONE]",
            ),
            "text/event-stream",
        )


@pytest.fixture
def fake_provider():
    servers = []

    def start(mode: str):
        handler = type(f"Handler_{mode}", (_MatrixHandler,), {"mode": mode, "upstream_requests": []})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        host, port = server.server_address
        return {
            "endpoint": f"http://{host}:{port}/v1",
            "requests": handler.upstream_requests,
        }

    clear_discovery_cache()
    yield start
    clear_discovery_cache()
    for server in servers:
        server.shutdown()
        server.server_close()


def _run_full(endpoint: str) -> dict:
    return probe_connection(
        endpoint,
        _VIRTUAL_KEY,
        _PROBE_MODEL,
        "openai-compatible",
        stage="full",
        profile_params=dict(_PROFILE_PARAMS),
    ).to_dict()


def _stage(result: dict, name: str) -> dict:
    return next(item for item in result["stages"] if item["stage"] == name)


def _stream_requests(requests: list[dict]) -> list[dict]:
    return [item for item in requests if item["body"].get("stream") is True]


def test_text_only_provider_reports_text_stage_only(fake_provider):
    """假服务文本 200、视觉 404：只显示文本阶段通过，完整链失败。"""
    server = fake_provider("text_only")
    result = _run_full(server["endpoint"])

    assert result["complete"] is False
    assert result["ok"] is False
    assert result["stage"] == "full"
    assert _stage(result, "local")["status"] == "passed"
    assert _stage(result, "auth_model")["status"] == "passed"
    assert _stage(result, "text")["status"] == "passed"
    assert _stage(result, "vision_stream")["status"] == "failed"
    assert _stage(result, "business_parse")["status"] == "skipped"
    assert "text_failed" not in result["warnings"]


def test_vision_rejected_provider_fails_vision_stage(fake_provider):
    """流式端点 400：vision 阶段失败并分类，业务阶段未执行。"""
    server = fake_provider("vision_reject")
    result = _run_full(server["endpoint"])

    vision = _stage(result, "vision_stream")
    assert vision["status"] == "failed"
    assert vision["error_category"] == "invalid_content_part"
    assert vision["status_code"] == 400
    assert _stage(result, "business_parse")["status"] == "skipped"
    assert result["complete"] is False


def test_malformed_sse_fails_vision_stream(fake_provider):
    """畸形 SSE（无内容、无终止标记）→ vision_stream 失败为 malformed_stream。"""
    server = fake_provider("malformed_sse")
    result = _run_full(server["endpoint"])

    vision = _stage(result, "vision_stream")
    assert vision["status"] == "failed"
    assert vision["error_category"] == "malformed_stream"
    assert "stream_incomplete" in vision["warnings"]
    assert result["complete"] is False


def test_empty_sse_never_reports_complete_success(fake_provider):
    """空 SSE（仅 [DONE]）→ 业务解析失败，不能显示完整成功。"""
    server = fake_provider("empty_sse")
    result = _run_full(server["endpoint"])

    assert _stage(result, "vision_stream")["status"] == "passed"
    business = _stage(result, "business_parse")
    assert business["status"] == "failed"
    assert business["error_category"] == "empty_output"
    assert "empty_business_items" in business["warnings"]
    assert result["complete"] is False


def test_reasoning_only_sse_fails_business_parse(fake_provider):
    """reasoning-only → 业务解析失败并分类明确。"""
    server = fake_provider("reasoning_only_sse")
    result = _run_full(server["endpoint"])

    vision = _stage(result, "vision_stream")
    assert vision["status"] == "passed"
    assert "reasoning_only" in vision["warnings"]
    business = _stage(result, "business_parse")
    assert business["status"] == "failed"
    assert business["error_category"] == "empty_output"
    assert result["complete"] is False


def test_filtered_items_fail_business_parse(fake_provider):
    """合法 SSE 但业务候选全部被过滤 → 业务解析失败。"""
    server = fake_provider("filtered_items")
    result = _run_full(server["endpoint"])

    assert _stage(result, "vision_stream")["status"] == "passed"
    business = _stage(result, "business_parse")
    assert business["status"] == "failed"
    assert business["error_category"] == "empty_output"
    assert result["complete"] is False


def test_legal_vision_sse_passes_and_sends_formal_payload(fake_provider):
    """合法视觉 SSE：完整阶段通过，且请求体复用正式视觉 payload。"""
    server = fake_provider("legal_sse")
    result = _run_full(server["endpoint"])

    assert result["ok"] is True
    assert result["complete"] is True
    for name in ("local", "auth_model", "text", "vision_stream", "business_parse"):
        assert _stage(result, name)["status"] == "passed", name

    streams = _stream_requests(server["requests"])
    assert len(streams) == 1, "vision 阶段必须只发一次同请求"
    body = streams[0]["body"]
    messages = body["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"]
    assert messages[-1]["role"] == "user"
    parts = messages[-1]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/")
    assert body["stream"] is True
    assert body["temperature"] == 0.3
    assert body.get("max_tokens", body.get("max_completion_tokens")) == 768
    # 密钥只出现在 Authorization，绝不进入 body
    assert _VIRTUAL_KEY not in json.dumps(body)


def test_legal_vision_sse_never_leaks_key_into_result(fake_provider):
    server = fake_provider("legal_sse")
    result = _run_full(server["endpoint"])
    assert _VIRTUAL_KEY not in json.dumps(result, default=str)


def test_rejected_target_does_not_run_network_stages():
    """出站目标被策略拒绝时，直接返回稳定分类，且不产生任何阶段伪造通过。"""
    result = probe_connection(
        "https://10.0.0.9/v1", _VIRTUAL_KEY, _PROBE_MODEL, "openai-compatible", stage="full"
    ).to_dict()
    assert result["ok"] is False
    assert result["error_category"] == "outbound_target_blocked"
    assert result["stage"] == "full"
    assert result["stages"] == []
    assert result["complete"] is False
