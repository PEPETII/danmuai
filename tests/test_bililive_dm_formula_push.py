"""W-BILILIVE-DM-PLUGIN-FORMULA-008 — 公式化弹幕 bililive_dm 旁路推送测试。"""

from __future__ import annotations

from unittest.mock import patch

from app.danmu_engine_models import DanmuItem

from tests.conftest import make_minimal_danmu_app


def _fake_item(text: str = "公式化补位") -> DanmuItem:
    return DanmuItem(content=text, y=42.0, speed=3.5)


def test_formula_broadcast_schedules_push_when_dm_mode_enabled():
    app = make_minimal_danmu_app()
    app.config.set("bililive_dm_mode_enabled", "1")
    item = _fake_item("池句A")
    with patch(
        "app.application.bililive_dm_push_service.schedule_push_batch"
    ) as mock_push:
        app._broadcast_live_overlay_item(item, "池句A", source="pool_topup")
        mock_push.assert_called_once()
        kwargs = mock_push.call_args.kwargs
        assert kwargs["items"] == ["池句A"]
        assert kwargs["batch_id"] == 1


def test_formula_broadcast_does_not_schedule_push_when_dm_mode_off():
    app = make_minimal_danmu_app()
    app.config.set("bililive_dm_mode_enabled", "0")
    item = _fake_item("池句B")
    with patch(
        "app.application.bililive_dm_push_service.schedule_push_batch"
    ) as mock_push:
        app._broadcast_live_overlay_item(item, "池句B", source="pool_topup")
        mock_push.assert_not_called()


def test_meme_barrage_broadcast_schedules_push_when_dm_mode_enabled():
    app = make_minimal_danmu_app()
    app.config.set("bililive_dm_mode_enabled", "1")
    item = _fake_item("烂梗句")
    with patch(
        "app.application.bililive_dm_push_service.schedule_push_batch"
    ) as mock_push:
        app._broadcast_live_overlay_item(item, "烂梗句", source="meme_barrage")
        mock_push.assert_called_once()
        assert mock_push.call_args.kwargs["items"] == ["烂梗句"]


def test_duplicate_topup_broadcast_schedules_push_when_dm_mode_enabled():
    app = make_minimal_danmu_app()
    app.config.set("bililive_dm_mode_enabled", "1")
    item = _fake_item("去重补偿")
    with patch(
        "app.application.bililive_dm_push_service.schedule_push_batch"
    ) as mock_push:
        app._broadcast_live_overlay_item(
            item,
            "去重补偿",
            source="pool_duplicate_topup",
        )
        mock_push.assert_called_once()


def test_ai_broadcast_does_not_trigger_formula_push_hook():
    app = make_minimal_danmu_app()
    app.config.set("bililive_dm_mode_enabled", "1")
    item = _fake_item("AI弹幕")
    with patch(
        "app.application.bililive_dm_push_service.schedule_push_batch"
    ) as mock_push:
        app._broadcast_live_overlay_item(item, "AI弹幕", source="ai")
        mock_push.assert_not_called()


def test_formula_push_increments_batch_id():
    app = make_minimal_danmu_app()
    app.config.set("bililive_dm_mode_enabled", "1")
    app._batch_id = 7
    with patch(
        "app.application.bililive_dm_push_service.schedule_push_batch"
    ) as mock_push:
        app._schedule_bililive_dm_formula_push(
            "句1",
            source="pool_topup",
            persona="",
        )
        assert app._batch_id == 8
        assert mock_push.call_args.kwargs["batch_id"] == 8
