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
import logging
import threading

import httpx
from PyQt6.QtCore import QObject, pyqtSignal

from app.ai_client_requests import (
    request_doubao,
    request_openai,
    resolve_mic_request_credentials,
    resolve_request_credentials,
    stream_doubao,
    stream_openai,
)
from app.ai_client_support import (
    DANMU_MIN_OUTPUT_TOKENS,
    DANMU_MIN_OUTPUT_TOKENS_THINKING,
    AiProbeResult,
    build_openai_vision_user_content,
    format_http_status_error,
    format_openai_http_error,
    is_mimo_endpoint,
    openai_compatible_request_extensions,
    parse_stream_usage,
    resolve_danmu_max_output_tokens,
    sanitize_provider_error_snippet,
)
from app.config_store import ConfigStore
from app.model_providers import resolve_api_transport
from app.providers.constants import THINKING_DISABLED
from app.translations import tr

logger = logging.getLogger(__name__)

__all__ = [
    "AiProbeResult",
    "AiWorker",
    "DANMU_MIN_OUTPUT_TOKENS",
    "DANMU_MIN_OUTPUT_TOKENS_THINKING",
    "build_openai_vision_user_content",
    "format_http_status_error",
    "format_openai_http_error",
    "is_mimo_endpoint",
    "openai_compatible_request_extensions",
    "parse_stream_usage",
    "resolve_danmu_max_output_tokens",
    "sanitize_provider_error_snippet",
    "THINKING_DISABLED",
]


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

    def resolve_request_credentials(self) -> tuple[str, str, str, str] | None:
        """Public façade for credential resolution (Web/mic probe)."""
        return resolve_request_credentials(self.config)

    def resolve_mic_request_credentials(self) -> tuple[str, str, str, str] | None:
        """Public façade for mic-specific credential resolution."""
        return resolve_mic_request_credentials(self.config)

    def run_mic_audio_probe(
        self,
        image_data_uri: str,
        user_pt: str,
        audio_data_uri: str,
        *,
        system_pt: str = "",
    ) -> AiProbeResult:
        """Run one mic audio probe HTTP request without emitting finished/error signals."""
        if self._stopping:
            return AiProbeResult(
                signal="error",
                message=tr("ai.error_request_failed").format(error="stopped"),
            )
        resolved = self.resolve_mic_request_credentials()
        if resolved is None:
            return AiProbeResult(
                signal="error",
                message=tr("custom_model.error_incomplete"),
            )
        endpoint, _, _, api_mode = resolved
        persona_id = "mic_probe"
        if resolve_api_transport(endpoint, api_mode) == "doubao":
            return self._request_doubao(
                image_data_uri,
                system_pt,
                user_pt,
                persona_id,
                0,
                0,
                0.0,
                0,
                audio_data_uri=audio_data_uri,
                resolved=resolved,
                emit=False,
            )
        return self._request_openai(
            image_data_uri,
            system_pt,
            user_pt,
            persona_id,
            0,
            0,
            0.0,
            0,
            audio_data_uri=audio_data_uri,
            resolved=resolved,
            emit=False,
        )

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

        audio_data_uri 用于麦克风插入：豆包 Responses（audio_url）或 MiMo Chat Completions（input_audio）。
        仅通过 finished/error 信号回传结果，禁止在此读写 DanmuApp / Overlay / 回复队列。
        """
        if self._stopping:
            return
        if audio_data_uri:
            resolved = self.resolve_mic_request_credentials()
        else:
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
                audio_data_uri=audio_data_uri,
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

    def _deliver_outcome(
        self,
        *,
        emit: bool,
        signal_name: str,
        message: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> AiProbeResult | None:
        if emit:
            self._emit_result(
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
            return None
        return AiProbeResult(
            signal=signal_name,
            message=message,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _resolve_request_credentials(self) -> tuple[str, str, str, str] | None:
        return resolve_request_credentials(self.config)

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
        emit: bool = True,
    ) -> AiProbeResult | None:
        return request_doubao(
            self,
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
            emit=emit,
        )

    def _stream_doubao(self, http_client, url: str, headers: dict, data: dict) -> tuple[str, int, int, str]:
        return stream_doubao(self, http_client, url, headers, data)

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
        audio_data_uri: str | None = None,
        resolved: tuple[str, str, str, str] | None = None,
        emit: bool = True,
    ) -> AiProbeResult | None:
        return request_openai(
            self,
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
            emit=emit,
        )

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
        return stream_openai(
            self,
            http_client,
            url,
            headers,
            data,
            endpoint=endpoint,
            api_mode=api_mode,
        )


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
        logger.debug(f"AI client connections closed: {len(clients)} clients cleaned up")
