"""Lightweight API connectivity probe for settings UI."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.ai_client import (
    THINKING_DISABLED,
    format_http_status_error,
    openai_compatible_request_extensions,
)
from app.model_providers import normalize_endpoint, normalize_mode, resolve_api_transport
from app.translations import tr


@dataclass
class ProbeResult:
    ok: bool
    message: str
    status_code: int | None = None


def probe_connection(
    endpoint: str,
    api_key: str,
    model_id: str,
    mode: str,
) -> ProbeResult:
    endpoint = normalize_endpoint(endpoint)
    api_key = (api_key or "").strip()
    model_id = (model_id or "").strip()
    mode = normalize_mode(mode)

    if not endpoint:
        return ProbeResult(False, tr("custom_model.error_endpoint"))
    if not api_key:
        return ProbeResult(False, tr("custom_model.error_api_key"))
    if not model_id:
        return ProbeResult(False, tr("custom_model.error_model_id"))

    try:
        if resolve_api_transport(endpoint, mode) == "doubao":
            return _probe_doubao(endpoint, api_key, model_id)
        return _probe_openai(endpoint, api_key, model_id)
    except httpx.TimeoutException:
        return ProbeResult(False, tr("ai.error_timeout"))
    except httpx.HTTPStatusError as exc:
        return ProbeResult(False, format_http_status_error(exc), exc.response.status_code)
    except Exception as exc:
        return ProbeResult(False, tr("ai.error_request_failed").format(error=exc))


def _probe_doubao(endpoint: str, api_key: str, model_id: str) -> ProbeResult:
    url = f"{endpoint}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = {
        "model": model_id,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "ping"}],
            }
        ],
        "stream": False,
        "max_output_tokens": 1,
        "thinking": dict(THINKING_DISABLED),
    }
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        try:
            resp = client.post(url, headers=headers, json=data)
            resp.raise_for_status()
            return ProbeResult(True, tr("custom_model.test_ok"), resp.status_code)
        except httpx.HTTPStatusError:
            raise
        except Exception:
            data["stream"] = True
            with client.stream("POST", url, headers=headers, json=data) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        break
            return ProbeResult(True, tr("custom_model.test_ok"))


def _probe_openai(endpoint: str, api_key: str, model_id: str) -> ProbeResult:
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = {
        "model": model_id,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
        **openai_compatible_request_extensions(endpoint),
    }
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        resp = client.post(url, headers=headers, json=data)
        resp.raise_for_status()
        return ProbeResult(True, tr("custom_model.test_ok"), resp.status_code)
