"""P1-05：连续业务空解析（empty_parse）的独立失败预算与暂停合同。

传输成功但无任何有效弹幕入队（空字符串 / `[]` / reasoning-only / 全被
normalize/filter 去除）被计为**业务空失败**：

- 每次只累计一次独立业务空计数，达阈值后停止 screenshot_timer 并上报
  "响应格式不可用"（AI-FORMAT-001），不得误报连接/网络错误；
- 有效规范化结果入队后清零业务空计数并按既有恢复合同解除暂停；
- 每个 request 只释放一次 slot/meta/timing、只统计一次 token；
- stale / meta-missing / mic reply / provider error 不参与本计数。
"""

import time

from app.application import generation_pipeline as gen_pipeline_mod
from app.application.generation_pipeline import VisualReplyOutcome
from main import DanmuApp

from tests.conftest import make_minimal_danmu_app


def _make_app():
    """最小主链 app + P1-05 业务空预算字段（生产由 _init_runtime_tracking_state 初始化）。

    最小实例未走 ``__init__``；显式初始化避免 QObject 动态 getattr 读取未设置字段。
    """
    app = make_minimal_danmu_app()
    app._consecutive_empty_parses = 0
    app._empty_parse_paused = False
    return app


def _register_visual_reply(app) -> None:
    app.ai_in_flight = 1
    app._register_request_meta(10, 10, 0, "visual")


def _deliver_visual_reply(
    app,
    text: str = "provider payload",
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    app._on_ai_reply(
        text,
        "persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=time.monotonic(),
        scene_generation=0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _force_empty_parse(monkeypatch) -> None:
    """让规范化结果为空的确定性口径：候选存在但全部被 normalize 去除。"""
    monkeypatch.setattr(
        gen_pipeline_mod,
        "parse_ai_reply_payload",
        lambda _text: ["raw candidate"],
    )
    monkeypatch.setattr(
        gen_pipeline_mod,
        "normalize_reply_batch",
        lambda _raw_items, **_kwargs: [],
    )


def test_generation_pipeline_reports_empty_normalized_result(monkeypatch):
    """空结果必须返回明确 EMPTY_PARSE outcome，而不是让调用方猜测 bool。"""
    app = _make_app()
    _force_empty_parse(monkeypatch)

    outcome = app._generation_pipeline.handle_reply_parsed_outcome(
        text="provider payload",
        persona_id="persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=1.0,
        scene_generation=0,
        request_started_at=2.0,
        reply_received_at=3.0,
    )

    assert outcome is VisualReplyOutcome.EMPTY_PARSE
    # 布尔包装仍向后兼容（既有调用方）
    assert app._generation_pipeline.handle_reply_parsed(
        text="provider payload",
        persona_id="persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=1.0,
        scene_generation=0,
        request_started_at=2.0,
        reply_received_at=3.0,
    ) is False
    assert app.reply_buffer.is_empty()
    assert any("empty_parse" in msg for msg in app.logger.warning_messages)


def test_single_empty_parse_increments_budget_without_pausing(monkeypatch):
    """单次空响应非阻断：只累计计数，不暂停也不误报连接错误。"""
    app = _make_app()
    app.engine.running = True
    app.screenshot_timer.active = True
    _force_empty_parse(monkeypatch)
    _register_visual_reply(app)

    _deliver_visual_reply(app)

    assert app._consecutive_empty_parses == 1
    assert app._empty_parse_paused is False
    assert app._failure_backoff_paused is False
    assert app.screenshot_timer.active is True
    assert app._consecutive_failures == 0
    assert app.get_active_problem() is None


def test_consecutive_empty_parses_pause_at_threshold_and_report_format_problem(monkeypatch):
    """连续达到阈值后停止 screenshot_timer，并上报“响应格式不可用”。"""
    app = _make_app()
    app.engine.running = True
    app.screenshot_timer.active = True
    _force_empty_parse(monkeypatch)
    threshold = app.EMPTY_PARSE_FAILURE_THRESHOLD
    assert threshold >= 2

    for index in range(threshold):
        _register_visual_reply(app)
        _deliver_visual_reply(app)
        if index < threshold - 1:
            # 阈值前仍可继续调度
            assert app._empty_parse_paused is False
            assert app.screenshot_timer.active is True

    assert app._consecutive_empty_parses == threshold
    assert app._empty_parse_paused is True
    assert app._failure_backoff_paused is True
    assert app.screenshot_timer.active is False
    # 未与网络/连接失败混用：传输失败计数保持 0，问题码为响应格式
    assert app._consecutive_failures == 0
    active = app.get_active_problem()
    assert active is not None
    assert active["code"] == "AI-FORMAT-001"
    assert active["category"] != "network"


def test_valid_enqueue_clears_budget_and_resumes_scheduling():
    """有效规范化结果入队后清零业务空计数并解除暂停（既有恢复合同）。"""
    app = _make_app()
    app.engine.running = True
    app.screenshot_timer.active = False
    app._consecutive_empty_parses = 3
    app._empty_parse_paused = True
    app._failure_backoff_paused = True
    _register_visual_reply(app)

    _deliver_visual_reply(app, text="not-json but valid plain text")

    assert app._consecutive_empty_parses == 0
    assert app._empty_parse_paused is False
    assert app._failure_backoff_paused is False
    assert app.screenshot_timer.active is True
    assert app.engine.calls
    assert app.engine.calls[0][0] == "not-json but valid plain text"


def test_nonempty_plain_text_visual_reply_resets_failure_backoff():
    """既有传输失败退避仍由有效入队复位（不回归旧合同）。"""
    app = _make_app()
    app.engine.running = True
    app._consecutive_failures = 4
    app._failure_backoff_paused = True
    app._last_error_message = "previous error"
    app.screenshot_timer.active = False
    _register_visual_reply(app)

    _deliver_visual_reply(app, text="not-json but valid plain text")

    assert app._consecutive_failures == 0
    assert app._failure_backoff_paused is False
    assert app._last_error_message == ""
    assert app.screenshot_timer.active is True
    assert app.engine.calls
    assert app.engine.calls[0][0] == "not-json but valid plain text"


def test_empty_parse_releases_once_accounts_token_once_and_counts_once(monkeypatch):
    """每个空解析 request 只释放一次 slot/timing、只计一次 token、只记一次业务空。"""
    app = _make_app()
    app.engine.running = True
    _force_empty_parse(monkeypatch)

    release_calls: list[str] = []
    timing_calls: list[tuple] = []
    original_release = DanmuApp._release_inflight_for_source.__get__(app, DanmuApp)
    original_timing = DanmuApp._consume_request_timing.__get__(app, DanmuApp)

    def spy_release(source: str) -> None:
        release_calls.append(source)
        original_release(source)

    def spy_timing(*args) -> None:
        timing_calls.append(args)
        original_timing(*args)

    app._release_inflight_for_source = spy_release
    app._consume_request_timing = spy_timing

    _register_visual_reply(app)
    _deliver_visual_reply(app, input_tokens=7, output_tokens=3)

    assert release_calls == ["visual"]
    assert len(timing_calls) == 1
    assert app._consecutive_empty_parses == 1
    assert app.ai_in_flight == 0
    assert app.stats_state.total_input_tokens == 7
    assert app.stats_state.total_output_tokens == 3


def test_meta_missing_reply_does_not_touch_empty_budget(monkeypatch):
    """meta 缺失（stop 后迟到回调）不参与业务空计数。"""
    app = _make_app()
    app.ai_in_flight = 1
    _force_empty_parse(monkeypatch)

    # 不注册 meta：_pop_request_meta 返回 {}
    _deliver_visual_reply(app)

    assert app._consecutive_empty_parses == 0
    assert app._empty_parse_paused is False


def test_stale_scene_generation_reply_does_not_touch_empty_budget(monkeypatch):
    """过期 scene_generation 回复不参与业务空计数。"""
    app = _make_app()
    app._scene_generation = 2
    _force_empty_parse(monkeypatch)
    _register_visual_reply(app)

    _deliver_visual_reply(app)  # scene_generation=0 < 2 → stale

    assert app._consecutive_empty_parses == 0
    assert app._empty_parse_paused is False


def test_mic_reply_does_not_touch_empty_budget(monkeypatch):
    """mic 回复走独立分流，不参与视觉业务空计数。"""
    app = _make_app()
    app.mic_in_flight = 1
    _force_empty_parse(monkeypatch)
    app._register_request_meta(-1, 10, 0, "mic")

    app._on_ai_reply("[]", "persona-1", -1, 10, time.monotonic(), 0)

    assert app._consecutive_empty_parses == 0
    assert app._empty_parse_paused is False


def test_provider_error_does_not_touch_empty_budget():
    """普通 provider 错误走传输失败链，不误增业务空计数。"""
    app = _make_app()
    app.ai_in_flight = 1
    app._register_request_meta(5, 5, 0, "visual")

    app._on_ai_error("AI timeout", "persona-1", 5, 5, time.monotonic(), 0)

    assert app._consecutive_empty_parses == 0
    assert app._empty_parse_paused is False
    assert app._consecutive_failures == 1


def test_diagnostic_snapshot_exposes_empty_parse_budget(monkeypatch):
    """诊断快照暴露独立业务空计数/阈值/暂停状态，供 Web 诊断区分格式与连接失败。"""
    app = _make_app()
    app.engine.running = True
    app.screenshot_timer.active = True
    _force_empty_parse(monkeypatch)
    app._consecutive_empty_parses = 3

    snapshot = app.build_diagnostic_snapshot()

    assert snapshot["empty_parse"]["consecutive"] == 3
    assert snapshot["empty_parse"]["threshold"] == app.EMPTY_PARSE_FAILURE_THRESHOLD
    assert snapshot["empty_parse"]["paused"] is False
    assert snapshot["empty_parse"]["reason"] == "empty_parse"
    assert snapshot["diagnosis"]["response_format_unavailable"] is False


def test_reset_empty_parse_backoff_is_noop_when_clean():
    """无业务空状态时恢复方法是 no-op，不影响传输失败退避状态。"""
    app = _make_app()
    app.engine.running = True
    app._failure_backoff_paused = True
    app._consecutive_failures = 5

    app._reset_empty_parse_backoff_if_needed()

    assert app._consecutive_empty_parses == 0
    assert app._empty_parse_paused is False
    # 传输失败退避不应被业务空恢复路径误清
    assert app._failure_backoff_paused is True
