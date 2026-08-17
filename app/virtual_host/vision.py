"""虚拟主播独立视觉模型：截图场景摘要（不占用主链路 visual_danmu 凭据）。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from app.doubao_responses_stream import extract_text_from_response
from app.model_providers import resolve_api_transport
from app.providers.request_planner import GenerationRequest, plan_http_request

logger = logging.getLogger(__name__)

_SCENE_SYSTEM_PROMPT = (
    "你是虚拟主播的画面理解助手。根据截图用 1-3 句中文概括当前画面内容，"
    "供主播理解场景。不要输出 JSON、列表或多余解释。"
)
_SCENE_USER_PROMPT = "请简要描述当前屏幕画面。"
_SCENE_MAX_OUTPUT_TOKENS = 256
_SCENE_TIMEOUT_SEC = 45.0


@dataclass(frozen=True)
class SceneSummaryResult:
    ok: bool
    text: str = ""
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


def _normalize_summary(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned[:240]


def _keywords_from_summary(summary: str) -> tuple[str, ...]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", summary)
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(token)
        if len(result) >= 8:
            break
    return tuple(result)


def request_scene_summary(
    image_data_uri: str,
    resolved: tuple[str, str, str, str],
    *,
    http_client: httpx.Client | None = None,
) -> SceneSummaryResult:
    """使用显式 resolved 凭据请求场景摘要；调用方负责递增请求计数。"""

    if not image_data_uri or not image_data_uri.startswith("data:"):
        return SceneSummaryResult(ok=False, error="invalid_image")
    endpoint, api_key, model_id, api_mode = resolved
    if not endpoint or not api_key or not model_id:
        return SceneSummaryResult(ok=False, error="incomplete_credentials")

    owns_client = http_client is None
    client = http_client or httpx.Client(
        timeout=httpx.Timeout(_SCENE_TIMEOUT_SEC, connect=5.0),
    )
    try:
        planned = plan_http_request(
            GenerationRequest(
                purpose="virtual_host_scene",
                model_id=model_id,
                endpoint=endpoint,
                api_key=api_key,
                api_mode=api_mode,
                system_text=_SCENE_SYSTEM_PROMPT,
                user_text=_SCENE_USER_PROMPT,
                image_data_uri=image_data_uri,
                max_output_tokens=_SCENE_MAX_OUTPUT_TOKENS,
                stream=False,
                force_thinking_off=True,
                supports_vision_override=True,
            )
        )
        response = client.post(
            planned.url,
            headers=planned.headers,
            json=planned.json_body,
        )
        if response.status_code >= 400:
            logger.info(
                "virtual_host scene summary http error status=%s model=%s",
                response.status_code,
                model_id,
            )
            return SceneSummaryResult(
                ok=False,
                model_id=model_id,
                error=f"http_{response.status_code}",
            )
        payload = response.json()
        if not isinstance(payload, dict):
            return SceneSummaryResult(ok=False, model_id=model_id, error="invalid_response")
        if resolve_api_transport(endpoint, api_mode) == "doubao":
            text = extract_text_from_response(payload)
        else:
            text = _extract_openai_chat_text(payload)
        summary = _normalize_summary(text)
        if not summary:
            return SceneSummaryResult(ok=False, model_id=model_id, error="empty_summary")
        return SceneSummaryResult(ok=True, text=summary, model_id=model_id)
    except httpx.HTTPError as exc:
        logger.info("virtual_host scene summary request failed: %r", exc)
        return SceneSummaryResult(ok=False, model_id=model_id, error=type(exc).__name__)
    except (TypeError, ValueError, KeyError) as exc:
        logger.info("virtual_host scene summary parse failed: %r", exc)
        return SceneSummaryResult(ok=False, model_id=model_id, error="parse_error")
    finally:
        if owns_client:
            client.close()


__all__ = [
    "SceneSummaryResult",
    "_keywords_from_summary",
    "request_scene_summary",
]
