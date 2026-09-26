"""P1-05 手工验证：本地 fake provider 连续返回 []（不调用真实付费 provider）。

用真实主链路方法（make_minimal_danmu_app + DanmuApp._on_ai_reply）驱动：
每个 tick 模拟一次截图→请求（若未暂停），provider 固定返回空数组 `[]`，
记录请求次数、暂停阈值、诊断 reason、token 统计与恢复路径。
"""
import sys
import time

sys.path.insert(0, r"E:\test\danmu")

from tests.conftest import make_minimal_danmu_app  # noqa: E402


def main() -> None:
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.screenshot_timer.active = True
    app._consecutive_empty_parses = 0
    app._empty_parse_paused = False
    app._consecutive_failures = 0

    request_round = 100
    fired = 0
    skipped_after_pause = 0

    def tick() -> None:
        nonlocal request_round, fired, skipped_after_pause
        # 模仿 _on_normal_capture_tick 的暂停门禁
        if app._failure_backoff_paused or app._empty_parse_paused:
            skipped_after_pause += 1
            return
        request_round += 1
        fired += 1
        app.ai_in_flight = 1
        app._register_request_meta(request_round, 10, 0, "visual")
        # provider 固定返回空数组 []（fake provider）
        app._on_ai_reply(
            "[]",
            "persona-1",
            request_round=request_round,
            screenshot_id=10,
            captured_at=time.monotonic(),
            scene_generation=0,
            input_tokens=10,
            output_tokens=2,
        )

    for _ in range(10):
        tick()

    active = app.get_active_problem()
    snap = app.build_diagnostic_snapshot()
    print("== 连续空响应（[]）==")
    print("requests_fired:", fired)
    print("threshold:", app.EMPTY_PARSE_FAILURE_THRESHOLD)
    print("consecutive_empty_parses:", app._consecutive_empty_parses)
    print("empty_parse_paused:", app._empty_parse_paused)
    print("failure_backoff_paused (scheduler gate):", app._failure_backoff_paused)
    print("screenshot_timer.active:", app.screenshot_timer.active)
    print("skipped_after_pause:", skipped_after_pause)
    print("consecutive_failures (transport):", app._consecutive_failures)
    print("active_problem.code:", (active or {}).get("code"))
    print("active_problem.title_key:", (active or {}).get("title_key"))
    print("diag.empty_parse:", snap.get("empty_parse"))
    print("diag.diagnosis.response_format_unavailable:",
          snap["diagnosis"]["response_format_unavailable"])
    print("tokens input/output:",
          app.stats_state.total_input_tokens, app.stats_state.total_output_tokens)

    # 恢复路径：有效入队后清零业务空计数并解除暂停
    request_round += 1
    app.ai_in_flight = 1
    app._register_request_meta(request_round, 10, 0, "visual")
    app._on_ai_reply(
        '["有效弹幕一", "有效弹幕二"]',
        "persona-1",
        request_round=request_round,
        screenshot_id=10,
        captured_at=time.monotonic(),
        scene_generation=0,
        input_tokens=5,
        output_tokens=4,
    )
    print("== 有效入队恢复 ==")
    print("consecutive_empty_parses:", app._consecutive_empty_parses)
    print("empty_parse_paused:", app._empty_parse_paused)
    print("failure_backoff_paused:", app._failure_backoff_paused)
    print("screenshot_timer.active:", app.screenshot_timer.active)
    print("active_problem:", app.get_active_problem())


if __name__ == "__main__":
    main()
