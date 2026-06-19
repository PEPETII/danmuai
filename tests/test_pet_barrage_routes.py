from unittest.mock import MagicMock

from app.web_api.routes import register_web_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_pet_settings_route_accepts_pet_barrage_payload():
    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    bridge.danmu_app.apply_pet_settings_patch.return_value = {
        "enabled": True,
        "pet_barrage": {"enabled": True, "count": 5},
    }

    def _check_token(authorization: str | None = None) -> None:
        if authorization != "Bearer pet-secret":
            from fastapi import HTTPException

            raise HTTPException(status_code=401)

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    response = client.post(
        "/api/pet/settings",
        json={
            "enabled": True,
            "pet_barrage_mode_enabled": True,
            "pet_barrage_slots": [
                {"slot_id": 0, "asset_source": "builtin", "asset_path": ""},
                {"slot_id": 1, "asset_source": "local", "asset_path": "C:/pets/cat"},
            ],
            "pet_barrage_slot_positions": [
                {"slot_id": 0, "x": 10, "y": 20},
                {"slot_id": 1, "x": 30, "y": 40},
            ],
        },
        headers={"Authorization": "Bearer pet-secret"},
    )

    assert response.status_code == 200
    patch_payload = bridge.danmu_app.apply_pet_settings_patch.call_args[0][0]
    assert patch_payload["pet_enabled"] is True
    assert patch_payload["pet_barrage_mode_enabled"] is True
    assert patch_payload["pet_barrage_slots"] == [
        {"slot_id": 0, "asset_source": "builtin", "asset_path": ""},
        {"slot_id": 1, "asset_source": "local", "asset_path": "C:/pets/cat"},
    ]
    assert patch_payload["pet_barrage_slot_positions"] == [
        {"slot_id": 0, "x": 10, "y": 20},
        {"slot_id": 1, "x": 30, "y": 40},
    ]
