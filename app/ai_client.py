"""AI 请求客户端：双 API 模式（豆包 Responses / OpenAI Chat Completions）与线程安全 httpx 连接池。

职责：
- 根据 api_mode 路由到 _request_doubao 或 _request_openai
- 在 QThreadPool 线程中执行 HTTP 请求（由 AiRunnable 调用 _request）
- 通过 Qt 信号 finished/error 将结果回传主线程 DanmuApp
- 管理线程局部 httpx 客户端池（httpx 非线程安全，每个线程独立实例）
- 重试策略：最多 2 次；超时/异常时关闭旧客户端重建；HTTP 状态错误不重试

线程安全约束：
- _clients 集合由 _client_lock 保护；_thread_local.client 为线程局部存储
- 信号 emit 均在 QThreadPool 工作线程发出，Qt 自动队列到主线程
- AiWorker 实例由 DanmuApp 构造并在主线程持有，但仍通过 _stopping 标志实现优雅中断

调用方：app.runnable.AiRunnable.run() → worker._request()
"""
import json
import logging
import threading

import httpx
from PyQt6.QtCore import QObject, pyqtSignal

from app.config_store import ConfigStore
from app.model_providers import (
    guess_provider_from_endpoint,
    normalize_endpoint,
    normalize_mode,
    resolve_api_transport,
)
from app.providers import get_capabilities_for_endpoint, get_openai_adapter
from app.providers.constants import THINKING_DISABLED
from app.translations import tr

# 弹幕固定 5 条 JSON 数组需要输出 token 余量；过低会在 JSON 中途截断导致解析失败。
DEFAULT_MAX_TOKENS = 512
DANMU_MIN_OUTPUT_TOKENS = 512  # 非 thinking 模式下限
DANMU_MIN_OUTPUT_TOKENS_THINKING = 1024  # thinking 模式需要更多 token（内部推理也计费）

logger = logging.getLogger(__name__)


def is_mimo_endpoint(endpoint: str) -> bool:
    return guess_provider_from_endpoint(endpoint) == "mimo"


def build_openai_vision_user_content(endpoint: str, user_pt: str, image_data_uri: str) -> list[dict]:
    """Build multimodal user content; MiMo docs use image before text."""
    adapter = get_openai_adapter(endpoint, "openai-compatible")
    return adapter.build_vision_user_content(user_pt, image_data_uri)


def openai_compatible_request_extensions(endpoint: str, *, max_tokens: int = 0) -> dict[str, object]:
    """OpenAI 兼容请求体附加字段（兼容 shim；新代码请用 ProviderAdapter）。"""
    adapter = get_openai_adapter(endpoint, "openai-compatible")
    caps = get_capabilities_for_endpoint(endpoint, "openai-compatible")
    data: dict[str, object] = {}
    if max_tokens > 0:
        data["max_tokens"] = max_tokens
    adapter.patch_probe_body(data, caps=caps)
    return data


def _http_error_message_and_code(exc: httpx.HTTPStatusError) -> tuple[str, object]:
    message = ""
    code: object = None
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            code = body.get("code")
            raw = body.get("message")
            if isinstance(raw, str):
                message = raw.strip()
            if not message:
                err = body.get("error")
                if isinstance(err, dict):
                    code = code or err.get("code")
                    nested = err.get("message")
                    if isinstance(nested, str):
                        message = nested.strip()
    except Exception:
        pass
    return message, code


def _looks_like_model_not_found(status: int, code: object, message: str) -> bool:
    if status == 404:
        return True
    if code in (20012, "ModelNotFound", "InvalidEndpointOrModel.NotFound"):
        return True
    lower = message.lower()
    if "model does not exist" in lower or "model not found" in lower:
        return True
    if "模型" in message and ("不存在" in message or "未找到" in message or "无效" in message):
        return True
    return False


def format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    """Map provider HTTP errors to user-facing messages (body message when safe)."""
    status = exc.response.status_code
    if status == 401:
        return tr("ai.error_auth_failed")
    if status == 429:
        return tr("ai.error_rate_limited")
    if status == 402:
        return tr("ai.error_insufficient_balance")
    if status == 504:
        return tr("ai.error_gateway_timeout")
    message, code = _http_error_message_and_code(exc)
    if _looks_like_model_not_found(status, code, message):
        return tr("ai.error_model_not_found")
    if message and len(message) <= 240:
        return tr("ai.error_http_with_message").format(status_code=status, message=message)
    return tr("ai.error_http_hidden").format(status_code=status)


def format_openai_http_error(exc: httpx.HTTPStatusError) -> str:
    """Alias kept for tests and api_probe imports."""
    return format_http_status_error(exc)


def resolve_danmu_max_output_tokens(configured: int, *, use_thinking: bool = False) -> int:
    """保证输出 token 不低于下限，防止 5 条弹幕 JSON 在生成中途被截断。

    thinking 模式下限更高（1024），因为内部推理也消耗输出 token。
    configured <= 0 时使用下限值。
    """
    floor = DANMU_MIN_OUTPUT_TOKENS_THINKING if use_thinking else DANMU_MIN_OUTPUT_TOKENS
    if configured <= 0:
        return floor
    return max(configured, floor)


def parse_stream_usage(usage: dict | None, *, usage_token_style: str = "openai") -> tuple[int, int]:
    """从 SSE 流的 usage 块中提取 token 用量，兼容 OpenAI 和 DashScope 两种字段名。"""
    from app.providers.adapters.default_openai import DefaultOpenAIAdapter
    from app.providers.capabilities import ProviderCapabilities

    caps = ProviderCapabilities(usage_token_style=usage_token_style)
    return DefaultOpenAIAdapter().normalize_usage(usage, caps=caps)


class AiWorker(QObject):
    """AI 请求工作线程对象，在 QThreadPool 中运行 HTTP 请求并通过信号回传结果。

    信号参数：(text/persona_id/request_round/screenshot_id/captured_at/scene_generation/input_tokens/output_tokens)
    由 AiRunnable.run() 调用 _request()；信号在 QThreadPool 工作线程中 emit，
    Qt 自动队列到主线程 DanmuApp._on_ai_reply / _on_ai_error。
    """

    finished = pyqtSignal(str, str, int, int, float, int, int, int)
    error = pyqtSignal(str, str, int, int, float, int, int, int)

    def __init__(self, config: ConfigStore):
        super().__init__()
        self.config = config
        self._stopping = False  # 优雅中断标志：stop() 时置 True，流式解析循环中检查并提前退出
        self._thread_local = threading.local()  # 线程局部存储：每个工作线程持有独立 httpx.Client
        self._client_lock = threading.Lock()  # 保护 _clients 集合的互斥锁
        self._clients: set[httpx.Client] = set()  # 所有已创建的 httpx 客户端，close() 时统一清理

    def _get_http_client(self) -> httpx.Client:
        """获取当前线程的 httpx 客户端；如不存在则创建并存入 _clients 集合。

        httpx.Client 非线程安全，必须每个线程独立实例。
        优先尝试 HTTP/2（http2=True），失败后降级到 HTTP/1.1。
        """
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
        """标记停止，流式解析循环中检查 _stopping 以优雅中断。"""
        self._stopping = True

    def reset_stopping(self):
        """新会话开始时重置，允许后续请求正常执行。"""
        self._stopping = False

    def _get_model_config(self) -> dict:
        """获取当前激活的自定义模型配置；如无则返回空 dict（走全局配置）。"""
        default_model_id = self.config.get_default_model_id()
        if not default_model_id:
            return {}
        custom_models = self.config.get_custom_models()
        for model in custom_models:
            if model.get("modelId") == default_model_id:
                return model
        return {}

    def _resolve_request_credentials(self) -> tuple[str, str, str, str] | None:
        """解析请求凭据，优先使用自定义模型配置，回退到全局配置。

        返回 (endpoint, api_key, model_id, api_mode) 或 None（凭据不完整时）。
        优先级：自定义模型（Web 控制台设置） > 全局配置（api_endpoint/api_key/model/api_mode）。
        """
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
        """双模式路由入口：根据 api_mode 分发到 _request_doubao 或 _request_openai。

        audio_data_uri 仅豆包模式使用（麦克风插入）。
        仅通过 finished/error 信号回传结果，禁止在此读写 DanmuApp / Overlay / 回复队列。
        """
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
        endpoint, _, _, api_mode = resolved
        if resolve_api_transport(endpoint, api_mode) == "doubao":
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
        """安全 emit：DanmuApp.stop() 后可能已销毁信号对象，捕获 RuntimeError 静默忽略。"""
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
        """豆包 Responses API 流式请求。

        请求体结构：model / input(user+image+audio) / stream=True / thinking / max_output_tokens。
        重试策略：超时或未知异常最多 2 次，异常时关闭旧 httpx 客户端并重建；
        HTTP 状态错误（401/402/404/429/504）不重试，直接报错。
        """
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
        max_output_tokens = resolve_danmu_max_output_tokens(configured_max, use_thinking=False)

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
        data["thinking"] = dict(THINKING_DISABLED)
        data["max_output_tokens"] = max_output_tokens

        url = f"{endpoint}/responses"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        http_client = self._get_http_client()

        # 最多 2 次尝试：超时/未知异常重建 httpx 客户端；HTTP 4xx/5xx 不重试
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
                msg = format_http_status_error(e)
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
        """豆包 SSE 流解析委托：调用 doubao_responses_stream.stream_doubao_responses 并提取结果。"""
        from app.doubao_responses_stream import stream_doubao_responses

        result = stream_doubao_responses(http_client, url, headers, data)
        if not result.text:
            logger.warning(
                "doubao stream 返回空文本: input_tokens=%s output_tokens=%s "
                "stream_events=%s error=%r",
                result.input_tokens,
                result.output_tokens,
                result.stream_events,
                result.error,
            )
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
        """OpenAI Chat Completions SSE 流式请求。

        请求体结构：model / messages(system+user+image) / stream=True / stream_options(include_usage)。
        重试策略与 _request_doubao 一致：超时或未知异常最多 2 次，HTTP 状态错误不重试。
        不支持 audio（OpenAI 模式无麦克风插入）。
        """
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
        endpoint, api_key, model, api_mode = resolved
        temperature = self.config.get_float("temperature", 0.7)
        configured_max = self.config.get_int("max_tokens", DEFAULT_MAX_TOKENS)
        caps = get_capabilities_for_endpoint(endpoint, api_mode)
        # MiMo 等模型即使设了 thinking:disabled 仍可能产生 reasoning_content，
        # 这些 token 也计入 max_completion_tokens，所以按 thinking 模式分配更大余量。
        max_tokens = resolve_danmu_max_output_tokens(
            configured_max, use_thinking=caps.thinking_param,
        )

        if not api_key:
            self._emit_result("error", tr("ai.error_api_key_missing"), persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)
            return

        http_client = self._get_http_client()
        adapter = get_openai_adapter(endpoint, api_mode)
        data: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_pt},
                {
                    "role": "user",
                    "content": adapter.build_vision_user_content(user_pt, image_data_uri),
                },
            ],
            "temperature": temperature,
            "stream": True,
        }
        adapter.patch_openai_chat_body(data, max_tokens=max_tokens, caps=caps)
        url = f"{endpoint}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # 重试策略同 _request_doubao；OpenAI 模式不支持 audio_data_uri
        for attempt in range(2):
            try:
                text, input_tokens, output_tokens = self._stream_openai(
                    http_client, url, headers, data, endpoint=endpoint, api_mode=api_mode
                )
                if text:
                    self._emit_result("finished", text.strip(), persona_id, request_round, screenshot_id, captured_at, scene_generation, input_tokens, output_tokens)
                else:
                    self._emit_result("error", tr("ai.error_empty_response"), persona_id, request_round, screenshot_id, captured_at, scene_generation, input_tokens, output_tokens)
                return
            except httpx.TimeoutException:
                if attempt < 1:
                    continue
                self._emit_result("error", tr("ai.error_timeout"), persona_id, request_round, screenshot_id, captured_at, scene_generation, 0, 0)
            except httpx.HTTPStatusError as e:
                msg = format_http_status_error(e)
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

    def _stream_openai(
        self,
        http_client,
        url: str,
        headers: dict,
        data: dict,
        *,
        endpoint: str = "",
        api_mode: str = "",
    ) -> tuple[str, int, int]:
        """OpenAI SSE 流式解析：逐行解析 data: 前缀，收集 content delta 和 usage。

        遇到 data: [DONE] 结束；usage 在最后一块（DashScope/百炼兼容模式下需 stream_options.include_usage）。
        _stopping=True 时提前中断循环。
        """
        collected: list[str] = []
        reasoning_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        caps = get_capabilities_for_endpoint(endpoint, api_mode)
        adapter = get_openai_adapter(endpoint, api_mode)
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
                        input_tokens, output_tokens = adapter.normalize_usage(usage, caps=caps)
                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        collected.append(content)
                    reasoning = delta.get("reasoning_content", "")
                    if reasoning:
                        reasoning_parts.append(reasoning)
                    if not content and not reasoning:
                        message = choice.get("message", {})
                        message_content = message.get("content", "")
                        if message_content:
                            collected.append(message_content)
                        message_reasoning = message.get("reasoning_content", "")
                        if message_reasoning:
                            reasoning_parts.append(message_reasoning)
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue
        text = "".join(collected)
        if not text and reasoning_parts:
            reasoning_len = sum(len(p) for p in reasoning_parts)
            logger.warning(
                "openai stream 只有 reasoning_content 没有 content "
                "(thinking:disabled 未生效，已通过增大 max_completion_tokens 缓解): "
                "input_tokens=%s output_tokens=%s reasoning_chars=%s endpoint=%s",
                input_tokens, output_tokens, reasoning_len,
                normalize_endpoint(endpoint) if endpoint else url,
            )
        if not text:
            logger.warning(
                "openai stream 返回空文本: input_tokens=%s output_tokens=%s "
                "endpoint=%s",
                input_tokens, output_tokens,
                normalize_endpoint(endpoint) if endpoint else url,
            )
        return text, input_tokens, output_tokens

    def close(self):
        """关闭所有 httpx 客户端连接。DanmuApp.quit() 时调用。"""
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
