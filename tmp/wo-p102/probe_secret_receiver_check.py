"""W-AUDIT-PROBE-SECRET-001 本机受控接收器验证（临时脚本，仅用虚拟 key）。

只向 127.0.0.1 上的受控 http.server 发探测请求，不使用任何真实凭据。
验证目标：
  1. 掩码 key + 调用方替换 endpoint → 400，接收端 B **未收到任何请求**；
  2. 显式新 key + 替换 endpoint → 允许，接收端 B 只看到新 key；
  3. 同一档案（无 endpoint 覆盖）掩码 key → 允许，接收端 A 收到已存 key（合法复用）；
  4. 自定义档案 probe 掩码 key + 改 endpoint → 400，接收端 B 未收到请求。

本脚本放在仓库 ``tmp/`` 下，不进入跟踪路径；报告中有说明。
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config_store import ConfigStore  # noqa: E402
from app.main_web_facade_mixin import DanmuAppWebFacadeMixin  # noqa: E402
from app.web_api.routes import register_web_routes  # noqa: E402

STORED_KEY = "sk-virtual-stored-profile-key"
NEW_KEY = "sk-virtual-caller-supplied-key"
MASKED = "********"

RECEIVED: dict[str, list[dict]] = {}


class _Recorder(BaseHTTPRequestHandler):
    label = "?"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        RECEIVED[self.label].append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "body_has_key": STORED_KEY in body.decode("utf-8", "replace"),
            }
        )
        payload = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence
        return


def _start_receiver(label: str) -> tuple[ThreadingHTTPServer, str]:
    RECEIVED[label] = []
    handler = type(f"_Recorder_{label}", (_Recorder,), {"label": label})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


class _ProbeHost(DanmuAppWebFacadeMixin):
    def __init__(self, config):
        self.config = config


def _client(host) -> TestClient:
    api = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    bridge.danmu_app = host

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(api, bridge, _check_token)
    return TestClient(api, raise_server_exceptions=False)


def main() -> int:
    tmp_dir = Path(__file__).resolve().parent
    server_b, endpoint_b = _start_receiver("B_attacker_endpoint")
    server_a, endpoint_a = _start_receiver("A_saved_profile_endpoint")

    config = ConfigStore(db_path=tmp_dir / "receiver-check.db")
    config.set_custom_models(
        [
            {
                "name": "LocalCompat",
                "model_ids": ["local-model"],
                "default_model_id": "local-model",
                "mode": "openai-compatible",
                "endpoint": endpoint_a,
                "apiKey": STORED_KEY,
                "provider": "custom_openai",
            }
        ]
    )
    host = _ProbeHost(config)
    client = _client(host)

    results: list[str] = []
    failures: list[str] = []

    # Case 1: generic /api/probe, masked key + replaced endpoint
    before_b = len(RECEIVED["B_attacker_endpoint"])
    res1 = client.post(
        "/api/probe",
        json={
            "api_endpoint": endpoint_b,
            "api_key": MASKED,
            "model": "local-model",
            "api_mode": "openai-compatible",
        },
    )
    b_hits_1 = len(RECEIVED["B_attacker_endpoint"]) - before_b
    results.append(
        f"case1 masked+changed-endpoint: HTTP {res1.status_code}, receiver B hits={b_hits_1}, "
        f"body={res1.text[:160]}"
    )
    if res1.status_code != 400 or b_hits_1 != 0:
        failures.append("case1")

    # Case 2: generic /api/probe, explicit new key + replaced endpoint
    before_b = len(RECEIVED["B_attacker_endpoint"])
    res2 = client.post(
        "/api/probe",
        json={
            "api_endpoint": endpoint_b,
            "api_key": NEW_KEY,
            "model": "local-model",
            "api_mode": "openai-compatible",
        },
    )
    new_hits = RECEIVED["B_attacker_endpoint"][before_b:]
    results.append(
        f"case2 explicit-new-key+changed-endpoint: HTTP {res2.status_code}, receiver B hits="
        f"{len(new_hits)}, auth={[h['authorization'] for h in new_hits]}, "
        f"stored_key_seen={any(h['body_has_key'] for h in new_hits)}"
    )
    if (
        res2.status_code != 200
        or len(new_hits) != 1
        or new_hits[0]["authorization"] != f"Bearer {NEW_KEY}"
        or any(h["body_has_key"] for h in new_hits)
    ):
        failures.append("case2")

    # Case 3: generic /api/probe, masked key, no scope override -> saved profile target
    before_a = len(RECEIVED["A_saved_profile_endpoint"])
    res3 = client.post("/api/probe", json={"api_key": MASKED})
    a_hits = RECEIVED["A_saved_profile_endpoint"][before_a:]
    results.append(
        f"case3 masked-key-same-scope: HTTP {res3.status_code}, receiver A hits={len(a_hits)}, "
        f"auth={[h['authorization'] for h in a_hits]}"
    )
    if res3.status_code != 200 or len(a_hits) != 1 or a_hits[0]["authorization"] != f"Bearer {STORED_KEY}":
        failures.append("case3")

    # Case 4: custom-model probe route, masked key + replaced endpoint
    before_b = len(RECEIVED["B_attacker_endpoint"])
    res4 = client.post(
        "/api/custom-models/probe",
        json={
            "name": "LocalCompat",
            "model_ids": ["local-model"],
            "default_model_id": "local-model",
            "mode": "openai-compatible",
            "endpoint": endpoint_b,
            "apiKey": MASKED,
            "provider": "custom_openai",
            "index": 0,
            "model_id": "local-model",
        },
    )
    b_hits_4 = len(RECEIVED["B_attacker_endpoint"]) - before_b
    results.append(
        f"case4 profile-probe masked+changed-endpoint: HTTP {res4.status_code}, "
        f"receiver B hits={b_hits_4}, body={res4.text[:160]}"
    )
    if res4.status_code != 400 or b_hits_4 != 0:
        failures.append("case4")

    # Case 5: custom-model probe route, masked key, same scope
    before_a = len(RECEIVED["A_saved_profile_endpoint"])
    res5 = client.post(
        "/api/custom-models/probe",
        json={
            "name": "LocalCompat",
            "model_ids": ["local-model"],
            "default_model_id": "local-model",
            "mode": "openai-compatible",
            "endpoint": endpoint_a,
            "apiKey": MASKED,
            "provider": "custom_openai",
            "index": 0,
            "model_id": "local-model",
        },
    )
    a_hits_5 = RECEIVED["A_saved_profile_endpoint"][before_a:]
    results.append(
        f"case5 profile-probe same-scope: HTTP {res5.status_code}, receiver A hits={len(a_hits_5)}, "
        f"auth={[h['authorization'] for h in a_hits_5]}"
    )
    if res5.status_code != 200 or len(a_hits_5) != 1 or a_hits_5[0]["authorization"] != f"Bearer {STORED_KEY}":
        failures.append("case5")

    server_a.shutdown()
    server_b.shutdown()

    print("=== W-AUDIT-PROBE-SECRET-001 receiver evidence ===")
    for line in results:
        print("-", line)
    print("stored key present in any attacker-endpoint body:", any(
        h["body_has_key"] for h in RECEIVED["B_attacker_endpoint"]
    ))
    print("RESULT:", "PASS" if not failures else f"FAIL {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
