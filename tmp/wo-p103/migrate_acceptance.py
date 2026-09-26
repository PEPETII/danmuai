"""W-AUDIT-MODEL-IDENTITY-001 手工验收：老库迁移 + 两个本地假 endpoint 的真实请求。

只在临时目录里创建数据库；不接触真实账户密钥（全部使用虚拟 key）。
运行： TEMP=<dir> TMP=<dir> /c/Python314/python.exe tmp/wo-p103/migrate_acceptance.py
退出码：0 = 全部验收点通过；1 = 有失败点（stdout 打印明细）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from app.ai_client_requests import resolve_request_credentials_for_persona  # noqa: E402
from app.config_store import ConfigStore  # noqa: E402
from app.config_store.storage_models import (  # noqa: E402
    invalidate_custom_models_cache_for_store,
)
from app.persona_manager import (  # noqa: E402
    PersonaManager,
    PersonaModelBindingError,
    resolve_persona_model_binding,
)
from app.providers.request_planner import GenerationRequest, plan_http_request  # noqa: E402

WORK = Path(os.environ.get("TEMP") or REPO / "tmp" / "wo-p103")
VERBOSE = True
FAILURES: list[str] = []
NOTES: list[str] = []

KEY_SHARED_A = "sk-virtual-key-aaaaaaaaaaaa"
KEY_SHARED_B = "sk-virtual-key-bbbbbbbbbbbb"
KEY_UNIQUE = "sk-virtual-key-cccccccccccc"
SHARED_MODEL = "virtual-shared-model"
UNIQUE_MODEL = "virtual-unique-model"


def check(label: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {label}" + (f" :: {detail}" if detail else "")
    print(line)
    if not ok:
        FAILURES.append(label)


def note(text: str) -> None:
    print(f"       {text}")
    NOTES.append(text)


def mask(value: str) -> str:
    text = str(value or "")
    if not text:
        return "(empty)"
    if len(text) <= 10:
        return text[:2] + "..."
    return f"{text[:7]}...{text[-4:]} (len={len(text)})"


def snapshot(label: str, store: ConfigStore) -> dict:
    models = store.get_custom_models()
    raw = store.conn.execute(
        "SELECT value FROM config WHERE key='custom_models'"
    ).fetchone()
    raw_text = raw[0] if raw else ""
    bindings = json.loads(store.get("persona_model_bindings", "{}") or "{}")
    view = {
        "profiles": [
            {
                "profile_id": m.get("profile_id"),
                "name": m.get("name"),
                "default_model_id": m.get("default_model_id"),
                "endpoint": m.get("endpoint"),
                "apiKey": mask(m.get("apiKey", "")),
            }
            for m in models
        ],
        "bindings": bindings,
        "raw_has_plaintext_key": any(
            key in raw_text
            for key in (KEY_SHARED_A, KEY_SHARED_B, KEY_UNIQUE)
        ),
    }
    print(f"--- 快照 {label} ---")
    print(json.dumps(view, ensure_ascii=False, indent=2))
    return view


# --- 本地假 endpoint ---------------------------------------------------------


class _Recorder(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler 接口)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        type(self).received.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body_len": len(body),
            }
        )
        payload = json.dumps({"ok": True, "provider": "fake"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):  # 静音
        return


def start_fake_endpoint() -> tuple[ThreadingHTTPServer, str, type]:
    handler = type("_RecorderInstance", (_Recorder,), {"received": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/v1", handler


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    db_path = WORK / "acceptance.db"
    if db_path.exists():
        db_path.unlink()

    print("=" * 78)
    print("步骤 1：构造老库（无 profile_id + 共享模型名 + 悬挂/歧义旧绑定）")
    print("=" * 78)
    store = ConfigStore(db_path=db_path)
    try:
        assert store._fernet is not None, "需要 cryptography/Fernet"
        legacy_profiles = [
            {
                "name": "Shared-A",
                "model_ids": [SHARED_MODEL],
                "default_model_id": SHARED_MODEL,
                "max_tokens": 512,
                "mode": "openai-compatible",
                "endpoint": "http://127.0.0.1:1/v1",
                "apiKey": KEY_SHARED_A,
                "provider": "custom_openai",
            },
            {
                "name": "Shared-B",
                "model_ids": [SHARED_MODEL],
                "default_model_id": SHARED_MODEL,
                "max_tokens": 512,
                "mode": "openai-compatible",
                "endpoint": "http://127.0.0.1:2/v1",
                "apiKey": KEY_SHARED_B,
                "provider": "custom_openai",
            },
            {
                "name": "Unique-C",
                "model_ids": [UNIQUE_MODEL],
                "default_model_id": UNIQUE_MODEL,
                "max_tokens": 512,
                "mode": "openai-compatible",
                "endpoint": "http://127.0.0.1:3/v1",
                "apiKey": KEY_UNIQUE,
                "provider": "custom_openai",
            },
        ]
        encoded = []
        for profile in legacy_profiles:
            entry = dict(profile)
            entry["apiKey"] = store._fernet.encrypt(entry["apiKey"].encode()).decode()
            encoded.append(entry)
        store.set("custom_models", json.dumps(encoded, ensure_ascii=False))
        invalidate_custom_models_cache_for_store(store)
        store.set(
            "persona_model_bindings",
            json.dumps(
                {
                    "唯一绑定人格": UNIQUE_MODEL,  # 唯一匹配 → 应迁移为版本化
                    "歧义绑定人格": SHARED_MODEL,  # 重复名 → 保留 unresolved
                },
                ensure_ascii=False,
            ),
        )
        before = snapshot("迁移前", store)
    finally:
        store.close()

    check("迁移前：旧档案无 profile_id", all(p["profile_id"] is None for p in before["profiles"]))
    check("迁移前：绑定为旧字符串", before["bindings"] == {
        "唯一绑定人格": UNIQUE_MODEL,
        "歧义绑定人格": SHARED_MODEL,
    })
    check("迁移前：原始行不含明文密钥", before["raw_has_plaintext_key"] is False)

    print()
    print("=" * 78)
    print("步骤 2：重新打开（启动期受控迁移）")
    print("=" * 78)
    store = ConfigStore(db_path=db_path)
    try:
        after = snapshot("迁移后", store)
        ids_first = [p["profile_id"] for p in after["profiles"]]
        check(
            "迁移后：全部档案获得非空且唯一的 profile_id",
            all(isinstance(pid, str) and pid for pid in ids_first)
            and len(set(ids_first)) == 3,
            f"ids={ids_first}",
        )
        check("迁移后：原始行仍不含明文密钥", after["raw_has_plaintext_key"] is False)

        raw_models = json.loads(
            store.conn.execute(
                "SELECT value FROM config WHERE key='custom_models'"
            ).fetchone()[0]
        )
        cipher_ok = all(
            isinstance(entry.get("apiKey"), str)
            and entry["apiKey"].startswith("gAAAAA")
            and len(entry["apiKey"]) >= 57
            for entry in raw_models
        )
        check("迁移后：custom_models.apiKey 仍为 Fernet 密文", cipher_ok)
        for entry in raw_models:
            note(f"密文样本 {entry['name']}: {mask(str(entry.get('apiKey')))}")

        unique_binding = after["bindings"].get("唯一绑定人格")
        check(
            "迁移后：唯一匹配旧绑定升级为版本化结构",
            isinstance(unique_binding, dict)
            and unique_binding.get("profile_id") == ids_first[2]
            and unique_binding.get("model_id") == UNIQUE_MODEL
            and unique_binding.get("v") == 1,
            json.dumps(unique_binding, ensure_ascii=False),
        )
        check(
            "迁移后：重复名旧绑定保留 unresolved 原文（不猜测）",
            after["bindings"].get("歧义绑定人格") == SHARED_MODEL,
        )

        personae = PersonaManager(store)
        check(
            "诊断：歧义绑定状态 = unresolved",
            personae.describe_model_binding("歧义绑定人格")["status"] == "unresolved",
        )
        try:
            resolve_persona_model_binding(store, "歧义绑定人格")
            check("显式歧义绑定不回退首档案", False, "未抛出 PersonaModelBindingError")
        except PersonaModelBindingError as exc:
            check(
                "显式歧义绑定不回退首档案（抛可观察错误且不含密钥）",
                exc.code == "unresolved"
                and KEY_SHARED_A not in str(exc)
                and KEY_SHARED_B not in str(exc)
                and KEY_UNIQUE not in str(exc),
                f"code={exc.code} message={exc}",
            )
    finally:
        store.close()

    print()
    print("=" * 78)
    print("步骤 3：重复执行 / 重启稳定")
    print("=" * 78)
    ids_per_run = [ids_first]
    for _ in range(2):
        reopened = ConfigStore(db_path=db_path)
        try:
            ids_per_run.append(
                [p["profile_id"] for p in reopened.get_custom_models()]
            )
        finally:
            reopened.close()
    check(
        "重复打开：profile_id 稳定",
        all(ids == ids_first for ids in ids_per_run),
        str(ids_per_run),
    )

    print()
    print("=" * 78)
    print("步骤 4：两个本地假 endpoint 的真实请求（绑定后命中正确档案）")
    print("=" * 78)
    server_a, endpoint_a, handler_a = start_fake_endpoint()
    server_b, endpoint_b, handler_b = start_fake_endpoint()
    try:
        store = ConfigStore(db_path=db_path)
        try:
            models = store.get_custom_models()
            by_name = {m["name"]: m for m in models}
            for target, endpoint in (
                ("Shared-A", endpoint_a),
                ("Shared-B", endpoint_b),
            ):
                entry = dict(by_name[target])
                entry["endpoint"] = endpoint
                store.set_custom_models(
                    [
                        entry if m["profile_id"] == entry["profile_id"] else m
                        for m in models
                    ]
                )
                models = store.get_custom_models()

            profiles = store.get_custom_models()
            pid_a = next(p["profile_id"] for p in profiles if p["name"] == "Shared-A")
            pid_b = next(p["profile_id"] for p in profiles if p["name"] == "Shared-B")
            personae = PersonaManager(store)
            personae.set_model_binding("甲方人格", profile_id=pid_a)
            personae.set_model_binding("乙方人格", profile_id=pid_b)

            for persona, endpoint, handler, key in (
                ("甲方人格", endpoint_a, handler_a, KEY_SHARED_A),
                ("乙方人格", endpoint_b, handler_b, KEY_SHARED_B),
            ):
                creds = resolve_request_credentials_for_persona(store, persona)
                assert creds is not None
                planned = plan_http_request(
                    GenerationRequest(
                        purpose="visual_danmu",
                        model_id=creds[2],
                        endpoint=creds[0],
                        api_key=creds[1],
                        api_mode=creds[3],
                    )
                )
                request = urllib.request.Request(
                    planned.url,
                    data=json.dumps(planned.json_body).encode("utf-8"),
                    headers=planned.headers,
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    body = response.read()
                check(
                    f"{persona}：请求命中 {endpoint} 且回调成功",
                    response.status == 200 and b'"ok": true' in body,
                    f"url={planned.url} status={response.status}",
                )
                check(
                    f"{persona}：使用正确档案的密钥",
                    handler.received
                    and handler.received[-1]["authorization"] == f"Bearer {key}",
                    f"sent={handler.received[-1] if handler.received else None}",
                )
                check(
                    f"{persona}：上游 model_id 正确传给 provider",
                    planned.model_id == SHARED_MODEL
                    and f'"model": "{SHARED_MODEL}"' in json.dumps(planned.json_body),
                    f"model_id={planned.model_id}",
                )
                note(f"{persona}: endpoint={endpoint} key={mask(key)}")
        finally:
            store.close()
    finally:
        server_a.shutdown()
        server_b.shutdown()

    print()
    print("=" * 78)
    if FAILURES:
        print(f"结果：FAIL（{len(FAILURES)} 项）")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("结果：PASS（全部验收点通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
