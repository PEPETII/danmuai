"""W-BILILIVE-DM-PLUGIN-BRIDGE-002 — bililive_dm 桥接路由契约测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web_api.bililive_dm_bridge import (
    BRIDGE_PATH,
    BililiveDmBridgeRequest,
    BililiveDmBridgeResponse,
    register_bililive_dm_bridge_route,
)


def _make_client(config=None):
    app = FastAPI()
    register_bililive_dm_bridge_route(app, config, lambda _auth: None)
    return TestClient(app)


def test_route_path_constant_matches_endpoint():
    assert BRIDGE_PATH == "/api/plugin/bililive-dm/reply"


def test_bridge_request_accepts_optional_room_id():
    req = BililiveDmBridgeRequest.model_validate(
        {
            "room_id": None,
            "user_name": "alice",
            "user_id": "u1",
            "text": "hi",
        }
    )
    assert req.user_name == "alice"


def test_bridge_response_round_trip():
    resp = BililiveDmBridgeResponse(ok=True, error=None, items=["a", "b"])
    data = resp.model_dump()
    restored = BililiveDmBridgeResponse.model_validate(data)
    assert restored.items == ["a", "b"]


def test_route_empty_text_returns_empty_text_error():
    client = _make_client()
    res = client.post(
        BRIDGE_PATH,
        json={"room_id": 1, "user_name": "alice", "user_id": "u1", "text": "   "},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "empty_text"
    assert body["items"] == []


def test_route_missing_text_field_still_hits_handler():
    client = _make_client()
    res = client.post(
        BRIDGE_PATH,
        json={"room_id": 1, "user_name": "alice", "user_id": "u1"},
    )
    assert res.status_code == 200
    assert res.json()["error"] == "empty_text"


def test_route_invalid_json_type_returns_422():
    client = _make_client()
    res = client.post(BRIDGE_PATH, json={"text": 123})
    assert res.status_code == 422


@patch("app.web_api.bililive_dm_bridge.generate_ai_replies")
def test_route_delegates_to_generate_ai_replies(mock_generate):
    mock_generate.return_value = BililiveDmBridgeResponse(
        ok=True,
        error=None,
        items=["reply"],
    )
    config = MagicMock()
    client = _make_client(config)
    payload = {
        "room_id": 7,
        "user_name": "bob",
        "user_id": "u2",
        "text": "hello",
    }
    res = client.post(BRIDGE_PATH, json=payload)
    assert res.status_code == 200
    assert res.json()["items"] == ["reply"]
    mock_generate.assert_called_once()
    assert mock_generate.call_args.args[1].text == "hello"


@patch("app.web_api.bililive_dm_bridge.generate_ai_replies")
def test_route_internal_exception_returns_structured_error(mock_generate):
    mock_generate.side_effect = RuntimeError("boom")
    client = _make_client(MagicMock())
    res = client.post(
        BRIDGE_PATH,
        json={"user_name": "x", "user_id": "u", "text": "hi"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "internal_error:RuntimeError"


def test_register_via_register_web_routes_end_to_end():
    from app.web_api.routes import register_web_routes

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = MagicMock()
    token_calls: list[str] = []

    def _check_token(auth):
        token_calls.append(auth or "")

    with patch(
        "app.web_api.bililive_dm_bridge.generate_ai_replies",
        return_value=BililiveDmBridgeResponse(ok=False, error="empty_text", items=[]),
    ):
        register_web_routes(app, bridge, _check_token)
        client = TestClient(app)
        res = client.post(
            BRIDGE_PATH,
            json={"user_name": "a", "user_id": "u", "text": ""},
        )
    assert res.status_code == 200
    assert token_calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"user_name": "a", "user_id": "u1", "text": "x"},
        {"room_id": 1, "user_name": "b", "user_id": "u2", "text": "y"},
        {"room_id": None, "user_name": "c", "user_id": "u3", "text": "z"},
        {"room_id": 99, "user_name": "", "user_id": "", "text": "w"},
    ],
)
@patch("app.web_api.bililive_dm_bridge.generate_ai_replies")
def test_route_payload_matrix(mock_generate, payload):
    mock_generate.return_value = BililiveDmBridgeResponse(ok=True, items=["ok"])
    client = _make_client(MagicMock())
    res = client.post(BRIDGE_PATH, json=payload)
    assert res.status_code == 200
    mock_generate.assert_called_once()
