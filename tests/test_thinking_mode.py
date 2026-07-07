"""Thinking mode parameter style and catalog gating."""

from app.model_catalog import (
    catalog_model_supports_thinking_toggle,
    get_thinking_mode_for_model,
)
from app.providers.capabilities import get_capabilities
from app.providers.thinking import apply_thinking_mode


def test_get_capabilities_thinking_param_styles():
    assert get_capabilities("dashscope").thinking_param_style == "enable_thinking"
    assert get_capabilities("doubao").thinking_param_style == "thinking_type"
    assert get_capabilities("mimo").thinking_param_style == "thinking_type"
    assert get_capabilities("zhipu").thinking_param_style == "thinking_type"
    assert get_capabilities("openrouter").thinking_param_style == "none"
    assert get_capabilities("custom_openai").thinking_param_style == "none"
    assert get_capabilities("siliconflow").thinking_param_style == "enable_thinking"


def test_apply_thinking_mode_thinking_type():
    caps = get_capabilities("moonshot")
    data: dict = {}
    apply_thinking_mode(data, enabled=True, caps=caps)
    assert data == {"thinking": {"type": "enabled"}}
    apply_thinking_mode(data, enabled=False, caps=caps)
    assert data == {"thinking": {"type": "disabled"}}


def test_apply_thinking_mode_enable_thinking():
    caps = get_capabilities("dashscope")
    data: dict = {"thinking": {"type": "enabled"}}
    apply_thinking_mode(data, enabled=True, caps=caps)
    assert data == {"enable_thinking": True}
    apply_thinking_mode(data, enabled=False, caps=caps)
    assert data == {"enable_thinking": False}


def test_apply_thinking_mode_none_clears_fields():
    caps = get_capabilities("openrouter")
    data = {"thinking": {"type": "enabled"}, "enable_thinking": True}
    apply_thinking_mode(data, enabled=True, caps=caps)
    assert "thinking" not in data
    assert "enable_thinking" not in data


def test_catalog_thinking_toggle_hybrid_only():
    assert get_thinking_mode_for_model("qwen3-vl-flash") == "hybrid"
    assert catalog_model_supports_thinking_toggle("qwen3-vl-flash") is True
    assert get_thinking_mode_for_model("qwen-vl-max") == "off"
    assert catalog_model_supports_thinking_toggle("qwen-vl-max") is False
    assert get_thinking_mode_for_model("Qwen/Qwen3-VL-8B-Instruct") == "off"
    assert get_thinking_mode_for_model("Qwen/Qwen3-VL-8B-Thinking") == "always"
    assert catalog_model_supports_thinking_toggle("Qwen/Qwen3-VL-8B-Thinking") is False
    assert get_thinking_mode_for_model("ernie-5-0-thinking-latest") == "always"
