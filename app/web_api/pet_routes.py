"""桌宠 Web API 路由注册。

路由（由 ``app.web_api.routes`` 调用 ``register_pet_routes``）：
- ``GET/POST /api/pet/settings``：桌宠配置读写
- ``POST /api/pet/import-folder`` / ``reset-asset``：主资源导入与重置
- ``GET /api/pet/barrage-slots/{slot_id}/preview``：弹幕槽预览
- ``POST /api/pet/barrage-slots/{slot_id}/*``：弹幕槽资源操作
- ``POST /api/pet/show`` / ``hide`` / ``close`` / ``command``：显隐与指令
- ``GET /api/pet/status``：运行态快照

写操作经 ``invoke_main``（``WebConsoleBridge.invoke_on_main`` 包装）回到主线程。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header
from pydantic import BaseModel

from app.web_api import pet as pet_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class PetSettingsPayload(BaseModel):
    enabled: bool | None = None
    visible: bool | None = None
    asset_source: str | None = None
    asset_path: str | None = None
    scale: float | None = None
    opacity: float | None = None
    always_on_top: bool | None = None
    click_through: bool | None = None
    position_x: int | None = None
    position_y: int | None = None
    command_box_enabled: bool | None = None
    command_ttl_sec: int | None = None
    command_apply_count: int | None = None
    pet_barrage_mode_enabled: bool | None = None
    pet_barrage_slots: list[dict] | None = None
    pet_barrage_slot_positions: list[dict] | None = None


class PetCommandPayload(BaseModel):
    text: str = ""


class PetBarrageSlotAssetPayload(BaseModel):
    asset_source: str = "builtin"
    asset_path: str = ""


def register_pet_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/pet/settings")
    def get_pet_settings():
        return pet_api.get_settings(bridge.danmu_app)

    @app.post("/api/pet/settings")
    @require_auth(check_token)
    def post_pet_settings(
        body: PetSettingsPayload,
        authorization: str | None = Header(default=None),
    ):
        raw = body.model_dump(exclude_none=True)
        payload = {
            "pet_enabled": raw.get("enabled"),
            "pet_asset_source": raw.get("asset_source"),
            "pet_asset_path": raw.get("asset_path"),
            "pet_scale": raw.get("scale"),
            "pet_opacity": raw.get("opacity"),
            "pet_always_on_top": raw.get("always_on_top"),
            "pet_click_through": raw.get("click_through"),
            "pet_position_x": raw.get("position_x"),
            "pet_position_y": raw.get("position_y"),
            "pet_command_box_enabled": raw.get("command_box_enabled"),
            "pet_command_ttl_sec": raw.get("command_ttl_sec"),
            "pet_command_apply_count": raw.get("command_apply_count"),
            "pet_barrage_mode_enabled": raw.get("pet_barrage_mode_enabled"),
            "pet_barrage_slots": raw.get("pet_barrage_slots"),
            "pet_barrage_slot_positions": raw.get("pet_barrage_slot_positions"),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return invoke_main(pet_api.save_settings, bridge.danmu_app, payload)

    @app.post("/api/pet/import-folder")
    @require_auth(check_token)
    def post_pet_import_folder(authorization: str | None = Header(default=None)):
        return invoke_main(pet_api.import_asset_via_dialog, bridge.danmu_app)

    @app.post("/api/pet/reset-asset")
    @require_auth(check_token)
    def post_pet_reset_asset(authorization: str | None = Header(default=None)):
        return invoke_main(pet_api.reset_asset_to_builtin, bridge.danmu_app)

    @app.get("/api/pet/barrage-slots/{slot_id}/preview")
    def get_pet_barrage_slot_preview(slot_id: int):
        return pet_api.get_barrage_slot_preview(bridge.danmu_app, slot_id)

    @app.post("/api/pet/barrage-slots/{slot_id}/asset")
    @require_auth(check_token)
    def post_pet_barrage_slot_asset(
        slot_id: int,
        body: PetBarrageSlotAssetPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(
            pet_api.set_barrage_slot_asset,
            bridge.danmu_app,
            slot_id,
            asset_source=body.asset_source,
            asset_path=body.asset_path,
        )

    @app.post("/api/pet/barrage-slots/{slot_id}/import-folder")
    @require_auth(check_token)
    def post_pet_barrage_slot_import_folder(
        slot_id: int,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(pet_api.import_barrage_slot_asset_via_dialog, bridge.danmu_app, slot_id)

    @app.post("/api/pet/barrage-slots/{slot_id}/reset")
    @require_auth(check_token)
    def post_pet_barrage_slot_reset(
        slot_id: int,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(pet_api.reset_barrage_slot_asset, bridge.danmu_app, slot_id)

    @app.post("/api/pet/show")
    @require_auth(check_token)
    def post_pet_show(authorization: str | None = Header(default=None)):
        return invoke_main(pet_api.show_pet, bridge.danmu_app)

    @app.post("/api/pet/hide")
    @require_auth(check_token)
    def post_pet_hide(authorization: str | None = Header(default=None)):
        return invoke_main(pet_api.hide_pet, bridge.danmu_app)

    @app.post("/api/pet/close")
    @require_auth(check_token)
    def post_pet_close(authorization: str | None = Header(default=None)):
        return invoke_main(pet_api.close_pet, bridge.danmu_app)

    @app.post("/api/pet/command")
    @require_auth(check_token)
    def post_pet_command(
        body: PetCommandPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(pet_api.submit_command, bridge.danmu_app, body.text)

    @app.get("/api/pet/status")
    def get_pet_status():
        return pet_api.get_status(bridge.danmu_app)
