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
