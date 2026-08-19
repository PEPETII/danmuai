from __future__ import annotations

import pytest
from app.config_defaults import CONFIG_DEFAULTS
from app.virtual_host.mode_config import (
    DANMU_ADAPTER_ENABLED_KEY,
    DIALOGUE_ENABLED_KEY,
    KNOWLEDGE_ENABLED_KEY,
    apply_virtual_host_mode_settings,
    export_virtual_host_mode_settings,
    sanitize_virtual_host_mode_settings,
    virtual_host_knowledge_enabled,
)


class _FakeConfig:
    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def set_batch(self, items: dict[str, str]) -> None:
        self._data.update(items)


def test_mode_defaults_when_keys_missing():
    config = _FakeConfig()

    exported = export_virtual_host_mode_settings(config)

    assert exported == {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": True,
        "knowledge_enabled": True,
    }


def test_config_defaults_include_virtual_host_mode_keys():
    assert CONFIG_DEFAULTS[DIALOGUE_ENABLED_KEY] == "0"
    assert CONFIG_DEFAULTS[DANMU_ADAPTER_ENABLED_KEY] == "1"
    assert CONFIG_DEFAULTS[KNOWLEDGE_ENABLED_KEY] == "1"


def test_sanitize_repairs_both_modes_enabled_in_storage():
    config = _FakeConfig(
        {
            DIALOGUE_ENABLED_KEY: "1",
            DANMU_ADAPTER_ENABLED_KEY: "1",
        }
    )

    sanitize_virtual_host_mode_settings(config, persist=True)

    assert export_virtual_host_mode_settings(config) == {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": True,
        "knowledge_enabled": True,
    }


def test_enable_dialogue_atomically_disables_danmu_adapter():
    config = _FakeConfig(
        {
            DIALOGUE_ENABLED_KEY: "0",
            DANMU_ADAPTER_ENABLED_KEY: "1",
        }
    )

    result = apply_virtual_host_mode_settings(config, {"dialogue_enabled": True})

    assert result == {
        "dialogue_enabled": True,
        "danmu_adapter_enabled": False,
        "knowledge_enabled": True,
    }
    assert config.get(DIALOGUE_ENABLED_KEY) == "1"
    assert config.get(DANMU_ADAPTER_ENABLED_KEY) == "0"


def test_enable_danmu_adapter_atomically_disables_dialogue():
    config = _FakeConfig(
        {
            DIALOGUE_ENABLED_KEY: "1",
            DANMU_ADAPTER_ENABLED_KEY: "0",
        }
    )

    result = apply_virtual_host_mode_settings(config, {"danmu_adapter_enabled": True})

    assert result == {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": True,
        "knowledge_enabled": True,
    }


def test_disable_either_mode_allows_both_false():
    config = _FakeConfig(
        {
            DIALOGUE_ENABLED_KEY: "1",
            DANMU_ADAPTER_ENABLED_KEY: "0",
        }
    )

    result = apply_virtual_host_mode_settings(config, {"dialogue_enabled": False})

    assert result == {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": False,
        "knowledge_enabled": True,
    }


def test_apply_rejects_both_modes_true_without_partial_save():
    config = _FakeConfig(
        {
            DIALOGUE_ENABLED_KEY: "0",
            DANMU_ADAPTER_ENABLED_KEY: "1",
        }
    )

    with pytest.raises(ValueError, match="virtual_host_modes_mutually_exclusive"):
        apply_virtual_host_mode_settings(
            config,
            {"dialogue_enabled": True, "danmu_adapter_enabled": True},
        )

    assert export_virtual_host_mode_settings(config) == {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": True,
        "knowledge_enabled": True,
    }


def test_apply_rejects_unknown_fields_and_invalid_types():
    config = _FakeConfig()

    with pytest.raises(ValueError, match="invalid_payload"):
        apply_virtual_host_mode_settings(config, {"unknown": True})

    with pytest.raises(ValueError, match="invalid_payload"):
        apply_virtual_host_mode_settings(config, {"dialogue_enabled": "1"})


def test_empty_patch_returns_current_settings_without_write():
    config = _FakeConfig(
        {
            DIALOGUE_ENABLED_KEY: "0",
            DANMU_ADAPTER_ENABLED_KEY: "1",
        }
    )

    result = apply_virtual_host_mode_settings(config, {})

    assert result == {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": True,
        "knowledge_enabled": True,
    }


def test_disable_knowledge_retrieval():
    config = _FakeConfig(
        {
            DIALOGUE_ENABLED_KEY: "0",
            DANMU_ADAPTER_ENABLED_KEY: "1",
            KNOWLEDGE_ENABLED_KEY: "1",
        }
    )

    result = apply_virtual_host_mode_settings(config, {"knowledge_enabled": False})

    assert result["knowledge_enabled"] is False
    assert config.get(KNOWLEDGE_ENABLED_KEY) == "0"
    assert virtual_host_knowledge_enabled(config) is False
