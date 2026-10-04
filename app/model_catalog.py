"""Platform model catalogs with pricing metadata for the Web console vision model picker.

二十二个平台目录（按 ``_CATALOG_BY_PROVIDER`` key）：
- ``doubao``：火山方舟（豆包 Responses 模型）
- ``dashscope``：阿里云百炼（qwen-vl-* 等）
- ``tokenrhythm``：基元律动（qwen3.7-flash）
- ``openai``：OpenAI（GPT 系列）
- ``deepseek``：DeepSeek（Flash / V4 系列）
- ``google_gemini``：Google Gemini（Gemini 系列）
- ``xai``：xAI（Grok 系列）
- ``mistral``：Mistral AI（Mistral / Ministral 系列）
- ``together``：Together AI（Qwen / Gemma / Kimi / MiniMax）
- ``fireworks``：Fireworks AI（Kimi / Qwen / Step / Gemma）
- ``dashscope_intl``：DashScope International（Qwen 视觉/多模态）
- ``siliconflow``：硅基流动（deepseek-ai/* 等）
- ``mimo``：小米 MiMo（V2.6 与兼容保留的 V2.5）
- ``zai``：Z.AI / 智谱（GLM-4.6V / GLM-4.5V）
- ``zhipu``：智谱 AI（GLM 视觉模型）
- ``moonshot``：Moonshot Kimi（kimi-latest / kimi-thinking-preview 等）
- ``hunyuan``：腾讯混元（hunyuan-turbos-vision 等）
- ``tencent_tokenhub``：腾讯 TokenHub（GLM / Kimi / MiMo 账号目录）
- ``stepfun``：阶跃星辰（step-3 / step-3-7-flash）
- ``baidu_cloud``：百度千帆 v2（ernie-*-vl / qianfan-*-vl）
- ``openrouter``：OpenRouter 聚合（anthropic/claude-* / google/gemini-* 等）
- ``modelscope``：魔搭社区（Qwen3-VL-* 开源镜像，免费额度）

每个 ``CatalogModel`` 含：name、id、price、modality、supports_vision、
main_flow_recommended、thinking_mode（off/hybrid/always）、lifecycle_status、availability。
``ModelPrice`` 含 input/output/可选 audio（每百万 token，默认 CNY）。

价格元数据仅用于 Web「视觉模型选择器」的预估成本展示，**不**写入计费。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal

ThinkingMode = Literal["off", "hybrid", "always"]
TemperatureSupport = Literal["always", "reasoning_none_only", "never"]


@dataclass(frozen=True)
class ModelPrice:
    input: float | None
    output: float | None
    audio: float | None = None
    currency: str = "CNY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "audio": self.audio,
            "output": self.output,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class CatalogModel:
    name: str
    id: str
    price: ModelPrice
    modality: str = "图片输入 + 文本输入 → 文本输出"
    supports_vision: bool | None = None
    main_flow_recommended: bool = True
    thinking_mode: ThinkingMode = "off"
    supports_mic: bool | None = False
    status: str = "active"
    lifecycle_status: str | None = None
    availability: str = "curated"
    replacement_model_id: str | None = None
    source_kind: str = "curated"
    source_url: str | None = None
    verified_at: str | None = "2026-08-01"
    input_modalities: tuple[str, ...] = ("text", "image")
    output_modalities: tuple[str, ...] = ("text",)
    temperature_support: TemperatureSupport = "always"
    reasoning_effort_values: tuple[str, ...] = ()
    reasoning_param_style_chat: str | None = None
    reasoning_param_style_responses: str | None = None
    max_tokens_field: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None

    @property
    def supports_thinking_toggle(self) -> bool:
        return self.thinking_mode == "hybrid"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "id": self.id,
            "price": self.price.to_dict(),
            "modality": self.modality,
            "supports_vision": self.supports_vision,
            "main_flow_recommended": self.main_flow_recommended,
            "thinking_mode": self.thinking_mode,
            "supports_thinking_toggle": self.supports_thinking_toggle,
            "supports_mic": self.supports_mic,
            "status": self.status,
            "lifecycle_status": self.lifecycle_status or self.status,
            "availability": self.availability,
            "replacement_model_id": self.replacement_model_id,
            "source_kind": self.source_kind,
            "source_url": self.source_url,
            "verified_at": self.verified_at,
            "input_modalities": list(self.input_modalities),
            "output_modalities": list(self.output_modalities),
            "temperature_support": self.temperature_support,
            "reasoning_effort_values": list(self.reasoning_effort_values),
            "reasoning_param_style_chat": self.reasoning_param_style_chat,
            "reasoning_param_style_responses": self.reasoning_param_style_responses,
            "max_tokens_field": self.max_tokens_field,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True)
class PlatformCatalog:
    platform_id: str
    platform_label: str
    provider_id: str
    models: tuple[CatalogModel, ...]

    def to_dict(self) -> dict[str, Any]:
        from app.model_providers import provider_region

        return {
            "platform_id": self.platform_id,
            "platform_label": self.platform_label,
            "provider_id": self.provider_id,
            "region": provider_region(self.provider_id),
            "default_model_id": default_catalog_model_id(self.provider_id),
            "models": enrich_platform_models(self.models, provider_id=self.provider_id),
        }


DOUBAO_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Doubao-Seed-2.1-pro",
        "doubao-seed-2-1-pro-260915",
        ModelPrice(input=None, audio=None, output=None),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://docs.volcengine.com/docs/ark/model-release-announcement?lang=zh",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "Doubao-Seed-2.1-lite",
        "doubao-seed-2-1-lite-260915",
        ModelPrice(input=None, audio=None, output=None),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://docs.volcengine.com/docs/ark/model-release-announcement?lang=zh",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "Doubao-Seed-2.0-pro",
        "doubao-seed-2-0-pro-260215",
        ModelPrice(input=1.0, audio=15, output=9),
        thinking_mode="hybrid",
        supports_mic=True,
    ),
    CatalogModel(
        "Doubao-Seed-2.0-lite",
        "doubao-seed-2-0-lite-260428",
        ModelPrice(input=0.6, audio=9, output=3.6),
        thinking_mode="hybrid",
        supports_mic=True,
    ),
    CatalogModel(
        "Doubao-Seed-2.0-mini",
        "doubao-seed-2-0-mini-260428",
        ModelPrice(input=0.2, audio=3, output=2),
        thinking_mode="hybrid",
        supports_mic=True,
    ),
    CatalogModel(
        "Doubao-Seed-1.8",
        "doubao-seed-1-8-251228",
        ModelPrice(input=0.8, audio=None, output=2),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Doubao-Seed-1.6",
        "doubao-seed-1-6-251015",
        ModelPrice(input=0.8, audio=None, output=2),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Doubao-Seed-1.6-vision",
        "doubao-seed-1-6-vision-250815",
        ModelPrice(input=0.8, audio=None, output=2),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Doubao-Seed-1.6-flash",
        "doubao-seed-1-6-flash-250828",
        ModelPrice(input=0.15, audio=None, output=1.5),
        thinking_mode="hybrid",
    ),
)

DASHSCOPE_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3.8-Max",
        "qwen3.8-max",
        ModelPrice(input=None, audio=None, output=None),
        supports_vision=True,
        thinking_mode="always",
        source_kind="official",
        source_url="https://help.aliyun.com/zh/model-studio/text-generation",
        verified_at="2026-09-30",
        reasoning_effort_values=("low", "medium", "high", "xhigh"),
        reasoning_param_style_chat="enable_thinking",
    ),
    CatalogModel(
        "Qwen3.8-Flash",
        "qwen3.8-flash",
        ModelPrice(input=None, audio=None, output=None),
        supports_vision=True,
        thinking_mode="always",
        source_kind="official",
        source_url="https://help.aliyun.com/zh/model-studio/text-generation",
        verified_at="2026-09-30",
        reasoning_effort_values=("low", "medium", "high", "xhigh"),
        reasoning_param_style_chat="enable_thinking",
    ),
    CatalogModel(
        "Qwen3-VL-Flash",
        "qwen3-vl-flash",
        ModelPrice(input=0.15, audio=None, output=1.5),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Qwen3-VL-Plus",
        "qwen3-vl-plus",
        ModelPrice(input=0.8, audio=None, output=2),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Qwen3.7-Plus",
        "qwen3.7-plus",
        ModelPrice(input=1.2, audio=None, output=7.2),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Qwen3.5-Flash",
        "qwen3.5-flash",
        ModelPrice(input=0.2, audio=None, output=2),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Qwen-VL-Plus",
        "qwen-vl-plus",
        ModelPrice(input=0.8, audio=None, output=2),
        thinking_mode="off",
    ),
    CatalogModel(
        "Qwen3.5-Plus",
        "qwen3.5-plus",
        ModelPrice(input=0.8, audio=None, output=4.8),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Qwen3.5-Omni-Plus",
        "qwen3.5-omni-plus",
        ModelPrice(input=0.8, audio=None, output=4.8),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Qwen3.6-Flash",
        "qwen3.6-flash",
        ModelPrice(input=1.2, audio=None, output=7.2),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Qwen3.6-Plus",
        "qwen3.6-plus",
        ModelPrice(input=1.2, audio=None, output=7.2),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Qwen-VL-Max",
        "qwen-vl-max",
        ModelPrice(input=1.6, audio=None, output=4),
        thinking_mode="off",
    ),
)

# The platform documents Chat Completions; the model-level thinking mapping
# follows Qwen3.7-Flash's upstream Chat contract and still needs live proxy verification.
TOKENRHYTHM_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3.8-Flash",
        "qwen3.8-flash",
        ModelPrice(input=None, output=None),
        supports_vision=True,
        thinking_mode="always",
        source_kind="official",
        source_url="https://tokenrhythm.studio/models",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "DeepSeek-Flash",
        "deepseek-flash",
        ModelPrice(input=None, output=None),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://tokenrhythm.studio/models",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "Qwen3.7-Flash",
        "qwen3.7-flash",
        ModelPrice(input=1.2, audio=None, output=4.8),
        modality="文本 / 图像 / 视频输入 → 文本输出",
        supports_vision=True,
        thinking_mode="hybrid",
        reasoning_param_style_chat="enable_thinking",
        status="testing",
        source_kind="official",
        source_url="https://tokenrhythm.studio/models",
        verified_at="2026-09-05",
        input_modalities=("text", "image", "video"),
        output_modalities=("text",),
        context_window=1_000_000,
        max_output_tokens=131_000,
    ),
)

OPENAI_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "GPT-6 Astra",
        "gpt-6-astra",
        ModelPrice(input=10.0, audio=None, output=50.0, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        source_kind="official",
        source_url="https://developers.openai.com/api/docs/models/gpt-6-astra",
        verified_at="2026-10-04",
        reasoning_effort_values=("low", "medium", "high", "xhigh", "max"),
        reasoning_param_style_chat="reasoning_effort_flat",
        reasoning_param_style_responses="reasoning_object",
        max_tokens_field="max_completion_tokens",
        context_window=1_050_000,
        max_output_tokens=128_000,
    ),
    CatalogModel(
        "GPT-6.1 Sol",
        "gpt-6.1-sol",
        ModelPrice(input=2.0, audio=None, output=10.0, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        source_kind="official",
        source_url="https://developers.openai.com/api/docs/models/gpt-6.1-sol",
        verified_at="2026-10-04",
        reasoning_effort_values=("low", "medium", "high", "xhigh", "max"),
        reasoning_param_style_chat="reasoning_effort_flat",
        reasoning_param_style_responses="reasoning_object",
        max_tokens_field="max_completion_tokens",
        context_window=1_050_000,
        max_output_tokens=128_000,
    ),
    CatalogModel(
        "GPT-6 Sol",
        "gpt-6-sol",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        status="legacy",
        lifecycle_status="legacy",
        main_flow_recommended=False,
        replacement_model_id="gpt-6.1-sol",
        source_kind="official",
        source_url="https://developers.openai.com/api/docs/models",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "GPT-6 Luna",
        "gpt-6-luna",
        ModelPrice(input=0.1, audio=None, output=0.5, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://developers.openai.com/api/docs/models/gpt-6-luna",
        verified_at="2026-10-04",
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh", "max"),
        reasoning_param_style_chat="reasoning_effort_flat",
        reasoning_param_style_responses="reasoning_object",
        max_tokens_field="max_completion_tokens",
        context_window=1_050_000,
        max_output_tokens=128_000,
    ),
    CatalogModel(
        "GPT-5.6 Sol",
        "gpt-5.6-sol",
        ModelPrice(input=5.0, audio=None, output=30.0, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://developers.openai.com/api/docs/models/gpt-5.6-sol",
        verified_at="2026-08-21",
        temperature_support="never",
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh", "max"),
        reasoning_param_style_chat="reasoning_effort_flat",
        reasoning_param_style_responses="reasoning_object",
        max_tokens_field="max_completion_tokens",
        context_window=1_050_000,
        max_output_tokens=128_000,
    ),
    CatalogModel(
        "GPT-5.6 Terra",
        "gpt-5.6-terra",
        ModelPrice(input=2.5, audio=None, output=15.0, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        verified_at="2026-08-21",
        temperature_support="never",
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh", "max"),
        reasoning_param_style_chat="reasoning_effort_flat",
        reasoning_param_style_responses="reasoning_object",
        max_tokens_field="max_completion_tokens",
        context_window=1_050_000,
        max_output_tokens=128_000,
    ),
    CatalogModel(
        "GPT-5.6 Luna",
        "gpt-5.6-luna",
        ModelPrice(input=1.0, audio=None, output=6.0, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://developers.openai.com/api/docs/models/gpt-5.6-luna",
        verified_at="2026-08-21",
        temperature_support="never",
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh", "max"),
        reasoning_param_style_chat="reasoning_effort_flat",
        reasoning_param_style_responses="reasoning_object",
        max_tokens_field="max_completion_tokens",
        context_window=1_050_000,
        max_output_tokens=128_000,
    ),
)

GOOGLE_GEMINI_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Gemini-3.8-Flash",
        "gemini-3.8-flash",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Gemini-3.7-Flash",
        "gemini-3.7-flash",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Gemini-3.6-Flash",
        "gemini-3.6-flash",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("minimal", "low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Gemini-3.1-Pro-Preview",
        "gemini-3.1-pro-preview",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Gemini-3-Flash-Preview",
        "gemini-3-flash-preview",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("minimal", "low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Gemini-3.5-Flash",
        "gemini-3.5-flash",
        ModelPrice(input=0.3, audio=None, output=2.5, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("minimal", "low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Gemini-3.1-Flash-Lite",
        "gemini-3.1-flash-lite",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("minimal", "low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite",
        verified_at="2026-10-04",
        input_modalities=("text", "image", "video", "audio", "file"),
        output_modalities=("text",),
        context_window=1_048_576,
        max_output_tokens=65_536,
    ),
    CatalogModel(
        "Gemini-3.1-Pro",
        "gemini-3.1-pro",
        ModelPrice(input=1.25, audio=None, output=10.0, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        status="deprecated",
        lifecycle_status="deprecated",
        main_flow_recommended=False,
        replacement_model_id="gemini-3.1-pro-preview",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Gemini-3-Flash",
        "gemini-3-flash",
        ModelPrice(input=0.3, audio=None, output=2.5, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("minimal", "low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        status="deprecated",
        lifecycle_status="deprecated",
        main_flow_recommended=False,
        replacement_model_id="gemini-3-flash-preview",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Gemini-2.5-Pro",
        "gemini-2.5-pro",
        ModelPrice(input=1.25, audio=None, output=10.0, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        reasoning_effort_values=("low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        main_flow_recommended=False,
        availability="restricted",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Gemini-2.5-Flash",
        "gemini-2.5-flash",
        ModelPrice(input=0.3, audio=None, output=2.5, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        reasoning_effort_values=("none", "low", "medium", "high"),
        reasoning_param_style_chat="reasoning_effort_flat",
        main_flow_recommended=False,
        availability="restricted",
        source_kind="official",
        source_url="https://ai.google.dev/gemini-api/docs/models?hl=en",
        verified_at="2026-10-04",
    ),
)

XAI_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Grok-4.7",
        "grok-4.7",
        ModelPrice(input=2.0, audio=None, output=6.0, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        reasoning_effort_values=("low", "medium", "high"),
        source_kind="official",
        source_url="https://docs.x.ai/developers/models",
        verified_at="2026-10-04",
        context_window=500_000,
    ),
    CatalogModel(
        "Grok-4.3",
        "grok-4.3",
        ModelPrice(input=1.25, audio=None, output=2.5, currency="USD"),
    ),
    CatalogModel(
        "Grok-4.20-Multi-Agent-0309",
        "grok-4.20-multi-agent-0309",
        ModelPrice(input=2.0, audio=None, output=6.0, currency="USD"),
        thinking_mode="always",
    ),
    CatalogModel(
        "Grok-4.20-0309-Reasoning",
        "grok-4.20-0309-reasoning",
        ModelPrice(input=2.0, audio=None, output=6.0, currency="USD"),
        thinking_mode="always",
    ),
    CatalogModel(
        "Grok-4.20-0309-Non-Reasoning",
        "grok-4.20-0309-non-reasoning",
        ModelPrice(input=2.0, audio=None, output=6.0, currency="USD"),
    ),
    CatalogModel(
        "Grok-Build-0.1",
        "grok-build-0.1",
        ModelPrice(input=0.2, audio=None, output=0.5, currency="USD"),
    ),
)

MISTRAL_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Mistral-Large-3",
        "mistral-large-3",
        ModelPrice(input=None, output=None, currency="USD"),
        supports_vision=None,
        status="legacy",
        lifecycle_status="legacy",
        main_flow_recommended=False,
        replacement_model_id="mistral-large-2512",
        source_kind="official",
        source_url="https://docs.mistral.ai/studio/conversations/vision",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Mistral-Large-2512",
        "mistral-large-2512",
        ModelPrice(input=2.0, audio=None, output=6.0, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://docs.mistral.ai/studio/conversations/vision",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Mistral-Medium-2508",
        "mistral-medium-2508",
        ModelPrice(input=0.4, audio=None, output=2.0, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://docs.mistral.ai/studio/conversations/vision",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Mistral-Small-2506",
        "mistral-small-2506",
        ModelPrice(input=0.1, audio=None, output=0.3, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://docs.mistral.ai/studio/conversations/vision",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Ministral-14B-2512",
        "ministral-14b-2512",
        ModelPrice(input=0.1, audio=None, output=0.3, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://docs.mistral.ai/studio/conversations/vision",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Ministral-8B-2512",
        "ministral-8b-2512",
        ModelPrice(input=0.05, audio=None, output=0.1, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://docs.mistral.ai/studio/conversations/vision",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Ministral-3B-2512",
        "ministral-3b-2512",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        main_flow_recommended=False,
        source_kind="official",
        source_url="https://docs.mistral.ai/studio/conversations/vision",
        verified_at="2026-10-04",
    ),
)

TOGETHER_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3.5-9B",
        "Qwen/Qwen3.5-9B",
        ModelPrice(input=0.17, audio=None, output=0.25, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://docs.together.ai/docs/serverless/models",
        verified_at="2026-10-04",
        context_window=262_144,
    ),
    CatalogModel(
        "Gemma-4-31B-it",
        "google/gemma-4-31B-it",
        ModelPrice(input=0.8, audio=None, output=0.8, currency="USD"),
    ),
    CatalogModel(
        "MiniMax-M3",
        "MiniMaxAI/MiniMax-M3",
        ModelPrice(input=0.3, audio=None, output=1.2, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://docs.together.ai/docs/serverless/models",
        verified_at="2026-10-04",
        context_window=524_288,
    ),
    CatalogModel(
        "Kimi-K2.7-Code",
        "moonshotai/Kimi-K2.7-Code",
        ModelPrice(input=0.6, audio=None, output=2.5, currency="USD"),
    ),
    CatalogModel(
        "Kimi-K2.6",
        "moonshotai/Kimi-K2.6",
        ModelPrice(input=0.6, audio=None, output=2.5, currency="USD"),
    ),
    CatalogModel(
        "Kimi-K3",
        "moonshotai/Kimi-K3",
        ModelPrice(input=3.0, audio=None, output=15.0, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://docs.together.ai/docs/serverless/models",
        verified_at="2026-10-04",
        context_window=1_048_576,
    ),
)

FIREWORKS_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Kimi-K2.6",
        "accounts/fireworks/models/kimi-k2p6",
        ModelPrice(input=0.95, audio=None, output=4.0, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://fireworks.ai/models/fireworks/kimi-k2p6",
        verified_at="2026-10-04",
        context_window=262_144,
    ),
    CatalogModel(
        "Qwen3.6-Plus",
        "accounts/fireworks/models/qwen3p6-plus",
        ModelPrice(input=0.4, audio=None, output=1.2, currency="USD"),
        supports_vision=True,
        main_flow_recommended=False,
        status="legacy",
        lifecycle_status="superseded",
        availability="restricted",
        source_kind="official",
        source_url="https://fireworks.ai/models/fireworks/qwen3p6-plus",
        verified_at="2026-10-04",
        context_window=262_144,
    ),
    CatalogModel(
        "Step-3.7-Flash-NVFP4",
        "accounts/fireworks/models/step-3p7-flash-nvfp4",
        ModelPrice(input=0.2, audio=None, output=0.8, currency="USD"),
        supports_vision=True,
        main_flow_recommended=False,
        availability="restricted",
        thinking_mode="hybrid",
        reasoning_effort_values=("low", "medium", "high"),
        source_kind="official",
        source_url="https://fireworks.ai/models/fireworks/step-3p7-flash-nvfp4",
        verified_at="2026-10-04",
        context_window=262_144,
    ),
    CatalogModel(
        "Gemma-4-31B-it",
        "accounts/fireworks/models/gemma-4-31b-it",
        ModelPrice(input=0.8, audio=None, output=0.8, currency="USD"),
        supports_vision=True,
        main_flow_recommended=False,
        availability="restricted",
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://fireworks.ai/models/fireworks/gemma-4-31b-it",
        verified_at="2026-10-04",
        context_window=262_144,
    ),
    CatalogModel(
        "Qwen3-Omni-30B-A3B-Instruct",
        "accounts/fireworks/models/qwen3-omni-30b-a3b-instruct",
        ModelPrice(input=0.7, audio=None, output=2.8, currency="USD"),
        supports_vision=True,
        main_flow_recommended=False,
        availability="restricted",
        input_modalities=("text", "image", "audio", "video"),
        source_kind="official",
        source_url="https://fireworks.ai/models/fireworks/qwen3-omni-30b-a3b-instruct",
        verified_at="2026-10-04",
        context_window=65_536,
    ),
    CatalogModel(
        "Kimi-K2.7-Code",
        "accounts/fireworks/models/kimi-k2p7-code",
        ModelPrice(input=0.95, audio=None, output=4.0, currency="USD"),
        supports_vision=True,
        source_kind="official",
        source_url="https://fireworks.ai/models/fireworks/kimi-k2p7-code",
        verified_at="2026-10-04",
        context_window=262_144,
    ),
)

DASHSCOPE_INTL_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3.8-Max",
        "qwen3.8-max",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        source_kind="official",
        source_url="https://www.alibabacloud.com/help/en/model-studio/visual-reasoning",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Qwen3.8-Flash",
        "qwen3.8-flash",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="always",
        source_kind="official",
        source_url="https://www.alibabacloud.com/help/en/model-studio/visual-reasoning",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Qwen3.8-Omni-Flash",
        "qwen3.8-omni-flash",
        ModelPrice(input=None, audio=None, output=None, currency="USD"),
        supports_vision=True,
        input_modalities=("text", "image", "audio", "video"),
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://www.alibabacloud.com/help/en/model-studio/model-list-omni/",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Qwen3-VL-Flash",
        "qwen3-vl-flash",
        ModelPrice(input=0.15, audio=None, output=1.5),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen3-vl-flash",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Qwen3-VL-Plus",
        "qwen3-vl-plus",
        ModelPrice(input=0.8, audio=None, output=2),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://www.alibabacloud.com/help/en/model-studio/visual-reasoning",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "Qwen-VL-Plus",
        "qwen-vl-plus",
        ModelPrice(input=0.8, audio=None, output=2),
        thinking_mode="off",
    ),
    CatalogModel(
        "Qwen-VL-Max",
        "qwen-vl-max",
        ModelPrice(input=1.6, audio=None, output=4),
        thinking_mode="off",
    ),
    CatalogModel(
        "Qwen3.5-Omni-Plus",
        "qwen3.5-omni-plus",
        ModelPrice(input=0.8, audio=None, output=4.8),
        supports_vision=True,
        input_modalities=("text", "image", "audio", "video"),
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://www.alibabacloud.com/help/en/model-studio/model-list-omni/",
        verified_at="2026-10-04",
    ),
)

# Vision/screenshot catalog.  Keep older IDs for configuration compatibility and
# expose lifecycle metadata instead of deleting them during a refresh.
MIMO_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "MiMo-V2.6-Pro",
        "mimo-v2.6-pro",
        ModelPrice(input=None, audio=None, output=None),
        supports_vision=True,
        input_modalities=("text", "image", "audio"),
        thinking_mode="hybrid",
        supports_mic=True,
        source_kind="official",
        source_url="https://mimo.mi.com/docs/zh-CN/api/model/list-models",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "MiMo-V2.6-Flash",
        "mimo-v2.6-flash",
        ModelPrice(input=None, audio=None, output=None),
        supports_vision=True,
        input_modalities=("text", "image", "audio"),
        thinking_mode="hybrid",
        supports_mic=True,
        source_kind="official",
        source_url="https://mimo.mi.com/docs/zh-CN/api/model/list-models",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "MiMo-V2.5",
        "mimo-v2.5",
        ModelPrice(input=1.0, audio=1.0, output=2.0),
        supports_vision=True,
        input_modalities=("text", "image", "audio"),
        thinking_mode="hybrid",
        supports_mic=True,
        status="deprecated",
        lifecycle_status="deprecated",
        replacement_model_id="mimo-v2.6-flash",
        source_kind="official",
        source_url="https://mimo.mi.com/docs/zh-CN/api/model/list-models",
        verified_at="2026-09-30",
    ),
)

SILICONFLOW_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3-VL-8B-Instruct",
        "Qwen/Qwen3-VL-8B-Instruct",
        ModelPrice(input=0.5, audio=None, output=2),
        thinking_mode="off",
    ),
    CatalogModel(
        "Qwen3-VL-8B-Thinking",
        "Qwen/Qwen3-VL-8B-Thinking",
        ModelPrice(input=0.5, audio=None, output=5),
        thinking_mode="always",
    ),
    CatalogModel(
        "Qwen3-VL-30B-A3B-Instruct",
        "Qwen/Qwen3-VL-30B-A3B-Instruct",
        ModelPrice(input=0.7, audio=None, output=2.8),
        thinking_mode="off",
    ),
    CatalogModel(
        "Qwen3-VL-30B-A3B-Thinking",
        "Qwen/Qwen3-VL-30B-A3B-Thinking",
        ModelPrice(input=0.7, audio=None, output=2.8),
        thinking_mode="always",
    ),
    CatalogModel(
        "Qwen3-Omni-30B-A3B-Instruct",
        "Qwen/Qwen3-Omni-30B-A3B-Instruct",
        ModelPrice(input=0.7, audio=None, output=2.8),
        thinking_mode="off",
    ),
    CatalogModel(
        "Qwen3-Omni-30B-A3B-Thinking",
        "Qwen/Qwen3-Omni-30B-A3B-Thinking",
        ModelPrice(input=0.7, audio=None, output=2.8),
        thinking_mode="always",
    ),
    CatalogModel(
        "Qwen3-Omni-30B-A3B-Captioner",
        "Qwen/Qwen3-Omni-30B-A3B-Captioner",
        ModelPrice(input=0.7, audio=None, output=2.8),
        thinking_mode="off",
    ),
    CatalogModel(
        "Qwen3-VL-32B-Instruct",
        "Qwen/Qwen3-VL-32B-Instruct",
        ModelPrice(input=1, audio=None, output=4),
        thinking_mode="off",
    ),
    CatalogModel(
        "Qwen3-VL-235B-A22B-Instruct",
        "Qwen/Qwen3-VL-235B-A22B-Instruct",
        ModelPrice(input=2, audio=None, output=8),
        thinking_mode="off",
    ),
    CatalogModel(
        "GLM-4.5V",
        "zai-org/GLM-4.5V",
        ModelPrice(input=1, audio=None, output=6),
        thinking_mode="off",
    ),
)

ZAI_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "GLM-5.3-Flash",
        "glm-5.3-flash",
        ModelPrice(input=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://docs.z.ai/guides/overview/quick-start",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "GLM-5.3-FlashX",
        "glm-5.3-flashx",
        ModelPrice(input=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://docs.z.ai/guides/overview/quick-start",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "GLM-4.6V",
        "glm-4.6v",
        ModelPrice(input=0.6, audio=None, output=1.8, currency="USD"),
        supports_vision=None,
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "GLM-4.5V",
        "glm-4.5v",
        ModelPrice(input=0.6, audio=None, output=1.8, currency="USD"),
        supports_vision=None,
        thinking_mode="hybrid",
    ),
)

# 智谱 AI（open.bigmodel.cn）— 视觉模型，无音频；定价来自智谱 AI 开放平台官网（CNY/百万 token）。
# glm-4v-flash 免费额度；glm-4v-plus 0.005元/千 token。
ZHIPU_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "GLM-5.3-Flash",
        "glm-5.3-flash",
        ModelPrice(input=None, output=None),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://cloud.tencent.com/document/product/1823/130079",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "GLM-5.3-FlashX",
        "glm-5.3-flashx",
        ModelPrice(input=None, output=None),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://cloud.tencent.com/document/product/1823/130079",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "GLM-4V-Flash",
        "glm-4v-flash",
        ModelPrice(input=0.0, output=0.0),
        thinking_mode="off",
    ),
    CatalogModel(
        "GLM-4V-Plus",
        "glm-4v-plus",
        ModelPrice(input=5.0, output=5.0),
        thinking_mode="off",
    ),
    CatalogModel(
        "GLM-4.5V",
        "glm-4.5v",
        ModelPrice(input=1.0, output=6.0),
        thinking_mode="hybrid",
    ),
)

# Moonshot (Kimi) — 视觉模型，无音频；定价来自 Moonshot 官网（CNY/百万 token）。
MOONSHOT_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Kimi-K3",
        "kimi-k3",
        ModelPrice(input=None, output=None),
        supports_vision=None,
        status="testing",
        source_kind="curated",
        source_url="https://platform.moonshot.cn/docs/intro",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "Kimi-K2.6",
        "kimi-k2.6",
        ModelPrice(input=None, output=None),
        supports_vision=None,
        status="testing",
        source_kind="curated",
        source_url="https://platform.moonshot.cn/docs/intro",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "Kimi-Latest",
        "kimi-latest",
        ModelPrice(input=4.0, output=12.0),
        thinking_mode="off",
    ),
    CatalogModel(
        "Kimi-Latest-128K",
        "kimi-latest-128k",
        ModelPrice(input=4.0, output=12.0),
        thinking_mode="off",
    ),
    CatalogModel(
        "Moonshot-v1-8K-Vision",
        "moonshot-v1-8k-vision-preview",
        ModelPrice(input=8.0, output=24.0),
        thinking_mode="off",
    ),
    CatalogModel(
        "Moonshot-v1-32K-Vision",
        "moonshot-v1-32k-vision-preview",
        ModelPrice(input=8.0, output=24.0),
        thinking_mode="off",
    ),
    CatalogModel(
        "Kimi-Thinking-Preview",
        "kimi-thinking-preview",
        ModelPrice(input=8.0, output=24.0),
        thinking_mode="always",
    ),
)

# DeepSeek official catalog.  The flash alias is a multimodal entry; the
# V4-Pro entry is intentionally text-only until an official vision contract
# is published.
DEEPSEEK_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "DeepSeek-Flash",
        "deepseek-flash",
        ModelPrice(input=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        temperature_support="reasoning_none_only",
        reasoning_effort_values=("none", "low", "high", "max"),
        reasoning_param_style_chat="reasoning_effort_flat",
        reasoning_param_style_responses="reasoning_object",
        max_tokens_field="max_tokens",
        context_window=1_048_576,
        max_output_tokens=393_216,
        source_kind="official",
        source_url="https://api-docs.deepseek.com/api/list-models/",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "DeepSeek-V4-Flash",
        "deepseek-v4-flash",
        ModelPrice(input=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        status="legacy",
        lifecycle_status="legacy",
        main_flow_recommended=False,
        replacement_model_id="deepseek-flash",
        temperature_support="reasoning_none_only",
        reasoning_effort_values=("none", "low", "high", "max"),
        reasoning_param_style_chat="reasoning_effort_flat",
        reasoning_param_style_responses="reasoning_object",
        max_tokens_field="max_tokens",
        context_window=1_048_576,
        max_output_tokens=393_216,
        source_kind="official",
        source_url="https://api-docs.deepseek.com/updates/",
        verified_at="2026-10-04",
    ),
    CatalogModel(
        "DeepSeek-V4-Pro",
        "deepseek-v4-pro",
        ModelPrice(input=None, output=None, currency="USD"),
        supports_vision=False,
        input_modalities=("text",),
        thinking_mode="hybrid",
        temperature_support="reasoning_none_only",
        reasoning_effort_values=("none", "low", "high", "max"),
        reasoning_param_style_chat="reasoning_effort_flat",
        reasoning_param_style_responses="reasoning_object",
        max_tokens_field="max_tokens",
        context_window=1_048_576,
        max_output_tokens=393_216,
        source_kind="official",
        source_url="https://api-docs.deepseek.com/api/list-models/",
        verified_at="2026-10-04",
    ),
)

# TokenHub is a separate provider/key domain.  Its model availability is
# account-dependent; entries without an explicit visual contract stay unknown.
TOKENHUB_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "GLM-5.3-Flash",
        "glm-5.3-flash",
        ModelPrice(input=None, output=None),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://cloud.tencent.com/document/product/1823/130079",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "Kimi-K3",
        "kimi-k3",
        ModelPrice(input=None, output=None),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://cloud.tencent.com/document/product/1823/130079",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "MiMo-V2.6-Flash",
        "mimo-v2.6-flash",
        ModelPrice(input=None, output=None),
        supports_vision=True,
        input_modalities=("text", "image", "audio"),
        thinking_mode="hybrid",
        supports_mic=True,
        source_kind="official",
        source_url="https://cloud.tencent.com/document/product/1823/130079",
        verified_at="2026-09-30",
    ),
)

# 腾讯混元 — legacy endpoint/model IDs retained only for compatibility.
HUNYUAN_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Hunyuan-Turbos-Vision",
        "hunyuan-turbos-vision",
        ModelPrice(input=3.0, output=9.0),
        status="retired",
        lifecycle_status="retired",
        main_flow_recommended=False,
        replacement_model_id="glm-5.3-flash",
        thinking_mode="off",
    ),
    CatalogModel(
        "Hunyuan-Vision",
        "hunyuan-vision",
        ModelPrice(input=3.0, output=9.0),
        status="retired",
        lifecycle_status="retired",
        main_flow_recommended=False,
        replacement_model_id="glm-5.3-flash",
        thinking_mode="off",
    ),
    CatalogModel(
        "Hunyuan-T1-Vision",
        "hunyuan-t1-vision",
        ModelPrice(input=6.0, output=18.0),
        status="retired",
        lifecycle_status="retired",
        main_flow_recommended=False,
        replacement_model_id="glm-5.3-flash",
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Hunyuan-Large-Vision",
        "hunyuan-large-vision",
        ModelPrice(input=4.0, output=12.0),
        status="retired",
        lifecycle_status="retired",
        main_flow_recommended=False,
        replacement_model_id="glm-5.3-flash",
        thinking_mode="off",
    ),
)

# 阶跃星辰 StepFun — 视觉模型，无音频；定价来自阶跃星辰官网（CNY/百万 token，近似值）。
STEPFUN_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Step-3.7-Flash",
        "step-3.7-flash",
        ModelPrice(input=None, output=None),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://platform.stepfun.com/",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "Step-1o-Turbo-Vision",
        "step-1o-turbo-vision",
        ModelPrice(input=0.5, output=2.0),
        thinking_mode="off",
    ),
    CatalogModel(
        "Step-1o-Vision-32K",
        "step-1o-vision-32k",
        ModelPrice(input=3.0, output=5.0),
        thinking_mode="off",
    ),
)

# 百度千帆 v2 — 视觉模型，无音频；定价为 USD/百万 token。ernie-5-0-thinking-latest 为思考模型。
BAIDU_CLOUD_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "ERNIE-5.0",
        "ernie-5.0",
        ModelPrice(input=None, output=None, currency="USD"),
        supports_vision=True,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://qianfan.cloud.baidu.com/",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "ERNIE-5.1",
        "ernie-5.1",
        ModelPrice(input=None, output=None, currency="USD"),
        supports_vision=False,
        thinking_mode="hybrid",
        source_kind="official",
        source_url="https://qianfan.cloud.baidu.com/",
        verified_at="2026-09-30",
    ),
    CatalogModel(
        "ERNIE-4.5-Turbo-VL",
        "ernie-4-5-turbo-vl",
        ModelPrice(input=2.8, output=8.4, currency="USD"),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "ERNIE-4.5-VL-A3B",
        "ernie-4-5-vl-a3b",
        ModelPrice(input=2.7, output=2.7, currency="USD"),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "ERNIE-4.5-VL-A47B",
        "ernie-4-5-vl-a47b",
        ModelPrice(input=4.0, output=12.0, currency="USD"),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "ERNIE-5.0",
        "ernie-5-0",
        ModelPrice(input=4.0, output=12.0, currency="USD"),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "ERNIE-5.0-Thinking-Latest",
        "ernie-5-0-thinking-latest",
        ModelPrice(input=6.0, output=18.0, currency="USD"),
        thinking_mode="always",
    ),
)

# OpenRouter 聚合 — 视觉 + 音频模型；定价来自 data/ai-platforms/models.json（USD/百万 token）。
# 前 3 个支持音频输入（audio 价格 = input 价格）；Claude 系列不支持音频。
OPENROUTER_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Gemini-3.1-Flash-Lite",
        "google/gemini-3.1-flash-lite",
        ModelPrice(input=0.25, audio=0.25, output=1.5, currency="USD"),
    ),
    CatalogModel(
        "MiMo-V2.5",
        "xiaomi/mimo-v2.5",
        ModelPrice(input=0.4, audio=0.4, output=2.0, currency="USD"),
    ),
    CatalogModel(
        "Gemini-3.1-Pro-Preview",
        "google/gemini-3.1-pro-preview",
        ModelPrice(input=2.0, audio=2.0, output=12.0, currency="USD"),
    ),
    CatalogModel(
        "Claude-Sonnet-4.5",
        "anthropic/claude-sonnet-4.5",
        ModelPrice(input=3.0, output=15.0, currency="USD"),
    ),
    CatalogModel(
        "Claude-Sonnet-4.6",
        "anthropic/claude-sonnet-4.6",
        ModelPrice(input=3.0, output=15.0, currency="USD"),
    ),
)

# 魔搭社区 ModelScope — 复用 SiliconFlow 的 Qwen3-VL 模型 ID（魔搭镜像同名），免费额度 price=0.0。
MODELSCOPE_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3-VL-8B-Instruct",
        "Qwen/Qwen3-VL-8B-Instruct",
        ModelPrice(input=0.0, output=0.0),
    ),
    CatalogModel(
        "Qwen3-VL-30B-A3B-Instruct",
        "Qwen/Qwen3-VL-30B-A3B-Instruct",
        ModelPrice(input=0.0, output=0.0),
    ),
    CatalogModel(
        "Qwen3-VL-32B-Instruct",
        "Qwen/Qwen3-VL-32B-Instruct",
        ModelPrice(input=0.0, output=0.0),
    ),
)


_EXPLICIT_VISION_MODEL_IDS = frozenset({
    "doubao-seed-2-0-pro-260215", "doubao-seed-2-0-lite-260428", "doubao-seed-2-0-mini-260428",
    "doubao-seed-1-8-251228", "doubao-seed-1-6-251015", "doubao-seed-1-6-vision-250815", "doubao-seed-1-6-flash-250828",
    "qwen3-vl-flash", "qwen3-vl-plus", "qwen3.7-plus", "qwen3.5-flash", "qwen-vl-plus", "qwen3.5-plus",
    "qwen3.5-omni-plus", "qwen3.6-flash", "qwen3.6-plus", "qwen-vl-max", "qwen3.7-flash",
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gemini-3.5-flash", "gemini-3.1-pro", "gemini-3-flash",
    "gemini-2.5-pro", "gemini-2.5-flash", "mistral-large-2512", "mistral-medium-2508", "mistral-small-2506",
    "ministral-14b-2512", "ministral-8b-2512", "Qwen/Qwen3.5-9B", "MiniMaxAI/MiniMax-M3", "moonshotai/Kimi-K3",
    "Qwen/Qwen3-VL-8B-Instruct", "Qwen/Qwen3-VL-8B-Thinking", "Qwen/Qwen3-VL-30B-A3B-Instruct",
    "Qwen/Qwen3-VL-30B-A3B-Thinking", "Qwen/Qwen3-Omni-30B-A3B-Instruct", "Qwen/Qwen3-Omni-30B-A3B-Thinking",
    "Qwen/Qwen3-Omni-30B-A3B-Captioner", "Qwen/Qwen3-VL-32B-Instruct", "Qwen/Qwen3-VL-235B-A22B-Instruct",
    "zai-org/GLM-4.5V", "mimo-v2.5", "glm-4v-flash", "glm-4v-plus", "kimi-latest",
    "kimi-latest-128k", "moonshot-v1-8k-vision-preview", "moonshot-v1-32k-vision-preview", "kimi-thinking-preview",
    "hunyuan-turbos-vision", "hunyuan-vision", "hunyuan-t1-vision", "hunyuan-large-vision", "step-1o-turbo-vision",
    "step-1o-vision-32k", "ernie-4-5-turbo-vl", "ernie-4-5-vl-a3b", "ernie-4-5-vl-a47b", "ernie-5-0",
    "ernie-5-0-thinking-latest", "google/gemini-3.1-flash-lite", "xiaomi/mimo-v2.5", "google/gemini-3.1-pro-preview",
    "anthropic/claude-sonnet-4.5", "anthropic/claude-sonnet-4.6", "Qwen/Qwen3-VL-30B-A3B-Instruct",
    "Qwen/Qwen3-VL-32B-Instruct",
})


def _apply_explicit_capability_manifest(models: tuple[CatalogModel, ...]) -> tuple[CatalogModel, ...]:
    """Apply only the declared model-ID capability manifest.

    A source label such as ``curated`` is not a capability claim.  Unknown
    IDs therefore remain ``None`` and are excluded from the default vision
    picker until a source-backed entry explicitly sets their capability.
    """
    return tuple(
        replace(model, supports_vision=True)
        if model.supports_vision is None and model.id in _EXPLICIT_VISION_MODEL_IDS
        else model
        for model in models
    )


DOUBAO_MODELS = _apply_explicit_capability_manifest(DOUBAO_MODELS)
DASHSCOPE_MODELS = _apply_explicit_capability_manifest(DASHSCOPE_MODELS)
TOKENRHYTHM_MODELS = _apply_explicit_capability_manifest(TOKENRHYTHM_MODELS)
OPENAI_MODELS = _apply_explicit_capability_manifest(OPENAI_MODELS)
GOOGLE_GEMINI_MODELS = _apply_explicit_capability_manifest(GOOGLE_GEMINI_MODELS)
XAI_MODELS = _apply_explicit_capability_manifest(XAI_MODELS)
MISTRAL_MODELS = _apply_explicit_capability_manifest(MISTRAL_MODELS)
TOGETHER_MODELS = _apply_explicit_capability_manifest(TOGETHER_MODELS)
FIREWORKS_MODELS = _apply_explicit_capability_manifest(FIREWORKS_MODELS)
DASHSCOPE_INTL_MODELS = _apply_explicit_capability_manifest(DASHSCOPE_INTL_MODELS)
SILICONFLOW_MODELS = _apply_explicit_capability_manifest(SILICONFLOW_MODELS)
MIMO_MODELS = _apply_explicit_capability_manifest(MIMO_MODELS)
ZAI_MODELS = _apply_explicit_capability_manifest(ZAI_MODELS)
ZHIPU_MODELS = _apply_explicit_capability_manifest(ZHIPU_MODELS)
MOONSHOT_MODELS = _apply_explicit_capability_manifest(MOONSHOT_MODELS)
HUNYUAN_MODELS = _apply_explicit_capability_manifest(HUNYUAN_MODELS)
STEPFUN_MODELS = _apply_explicit_capability_manifest(STEPFUN_MODELS)
BAIDU_CLOUD_MODELS = _apply_explicit_capability_manifest(BAIDU_CLOUD_MODELS)
OPENROUTER_MODELS = _apply_explicit_capability_manifest(OPENROUTER_MODELS)
MODELSCOPE_MODELS = _apply_explicit_capability_manifest(MODELSCOPE_MODELS)

PLATFORM_CATALOGS: tuple[PlatformCatalog, ...] = (
    PlatformCatalog(
        platform_id="doubao",
        platform_label="Doubao",
        provider_id="doubao",
        models=DOUBAO_MODELS,
    ),
    PlatformCatalog(
        platform_id="dashscope",
        platform_label="DashScope",
        provider_id="dashscope",
        models=DASHSCOPE_MODELS,
    ),
    PlatformCatalog(
        platform_id="tokenrhythm",
        platform_label="基元律动",
        provider_id="tokenrhythm",
        models=TOKENRHYTHM_MODELS,
    ),
    PlatformCatalog(
        platform_id="openai",
        platform_label="OpenAI",
        provider_id="openai",
        models=OPENAI_MODELS,
    ),
    PlatformCatalog(
        platform_id="deepseek",
        platform_label="DeepSeek",
        provider_id="deepseek",
        models=DEEPSEEK_MODELS,
    ),
    PlatformCatalog(
        platform_id="google-gemini",
        platform_label="Google Gemini",
        provider_id="google_gemini",
        models=GOOGLE_GEMINI_MODELS,
    ),
    PlatformCatalog(
        platform_id="xai",
        platform_label="xAI",
        provider_id="xai",
        models=XAI_MODELS,
    ),
    PlatformCatalog(
        platform_id="mistral",
        platform_label="Mistral AI",
        provider_id="mistral",
        models=MISTRAL_MODELS,
    ),
    PlatformCatalog(
        platform_id="together",
        platform_label="Together AI",
        provider_id="together",
        models=TOGETHER_MODELS,
    ),
    PlatformCatalog(
        platform_id="fireworks",
        platform_label="Fireworks AI",
        provider_id="fireworks",
        models=FIREWORKS_MODELS,
    ),
    PlatformCatalog(
        platform_id="dashscope-intl",
        platform_label="DashScope International",
        provider_id="dashscope_intl",
        models=DASHSCOPE_INTL_MODELS,
    ),
    PlatformCatalog(
        platform_id="siliconflow",
        platform_label="硅基流动",
        provider_id="siliconflow",
        models=SILICONFLOW_MODELS,
    ),
    PlatformCatalog(
        platform_id="mimo",
        platform_label="小米 MiMo",
        provider_id="mimo",
        models=MIMO_MODELS,
    ),
    PlatformCatalog(
        platform_id="zai",
        platform_label="Z.AI / 智谱",
        provider_id="zai",
        models=ZAI_MODELS,
    ),
    PlatformCatalog(
        platform_id="zhipu",
        platform_label="智谱 AI",
        provider_id="zhipu",
        models=ZHIPU_MODELS,
    ),
    PlatformCatalog(
        platform_id="moonshot",
        platform_label="Moonshot (Kimi)",
        provider_id="moonshot",
        models=MOONSHOT_MODELS,
    ),
    PlatformCatalog(
        platform_id="hunyuan",
        platform_label="腾讯混元",
        provider_id="hunyuan",
        models=HUNYUAN_MODELS,
    ),
    PlatformCatalog(
        platform_id="tencent-tokenhub",
        platform_label="腾讯 TokenHub",
        provider_id="tencent_tokenhub",
        models=TOKENHUB_MODELS,
    ),
    PlatformCatalog(
        platform_id="stepfun",
        platform_label="阶跃星辰",
        provider_id="stepfun",
        models=STEPFUN_MODELS,
    ),
    PlatformCatalog(
        platform_id="baidu-cloud",
        platform_label="百度千帆",
        provider_id="baidu_cloud",
        models=BAIDU_CLOUD_MODELS,
    ),
    PlatformCatalog(
        platform_id="openrouter",
        platform_label="OpenRouter",
        provider_id="openrouter",
        models=OPENROUTER_MODELS,
    ),
    PlatformCatalog(
        platform_id="modelscope",
        platform_label="魔搭社区",
        provider_id="modelscope",
        models=MODELSCOPE_MODELS,
    ),
)

_CATALOG_BY_PROVIDER = {p.provider_id: p for p in PLATFORM_CATALOGS}
_CATALOG_BY_PLATFORM = {p.platform_id: p for p in PLATFORM_CATALOGS}
_CATALOG_BY_MODEL_ID: dict[str, CatalogModel] = {}
for _platform in PLATFORM_CATALOGS:
    for _model in _platform.models:
        _CATALOG_BY_MODEL_ID[_model.id] = _model

_CATALOG_SOURCE_BY_PROVIDER = {
    "doubao": "https://docs.volcengine.com/docs/ark/model-release-announcement?lang=zh",
    "dashscope": "https://help.aliyun.com/zh/model-studio/text-generation",
    "tokenrhythm": "https://tokenrhythm.studio/docs/api-integration",
    "openai": "https://developers.openai.com/api/docs/models",
    "deepseek": "https://api-docs.deepseek.com/zh-cn/",
    "google_gemini": "https://ai.google.dev/gemini-api/docs/models?hl=en",
    "xai": "https://docs.x.ai/docs/models",
    "mistral": "https://docs.mistral.ai/models",
    "together": "https://docs.together.ai/docs/models",
    "fireworks": "https://docs.fireworks.ai/guides/querying-models",
    "dashscope_intl": "https://help.aliyun.com/en/model-studio/text-generation",
    "siliconflow": "https://docs.siliconflow.cn/",
    "mimo": "https://mimo.mi.com/docs/zh-CN/api/model/list-models",
    "zai": "https://cloud.tencent.com/document/product/1823/130079",
    "zhipu": "https://cloud.tencent.com/document/product/1823/130079",
    "moonshot": "https://platform.moonshot.cn/docs/intro",
    "hunyuan": "https://cloud.tencent.com/announce/detail/2287",
    "tencent_tokenhub": "https://cloud.tencent.com/document/product/1823/130079",
    "stepfun": "https://platform.stepfun.com/",
    "baidu_cloud": "https://qianfan.cloud.baidu.com/",
    "openrouter": "https://openrouter.ai/docs/quick-start",
    "modelscope": "https://modelscope.cn/docs",
}


def enrich_platform_models(
    models: tuple[CatalogModel, ...] | list[CatalogModel],
    *,
    provider_id: str = "",
) -> list[dict[str, Any]]:
    """Attach ``cheapest`` and ``supports_mic`` for API / UI."""
    items = list(models)
    if not items:
        return []

    numeric_inputs = [m.price.input for m in items if m.price.input is not None]
    min_input = min(numeric_inputs) if numeric_inputs else None
    cheapest_id: str | None = None
    for model in items:
        if min_input is not None and model.price.input == min_input:
            cheapest_id = model.id
            break

    result: list[dict[str, Any]] = []
    for model in items:
        payload = model.to_dict()
        payload["source_url"] = payload["source_url"] or _CATALOG_SOURCE_BY_PROVIDER.get(provider_id)
        payload["verified_at"] = payload["verified_at"] or "2026-09-30"
        payload["cheapest"] = model.id == cheapest_id
        result.append(payload)
    return result


def list_platform_catalogs() -> list[dict[str, Any]]:
    return [platform.to_dict() for platform in PLATFORM_CATALOGS]


def get_catalog_for_provider(provider_id: str) -> dict[str, Any] | None:
    platform = _CATALOG_BY_PROVIDER.get((provider_id or "").strip())
    return platform.to_dict() if platform else None


def catalog_model_ids(provider_id: str) -> frozenset[str]:
    """Model IDs listed in the vision catalog for a provider preset."""
    platform = _CATALOG_BY_PROVIDER.get((provider_id or "").strip())
    if platform is None:
        return frozenset()
    return frozenset(m.id for m in platform.models)


_MIMO_DEFAULT_MODEL_ID = "mimo-v2.6-flash"


def default_catalog_model_id(provider_id: str) -> str:
    """Default vision model when switching provider: curated recommendation, else first.

    MiMo defaults to V2.6 Flash while retaining V2.5 for compatibility.
    """
    pid = (provider_id or "").strip()
    if pid == "mimo":
        return _MIMO_DEFAULT_MODEL_ID
    platform = _CATALOG_BY_PROVIDER.get(pid)
    if platform is None or not platform.models:
        return ""
    for model in platform.models:
        if model.main_flow_recommended:
            return model.id
    return platform.models[0].id


def is_catalog_model_for_provider(provider_id: str, model_id: str) -> bool:
    mid = (model_id or "").strip()
    if not mid:
        return False
    return mid in catalog_model_ids(provider_id)


def catalog_provider_ids_for_model(model_id: str) -> frozenset[str]:
    """Provider ids whose vision catalog explicitly contains ``model_id``."""
    mid = (model_id or "").strip()
    if not mid:
        return frozenset()
    provider_ids: set[str] = set()
    for platform in PLATFORM_CATALOGS:
        if any(model.id == mid for model in platform.models):
            provider_ids.add(platform.provider_id)
    return frozenset(provider_ids)


def catalog_model_supports_mic(model_id: str) -> bool:
    """Return explicit microphone capability; pricing is never a capability source."""
    mid = (model_id or "").strip()
    if not mid:
        return False
    for platform in PLATFORM_CATALOGS:
        for model in platform.models:
            if model.id == mid:
                return model.supports_mic is True
    return False


def lookup_catalog_model(model_id: str) -> CatalogModel | None:
    """Return catalog model entry when ``model_id`` is listed in a platform catalog."""
    return _CATALOG_BY_MODEL_ID.get((model_id or "").strip())


def get_thinking_mode_for_model(model_id: str) -> ThinkingMode:
    """Catalog thinking mode for ``model_id``; unknown models return ``off``."""
    mid = (model_id or "").strip()
    if not mid:
        return "off"
    model = _CATALOG_BY_MODEL_ID.get(mid)
    if model is None:
        return "off"
    return model.thinking_mode


def catalog_model_supports_thinking_toggle(model_id: str) -> bool:
    """True when settings may toggle thinking for a catalog-listed model."""
    return get_thinking_mode_for_model(model_id) == "hybrid"


def list_model_definitions_for_provider(provider_id: str):
    """V2 catalog models for a provider preset (Batch 2)."""
    from app.providers.platform_registry import list_model_definitions_for_provider as _list

    return _list(provider_id)
