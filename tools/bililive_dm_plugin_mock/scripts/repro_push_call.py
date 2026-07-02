"""
Reproduce the PUSH-004 path: DanmuAI POSTs to the plugin HttpListener.

Mirrors app/application/bililive_dm_push_service.push_batch_to_bililive_dm:
  1. Serialize BililiveDmPushRequest -> snake_case JSON.
  2. POST application/json; charset=utf-8.
  3. Timeout = 3s.
  4. On 2xx, print displayed count from PushResponse.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "http://127.0.0.1:18766/api/plugin/danmuai/push/"
TIMEOUT = 3.0
PLUGIN_SECRET_HEADER = "X-DanmuAI-Plugin-Secret"


def _read_plugin_secret() -> str | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    path = Path(appdata) / "DanmuAI" / "bililive_dm_plugin.secret"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None

payload = {
    "source": "danmuai_main",
    "batch_id": 99,
    "items": [
        "【push-repro】DanmuAI 主动推送测试",
        "第二条 mock 弹幕",
    ],
    "persona": "repro",
}

body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
headers = {"Content-Type": "application/json; charset=utf-8"}
secret = _read_plugin_secret()
if secret:
    headers[PLUGIN_SECRET_HEADER] = secret
req = urllib.request.Request(
    ENDPOINT,
    data=body,
    headers=headers,
    method="POST",
)

t0 = time.perf_counter()
try:
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        status = resp.status
        elapsed = time.perf_counter() - t0
        raw = resp.read()
        print(f"[OK] status={status} elapsed={elapsed:.3f}s body={raw!r}")
        decoded = json.loads(raw.decode("utf-8"))
        if not decoded.get("ok"):
            print(f"[PUSH-FAIL] error={decoded.get('error')!r}")
            sys.exit(2)
        print(f"[DISPLAYED] count={decoded.get('displayed')}")
except urllib.error.HTTPError as exc:
    elapsed = time.perf_counter() - t0
    print(f"[HTTP-ERR] status={exc.code} elapsed={elapsed:.3f}s body={exc.read()!r}")
    sys.exit(3)
except TimeoutError:
    elapsed = time.perf_counter() - t0
    print(f"[PUSH-TIMEOUT] elapsed={elapsed:.3f}s (limit {TIMEOUT}s)")
    sys.exit(4)
except urllib.error.URLError as exc:
    elapsed = time.perf_counter() - t0
    print(f"[PUSH-URLERR] elapsed={elapsed:.3f}s reason={exc.reason!r}")
    sys.exit(5)
