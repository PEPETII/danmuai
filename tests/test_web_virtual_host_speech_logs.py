from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from unittest.mock import MagicMock

from app.virtual_host.contracts import HostTurnResult
from app.virtual_host.runtime_service import VirtualHostRuntimeService
from app.web_api import virtual_host as virtual_host_api
from app.web_api.routes import register_web_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def _client() -> tuple[TestClient, MagicMock]:
    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    def check_token(authorization: str | None = None) -> None:
        del authorization

    register_web_routes(app, bridge, check_token)
    return TestClient(app), bridge


def test_virtual_host_speech_logs_api_delegates_to_danmu_app_facade():
    app = MagicMock()
    payload = {"items": [{"id": "session:1", "text": "欢迎来到直播间。"}]}
    app.get_virtual_host_speech_logs.return_value = payload

    assert virtual_host_api.get_speech_logs(app) == payload
    app.get_virtual_host_speech_logs.assert_called_once_with()


def test_virtual_host_speech_logs_route_uses_public_facade():
    client, bridge = _client()
    bridge.danmu_app.get_virtual_host_speech_logs.return_value = {
        "items": [{"id": "session:1", "timestamp": 1, "source": "user_mic", "text": "你好。"}],
    }

    response = client.get("/api/virtual-host/speech-logs")

    assert response.status_code == 200
    assert response.json()["items"][0]["text"] == "你好。"
    bridge.danmu_app.get_virtual_host_speech_logs.assert_called_once_with()


def test_virtual_host_speech_logs_tab_is_in_source_and_built_index():
    partial = (ROOT / "web/static/partials/content-pages.html").read_text(encoding="utf-8")
    index = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
    app = (ROOT / "web/static/app.js").read_text(encoding="utf-8")
    module = (ROOT / "web/static/modules/virtual-host-logs.js").read_text(encoding="utf-8")

    for html in (partial, index):
        assert 'data-guide-tab="virtual-host-logs"' in html
        assert 'id="guideTab-virtual-host-logs"' in html
        assert 'id="page-virtual-host-logs"' in html
        assert 'id="virtualHostSpeechLogView"' in html
    assert "virtual-host-logs" in app
    assert "/api/virtual-host/speech-logs" in module


def test_virtual_host_speech_logs_locale_keys_exist():
    for language in ("zh", "en"):
        content = json.loads(
            (ROOT / f"web/static/locales/{language}/content.json").read_text(encoding="utf-8"),
        )
        dynamic = json.loads(
            (ROOT / f"web/static/locales/{language}/dynamic.json").read_text(encoding="utf-8"),
        )
        assert content["content"]["text"]["虚拟主播日志"]
        assert dynamic["dynamic"]["virtualHostLogs"]["empty"]


def test_virtual_host_speech_log_records_only_spoken_text_and_keeps_latest_entries():
    service = object.__new__(VirtualHostRuntimeService)
    service._speech_logs = deque(maxlen=2)

    service._record_speech_log(
        HostTurnResult(session_id="session", turn_id=1, text="第一句"),
        source="user_mic",
        event_kind="user_mic",
        timestamp=101.0,
    )
    service._record_speech_log(
        HostTurnResult(session_id="session", turn_id=2, text="不播报", speak=False),
        source="auto_reply",
        timestamp=102.0,
    )
    service._record_speech_log(
        HostTurnResult(session_id="session", turn_id=3, text="第二句"),
        source="auto_reply",
        event_kind="danmu_batch",
        timestamp=103.0,
    )
    service._record_speech_log(
        HostTurnResult(session_id="session", turn_id=4, text="第三句"),
        source="auto_reply",
        timestamp=104.0,
    )

    assert service.get_speech_logs() == [
        {
            "id": "session:3",
            "timestamp": 103.0,
            "turn_id": 3,
            "source": "auto_reply",
            "event_kind": "danmu_batch",
            "text": "第二句",
        },
        {
            "id": "session:4",
            "timestamp": 104.0,
            "turn_id": 4,
            "source": "auto_reply",
            "event_kind": "",
            "text": "第三句",
        },
    ]
