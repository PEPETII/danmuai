"""virtual_host_chat 解析与 HTTP 契约测试。"""

from __future__ import annotations

import json

from app.providers.request_planner import GenerationRequest, plan_http_request
from app.virtual_host.chat import HostChatHttpResult, parse_host_turn_result, request_host_chat
from app.virtual_host.contracts import ActionDraft, EmotionDraft, HostPrompt, KnowledgeContextResult


def _prompt() -> HostPrompt:
    return HostPrompt(
        persona_system="你是主播",
        persona_user="保持友好",
        session_context="",
        scene_context="游戏画面",
        danmu_context=("弹幕一",),
        knowledge=KnowledgeContextResult(status="unavailable"),
        current_input="弹幕一",
    )


def test_parse_host_turn_result_from_json():
    raw = json.dumps(
        {
            "text": "大家好",
            "speak": False,
            "emotion": {"name": "happy", "intensity": 0.8},
            "actions": [{"kind": "gesture", "intensity": 0.5, "duration_seconds": 1.5}],
            "memory_effects": [{"kind": "note", "value": "记住", "approved": False}],
        }
    )
    result = parse_host_turn_result(raw, session_id="sid", turn_id=3)
    assert result is not None
    assert result.text == "大家好"
    assert result.speak is False
    assert result.emotion == EmotionDraft("happy", 0.8)
    assert result.actions == (ActionDraft("gesture", 0.5, 1.5),)
    assert len(result.memory_effects) == 1


def test_parse_host_turn_result_reads_action_name():
    raw = json.dumps(
        {
            "text": "回应",
            "actions": [{"kind": "gesture", "name": "  wave   hello "}],
        }
    )
    result = parse_host_turn_result(raw, session_id="sid", turn_id=2)
    assert result is not None
    assert result.actions == (ActionDraft("gesture", name="wave hello"),)


def test_action_draft_name_defaults_empty_and_is_clipped():
    assert ActionDraft("gesture").name == ""
    raw_name = "  " + "wave " * 30
    action = ActionDraft("gesture", name=raw_name)
    expected = " ".join(raw_name.split())[: ActionDraft.MAX_NAME_CHARS].rstrip()
    assert action.name == expected
    assert len(action.name) <= ActionDraft.MAX_NAME_CHARS


def test_parse_host_turn_result_skips_action_with_invalid_name():
    raw = json.dumps(
        {
            "text": "回应",
            "actions": [
                {"kind": "gesture", "name": {"command": "do-not-run"}},
                {"kind": "idle"},
            ],
        }
    )
    result = parse_host_turn_result(raw, session_id="sid", turn_id=2)
    assert result is not None
    assert result.actions == (ActionDraft("idle"),)


def test_parse_host_turn_result_plain_text_fallback():
    result = parse_host_turn_result("纯文本回复", session_id="sid", turn_id=1)
    assert result is not None
    assert result.text == "纯文本回复"
    assert result.speak is True


def test_request_host_chat_posts_virtual_host_chat_purpose(monkeypatch):
    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"text":"回应","speak":true}'}}]}

    class _FakeClient:
        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

        def close(self):
            return None

    monkeypatch.setattr("app.virtual_host.chat.httpx.Client", lambda **kwargs: _FakeClient())

    planned = plan_http_request(
        GenerationRequest(
            purpose="virtual_host_chat",
            model_id="qwen3-vl-flash",
            endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="secret",
            api_mode="openai-compatible",
            system_text="system",
            user_text="user",
            stream=False,
            force_thinking_off=True,
        )
    )
    assert planned.json_body is not None

    resolved = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "secret",
        "qwen3-vl-flash",
        "openai-compatible",
    )
    result = request_host_chat(_prompt(), resolved, session_id="sid", turn_id=7)
    assert isinstance(result, HostChatHttpResult)
    assert result.ok is True
    assert result.result is not None
    assert result.result.text == "回应"
    assert result.model_id == "qwen3-vl-flash"
    assert "messages" in str(captured.get("json"))


def test_request_host_chat_empty_parse_returns_error(monkeypatch):
    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": ""}}]}

    class _FakeClient:
        def post(self, url, headers=None, json=None):
            return _FakeResponse()

        def close(self):
            return None

    monkeypatch.setattr("app.virtual_host.chat.httpx.Client", lambda **kwargs: _FakeClient())
    resolved = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "secret",
        "qwen3-vl-flash",
        "openai-compatible",
    )
    result = request_host_chat(_prompt(), resolved, session_id="sid", turn_id=1)
    assert result.ok is False
    assert result.error == "empty_parse"
