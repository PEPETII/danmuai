"""Per-provider thinking mode request body injection.

Official parameter shapes (see completion report for doc URLs):
- ``thinking_type``: ``thinking: {"type": "enabled"|"disabled"}`` (Doubao Responses, Kimi, MiMo, GLM, Hunyuan)
- ``enable_thinking``: ``enable_thinking: true|false`` (DashScope, SiliconFlow, StepFun, Qianfan)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.providers.capabilities import ProviderCapabilities


def apply_thinking_mode(
    data: dict,
    *,
    enabled: bool,
    caps: ProviderCapabilities,
) -> None:
    """Set or clear thinking-related fields on an OpenAI-compat or probe body."""
    data.pop("thinking", None)
    data.pop("enable_thinking", None)
    style = caps.thinking_param_style
    if style == "none":
        return
    if style == "thinking_type":
        data["thinking"] = {"type": "enabled" if enabled else "disabled"}
        return
    if style == "enable_thinking":
        data["enable_thinking"] = bool(enabled)
        return


def apply_thinking_disabled(data: dict, *, caps: ProviderCapabilities) -> None:
    """Force thinking off using the provider's native parameter shape."""
    apply_thinking_mode(data, enabled=False, caps=caps)
