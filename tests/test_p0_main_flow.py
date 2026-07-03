"""P0 main flow tests: stale AiRunnable race (W-RACE-001 / bug-03 缺陷 3).

验证 ``stop() → start()`` 之间陈旧 ``AiRunnable`` 到达 ``_on_ai_reply`` 时不
上屏、不消耗新会话 in-flight 槽位、token 统计不被污染（既有正常路径不受影响）。
"""
import time
from unittest.mock import MagicMock

import main as main_mod

from app.application import generation_pipeline as gen_pipeline_mod
from app.application.request_timing_service import RequestTimingService
from app.main_helpers import VISUAL_INFLIGHT_RECOVER_SEC

from tests.conftest import bind_minimal_danmu_app, make_minimal_danmu_app
from tests.fakes import FakeLogger


def _bind_on_ai_reply(app):
    """把 DanmuApp._on_ai_reply 绑到最小 app 实例上（与 make_minimal_danmu_app 一致）。"""
    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)


def test_stale_runable_after_stop_does_not_consume_new_inflight():
    """W-RACE-001 Case A：陈旧 AiRunnable（meta 已被 stop 清空）不上屏、不消耗 in-flight。

    触发链：
    1. start() → 触发 AiRunnable（已构造但未开始）
    2. stop() → 清空 _pending_request_meta、ai_in_flight=0
    3. start() → 重新递增 screenshot_round
    4. 新一轮 _trigger_api_call → ai_in_flight += 1（现为 1）
    5. 旧 AiRunnable 完成 → _on_ai_reply(meta=None) → 应当被丢弃
    """
    app = make_minimal_danmu_app()
    _bind_on_ai_reply(app)
    app.logger = FakeLogger()

    # 模拟 stop() 后的状态：_pending_request_meta 已被清空
    app._pending_request_meta = {}
    # 模拟 start() 后新一轮 _trigger_api_call 已递增 ai_in_flight
    app.ai_in_flight = 1
    app.screenshot_round = 5

    enqueue_calls = []
    app._enqueue_reply_batch = MagicMock(
        side_effect=lambda *a, **k: enqueue_calls.append((a, k))
    )
    app._consume_request_timing = MagicMock()
    app._release_inflight_for_source = MagicMock()
    add_tokens_calls = []
    app.stats_state.add_tokens = MagicMock(
        side_effect=lambda *a, **k: add_tokens_calls.append((a, k))
    )
    app.lifetime_stats.add_tokens = MagicMock(
        side_effect=lambda *a, **k: add_tokens_calls.append((a, k))
    )

    # 不抛异常即为基本要求
    app._on_ai_reply(
        '["stale reply content"]',
        "persona-stale",
        request_round=1,
        screenshot_id=1,
        captured_at=time.monotonic(),
        scene_generation=0,
        input_tokens=100,
        output_tokens=50,
    )

    # in-flight 不被错误释放
    assert app.ai_in_flight == 1
    # 不入队
    assert app._enqueue_reply_batch.call_count == 0
    assert enqueue_calls == []
    # 不释放 in-flight（也即不进 _release_inflight_for_source）
    assert app._release_inflight_for_source.call_count == 0
    # token 统计不被污染
    assert app.stats_state.add_tokens.call_count == 0
    assert app.lifetime_stats.add_tokens.call_count == 0
    assert add_tokens_calls == []
    # 既有 _pop_request_meta 的 request_meta_missing warning 仍记录
    assert any("request_meta_missing" in msg for msg in app.logger.warning_messages)
    # 新增 stale_reply_dropped warning
    assert any("stale_reply_dropped" in msg for msg in app.logger.warning_messages)


def test_normal_on_ai_reply_path_unaffected():
    """W-RACE-001 Case B：正常路径（meta 存在）应正常释放 in-flight 并入队。"""
    app = make_minimal_danmu_app()
    _bind_on_ai_reply(app)
    app.logger = FakeLogger()

    request_round = 3
    screenshot_id = 7
    scene_generation = 0
    # 正常注册 meta
    app._register_request_meta(request_round, screenshot_id, scene_generation, "visual")
    app.ai_in_flight = 1
    app.screenshot_round = request_round

    enqueue_calls = []
    app._enqueue_reply_batch = MagicMock(
        side_effect=lambda *a, **k: enqueue_calls.append((a, k))
    )
    app._consume_reply_queue = MagicMock()
    app._consume_request_timing = MagicMock()
    app._publish_live_status = MagicMock()
    app._notify_pet_visual_success = MagicMock()

    app._on_ai_reply(
        '["normal reply"]',
        "persona-1",
        request_round=request_round,
        screenshot_id=screenshot_id,
        captured_at=time.monotonic(),
        scene_generation=scene_generation,
    )

    # in-flight 正常释放
    assert app.ai_in_flight == 0
    # 正常入队
    assert app._enqueue_reply_batch.call_count == 1
    assert len(enqueue_calls) == 1


def test_visual_reply_enqueue_and_consume_to_engine(monkeypatch):
    """W-TEST-MAIN-E2E-001：AI 回复 → 入队 → _consume_reply_queue 上屏（无 HTTP/Qt 窗）。"""
    import main as main_mod

    app = make_minimal_danmu_app()
    app.engine.running = True
    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)
    app._consume_reply_queue = main_mod.DanmuApp._consume_reply_queue.__get__(app, main_mod.DanmuApp)
    app._notify_pet_visual_success = lambda: None

    request_round = 2
    screenshot_id = 5
    app._register_request_meta(request_round, screenshot_id, 0, "visual")
    app.ai_in_flight = 1

    monkeypatch.setattr(
        gen_pipeline_mod,
        "normalize_reply_batch",
        lambda raw_items, **kwargs: list(raw_items),
    )

    app._on_ai_reply(
        '["弹幕一", "弹幕二"]',
        "persona-1",
        request_round,
        screenshot_id,
        time.monotonic(),
        0,
    )

    assert not app.reply_buffer.is_empty()
    app._consume_reply_queue()
    assert app.engine.calls
    assert app.engine.calls[0][0] == "弹幕一"


def test_acquire_and_release_visual_inflight_atomic():
    """W-MAIN-INFLIGHT-ATOMIC-001：acquire/release 同步清零三字段。"""
    app = make_minimal_danmu_app()
    app._acquire_visual_inflight(42, 3)
    assert app.ai_in_flight == 1
    assert app._inflight_screenshot_id == 42
    assert app._inflight_scene_generation == 3
    assert app._is_generating is True
    assert app._inflight_started_at > 0

    app._release_inflight_for_source("visual")
    assert app.ai_in_flight == 0
    assert app._inflight_screenshot_id == 0
    assert app._inflight_scene_generation == 0
    assert app._is_generating is False
    assert app._inflight_started_at == 0.0
    # 不应有 stale_reply_dropped
    assert not any("stale_reply_dropped" in msg for msg in app.logger.warning_messages)


def test_pop_request_meta_for_inflight_tuple_key():
    """W-VISUAL-INFLIGHT-WATCHDOG-001：tuple 键精确 pop，不调用 endswith。"""
    app = make_minimal_danmu_app()
    app._pending_request_meta = {
        (30, 7, 0): {"source": "visual"},
        (29, 7, 0): {"source": "visual"},
    }

    popped = app._pop_request_meta_for_inflight(30, 7, 0)

    assert popped == [(30, 7, 0)]
    assert (30, 7, 0) not in app._pending_request_meta
    assert (29, 7, 0) in app._pending_request_meta


def test_recover_stale_visual_inflight_tuple_keys_releases_slot():
    """W-VISUAL-INFLIGHT-WATCHDOG-001：watchdog 恢复路径在 tuple 键下不崩溃并释放槽位。"""
    app = make_minimal_danmu_app()
    bind_minimal_danmu_app(
        app,
        ai_in_flight=1,
        screenshot_round=30,
        _is_generating=True,
        _inflight_screenshot_id=30,
        _inflight_scene_generation=0,
        _inflight_started_at=time.monotonic() - VISUAL_INFLIGHT_RECOVER_SEC - 2.0,
        _pending_request_meta={(30, 30, 0): {"source": "visual"}},
        _consecutive_failures=0,
    )
    object.__setattr__(app, "_request_timing_service", RequestTimingService())
    app._get_request_timing_service().mark_started(
        request_id=(30, 30, 0),
        now=time.monotonic() - 50.0,
    )

    assert app._try_recover_stale_visual_inflight() is True
    assert app.ai_in_flight == 0
    assert app._is_generating is False
    assert app._inflight_started_at == 0.0
    assert app._inflight_screenshot_id == 0
    assert app._inflight_scene_generation == 0
    assert app._pending_request_meta == {}
    assert app._get_request_timing_service().request_started_at_by_id == {}
    assert app._consecutive_failures == 1
    assert any(
        "inflight_watchdog_recover" in msg for msg in app.logger.error_messages
    )


def test_recover_stale_visual_inflight_preserves_unrelated_meta():
    """W-VISUAL-INFLIGHT-WATCHDOG-001：恢复只清理当前 request_round 的视觉 meta。"""
    app = make_minimal_danmu_app()
    bind_minimal_danmu_app(
        app,
        ai_in_flight=1,
        screenshot_round=30,
        _is_generating=True,
        _inflight_screenshot_id=30,
        _inflight_scene_generation=0,
        _inflight_started_at=time.monotonic() - VISUAL_INFLIGHT_RECOVER_SEC - 1.0,
        _pending_request_meta={
            (30, 30, 0): {"source": "visual"},
            (29, 30, 0): {"source": "visual"},
            (-1, 30, 0): {"source": "mic"},
        },
        _consecutive_failures=0,
    )
    object.__setattr__(app, "_request_timing_service", RequestTimingService())
    app._get_request_timing_service().mark_started(
        request_id=(30, 30, 0),
        now=time.monotonic() - 50.0,
    )

    assert app._try_recover_stale_visual_inflight() is True
    assert app.ai_in_flight == 0
    assert (30, 30, 0) not in app._pending_request_meta
    assert app._pending_request_meta == {
        (29, 30, 0): {"source": "visual"},
        (-1, 30, 0): {"source": "mic"},
    }
