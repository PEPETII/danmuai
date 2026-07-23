"""Platform model catalogs with pricing metadata for the Web console vision model picker.

十八平台目录（按 ``_CATALOG_BY_PROVIDER`` key）：
- ``doubao``：火山方舟（豆包 Responses 模型）
- ``dashscope``：阿里云百炼（qwen-vl-* 等）
- ``openai``：OpenAI（GPT 系列）
- ``google_gemini``：Google Gemini（Gemini 系列）
- ``xai``：xAI（Grok 系列）
- ``mistral``：Mistral AI（Mistral / Ministral 系列）
- ``together``：Together AI（Qwen / Gemma / Kimi / MiniMax）
- ``fireworks``：Fireworks AI（Kimi / Qwen / Step / Gemma）
- ``dashscope_intl``：DashScope International（Qwen 视觉/多模态）
- ``siliconflow``：硅基流动（deepseek-ai/* 等）
- ``mimo``：小米 MiMo（仅 ``mimo-v2.5``）
- ``zai``：Z.AI / 智谱（GLM-4.6V / GLM-4.5V）
- ``moonshot``：Moonshot Kimi（kimi-latest / kimi-thinking-preview 等）
- ``hunyuan``：腾讯混元（hunyuan-turbos-vision 等）
- ``stepfun``：阶跃星辰（step-3 / step-3-7-flash）
- ``baidu_cloud``：百度千帆 v2（ernie-*-vl / qianfan-*-vl）
- ``openrouter``：OpenRouter 聚合（anthropic/claude-* / google/gemini-* 等）
- ``modelscope``：魔搭社区（Qwen3-VL-* 开源镜像，免费额度）

每个 ``CatalogModel`` 含：name、id、price、modality、supports_vision、
main_flow_recommended、thinking_mode（off/hybrid/always）。
``ModelPrice`` 含 input/output/可选 audio（每百万 token，默认 CNY）。

价格元数据仅用于 Web「视觉模型选择器」的预估成本展示，**不**写入计费。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ThinkingMode = Literal["off", "hybrid", "always"]


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
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
    supports_vision: bool = True
    main_flow_recommended: bool = True
    thinking_mode: ThinkingMode = "off"

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
        "Doubao-Seed-2.0-pro",
        "doubao-seed-2-0-pro-260215",
        ModelPrice(input=1.0, audio=15, output=9),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Doubao-Seed-2.0-lite",
        "doubao-seed-2-0-lite-260428",
        ModelPrice(input=0.6, audio=9, output=3.6),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Doubao-Seed-2.0-mini",
        "doubao-seed-2-0-mini-260428",
        ModelPrice(input=0.2, audio=3, output=2),
        thinking_mode="hybrid",
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

OPENAI_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "GPT-5.1",
        "gpt-5.1",
        ModelPrice(input=1.25, audio=None, output=10.0, currency="USD"),
    ),
    CatalogModel(
        "GPT-5",
        "gpt-5",
        ModelPrice(input=1.25, audio=None, output=10.0, currency="USD"),
    ),
    CatalogModel(
        "GPT-5-mini",
        "gpt-5-mini",
        ModelPrice(input=0.25, audio=None, output=2.0, currency="USD"),
    ),
    CatalogModel(
        "GPT-5-nano",
        "gpt-5-nano",
        ModelPrice(input=0.05, audio=None, output=0.4, currency="USD"),
    ),
    CatalogModel(
        "GPT-4.1",
        "gpt-4.1",
        ModelPrice(input=2.0, audio=None, output=8.0, currency="USD"),
    ),
)

GOOGLE_GEMINI_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Gemini-3.5-Flash",
        "gemini-3.5-flash",
        ModelPrice(input=0.3, audio=None, output=2.5, currency="USD"),
    ),
    CatalogModel(
        "Gemini-3.1-Pro",
        "gemini-3.1-pro",
        ModelPrice(input=1.25, audio=None, output=10.0, currency="USD"),
    ),
    CatalogModel(
        "Gemini-3-Flash",
        "gemini-3-flash",
        ModelPrice(input=0.3, audio=None, output=2.5, currency="USD"),
    ),
    CatalogModel(
        "Gemini-2.5-Pro",
        "gemini-2.5-pro",
        ModelPrice(input=1.25, audio=None, output=10.0, currency="USD"),
    ),
    CatalogModel(
        "Gemini-2.5-Flash",
        "gemini-2.5-flash",
        ModelPrice(input=0.3, audio=None, output=2.5, currency="USD"),
    ),
)

XAI_MODELS: tuple[CatalogModel, ...] = (
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
        "Mistral-Large-2512",
        "mistral-large-2512",
        ModelPrice(input=2.0, audio=None, output=6.0, currency="USD"),
    ),
    CatalogModel(
        "Mistral-Medium-2508",
        "mistral-medium-2508",
        ModelPrice(input=0.4, audio=None, output=2.0, currency="USD"),
    ),
    CatalogModel(
        "Mistral-Small-2506",
        "mistral-small-2506",
        ModelPrice(input=0.1, audio=None, output=0.3, currency="USD"),
    ),
    CatalogModel(
        "Ministral-14B-2512",
        "ministral-14b-2512",
        ModelPrice(input=0.1, audio=None, output=0.3, currency="USD"),
    ),
    CatalogModel(
        "Ministral-8B-2512",
        "ministral-8b-2512",
        ModelPrice(input=0.05, audio=None, output=0.1, currency="USD"),
    ),
)

TOGETHER_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3.5-9B",
        "Qwen/Qwen3.5-9B",
        ModelPrice(input=0.3, audio=None, output=0.6, currency="USD"),
    ),
    CatalogModel(
        "Gemma-4-31B-it",
        "google/gemma-4-31B-it",
        ModelPrice(input=0.8, audio=None, output=0.8, currency="USD"),
    ),
    CatalogModel(
        "MiniMax-M3",
        "MiniMaxAI/MiniMax-M3",
        ModelPrice(input=0.4, audio=None, output=0.4, currency="USD"),
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
)

FIREWORKS_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Kimi-K2.6",
        "accounts/fireworks/models/kimi-k2p6",
        ModelPrice(input=0.95, audio=None, output=4.0, currency="USD"),
    ),
    CatalogModel(
        "Qwen3.6-Plus",
        "accounts/fireworks/models/qwen3p6-plus",
        ModelPrice(input=0.4, audio=None, output=1.2, currency="USD"),
    ),
    CatalogModel(
        "Step-3.7-Flash-NVFP4",
        "accounts/fireworks/models/step-3p7-flash-nvfp4",
        ModelPrice(input=0.2, audio=None, output=0.8, currency="USD"),
    ),
    CatalogModel(
        "Gemma-4-31B-it",
        "accounts/fireworks/models/gemma-4-31b-it",
        ModelPrice(input=0.8, audio=None, output=0.8, currency="USD"),
    ),
    CatalogModel(
        "Qwen3-Omni-30B-A3B-Instruct",
        "accounts/fireworks/models/qwen3-omni-30b-a3b-instruct",
        ModelPrice(input=0.7, audio=None, output=2.8, currency="USD"),
    ),
)

DASHSCOPE_INTL_MODELS: tuple[CatalogModel, ...] = (
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
        thinking_mode="hybrid",
    ),
)

# Vision/screenshot catalog: mimo-v2.5 only (official image input for screenshot danmu).
MIMO_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "MiMo-V2.5",
        "mimo-v2.5",
        ModelPrice(input=1.0, audio=1.0, output=2.0),
        thinking_mode="hybrid",
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
        "GLM-4.6V",
        "glm-4.6v",
        ModelPrice(input=0.6, audio=None, output=1.8, currency="USD"),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "GLM-4.5V",
        "glm-4.5v",
        ModelPrice(input=0.6, audio=None, output=1.8, currency="USD"),
        thinking_mode="hybrid",
    ),
)

# 智谱 AI（open.bigmodel.cn）— 视觉模型，无音频；定价来自智谱 AI 开放平台官网（CNY/百万 token）。
# glm-4v-flash 免费额度；glm-4v-plus 0.005元/千 token。
ZHIPU_MODELS: tuple[CatalogModel, ...] = (
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

# 腾讯混元 — 视觉模型，无音频；定价来自腾讯云官网（CNY/百万 token）。T1 为思考模型。
HUNYUAN_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Hunyuan-Turbos-Vision",
        "hunyuan-turbos-vision",
        ModelPrice(input=3.0, output=9.0),
        thinking_mode="off",
    ),
    CatalogModel(
        "Hunyuan-Vision",
        "hunyuan-vision",
        ModelPrice(input=3.0, output=9.0),
        thinking_mode="off",
    ),
    CatalogModel(
        "Hunyuan-T1-Vision",
        "hunyuan-t1-vision",
        ModelPrice(input=6.0, output=18.0),
        thinking_mode="hybrid",
    ),
    CatalogModel(
        "Hunyuan-Large-Vision",
        "hunyuan-large-vision",
        ModelPrice(input=4.0, output=12.0),
        thinking_mode="off",
    ),
)

# 阶跃星辰 StepFun — 视觉模型，无音频；定价来自阶跃星辰官网（CNY/百万 token，近似值）。
STEPFUN_MODELS: tuple[CatalogModel, ...] = (
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
        "openrouter/google/gemini-3.1-flash-lite",
        ModelPrice(input=0.25, audio=0.25, output=1.5, currency="USD"),
    ),
    CatalogModel(
        "MiMo-V2.5",
        "openrouter/xiaomi/mimo-v2.5",
        ModelPrice(input=0.4, audio=0.4, output=2.0, currency="USD"),
    ),
    CatalogModel(
        "Gemini-3.1-Pro-Preview",
        "openrouter/google/gemini-3.1-pro-preview",
        ModelPrice(input=2.0, audio=2.0, output=12.0, currency="USD"),
    ),
    CatalogModel(
        "Claude-Sonnet-4.5",
        "openrouter/anthropic/claude-sonnet-4.5",
        ModelPrice(input=3.0, output=15.0, currency="USD"),
    ),
    CatalogModel(
        "Claude-Sonnet-4.6",
        "openrouter/anthropic/claude-sonnet-4.6",
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
        platform_id="openai",
        platform_label="OpenAI",
        provider_id="openai",
        models=OPENAI_MODELS,
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


def enrich_platform_models(
    models: tuple[CatalogModel, ...] | list[CatalogModel],
    *,
    provider_id: str = "",
) -> list[dict[str, Any]]:
    """Attach ``cheapest`` and ``supports_mic`` for API / UI."""
    items = list(models)
    if not items:
        return []

    min_input = min(m.price.input for m in items)
    cheapest_id: str | None = None
    for model in items:
        if model.price.input == min_input:
            cheapest_id = model.id
            break

    result: list[dict[str, Any]] = []
    for model in items:
        payload = model.to_dict()
        payload["supports_mic"] = model.price.audio is not None
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


_MIMO_DEFAULT_MODEL_ID = "mimo-v2.5"


def default_catalog_model_id(provider_id: str) -> str:
    """Default vision model when switching provider: cheapest in catalog, else first.

    MiMo catalog lists only ``mimo-v2.5``.
    """
    pid = (provider_id or "").strip()
    if pid == "mimo":
        return _MIMO_DEFAULT_MODEL_ID
    platform = _CATALOG_BY_PROVIDER.get(pid)
    if platform is None or not platform.models:
        return ""
    enriched = enrich_platform_models(platform.models, provider_id=pid)
    for model in enriched:
        if model.get("cheapest"):
            return str(model["id"])
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
    """True when ``model_id`` is listed in a platform catalog with audio pricing."""
    mid = (model_id or "").strip()
    if not mid:
        return False
    for platform in PLATFORM_CATALOGS:
        for model in platform.models:
            if model.id == mid and model.price.audio is not None:
                return True
    return False


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
