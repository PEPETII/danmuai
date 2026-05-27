# Phase 4 Freeze

> Archived. Summary in [CONTRIBUTING_ARCHITECTURE.md](../../CONTRIBUTING_ARCHITECTURE.md).

## 已完成成果

- `RequestScheduler` 已接管 `last_api_trigger_at` 的真实所有权。
- `RequestTimingService` 已接管 `request_started_at_by_id` 的真实所有权。
- `RequestTimingService` 已接管 `rtt_history` 的真实所有权。
- `DanmuApp` 保留兼容 façade：
  - `_last_api_trigger_at`
  - `_request_started_at_by_id`
  - `_rtt_history`
  - `_api_schedule_block_reason()`
  - `_consume_request_timing()`
  - `_rtt_avg()`
  - `_smart_cooldown_ms()`
- Web/API 返回字段保持不变。
- 主链路时序保持不变。

## 当前稳定边界

- `RequestScheduler` 只负责视觉请求触发调度判断。
- `RequestTimingService` 只负责 request timing、RTT 样本与 cooldown 数据。
- `DanmuApp` 负责运行时装配、线程对象持有和兼容入口。
- `RuntimeState` 负责只读投影。
- `StatusSnapshotBuilder` 负责输出快照。
- Web/API 不得穿透内部状态。

## 禁止继续迁移的字段与对象

- `ai_in_flight`
- `_pending_request_meta`
- `_inflight_screenshot_id`
- `_scene_generation`
- `reply_buffer`
- `danmu_queue`
- `_latest_screenshot`
- `_latest_screenshot_id`
- `QTimer`
- `QThreadPool`
- `QPixmap`
- 截图对象
- `_mic_service`

## Phase 5 之前不要做的事

- 不要迁移 scene generation。
- 不要迁移 reply queue。
- 不要迁移 screenshot / `QPixmap`。
- 不要重写 `_trigger_api_call()`。
- 不要重写 `_on_ai_reply()` / `_on_ai_error()`。
- 不要重写 `_consume_reply_queue()`。
- 不要拆 `DanmuEngine` / `Overlay`。
- 不要做 Storage Repository 大拆。

## 后续新增调度相关功能的规则

- 必须先阅读本文与 [CONTRIBUTING_ARCHITECTURE.md](../../CONTRIBUTING_ARCHITECTURE.md)。
- 必须运行 `python -m pytest tests/test_request_scheduling.py -q`。
- 必须运行 `python scripts/boundary_guard.py`。
- 不允许绕过 `RequestScheduler`。
- 不允许绕过 `RequestTimingService`。
- 不允许在 `DanmuApp` 中新增同类调度/timing 字段。
