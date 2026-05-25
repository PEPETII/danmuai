import json
import threading

import httpx
from PyQt6.QtCore import QObject, pyqtSignal

from app.config_store import ConfigStore
from app.model_providers import is_doubao_mode, normalize_endpoint, normalize_mode
from app.translations import tr

# Fixed 5-item danmu (JSON array) needs headroom; low limits truncate before parse.
DEFAULT_MAX_TOKENS = 512
DANMU_MIN_OUTPUT_TOKENS = 512
DANMU_MIN_OUTPUT_TOKENS_THINKING = 1024


def resolve_danmu_max_output_tokens(configured: int, *, use_thinking: bool = False) -> int:
    """Apply a generation floor so 5 danmu replies are not cut off mid-JSON."""
    floor = DANMU_MIN_OUTPUT_TOKENS_THINKING if use_thinking else DANMU_MIN_OUTPUT_TOKENS
    if configured <= 0:
        return floor
    return max(configured, floor)


def parse_stream_usage(usage: dict | None) -> tuple[int, int]:
    """Normalize usage from OpenAI-compatible streaming chunks (incl. DashScope)."""
    if not usage:
        return 0, 0
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if prompt is None and completion is None:
        prompt = usage.get("input_tokens", 0)
        completion = usage.get("output_tokens", 0)
    return int(prompt or 0), int(completion or 0)


class AiWorker(QObject):
    finished = pyqtSignal(str, str, int, int, float, int, int, int)
    error = pyqtSignal(str, str, int, int, float, int, int, int)

    def __init__(self, config: ConfigStore):
        super().__init__()
        self.config = config
        self._stopping = False
        self._thread_local = threading.local()
        self._client_lock = threading.Lock()
        self._clients: set[httpx.Client] = set()

    def _get_http_client(self) -> httpx.Client:
        if not hasattr(self._thread_local, "client") or self._thread_local.client is None:
            try:
                client = httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0), http2=True)
            except Exception:
                client = httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0))
            self._thread_local.client = client
            with self._client_lock:
                self._clients.add(client)
        return self._thread_local.client

    def mark_stopping(self):
        self._stopping = True

    def reset_stopping(self):
        self._stopping = False

    def _get_model_config(self) -> dict:
        default_model_id = self.config.get_default_model_id()
        if not default_model_id:
            return {}
        custom_models = self.config.get_custom_models()
        for model in custom_models:
            if model.get("modelId") == default_model_id:
                return model
        return {}

    def _resolve_request_credentials(self) -> tuple[str, str, str, str] | None:
        model_config = self._get_model_config()
        if model_config:
            endpoint = normalize_endpoint(model_config.get("endpoint", ""))
            api_key = (model_config.get("apiKey") or "").strip()
            model_id = (model_config.get("modelId") or "").strip()
            api_mode = normalize_mode(model_config.get("mode", ""))
            if not endpoint or not api_key or not model_id:
                return None
            return endpoint, api_key, model_id, api_mode

        endpoint = normalize_endpoint(
            self.config.get("api_endpoint", "https://ark.cn-beijing.volces.com/api/v3")
        )
        api_key = (self.config.get_api_key() or "").strip()
        model_id = (
            self.config.get_default_model_id()
            or self.config.get("model", "doubao-seed-1-6-flash-250828")
        )
        api_mode = normalize_mode(self.config.get("api_mode", "doubao"))
        return endpoint, api_key, model_id, api_mode

    def _request(
        self,
        image_data_uri: str,
        system_pt: str,
        user_pt: str,
        persona_id: str = "",
        request_round: int = 0,
        screenshot_id: int = 0,
        captured_at: float = 0.0,
        scene_generation: int = 0,
        audio_data_uri: str | None = None,
    ):
        if self._stopping:
            return
        resolved = self._resolve_request_credentials()
        if resolved is None:
            self._emit_result(
                "error",
                tr("custom_model.error_incomplete"),
                persona_id,
                request_round,
                screenshot_id,
                captured_at,
                scene_generation,
                0,
                0,
            )
            return
        _, _, _, api_mode = resolved
        if is_doubao_mode(api_mode):
            self._request_doubao(
                image_data_uri,
                system_pt,
                user_pt,
                persona_id,
                request_round,
                screenshot_id,
                captured_at,
                scene_generation,
                audio_data_uri=audio_data_uri,
                resolved=resolved,
            )
        else:
            self._request_openai(
                image_data_uri,
                system_pt,
                user_pt,
                persona_id,
                request_round,
                screenshot_id,
                captured_at,
                scene_generation,
                resolved=resolved,
            )

    def _emit_safe(self, signal_name, *args):
        if self._stopping:
            return
        try:
            getattr(self, signal_name).emit(*args)
        except RuntimeError:
            pass

    def _emit_result(
        self,
        signal_name: str,
        message: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ):
        self._emit_safe(
            signal_name,
            message,
            persona_id,
            request_round,
            screenshot_id,
            captured_at,
            scene_generation,
            input_tokens,
            output_tokens,
        )

    def _request_doubao(
        self,
        image_data_uri: str,
        system_pt: str,
        user_pt: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        *,
        audio_data_uri: str | None = None,
        resolved: tuple[str, str, str, str] | None = None,
    ):
        if resolved is None:
            resolved = self._resolve_request_credentials()
        if resolved is None:
            self._emit_result(
                "error",
                tr("custom_model.error_incomplete"),
                persona_id,
                request_round,
                screenshot_id,
                captured_at,
                scene_generation,
                0,
                0,
            )
            return
        endpoint, api_key, model, _ = resolved
        temperature = self.config.get_float("temperature", 0.7)
        configured_max = self.config.get_int("max_tokens", DEFAULT_MAX_TOKENS)
        use_thinking = self.config.get("use_thinking", "0") == "1"
        max_output_tokens = resolve_danmu_max_output_tokens(configured_max, use_thinking=use_thinking)

        if not api_key:
            self._emit_result("error", tr("ai.error_api_key_missing"), persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)
            return

        user_content: list[dict] = [
            {"type": "input_image", "image_url": image_data_uri},
            {"type": "input_text", "text": user_pt},
        ]
        if audio_data_uri:
            user_content.append({"type": "input_audio", "audio_url": audio_data_uri})

        input_messages = [
            {
                "type": "message",
                "role": "user",
                "content": user_content,
            }
        ]

        data = {
            "model": model,
            "input": input_messages,
            "stream": True,
        }
        if system_pt:
            data["instructions"] = system_pt
        if temperature:
            data["temperature"] = temperature
        data["thinking"] = {"type": "enabled" if use_thinking else "disabled"}
        data["max_output_tokens"] = max_output_tokens

        url = f"{endpoint}/responses"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        http_client = self._get_http_client()

        for attempt in range(2):
            try:
                text, input_tokens, output_tokens, stream_error = self._stream_doubao(http_client, url, headers, data)
                if text:
                    self._emit_result("finished", text.strip(), persona_id, request_round, screenshot_id, captured_at, scene_generation, input_tokens, output_tokens)
                else:
                    msg = stream_error or tr("ai.error_empty_response")
                    self._emit_result("error", msg, persona_id, request_round, screenshot_id, captured_at, scene_generation, input_tokens, output_tokens)
                return
            except httpx.TimeoutException:
                if attempt < 1:
                    continue
                self._emit_result("error", tr("ai.error_timeout"), persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    msg = tr("ai.error_auth_failed")
                elif e.response.status_code == 429:
                    msg = tr("ai.error_rate_limited")
                elif e.response.status_code == 402:
                    msg = tr("ai.error_insufficient_balance")
                elif e.response.status_code == 404:
                    msg = tr("ai.error_model_not_found")
                elif e.response.status_code == 504:
                    msg = tr("ai.error_gateway_timeout")
                else:
                    msg = tr("ai.error_http_hidden").format(status_code=e.response.status_code)
                self._emit_result("error", msg, persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)
                return
            except Exception as e:
                if attempt < 1:
                    if hasattr(self._thread_local, "client") and self._thread_local.client is not None:
                        try:
                            self._thread_local.client.close()
                        except Exception:
                            pass
                        with self._client_lock:
                            self._clients.discard(self._thread_local.client)
                        self._thread_local.client = None
                    http_client = self._get_http_client()
                    continue
                self._emit_result("error", tr("ai.error_request_failed").format(error=e), persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)

    def _stream_doubao(self, http_client, url: str, headers: dict, data: dict) -> tuple[str, int, int, str]:
        from app.doubao_responses_stream import stream_doubao_responses

        result = stream_doubao_responses(http_client, url, headers, data)
        return result.text, result.input_tokens, result.output_tokens, result.error

    def _request_openai(
        self,
        image_data_uri: str,
        system_pt: str,
        user_pt: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        *,
        resolved: tuple[str, str, str, str] | None = None,
    ):
        if resolved is None:
            resolved = self._resolve_request_credentials()
        if resolved is None:
            self._emit_result(
                "error",
                tr("custom_model.error_incomplete"),
                persona_id,
                request_round,
                screenshot_id,
                captured_at,
                scene_generation,
                0,
                0,
            )
            return
        endpoint, api_key, model, _ = resolved
        temperature = self.config.get_float("temperature", 0.7)
        configured_max = self.config.get_int("max_tokens", DEFAULT_MAX_TOKENS)
        max_tokens = resolve_danmu_max_output_tokens(configured_max, use_thinking=False)

        if not api_key:
            self._emit_result("error", tr("ai.error_api_key_missing"), persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)
            return

        http_client = self._get_http_client()

        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_pt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_pt},
                        {"type": "image_url", "image_url": {"url": image_data_uri}},
                    ],
                },
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            # DashScope / 百炼 compatible-mode: usage only in final chunk when enabled.
            "stream_options": {"include_usage": True},
        }
        url = f"{endpoint}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(2):
            try:
                text, input_tokens, output_tokens = self._stream_openai(http_client, url, headers, data)
                if text:
                    self._emit_result("finished", text.strip(), persona_id, request_round, screenshot_id, captured_at, scene_generation, input_tokens, output_tokens)
                else:
                    self._emit_result("error", tr("ai.error_empty_response"), persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)
                return
            except httpx.TimeoutException:
                if attempt < 1:
                    continue
                self._emit_result("error", tr("ai.error_timeout"), persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    msg = tr("ai.error_auth_failed")
                elif e.response.status_code == 429:
                    msg = tr("ai.error_rate_limited")
                elif e.response.status_code == 402:
                    msg = tr("ai.error_insufficient_balance")
                elif e.response.status_code == 404:
                    msg = tr("ai.error_model_not_found")
                elif e.response.status_code == 504:
                    msg = tr("ai.error_gateway_timeout")
                else:
                    msg = tr("ai.error_http_hidden").format(status_code=e.response.status_code)
                self._emit_result("error", msg, persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)
                return
            except Exception as e:
                if attempt < 1:
                    if hasattr(self._thread_local, "client") and self._thread_local.client is not None:
                        try:
                            self._thread_local.client.close()
                        except Exception:
                            pass
                        with self._client_lock:
                            self._clients.discard(self._thread_local.client)
                        self._thread_local.client = None
                    http_client = self._get_http_client()
                    continue
                self._emit_result("error", tr("ai.error_request_failed").format(error=e), persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)

    def _stream_openai(self, http_client, url: str, headers: dict, data: dict) -> tuple[str, int, int]:
        collected = []
        input_tokens = 0
        output_tokens = 0
        with http_client.stream("POST", url, headers=headers, json=data) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if self._stopping:
                    break
                if not line or not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                    usage = chunk.get("usage")
                    if usage:
                        input_tokens, output_tokens = parse_stream_usage(usage)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        collected.append(content)
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue
        return "".join(collected), input_tokens, output_tokens

    def close(self):
        with self._client_lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
        if hasattr(self._thread_local, "client"):
            self._thread_local.client = None
