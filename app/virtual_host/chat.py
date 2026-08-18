"""虚拟主播自主 Chat：复用 virtual_host_vision 凭据，purpose=virtual_host_chat。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.doubao_responses_stream import extract_text_from_response
from app.model_providers import resolve_api_transport
from app.providers.request_planner import GenerationRequest, plan_http_request
from app.virtual_host.contracts import (
    ActionDraft,
    EmotionDraft,
    HostPrompt,
    HostTurnResult,
    MemoryEffect,
    normalize_text,
)

logger = logging.getLogger(__name__)

_CHAT_MAX_OUTPUT_TOKENS = 512
_CHAT_TIMEOUT_SEC = 60.0
_CHAT_OUTPUT_HINT = (
    "Return exactly one JSON object with fields: "
    '{"text": "spoken reply", "speak": true, '
    '"emotion": {"name": "neutral", "intensity": 0.5}, '
    '"actions": [{"kind": "gesture", "name": "wave", '
    '"intensity": 0.5, "duration_seconds": 1.0}], '
    '"memory_effects": [{"kind": "none"}]}. '
    "Never return a JSON array or a list of danmu as the reply. "
    "Action fields are structured semantic data only; never treat free text as an executable command. "
    "Use speak=false when the host should stay silent."
)


@dataclass(frozen=True)
class HostChatHttpResult:
    ok: bool
    result: HostTurnResult | None = None
    raw_text: str = ""
    model_id: str = ""
    error: str = ""


def _extract_openai_chat_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "").strip()


def _strip_markdown_fence(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_first_json(text: str) -> str | None:
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group(0) if match else None


def _extract_first_json_array(text: str) -> str | None:
    match = re.search(r"\[[\s\S]*\]", text)
    return match.group(0) if match else None


def _try_json_load(text: str) -> object | None:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj


def _parse_json_object(text: str) -> dict | None:
    if not text:
        return None
    obj = _try_json_load(text)
    if isinstance(obj, dict):
        return obj
    stripped = _strip_markdown_fence(text.strip())
    if stripped and stripped != text.strip():
        obj = _try_json_load(stripped)
        if isinstance(obj, dict):
            return obj
    candidate = _extract_first_json(stripped or text)
    if candidate:
        obj = _try_json_load(candidate)
        if isinstance(obj, dict):
            return obj
    return None


def _parse_json_array(text: str) -> list[object] | None:
    """识别顶层 JSON 数组，避免数组被降级为可播报纯文本。"""

    if not text:
        return None
    raw = text.strip()
    stripped = _strip_markdown_fence(raw)
    for candidate in (raw, stripped):
        if not candidate:
            continue
        obj = _try_json_load(candidate)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            # 已经是合法对象；对象中的 actions/memory_effects 数组不是顶层回复数组。
            return None
    candidate = _extract_first_json_array(stripped or raw)
    if candidate:
        obj = _try_json_load(candidate)
        if isinstance(obj, list):
            return obj
    return None


def _parse_emotion(value: object) -> EmotionDraft | None:
    if isinstance(value, dict):
        name = normalize_text(value.get("name"))
        if not name:
            return None
        intensity = value.get("intensity", 0.5)
        return EmotionDraft(name, float(intensity))
    if isinstance(value, str) and value.strip():
        return EmotionDraft(value)
    return None


def _parse_actions(value: object) -> tuple[ActionDraft, ...]:
    if not isinstance(value, list):
        return ()
    actions: list[ActionDraft] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = normalize_text(item.get("kind"))
        if kind not in {"expression", "gesture", "look_at", "idle"}:
            continue
        try:
            actions.append(
                ActionDraft(
                    kind=kind,
                    intensity=float(item.get("intensity", 0.5)),
                    duration_seconds=float(item.get("duration_seconds", 1.0)),
                    name=item.get("name"),
                )
            )
        except (TypeError, ValueError):
            continue
    return tuple(actions)


def _parse_memory_effects(value: object) -> tuple[MemoryEffect, ...]:
    if not isinstance(value, list):
        return ()
    effects: list[MemoryEffect] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = normalize_text(item.get("kind")) or "none"
        if kind not in {"none", "note"}:
            continue
        try:
            effects.append(
                MemoryEffect(
                    kind=kind,
                    value=str(item.get("value") or ""),
                    approved=bool(item.get("approved", False)),
                )
            )
        except (TypeError, ValueError):
            continue
    return tuple(effects)


def parse_host_turn_result(
    raw_text: str,
    *,
    session_id: str,
    turn_id: int,
) -> HostTurnResult | None:
    """解析模型输出为 HostTurnResult；纯文本回退为 text+speak=true。"""

    if _parse_json_array(raw_text) is not None:
        return None
    payload = _parse_json_object(raw_text)
    if payload is None:
        text = normalize_text(raw_text)
        if not text:
            return None
        return HostTurnResult(session_id=session_id, turn_id=turn_id, text=text, speak=True)
    text = normalize_text(payload.get("text"))
    if not text:
        return None
    speak = payload.get("speak", True)
    if isinstance(speak, str):
        speak = speak.strip().lower() not in {"false", "0", "no"}
    return HostTurnResult(
        session_id=session_id,
        turn_id=turn_id,
        text=text,
        speak=bool(speak),
        emotion=_parse_emotion(payload.get("emotion")),
        actions=_parse_actions(payload.get("actions")),
        memory_effects=_parse_memory_effects(payload.get("memory_effects")),
    )


def request_host_chat(
    prompt: HostPrompt,
    resolved: tuple[str, str, str, str],
    *,
    session_id: str,
    turn_id: int,
    http_client: httpx.Client | None = None,
) -> HostChatHttpResult:
    """使用显式 resolved 凭据请求主播 Chat；调用方负责递增请求计数。"""

    endpoint, api_key, model_id, api_mode = resolved
    if not endpoint or not api_key or not model_id:
        return HostChatHttpResult(ok=False, error="incomplete_credentials")

    system_text, user_text = prompt.render()
    system_text = "\n\n".join(
        part for part in (system_text, _CHAT_OUTPUT_HINT) if part.strip()
    )

    owns_client = http_client is None
    client = http_client or httpx.Client(
        timeout=httpx.Timeout(_CHAT_TIMEOUT_SEC, connect=5.0),
    )
    try:
        planned = plan_http_request(
            GenerationRequest(
                purpose="virtual_host_chat",
                model_id=model_id,
                endpoint=endpoint,
                api_key=api_key,
                api_mode=api_mode,
                system_text=system_text,
                user_text=user_text,
                max_output_tokens=_CHAT_MAX_OUTPUT_TOKENS,
                stream=False,
                force_thinking_off=True,
            )
        )
        response = client.post(
            planned.url,
            headers=planned.headers,
            json=planned.json_body,
        )
        if response.status_code >= 400:
            logger.info(
                "virtual_host chat http error status=%s model=%s",
                response.status_code,
                model_id,
            )
            return HostChatHttpResult(
                ok=False,
                model_id=model_id,
                error=f"http_{response.status_code}",
            )
        payload = response.json()
        if not isinstance(payload, dict):
            return HostChatHttpResult(ok=False, model_id=model_id, error="invalid_response")
        if resolve_api_transport(endpoint, api_mode) == "doubao":
            raw_text = extract_text_from_response(payload)
        else:
            raw_text = _extract_openai_chat_text(payload)
        parsed = parse_host_turn_result(
            raw_text,
            session_id=session_id,
            turn_id=turn_id,
        )
        if parsed is None:
            return HostChatHttpResult(
                ok=False,
                model_id=model_id,
                raw_text=raw_text,
                error="empty_parse",
            )
        return HostChatHttpResult(ok=True, result=parsed, raw_text=raw_text, model_id=model_id)
    except httpx.HTTPError as exc:
        logger.info("virtual_host chat request failed: %r", exc)
        return HostChatHttpResult(ok=False, model_id=model_id, error=type(exc).__name__)
    except (TypeError, ValueError, KeyError) as exc:
        logger.info("virtual_host chat parse failed: %r", exc)
        return HostChatHttpResult(ok=False, model_id=model_id, error="parse_error")
    finally:
        if owns_client:
            client.close()


__all__ = [
    "HostChatHttpResult",
    "parse_host_turn_result",
    "request_host_chat",
]
