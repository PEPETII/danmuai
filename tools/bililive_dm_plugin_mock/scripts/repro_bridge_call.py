"""
Reproduce the BRIDGE-002 failure path that the C# plugin follows.

Plugin's CallDanmuAiAsync flow (net461, mirrored in Python with requests):
  1. Serialize BridgeRequest -> snake_case JSON (Newtonsoft.Json default).
  2. POST as application/json; charset=utf-8.
  3. HttpClient.Timeout = 3s.
  4. On 2xx, deserialize BridgeResponse and AddDM() each item.
  5. On 4xx/5xx, log and bail.
  6. On TaskCanceledException, log "bridge timeout".
  7. On HttpRequestException, log "bridge http exception".

What we want to see:
  - Which one of 6/7 fires first (or neither, if 4xx comes back).
  - How long the round trip takes on a healthy DanmuAI instance.
  - How the response body looks on the wire (UTF-8 vs CP1252 garbling).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "http://127.0.0.1:18765/api/plugin/bililive-dm/reply"
TIMEOUT = 3.0  # mirrors BridgeTimeoutSec = 3 in C# plugin
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

# Mirror the C# BridgeRequest DTO verbatim: snake_case field names.
payload = {
    "room_id": None,            # 弹幕姬 sets this.RoomId = null until MainConnected fires
    "user_name": "彈幕姬",        # mirror the user's actual test text
    "user_id": "u1",
    "text": "外掛程式彈幕測試",
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
        # Mirror C#: JsonConvert.DeserializeObject<BridgeResponse>(body)
        decoded = json.loads(raw.decode("utf-8"))
        if not decoded.get("ok"):
            print(f"[BRIDGE-EMPTY] error={decoded.get('error')!r} items={decoded.get('items')!r}")
            sys.exit(2)
        for item in decoded.get("items") or []:
            if item and item.strip():
                print(f"[ADD-DM] {item!r}")
except urllib.error.HTTPError as exc:
    elapsed = time.perf_counter() - t0
    print(f"[HTTP-ERR] status={exc.code} elapsed={elapsed:.3f}s reason={exc.reason!r} body={exc.read()!r}")
    sys.exit(3)
except TimeoutError:
    elapsed = time.perf_counter() - t0
    print(f"[BRIDGE-TIMEOUT] elapsed={elapsed:.3f}s (limit {TIMEOUT}s)")
    sys.exit(4)
except urllib.error.URLError as exc:
    elapsed = time.perf_counter() - t0
    print(f"[BRIDGE-URLERR] elapsed={elapsed:.3f}s reason={exc.reason!r}")
    sys.exit(5)
