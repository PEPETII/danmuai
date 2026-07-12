"""Provider presets and validation for custom model configurations.

21 个服务商预设（``PROVIDERS`` 列表）：
- doubao（火山方舟） — mode=doubao，lock_mode=True（不可切换 Chat Completions）
- dashscope（阿里云百炼） — OpenAI 兼容
- openai（OpenAI） — OpenAI 兼容
- google_gemini（Google Gemini） — OpenAI 兼容
- xai（xAI） — OpenAI 兼容
- mistral（Mistral AI） — OpenAI 兼容
- together（Together AI） — OpenAI 兼容
- fireworks（Fireworks AI） — OpenAI 兼容
- dashscope_intl（DashScope International） — OpenAI 兼容
- zai（Z.AI / 智谱） — OpenAI 兼容
- zhipu（智谱 AI） — OpenAI 兼容
- moonshot（Moonshot Kimi） — OpenAI 兼容
- siliconflow（硅基流动） — OpenAI 兼容
- mimo（小米 MiMo） — OpenAI 兼容；视觉 + 音频需 mimo-v2.5
- hunyuan（腾讯混元） — OpenAI 兼容
- stepfun（阶跃星辰） — OpenAI 兼容
- baidu_cloud（百度千帆 v2） — OpenAI 兼容
- openrouter（OpenRouter 聚合） — OpenAI 兼容；特殊 headers 由 registry 注入
- modelscope（魔搭社区） — OpenAI 兼容；免费额度
- custom_openai（自定义 OpenAI 兼容） — lock_mode=False，可改 endpoint
- custom_doubao（自定义豆包 Responses） — mode=doubao，可改 endpoint

``guess_provider_from_endpoint`` 逻辑：先经 ``app.providers.registry.match_host_entry``
做 host 子串匹配；未命中时按 ``api_mode`` 返回 ``custom_doubao``，否则回退
``DEFAULT_PROVIDER_ID``（custom_openai）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

Region = Literal["china", "international", "global"]


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label_zh: str
    label_en: str
    default_endpoint: str
    mode: str
    model_id_hint_zh: str
    model_id_hint_en: str
    region: Region
    lock_mode: bool = True
    lock_endpoint: bool = False
    website: str | None = None


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="doubao",
        label_zh="火山方舟",
        label_en="Volcengine Ark",
        default_endpoint="https://ark.cn-beijing.volces.com/api/v3",
        mode="doubao",
        model_id_hint_zh="截图弹幕可用 flash；开麦请用 doubao-seed-2-0-mini-260428 等全模态/vision 模型",
        model_id_hint_en="flash for vision-only danmu; enable mic with doubao-seed-2-0-mini-260428 or vision models",
        region="china",
        website="https://www.volcengine.com/product/ark",
    ),
    ProviderSpec(
        id="dashscope",
        label_zh="阿里云百炼",
        label_en="Alibaba DashScope",
        default_endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
        mode="openai-compatible",
        model_id_hint_zh="例如：qwen-vl-max",
        model_id_hint_en="e.g. qwen-vl-max",
        region="china",
        website="https://help.aliyun.com/zh/dashscope/",
    ),
    ProviderSpec(
        id="openai",
        label_zh="OpenAI",
        label_en="OpenAI",
        default_endpoint="https://api.openai.com/v1",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：gpt-5.1 / gpt-5 / gpt-4.1",
        model_id_hint_en="Vision danmu: gpt-5.1 / gpt-5 / gpt-4.1",
        region="international",
        website="https://platform.openai.com/",
    ),
    ProviderSpec(
        id="google_gemini",
        label_zh="Google Gemini",
        label_en="Google Gemini",
        default_endpoint="https://generativelanguage.googleapis.com/v1beta/openai",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：gemini-3.5-flash / gemini-2.5-flash",
        model_id_hint_en="Vision danmu: gemini-3.5-flash / gemini-2.5-flash",
        region="international",
        website="https://ai.google.dev/gemini-api/docs",
    ),
    ProviderSpec(
        id="xai",
        label_zh="xAI",
        label_en="xAI",
        default_endpoint="https://api.x.ai/v1",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：grok-4.3 / grok-4.20 系列",
        model_id_hint_en="Vision danmu: grok-4.3 / grok-4.20 series",
        region="international",
        website="https://docs.x.ai/",
    ),
    ProviderSpec(
        id="mistral",
        label_zh="Mistral AI",
        label_en="Mistral AI",
        default_endpoint="https://api.mistral.ai/v1",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：mistral-large-2512 / mistral-medium-2508",
        model_id_hint_en="Vision danmu: mistral-large-2512 / mistral-medium-2508",
        region="international",
        website="https://docs.mistral.ai/",
    ),
    ProviderSpec(
        id="together",
        label_zh="Together AI",
        label_en="Together AI",
        default_endpoint="https://api.together.xyz/v1",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：Qwen / Gemma / Kimi / MiniMax 多模型预设",
        model_id_hint_en="Vision danmu: Qwen / Gemma / Kimi / MiniMax presets",
        region="international",
        website="https://docs.together.ai/",
    ),
    ProviderSpec(
        id="fireworks",
        label_zh="Fireworks AI",
        label_en="Fireworks AI",
        default_endpoint="https://api.fireworks.ai/inference/v1",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：Kimi / Qwen / Step / Gemma 多模型预设",
        model_id_hint_en="Vision danmu: Kimi / Qwen / Step / Gemma presets",
        region="international",
        website="https://docs.fireworks.ai/",
    ),
    ProviderSpec(
        id="dashscope_intl",
        label_zh="DashScope International",
        label_en="DashScope International",
        default_endpoint="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：qwen3-vl-flash / qwen-vl-max",
        model_id_hint_en="Vision danmu: qwen3-vl-flash / qwen-vl-max",
        region="international",
        website="https://www.alibabacloud.com/help/en/model-studio/",
    ),
    ProviderSpec(
        id="zai",
        label_zh="Z.AI / 智谱",
        label_en="Z.AI / Zhipu",
        default_endpoint="https://api.z.ai/api/paas/v4",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：glm-4.6v / glm-4.5v（图片输入 + 文本输入 → 文本输出）",
        model_id_hint_en="Vision danmu: glm-4.6v / glm-4.5v (image + text input to text output)",
        region="international",
        website="https://z.ai/",
    ),
    ProviderSpec(
        id="zhipu",
        label_zh="智谱 AI",
        label_en="Zhipu AI",
        default_endpoint="https://open.bigmodel.cn/api/paas/v4",
        mode="openai-compatible",
        model_id_hint_zh="例如：glm-4v-flash",
        model_id_hint_en="e.g. glm-4v-flash",
        region="china",
        website="https://open.bigmodel.cn/",
    ),
    ProviderSpec(
        id="moonshot",
        label_zh="Moonshot (Kimi)",
        label_en="Moonshot (Kimi)",
        default_endpoint="https://api.moonshot.cn/v1",
        mode="openai-compatible",
        model_id_hint_zh="例如：moonshot-v1-8k-vision-preview",
        model_id_hint_en="e.g. moonshot-v1-8k-vision-preview",
        region="china",
        website="https://platform.moonshot.cn/",
    ),
    ProviderSpec(
        id="siliconflow",
        label_zh="硅基流动",
        label_en="SiliconFlow",
        default_endpoint="https://api.siliconflow.cn/v1",
        mode="openai-compatible",
        model_id_hint_zh="例如：deepseek-ai/DeepSeek-V3",
        model_id_hint_en="e.g. deepseek-ai/DeepSeek-V3",
        region="china",
        website="https://siliconflow.cn/",
    ),
    ProviderSpec(
        id="mimo",
        label_zh="小米 MiMo",
        label_en="Xiaomi MiMo",
        default_endpoint="https://api.xiaomimimo.com/v1",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕与开麦：mimo-v2.5",
        model_id_hint_en="Vision danmu and mic: mimo-v2.5",
        region="global",
        website="https://api.xiaomimimo.com/",
    ),
    ProviderSpec(
        id="hunyuan",
        label_zh="腾讯混元",
        label_en="Tencent Hunyuan",
        default_endpoint="https://api.hunyuan.cloud.tencent.com",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：hunyuan-turbos-vision / hunyuan-t1-vision",
        model_id_hint_en="Vision danmu: hunyuan-turbos-vision / hunyuan-t1-vision",
        region="china",
        website="https://cloud.tencent.com/product/hunyuan",
    ),
    ProviderSpec(
        id="stepfun",
        label_zh="阶跃星辰",
        label_en="StepFun",
        default_endpoint="https://api.stepfun.com",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：step-3 / step-3-7-flash",
        model_id_hint_en="Vision danmu: step-3 / step-3-7-flash",
        region="china",
        website="https://platform.stepfun.com/",
    ),
    ProviderSpec(
        id="baidu_cloud",
        label_zh="百度千帆",
        label_en="Baidu Qianfan",
        default_endpoint="https://qianfan.baidubce.com/v2",
        mode="openai-compatible",
        model_id_hint_zh="截图弹幕：ernie-4-5-turbo-vl / ernie-5-0-thinking-latest",
        model_id_hint_en="Vision danmu: ernie-4-5-turbo-vl / ernie-5-0-thinking-latest",
        region="china",
        website="https://qianfan.cloud.baidu.com/",
    ),
    ProviderSpec(
        id="openrouter",
        label_zh="OpenRouter",
        label_en="OpenRouter",
        default_endpoint="https://openrouter.ai/api/v1",
        mode="openai-compatible",
        model_id_hint_zh="例如：anthropic/claude-sonnet-4.5（带厂商前缀）",
        model_id_hint_en="e.g. anthropic/claude-sonnet-4.5 (with vendor prefix)",
        region="international",
        website="https://openrouter.ai/",
    ),
    ProviderSpec(
        id="modelscope",
        label_zh="魔搭社区",
        label_en="ModelScope",
        default_endpoint="https://api-inference.modelscope.cn/v1",
        mode="openai-compatible",
        model_id_hint_zh="例如：Qwen/Qwen3-VL-8B-Instruct（与 SiliconFlow 同名）",
        model_id_hint_en="e.g. Qwen/Qwen3-VL-8B-Instruct (same as SiliconFlow)",
        region="china",
        website="https://modelscope.cn/",
    ),
    ProviderSpec(
        id="custom_openai",
        label_zh="自定义 OpenAI 兼容接口",
        label_en="Custom OpenAI-compatible endpoint",
        default_endpoint="",
        mode="openai-compatible",
        model_id_hint_zh="填写服务商文档中的模型 ID",
        model_id_hint_en="Model ID from your provider docs",
        region="international",
        lock_mode=False,
        lock_endpoint=False,
    ),
    ProviderSpec(
        id="custom_doubao",
        label_zh="自定义豆包 Responses 接口",
        label_en="Custom Doubao Responses endpoint",
        default_endpoint="",
        mode="doubao",
        model_id_hint_zh="填写豆包 Responses API 的模型或接入点 ID",
        model_id_hint_en="Doubao Responses model or endpoint ID",
        region="china",
        lock_mode=False,
        lock_endpoint=False,
    ),
)

_PROVIDER_BY_ID = {p.id: p for p in PROVIDERS}

DEFAULT_PROVIDER_ID = "custom_openai"


def get_provider(provider_id: str) -> ProviderSpec | None:
    return _PROVIDER_BY_ID.get(provider_id)


def provider_region(provider_id: str) -> Region:
    spec = get_provider(provider_id)
    return spec.region if spec is not None else "china"


def provider_label(provider_id: str, lang: str = "zh") -> str:
    spec = get_provider(provider_id) or get_provider(DEFAULT_PROVIDER_ID)
    if spec is None:
        return provider_id
    return spec.label_zh if lang == "zh" else spec.label_en


def apply_provider_to_form(provider_id: str) -> dict:
    spec = get_provider(provider_id) or get_provider(DEFAULT_PROVIDER_ID)
    if spec is None:
        return {"endpoint": "", "mode": "openai-compatible", "lock_mode": False, "lock_endpoint": False}
    return {
        "endpoint": spec.default_endpoint,
        "mode": spec.mode,
        "lock_mode": spec.lock_mode,
        "lock_endpoint": spec.lock_endpoint,
        "model_id_hint_zh": spec.model_id_hint_zh,
        "model_id_hint_en": spec.model_id_hint_en,
    }


_ENDPOINT_PATH_SUFFIXES = ("/chat/completions", "/responses")


def normalize_endpoint(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    # Users often paste full request URLs from provider docs; strip known API paths
    # so runtime/probe can append /chat/completions or /responses once.
    while True:
        stripped = False
        for suffix in _ENDPOINT_PATH_SUFFIXES:
            if value.endswith(suffix):
                value = value[: -len(suffix)].rstrip("/")
                stripped = True
                break
        if not stripped:
            break
    return value


def is_valid_endpoint(url: str) -> bool:
    normalized = normalize_endpoint(url)
    if not normalized:
        return False
    parsed = urlparse(normalized)
    return parsed.scheme in ("https", "http") and bool(parsed.netloc)


def normalize_mode(mode: str) -> str:
    value = (mode or "").strip().lower()
    if value == "doubao":
        return "doubao"
    if value in ("openai", "openai-compatible", "openai_compatible"):
        return "openai-compatible"
    return value or "openai-compatible"


def is_doubao_mode(mode: str) -> bool:
    return normalize_mode(mode) == "doubao"


def guess_provider_from_endpoint(endpoint: str, mode: str = "") -> str:
    from app.providers.registry import guess_provider_from_endpoint as _guess

    return _guess(endpoint, mode)


def resolve_api_transport(endpoint: str, api_mode: str) -> str:
    from app.providers.registry import resolve_api_transport as _resolve

    return _resolve(endpoint, api_mode)


def normalize_api_mode_for_select(mode: str, endpoint: str = "") -> str:
    from app.providers.registry import normalize_api_mode_for_select as _normalize

    return _normalize(mode, endpoint)


def provider_rules_for_api() -> dict:
    from app.providers.registry import provider_rules_for_api as _rules

    return _rules()


def resolve_provider_for_ui(endpoint: str, api_mode: str = "") -> dict:
    from app.providers.registry import resolve_provider_for_ui as _resolve

    return _resolve(endpoint, api_mode)


def validate_endpoint_mode_consistency(endpoint: str, api_mode: str) -> str | None:
    """Return a translation key when a known provider host conflicts with api_mode."""
    from app.providers.registry import match_host_entry

    ep = normalize_endpoint(endpoint)
    if not ep or not is_valid_endpoint(ep):
        return None
    entry = match_host_entry(ep)
    if entry is None:
        return None
    mode = normalize_mode(api_mode)
    if is_doubao_mode(mode) and entry.transport != "doubao":
        return "config.error_endpoint_mode_mismatch"
    if not is_doubao_mode(mode) and entry.transport == "doubao":
        return "config.error_endpoint_mode_mismatch"
    return None


def custom_model_profile_id(entry: dict) -> str:
    """Active model id from a canonical ``get_custom_models()`` profile."""
    return str(entry.get("default_model_id") or "").strip()


def find_custom_model_profile(custom_models: list, model_id: str) -> dict | None:
    """Find a custom model profile by canonical ``default_model_id``."""
    mid = (model_id or "").strip()
    if not mid:
        return None
    for entry in custom_models:
        if not isinstance(entry, dict):
            continue
        if custom_model_profile_id(entry) == mid:
            return entry
    return None


def resolve_active_model_id(config) -> str:
    """Model id used for API requests (matches ``AiWorker._resolve_request_credentials``)."""
    default_id = (config.get_default_model_id() or "").strip()
    if default_id:
        if find_custom_model_profile(config.get_custom_models(), default_id):
            return default_id
        return default_id
    return (config.get("model") or "").strip()


MIMO_MIC_MODEL_ID = "mimo-v2.5"


def is_mimo_mic_model(model_id: str) -> bool:
    return (model_id or "").strip().lower() == MIMO_MIC_MODEL_ID


def resolve_openai_provider_id(model_id: str, endpoint: str, api_mode: str = "") -> str:
    """Provider id for OpenAI-compat adapter/capability selection."""
    ep = normalize_endpoint(endpoint)
    mode = normalize_mode(api_mode)
    if is_mimo_mic_model(model_id) and resolve_api_transport(ep, mode) == "openai":
        if guess_provider_from_endpoint(ep, mode) == "mimo":
            return "mimo"
    return guess_provider_from_endpoint(ep, mode)


def get_capabilities_for_model(model_id: str, endpoint: str, api_mode: str = ""):
    from app.providers.capabilities import get_capabilities, get_capabilities_for_endpoint

    if resolve_openai_provider_id(model_id, endpoint, api_mode) == "mimo":
        return get_capabilities("mimo")
    return get_capabilities_for_endpoint(endpoint, api_mode)


def get_openai_adapter_for_model(model_id: str, endpoint: str, api_mode: str = ""):
    from app.providers import get_openai_adapter
    from app.providers.adapters.mimo import MimoOpenAIAdapter

    if resolve_openai_provider_id(model_id, endpoint, api_mode) == "mimo":
        adapter = get_openai_adapter(endpoint, api_mode)
        if isinstance(adapter, MimoOpenAIAdapter):
            return adapter
        return MimoOpenAIAdapter()
    return get_openai_adapter(endpoint, api_mode)


def model_likely_supports_mic_audio(model_id: str) -> bool:
    """Heuristic for Doubao Responses models that accept ``input_audio``."""
    mid = (model_id or "").strip().lower()
    if not mid:
        return False
    if "flash" in mid and "vision" not in mid:
        return False
    return any(tag in mid for tag in ("vision", "seed-2-0", "seed-1-8"))


def _coerce_supports_mic_declared(value) -> bool | None:
    if value is True:
        return True
    if value is False:
        return False
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    return None


def model_supports_mic_audio(
    model_id: str,
    *,
    endpoint: str = "",
    api_mode: str = "",
    supports_mic_declared: bool | str | None = None,
) -> bool:
    """Whether mic insert may attach audio for the active endpoint/model.

    Gate order: doubao heuristic → explicit ``supportsMic`` on custom model →
    built-in catalog → provider ``mic_audio`` capability (MiMo mimo-v2.5).
    """
    from app.model_catalog import catalog_model_supports_mic

    mode = normalize_mode(api_mode)
    ep = normalize_endpoint(endpoint)
    transport = resolve_api_transport(ep, mode)
    if is_doubao_mode(mode) or transport == "doubao":
        return model_likely_supports_mic_audio(model_id)

    declared = _coerce_supports_mic_declared(supports_mic_declared)
    if declared is True:
        return True
    if declared is False:
        return False

    if catalog_model_supports_mic(model_id):
        return True

    caps = get_capabilities_for_model(model_id, ep, mode)
    if caps.mic_audio and is_mimo_mic_model(model_id):
        return True
    return False


def mic_audio_unsupported_message(model_id: str) -> str:
    """User-facing reason when local gate rejects mic audio attachment."""
    mid = (model_id or "").strip() or "?"
    return (
        f"当前 provider/model「{mid}」未声明 mic_audio 支持。"
        "请在模型配置档案中勾选「支持麦克风」，或改用豆包全模态 / MiMo mimo-v2.5。"
    )


def mic_audio_supported_for_config(config) -> bool:
    """Match runtime mic gating: active model + global or custom endpoint/mode."""
    default_model_id = (config.get_default_model_id() or "").strip()
    if default_model_id:
        model = find_custom_model_profile(config.get_custom_models(), default_model_id)
        if model is not None:
            return model_supports_mic_audio(
                default_model_id,
                endpoint=(model.get("endpoint") or ""),
                api_mode=(model.get("mode") or ""),
                supports_mic_declared=model.get("supportsMic"),
            )
    return model_supports_mic_audio(
        resolve_active_model_id(config),
        endpoint=(config.get("api_endpoint") or ""),
        api_mode=(config.get("api_mode") or ""),
    )


def mic_audio_supported_for_mic_config(config) -> bool:
    """Mic gating based on mic tab credentials (falls back to visual when linked)."""
    if config.get("mic_use_visual_model", "1") == "1":
        return mic_audio_supported_for_config(config)
    endpoint = normalize_endpoint(config.get("mic_api_endpoint", ""))
    getter = getattr(config, "get_mic_api_key", None)
    api_key = (getter() if callable(getter) else "").strip()
    model_id = (config.get("mic_model") or "").strip()
    api_mode = normalize_mode(config.get("mic_api_mode", "doubao"))
    if not endpoint or not api_key or not model_id:
        return False
    return model_supports_mic_audio(model_id, endpoint=endpoint, api_mode=api_mode)


def resolve_mic_model_id(config) -> str:
    """Model id used for mic runtime logs and support checks."""
    if config.get("mic_use_visual_model", "1") == "1":
        return resolve_active_model_id(config)
    return (config.get("mic_model") or "").strip()


def validate_model_config(data: dict) -> list[str]:
    """Return translation keys for validation errors (in order).

    W-ARCH-MODEL-PROFILE-CANONICAL-004：仅校验 canonical shape（``model_ids`` 数组 +
    ``default_model_id``）。
    """
    errors: list[str] = []
    name = (data.get("name") or "").strip()
    endpoint = normalize_endpoint(data.get("endpoint") or "")
    api_key = (data.get("apiKey") or data.get("api_key") or "").strip()

    if not endpoint:
        errors.append("custom_model.error_endpoint")
    elif not is_valid_endpoint(endpoint):
        errors.append("custom_model.error_endpoint_invalid")

    model_ids = data.get("model_ids")
    if isinstance(model_ids, list):
        if not model_ids:
            errors.append("custom_model.error_model_id")
        else:
            for mid in model_ids:
                mid_str = str(mid or "").strip()
                if not mid_str:
                    errors.append("custom_model.error_model_id")
                    break
                if not re.match(r'^[a-zA-Z0-9_./:-]+$', mid_str):
                    errors.append("custom_model.error_model_id_invalid")
                    break
            default_model_id = (data.get("default_model_id") or "").strip()
            if default_model_id and default_model_id not in [
                str(mid).strip() for mid in model_ids if str(mid or "").strip()
            ]:
                errors.append("custom_model.error_model_id_invalid")
            elif not default_model_id:
                errors.append("custom_model.error_model_id")
    else:
        errors.append("custom_model.error_model_id")

    if not name:
        errors.append("custom_model.error_name")
    if not api_key:
        errors.append("custom_model.error_api_key")

    mode_raw = (data.get("mode") or data.get("api_mode") or "doubao")
    mode_key = validate_endpoint_mode_consistency(
        endpoint,
        normalize_api_mode_for_select(mode_raw, endpoint),
    )
    if mode_key:
        errors.append(mode_key)

    return errors


def is_model_config_complete(data: dict) -> bool:
    return len(validate_model_config(data)) == 0
