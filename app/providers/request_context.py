"""冻结后的 provider request context。

该模块只定义请求边界的数据契约，不读取配置，也不执行网络请求。内部凭据
通过 ``RequestCredentials`` 单独保存；对外需要展示时只能使用
``ResolvedRequestPublicProjection``。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RequestCredentials:
    """仅供 provider planner 使用的内部凭据。"""

    api_key: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResolvedRequestPublicProjection:
    """不含 endpoint 全路径、API key 等敏感信息的安全公开投影。"""

    profile_id: str
    model_id: str
    provider_id: str
    api_family: str
    endpoint_host: str
    max_tokens: int
    temperature: float | None
    thinking: str


@dataclass(frozen=True, slots=True)
class ResolvedRequestContext:
    """正式 provider dispatch 前冻结的最小内部请求上下文。"""

    profile_id: str
    model_id: str
    provider_id: str
    api_family: str
    endpoint: str
    endpoint_host: str
    api_mode: str
    max_tokens: int
    max_output_tokens: int
    temperature: float | None
    thinking: str
    thinking_enabled: bool
    reasoning_effort: str | None
    supports_mic_declared: bool | str | None
    credentials: RequestCredentials = field(repr=False)

    @property
    def api_key(self) -> str:
        """Provider path 的内部凭据访问器；不会进入 ``repr`` 或公开投影。"""
        return self.credentials.api_key

    def public_projection(self) -> ResolvedRequestPublicProjection:
        """构造安全公开投影，明确不携带内部凭据。"""
        return ResolvedRequestPublicProjection(
            profile_id=self.profile_id,
            model_id=self.model_id,
            provider_id=self.provider_id,
            api_family=self.api_family,
            endpoint_host=self.endpoint_host,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            thinking=self.thinking,
        )
