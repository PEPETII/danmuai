"""Provider presets and validation for custom model configurations."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label_zh: str
    label_en: str
    default_endpoint: str
    mode: str
    model_id_hint_zh: str
    model_id_hint_en: str
    lock_mode: bool = True
    lock_endpoint: bool = False


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="doubao",
        label_zh="火山方舟",
        label_en="Volcengine Ark",
        default_endpoint="https://ark.cn-beijing.volces.com/api/v3",
        mode="doubao",
        model_id_hint_zh="截图弹幕可用 flash；开麦请用 doubao-seed-2-0-mini-260428 等全模态/vision 模型",
        model_id_hint_en="flash for vision-only danmu; enable mic with doubao-seed-2-0-mini-260428 or vision models",
    ),
    ProviderSpec(
        id="dashscope",
        label_zh="阿里云百炼",
        label_en="Alibaba DashScope",
        default_endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
        mode="openai-compatible",
        model_id_hint_zh="例如：qwen-vl-max",
        model_id_hint_en="e.g. qwen-vl-max",
    ),
    ProviderSpec(
        id="zhipu",
        label_zh="智谱 AI",
        label_en="Zhipu AI",
        default_endpoint="https://open.bigmodel.cn/api/paas/v4",
        mode="openai-compatible",
        model_id_hint_zh="例如：glm-4v-flash",
        model_id_hint_en="e.g. glm-4v-flash",
    ),
    ProviderSpec(
        id="deepseek",
        label_zh="DeepSeek",
        label_en="DeepSeek",
        default_endpoint="https://api.deepseek.com/v1",
        mode="openai-compatible",
        model_id_hint_zh="例如：deepseek-chat",
        model_id_hint_en="e.g. deepseek-chat",
    ),
    ProviderSpec(
        id="moonshot",
        label_zh="Moonshot (Kimi)",
        label_en="Moonshot (Kimi)",
        default_endpoint="https://api.moonshot.cn/v1",
        mode="openai-compatible",
        model_id_hint_zh="例如：moonshot-v1-8k-vision-preview",
        model_id_hint_en="e.g. moonshot-v1-8k-vision-preview",
    ),
    ProviderSpec(
        id="siliconflow",
        label_zh="轨迹流动",
        label_en="SiliconFlow",
        default_endpoint="https://api.siliconflow.cn/v1",
        mode="openai-compatible",
        model_id_hint_zh="例如：deepseek-ai/DeepSeek-V3",
        model_id_hint_en="e.g. deepseek-ai/DeepSeek-V3",
    ),
    ProviderSpec(
        id="custom_openai",
        label_zh="自定义（OpenAI 兼容）",
        label_en="Custom (OpenAI compatible)",
        default_endpoint="",
        mode="openai-compatible",
        model_id_hint_zh="填写服务商文档中的模型 ID",
        model_id_hint_en="Model ID from your provider docs",
        lock_mode=False,
        lock_endpoint=False,
    ),
    ProviderSpec(
        id="custom_doubao",
        label_zh="自定义（豆包 Responses）",
        label_en="Custom (Doubao Responses)",
        default_endpoint="",
        mode="doubao",
        model_id_hint_zh="填写豆包 Responses API 的模型或接入点 ID",
        model_id_hint_en="Doubao Responses model or endpoint ID",
        lock_mode=False,
        lock_endpoint=False,
    ),
)

_PROVIDER_BY_ID = {p.id: p for p in PROVIDERS}

DEFAULT_PROVIDER_ID = "custom_openai"

# endpoint substring -> provider id (longer matches first)
_ENDPOINT_GUESSES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [
            ("ark.cn-beijing.volces.com", "doubao"),
            ("dashscope.aliyuncs.com", "dashscope"),
            ("open.bigmodel.cn", "zhipu"),
            ("api.deepseek.com", "deepseek"),
            ("api.moonshot.cn", "moonshot"),
            ("api.siliconflow.cn", "siliconflow"),
        ],
        key=lambda item: -len(item[0]),
    )
)


def list_providers() -> list[ProviderSpec]:
    return list(PROVIDERS)


def get_provider(provider_id: str) -> ProviderSpec | None:
    return _PROVIDER_BY_ID.get(provider_id)


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


def guess_provider_from_endpoint(endpoint: str, mode: str = "") -> str:
    normalized = normalize_endpoint(endpoint) if endpoint else ""
    for fragment, provider_id in _ENDPOINT_GUESSES:
        if fragment in normalized:
            return provider_id
    if normalize_mode(mode) == "doubao":
        return "custom_doubao"
    return DEFAULT_PROVIDER_ID


def normalize_endpoint(url: str) -> str:
    value = (url or "").strip().rstrip("/")
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


def resolve_active_model_id(config) -> str:
    """Model id used for API requests (matches ``AiWorker._resolve_request_credentials``)."""
    default_id = (config.get_default_model_id() or "").strip()
    if default_id:
        for entry in config.get_custom_models():
            if (entry.get("modelId") or "").strip() == default_id:
                return default_id
        return default_id
    return (config.get("model") or "").strip()


def model_likely_supports_mic_audio(model_id: str) -> bool:
    """Heuristic for Doubao Responses models that accept ``input_audio``."""
    mid = (model_id or "").strip().lower()
    if not mid:
        return False
    if "flash" in mid and "vision" not in mid:
        return False
    return any(tag in mid for tag in ("vision", "seed-2-0", "seed-1-8"))


def validate_model_config(data: dict) -> list[str]:
    """Return translation keys for validation errors (in order)."""
    errors: list[str] = []
    name = (data.get("name") or "").strip()
    model_id = (data.get("modelId") or data.get("model_id") or "").strip()
    endpoint = normalize_endpoint(data.get("endpoint") or "")
    api_key = (data.get("apiKey") or data.get("api_key") or "").strip()
    if not name:
        errors.append("custom_model.error_name")
    if not model_id:
        errors.append("custom_model.error_model_id")
    if not endpoint:
        errors.append("custom_model.error_endpoint")
    elif not is_valid_endpoint(endpoint):
        errors.append("custom_model.error_endpoint_invalid")
    if not api_key:
        errors.append("custom_model.error_api_key")

    return errors


def is_model_config_complete(data: dict) -> bool:
    return len(validate_model_config(data)) == 0
