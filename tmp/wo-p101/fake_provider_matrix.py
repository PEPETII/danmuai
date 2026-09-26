"""W-AUDIT-PROBE-PARITY-001：本机假 HTTP/SSE 服务矩阵（不使用真实 API key / provider）。

对 5 类假服务行为（+业务过滤/reasoning-only）分别运行：
  A. 基线（``git show HEAD:app/api_probe.py`` 载入为独立模块，代表修复前语义）；
  B. 当前工作区（``stage="full"`` 完整阶段链）。

输出对照表，供完成报告引用。脚本自身在 127.0.0.1 随机端口建服务器，运行后销毁。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from app.providers.model_discovery import clear_discovery_cache  # noqa: E402

MODEL = "matrix-vision-model"
KEY = "sk-virtual-matrix-key"
PROFILE_PARAMS = {"temperature": 0.3, "thinking_effort": "low", "max_tokens": 768}

MODES = (
    "text_only",
    "vision_reject",
    "malformed_sse",
    "empty_sse",
    "reasoning_only_sse",
    "filtered_items",
    "legal_sse",
)


def _sse(*chunks: str) -> bytes:
    return "".join(f"data: {chunk}\n\n" for chunk in chunks).encode("utf-8")


def _content(text: str) -> str:
    return json.dumps({"choices": [{"delta": {"content": text}}]})


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "legal_sse"

    def log_message(self, *_args):
        return

    def _send(self, status, body, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.endswith("/models"):
            self._send(200, json.dumps({"data": [{"id": MODEL}]}).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {}
        decoded = raw.decode("utf-8", "replace")
        has_image = "image_url" in decoded or "input_image" in decoded
        if self.mode == "text_only" and has_image:
            self._send(404, b'{"error":"no streaming endpoint"}')
            return
        if self.mode == "vision_reject" and has_image:
            self._send(400, b'{"error":"image input not supported"}')
            return
        if not body.get("stream"):
            self._send(200, json.dumps({"choices": [{"message": {"content": "pong"}}]}).encode())
            return
        if self.mode == "text_only":
            self._send(404, b'{"error":"no streaming endpoint"}')
        elif self.mode == "vision_reject":
            self._send(400, b'{"error":"image input not supported"}')
        elif self.mode == "malformed_sse":
            self._send(200, b"not-an-sse-frame\n\nstill not json\n\n", "text/event-stream")
        elif self.mode == "empty_sse":
            self._send(200, _sse("[DONE]"), "text/event-stream")
        elif self.mode == "reasoning_only_sse":
            chunk = json.dumps({"choices": [{"delta": {"reasoning_content": "thinking..."}}]})
            self._send(200, _sse(chunk, "[DONE]"), "text/event-stream")
        elif self.mode == "filtered_items":
            self._send(200, _sse(_content('{"comments": ["comment 1", ":"]}'), "[DONE]"), "text/event-stream")
        else:
            self._send(200, _sse(_content('{"comments": ["合法弹幕候选一", "合法弹幕候选二"]}'), "[DONE]"), "text/event-stream")


def start_server(mode: str):
    handler = type(f"H_{mode}", (Handler,), {"mode": mode})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address
    return server, f"http://{host}:{port}/v1"


def load_baseline_module():
    src = subprocess.check_output(
        ["git", "show", "HEAD:app/api_probe.py"], cwd=str(REPO)
    )
    target = pathlib.Path(__file__).with_name("baseline_api_probe.py")
    target.write_bytes(src)
    spec = importlib.util.spec_from_file_location("baseline_api_probe", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules["baseline_api_probe"] = module
    spec.loader.exec_module(module)
    return module


def _stage(result, name):
    return next((item for item in result.get("stages", []) if item["stage"] == name), None)


def main() -> int:
    import app.api_probe as current

    baseline = load_baseline_module()
    print(f"baseline _STAGES = {sorted(baseline._STAGES)}")
    print(f"current  _STAGES = {sorted(current._STAGES)}")
    print()
    header = f"{'mode':<18} {'baseline(text)':<16} {'baseline(stream/vision)':<26} {'current(full)':<14} stages"
    print(header)
    print("-" * len(header))
    failures = []
    for mode in MODES:
        server, endpoint = start_server(mode)
        try:
            clear_discovery_cache()
            base_text = baseline.probe_connection(endpoint, KEY, MODEL, "openai-compatible", stage="text")
            clear_discovery_cache()
            legacy_stage = "stream" if mode in {"malformed_sse", "empty_sse", "reasoning_only_sse", "filtered_items", "legal_sse"} else "vision"
            base_legacy = baseline.probe_connection(endpoint, KEY, MODEL, "openai-compatible", stage=legacy_stage)
            clear_discovery_cache()
            cur = current.probe_connection(
                endpoint, KEY, MODEL, "openai-compatible",
                stage="full", profile_params=dict(PROFILE_PARAMS),
            ).to_dict()
        finally:
            server.shutdown()
            server.server_close()
        stages = " ".join(
            f"{item['stage']}={item['status']}" for item in cur["stages"]
        ) or "-"
        print(
            f"{mode:<18} ok={str(base_text.ok):<12} "
            f"{legacy_stage}:ok={str(base_legacy.ok):<18} "
            f"ok={str(cur['ok']):<10} complete={cur['complete']} {stages}"
        )
        failures.append(
            {
                "mode": mode,
                "baseline_text_ok": base_text.ok,
                "baseline_legacy_stage": legacy_stage,
                "baseline_legacy_ok": base_legacy.ok,
                "current_ok": cur["ok"],
                "current_complete": cur["complete"],
                "current_stages": {item["stage"]: item["status"] for item in cur["stages"]},
            }
        )
    print()
    print("JSON:", json.dumps(failures, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
