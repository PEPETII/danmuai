"""Lightweight API connectivity probe for settings UI."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.ai_client import format_http_status_error
from app.ai_client_support import sanitize_provider_error_snippet
from app.errors import AppError
from app.model_providers import normalize_endpoint, normalize_mode, resolve_api_transport
from app.providers.request_planner import GenerationRequest, plan_http_request
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
        planned = plan_http_request(
            GenerationRequest(
                purpose="connection_probe",
                model_id=model_id,
                endpoint=endpoint,
                api_key=api_key,
                api_mode=mode,
                user_text="ping",
                max_output_tokens=1,
                stream=False,
                force_thinking_off=True,
            )
        )
        if resolve_api_transport(endpoint, mode) == "doubao":
            return _post_probe(planned.url, planned.headers, planned.json_body, allow_stream_fallback=True)
        return _post_probe(planned.url, planned.headers, planned.json_body)
    except httpx.TimeoutException:
        return ProbeResult(False, tr("ai.error_timeout"))
    except httpx.HTTPStatusError as exc:
        return ProbeResult(False, format_http_status_error(exc), exc.response.status_code)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return ProbeResult(False, tr("ai.error_connection_failed"))
    except AppError as exc:
        detail = sanitize_provider_error_snippet(str(exc))
        return ProbeResult(False, tr("ai.error_request_failed").format(error=detail))
    except Exception as exc:  # boundary: unexpected probe failure
        detail = sanitize_provider_error_snippet(str(exc))
        return ProbeResult(False, tr("ai.error_request_failed").format(error=detail))


def _post_probe(
    url: str,
    headers: dict,
    data: dict,
    *,
    allow_stream_fallback: bool = False,
) -> ProbeResult:
    with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        try:
            resp = client.post(url, headers=headers, json=data)
            resp.raise_for_status()
            return ProbeResult(True, tr("custom_model.test_ok"), resp.status_code)
        except httpx.HTTPStatusError:
            raise
        except (httpx.HTTPError, httpx.TimeoutException):
            if not allow_stream_fallback:
                raise
            data = dict(data)
            data["stream"] = True
            with client.stream("POST", url, headers=headers, json=data) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        break
            return ProbeResult(True, tr("custom_model.test_ok"))
