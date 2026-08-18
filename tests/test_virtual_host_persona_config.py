"""虚拟主播独立人格 Prompt 配置测试。"""

from __future__ import annotations

import json

import pytest
from app.config_defaults import CONFIG_DEFAULTS
from app.virtual_host.persona_config import (
    MAX_PROMPT_CHARS,
    PERSONA_CONFIG_KEY,
    VirtualHostPersonaSnapshot,
    apply_virtual_host_persona_config,
    default_persona_values,
    export_virtual_host_persona_config,
    load_virtual_host_persona_snapshot,
    load_virtual_host_persona_values,
    sanitize_virtual_host_persona_config,
)


class _FakeConfig:
    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def set_batch(self, items: dict[str, str]) -> None:
        self._data.update(items)


def test_config_defaults_include_virtual_host_persona_key():
    assert CONFIG_DEFAULTS[PERSONA_CONFIG_KEY] == ""


def test_defaults_when_key_missing():
    config = _FakeConfig()

    values = load_virtual_host_persona_values(config)

    assert values == default_persona_values()


def test_corrupt_json_falls_back_to_defaults():
    config = _FakeConfig({PERSONA_CONFIG_KEY: "{not-json"})

    values = sanitize_virtual_host_persona_config(config, persist=True)

    assert values == default_persona_values()
    stored = json.loads(config.get(PERSONA_CONFIG_KEY))
    assert stored == default_persona_values()


def test_partial_stored_fields_use_defaults_for_missing():
    config = _FakeConfig(
        {
            PERSONA_CONFIG_KEY: json.dumps({"system_prompt": "  自定义系统  "}),
        }
    )

    values = load_virtual_host_persona_values(config)

    assert values["system_prompt"] == "自定义系统"
    assert values["voice_dialogue_prompt"] == default_persona_values()["voice_dialogue_prompt"]


def test_apply_saves_both_fields_atomically():
    config = _FakeConfig()
    patch = {
        "system_prompt": "  系统层  ",
        "voice_dialogue_prompt": "  语音层  ",
    }

    result = apply_virtual_host_persona_config(config, patch)

    assert result["system_prompt"] == "系统层"
    assert result["voice_dialogue_prompt"] == "语音层"
    assert result["defaults"] == default_persona_values()
    reloaded = load_virtual_host_persona_values(config)
    assert reloaded == {
        "system_prompt": "系统层",
        "voice_dialogue_prompt": "语音层",
    }


def test_apply_reset_restores_code_defaults():
    config = _FakeConfig(
        {
            PERSONA_CONFIG_KEY: json.dumps(
                {
                    "system_prompt": "自定义",
                    "voice_dialogue_prompt": "自定义语音",
                }
            )
        }
    )

    result = apply_virtual_host_persona_config(config, {}, reset=True)

    assert result["system_prompt"] == default_persona_values()["system_prompt"]
    assert result["voice_dialogue_prompt"] == default_persona_values()["voice_dialogue_prompt"]


def test_apply_rejects_unknown_fields():
    config = _FakeConfig()

    with pytest.raises(ValueError, match="invalid_payload"):
        apply_virtual_host_persona_config(config, {"extra": "x"})


def test_apply_rejects_empty_prompt():
    config = _FakeConfig()

    with pytest.raises(ValueError, match="empty_prompt_not_allowed"):
        apply_virtual_host_persona_config(config, {"system_prompt": "   "})


def test_apply_rejects_non_string_prompt():
    config = _FakeConfig()

    with pytest.raises(ValueError, match="invalid_payload"):
        apply_virtual_host_persona_config(config, {"system_prompt": 123})


def test_apply_rejects_too_long_prompt():
    config = _FakeConfig()

    with pytest.raises(ValueError, match="prompt_too_long"):
        apply_virtual_host_persona_config(
            config,
            {"system_prompt": "x" * (MAX_PROMPT_CHARS + 1)},
        )


def test_snapshot_loader_returns_frozen_values():
    config = _FakeConfig()
    apply_virtual_host_persona_config(
        config,
        {
            "system_prompt": "快照系统",
            "voice_dialogue_prompt": "快照语音",
        },
    )

    snapshot = load_virtual_host_persona_snapshot(config)

    assert snapshot == VirtualHostPersonaSnapshot(
        system_prompt="快照系统",
        voice_dialogue_prompt="快照语音",
    )


def test_export_includes_defaults_block():
    config = _FakeConfig()

    exported = export_virtual_host_persona_config(config)

    assert exported["defaults"] == default_persona_values()
    assert exported["system_prompt"] == default_persona_values()["system_prompt"]


def test_apply_does_not_touch_unrelated_config_keys():
    config = _FakeConfig(
        {
            "custom_personae": '{"foo": "bar"}',
            "active_personae": '["路人惊讶型"]',
            "danmu_read_enabled": "1",
        }
    )

    apply_virtual_host_persona_config(
        config,
        {
            "system_prompt": "隔离系统",
            "voice_dialogue_prompt": "隔离语音",
        },
    )

    assert config.get("custom_personae") == '{"foo": "bar"}'
    assert config.get("active_personae") == '["路人惊讶型"]'
    assert config.get("danmu_read_enabled") == "1"
