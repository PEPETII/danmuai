"""DanmuApp 桌宠显示与 Web façade mixin。

职责边界：
- 桌宠窗口显隐同步与 Web API façade 委托
- 视觉成功/失败动画通知
- 不迁出 app/pet/ 子模块实现
"""

from __future__ import annotations


class DanmuAppPetMixin:
    def _sync_pet_window_visibility(self) -> None:
        """独立于 danmu_render_mode；pet_enabled + pet_visible 控制桌宠显隐。"""
        # 未初始化且配置不要求显示桌宠 → 快速跳过（保留 PERF-002 惰性初始化收益）
        if self.__dict__.get("pet_window") is None:
            if self.config.get("pet_enabled", "0") != "1":
                return
            if self.config.get("pet_visible", "0") != "1":
                return
            self._ensure_pet_components()
        from app.pet.pet_facade import sync_pet_window_visibility

        sync_pet_window_visibility(self)

    def get_pet_animation_hint(self) -> str:
        from app.pet.pet_facade import get_pet_animation_hint

        return get_pet_animation_hint(self)

    def get_pet_settings_snapshot(self) -> dict[str, object]:
        from app.pet.pet_facade import get_pet_settings_snapshot

        return get_pet_settings_snapshot(self)

    def apply_pet_settings_patch(self, payload: dict[str, object]) -> dict[str, object]:
        from app.pet.pet_facade import apply_pet_settings_patch

        return apply_pet_settings_patch(self, payload)

    def import_pet_asset_via_dialog(self) -> dict[str, object]:
        from app.pet.pet_facade import import_pet_asset_via_dialog

        return import_pet_asset_via_dialog(self)

    def import_pet_barrage_slot_asset_via_dialog(self, slot_id: int) -> dict[str, object]:
        from app.pet.pet_facade import import_pet_barrage_slot_asset_via_dialog

        return import_pet_barrage_slot_asset_via_dialog(self, slot_id)

    def reset_pet_asset_to_builtin(self) -> dict[str, object]:
        from app.pet.pet_facade import reset_pet_asset_to_builtin

        return reset_pet_asset_to_builtin(self)

    def set_pet_barrage_slot_asset(
        self,
        slot_id: int,
        *,
        asset_source: str,
        asset_path: str,
    ) -> dict[str, object]:
        from app.pet.pet_facade import set_pet_barrage_slot_asset

        return set_pet_barrage_slot_asset(
            self,
            slot_id,
            asset_source=asset_source,
            asset_path=asset_path,
        )

    def reset_pet_barrage_slot_asset(self, slot_id: int) -> dict[str, object]:
        from app.pet.pet_facade import reset_pet_barrage_slot_asset

        return reset_pet_barrage_slot_asset(self, slot_id)

    def show_pet(self) -> dict[str, object]:
        self._ensure_pet_components()
        from app.pet.pet_facade import show_pet

        return show_pet(self)

    def hide_pet(self) -> dict[str, object]:
        self._ensure_pet_components()
        from app.pet.pet_facade import hide_pet

        return hide_pet(self)

    def close_pet(self) -> dict[str, object]:
        self._ensure_pet_components()
        from app.pet.pet_facade import close_pet

        return close_pet(self)

    def submit_pet_command(self, text: str, *, source: str = "web_api") -> dict[str, object]:
        from app.pet.pet_facade import submit_pet_command

        return submit_pet_command(self, text, source=source)

    def get_pet_status_snapshot(self) -> dict[str, object]:
        from app.pet.pet_facade import get_pet_status_snapshot

        return get_pet_status_snapshot(self)

    def _notify_pet_visual_success(self) -> None:
        window = self.__dict__.get("pet_window")
        barrage = self.__dict__.get("pet_barrage_controller")
        if barrage is not None and hasattr(barrage, "notify_success"):
            try:
                barrage.notify_success()
            except RuntimeError as exc:
                self.logger.debug(f"pet barrage success animation skipped: {exc!r}")
        if window is not None:
            try:
                window.notify_reply_success()
            except RuntimeError as exc:
                self.logger.debug(f"pet success animation skipped: {exc!r}")

    def _notify_pet_visual_error(self) -> None:
        window = self.__dict__.get("pet_window")
        barrage = self.__dict__.get("pet_barrage_controller")
        if barrage is not None and hasattr(barrage, "notify_error"):
            try:
                barrage.notify_error()
            except RuntimeError as exc:
                self.logger.debug(f"pet barrage error animation skipped: {exc!r}")
        if window is not None:
            try:
                window.notify_error()
            except RuntimeError as exc:
                self.logger.debug(f"pet error animation skipped: {exc!r}")
