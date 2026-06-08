"""PET-006: pet command consumed only when visual request actually fires."""

import time
from unittest.mock import Mock

from main import DanmuApp

from tests.conftest import make_minimal_danmu_app


def test_trigger_api_call_blocked_does_not_consume_pet_command(monkeypatch):
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._latest_screenshot = object()
    app._latest_screenshot_id = 1
    app._latest_screenshot_time = time.monotonic()
    app.personae = Mock(pick_random=Mock(return_value="吐槽型"), get_prompt=Mock(return_value=("sys", "user")))

    from app.pet.pet_command_service import PetCommandService

    app.pet_command_service = PetCommandService()
    app.pet_command_service.submit("blocked cmd", ttl_sec=30, apply_count=1)

    app._api_schedule_block_reason = Mock(return_value="in_flight")
    app._log_api_schedule = Mock()
    app._trigger_api_call = DanmuApp._trigger_api_call.__get__(app, DanmuApp)
    app._trigger_api_call()
    assert app.pet_command_service.has_pending()


def test_trigger_api_call_fire_consumes_and_injects_prompt(monkeypatch):
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._latest_screenshot = object()
    app._latest_screenshot_id = 2
    app._latest_screenshot_time = time.monotonic()
    app.personae = Mock(pick_random=Mock(return_value="吐槽型"), get_prompt=Mock(return_value=("sys", "user")))
    app._append_scene_memory_to_user_pt = DanmuApp._append_scene_memory_to_user_pt.__get__(app, DanmuApp)

    from app.pet.pet_command_service import PetCommandService

    app.pet_command_service = PetCommandService()
    app.pet_command_service.submit("inject me", ttl_sec=30, apply_count=1)

    captured = {}

    class _Runnable:
        def __init__(self, _worker, _pixmap, system_pt, user_pt, *_rest, **_kw):
            captured["system_pt"] = system_pt
            captured["user_pt"] = user_pt
            captured["persona"] = _rest[0] if _rest else ""

    pool = Mock()
    pool.start = Mock()
    monkeypatch.setattr("PyQt6.QtCore.QThreadPool", Mock(globalInstance=Mock(return_value=pool)))
    monkeypatch.setattr("app.runnable.AiRunnable", _Runnable)

    app._api_schedule_block_reason = Mock(return_value="")
    app._get_request_scheduler = Mock(return_value=Mock(record_trigger_time=Mock()))
    app._get_request_timing_service = Mock(return_value=Mock(mark_started=Mock()))
    app._register_request_meta = Mock()
    app._publish_live_status = Mock()
    app._log_api_schedule = Mock()
    app._trigger_api_call = DanmuApp._trigger_api_call.__get__(app, DanmuApp)

    app._trigger_api_call()
    assert not app.pet_command_service.has_pending()
    assert "inject me" in captured["user_pt"]
    assert "【桌宠观众指令 · 本批优先】" in captured["user_pt"]
    assert "inject me" in captured["system_pt"]
    assert "桌宠指令" in captured["system_pt"]
