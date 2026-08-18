from __future__ import annotations

from unittest.mock import MagicMock

from app.web_api import virtual_host as virtual_host_api


def test_virtual_host_api_delegates_to_danmu_app_facade():
    app = MagicMock()
    app.get_virtual_host_model_config.return_value = {"vision_model_id": ""}
    app.apply_virtual_host_model_config.return_value = {"vision_model_id": "m1"}

    assert virtual_host_api.get_model_config(app) == {"vision_model_id": ""}
    assert virtual_host_api.save_model_config(app, {"vision_model_id": "m1"}) == {"vision_model_id": "m1"}
    app.apply_virtual_host_model_config.assert_called_once_with({"vision_model_id": "m1"})


def test_virtual_host_settings_api_delegates_to_danmu_app_facade():
    app = MagicMock()
    app.get_virtual_host_settings.return_value = {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": True,
    }
    app.apply_virtual_host_settings.return_value = {
        "dialogue_enabled": True,
        "danmu_adapter_enabled": False,
    }

    assert virtual_host_api.get_settings(app) == {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": True,
    }
    assert virtual_host_api.save_settings(app, {"dialogue_enabled": True}) == {
        "dialogue_enabled": True,
        "danmu_adapter_enabled": False,
    }
    app.apply_virtual_host_settings.assert_called_once_with({"dialogue_enabled": True})


def test_virtual_host_voice_status_api_delegates_to_danmu_app_facade():
    app = MagicMock()
    app.get_virtual_host_voice_status.return_value = {"phase": "idle", "armed": False}

    assert virtual_host_api.get_voice_status(app) == {"phase": "idle", "armed": False}
    app.get_virtual_host_voice_status.assert_called_once_with()
