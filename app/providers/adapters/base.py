"""OpenAI Chat Completions adapter protocol.

``ProviderAdapter`` 协议定义了所有 Chat Completions 适配器必须实现的四个钩子：
- ``build_vision_user_content``：构造 user content 列表（text/image/audio parts）。
- ``patch_openai_chat_body``：就地修改请求体（max_tokens/stream_options/thinking 等）。
- ``patch_probe_body``：``api_probe`` 轻量探活请求的特殊 body 调整。
- ``normalize_usage``：把各家差异的 usage 字段归一为 ``(prompt, completion)``。

新增 provider：实现一个子类并注册到 ``app.providers.__init__._DEFAULT_ADAPTER``
（如 MiMo 的 ``MimoOpenAIAdapter``），再在 ``registry.py`` 添加 HostEntry。
"""

from __future__ import annotations

from typing import Protocol

from app.providers.capabilities import ProviderCapabilities


class ProviderAdapter(Protocol):
    def build_vision_user_content(
        self,
        user_pt: str,
        image_data_uri: str,
        audio_data_uri: str | None = None,
    ) -> list[dict]:
        ...

    def patch_openai_chat_body(
        self,
        data: dict,
        *,
        max_tokens: int,
        caps: ProviderCapabilities,
    ) -> None:
        ...

    def patch_probe_body(self, data: dict, *, caps: ProviderCapabilities) -> None:
        ...

    def normalize_usage(self, usage: dict | None, *, caps: ProviderCapabilities) -> tuple[int, int]:
        ...

    def add_optional_fields(self, data: dict, *, request, caps: ProviderCapabilities) -> None:
        ...

    def supports_endpoint(self, endpoint: str) -> bool:
        ...
