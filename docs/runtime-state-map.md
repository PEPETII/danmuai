# Runtime State Map

> 维护者登记表。Boundary Guard 读取本文中的反引号字段名，确认新增运行态字段已登记。  
> 本文只描述**当前事实**，不再混入旧阶段的迁移建议与过期行号。

---

## 1. 说明

本文关注 `DanmuApp` 当前持有或间接拥有的运行态字段，不展开业务逻辑，也不把普通依赖对象解释成运行态。

### 当前代码位置

- 类定义与主链路锚点：`main.py`
- 生命周期装配：`app/main_lifecycle_mixin.py`
- request/timing/memory 辅助：`app/main_request_context_mixin.py`
- display / live status / floating panel 辅助：`app/main_display_mixin.py`
- mic 辅助：`app/main_mic_mixin.py`

---

## 2. 顶层运行态分类

| 类别 | 字段 |
|------|------|
| Web / 壳状态 | `web_launch_mode`、`web_server`、`web_bridge`、`webview_shell`、`web_runtime_state`、`_region_selector`、`_region_selection_state`、`_region_selection_screen_index` |
| 截图与视觉请求 | `screenshot_round`、`screenshot_timer`、`ai_in_flight`、`_capture_in_flight`、`_latest_screenshot`、`_latest_screenshot_time`、`_latest_screenshot_id`、`_latest_requested_screenshot_id`、`_inflight_screenshot_id`、`_inflight_started_at`、`_is_generating` |
| 麦克风与语音 | `mic_in_flight`、`_mic_request_seq`、`_mic_batch_id`、`_mic_poll_timer`、`_mic_poll_ms`、`_mic_service`、`_mic_orchestrator`、`_danmu_read_service` |
| 队列与批次 | `reply_buffer`、`reply_timer`、`_pool_topup_timer`、`_meme_collect_timer`、`_meme_display_timer`、`_meme_barrage_service`、`_queue_low_watermark`、`_queue_fallback_keep`、`_reply_scene_count`、`_reply_filler_count`、`_queue_batch_size`、`_batch_id`、`_current_batch`、`_pending` |
| request meta / 调度 | `_pending_request_meta`、`_request_scheduler`、`_request_timing_service`、`_inflight_scene_generation` |
| memory / 场景 | `_scene_generation` |
| 显示与可见性 | `_latest_displayed_round`、`_latest_queued_screenshot_id`、`_latest_displayed_screenshot_id`、`floating_panel_engine`、`floating_panel_overlay` |
| 失败与状态推送 | `_local_fallback_active`、`_consecutive_failures`、`_capture_fail_streak`、`_capture_error_active`、`_failure_backoff_paused`、`_last_error_message`、`MAX_CONSECUTIVE_FAILURES`、`_live_status_timer` |
| 统计与持久累计 | `stats_state`、`session_run_log`、`lifetime_stats`、`_lifetime_flush_timer` |

---

## 3. 关键字段登记

### Web / 壳

- `web_launch_mode`
- `web_server`
- `web_bridge`
- `webview_shell`
- `web_runtime_state`
- `_region_selector`
- `_region_selection_state`
- `_region_selection_screen_index`

### 截图 / 请求

- `screenshot_round`
- `screenshot_timer`
- `ai_in_flight`
- `_capture_in_flight`
- `mic_in_flight`
- `_latest_screenshot`
- `_latest_screenshot_time`
- `_latest_screenshot_id`
- `_latest_requested_screenshot_id`
- `_latest_queued_screenshot_id`
- `_latest_displayed_screenshot_id`
- `_inflight_screenshot_id`
- `_inflight_started_at`
- `_inflight_scene_generation`
- `_is_generating`
- `_pending_request_meta`

### 麦克风 / 读弹幕

- `_mic_request_seq`
- `_mic_batch_id`
- `_mic_poll_timer`
- `_mic_poll_ms`
- `_mic_service`
- `_mic_orchestrator`
- `_danmu_read_service`

### 队列 / 批次

- `reply_buffer`
- `reply_timer`
- `_pool_topup_timer`
- `_meme_collect_timer`
- `_meme_display_timer`
- `_meme_barrage_service`（烂梗 AI 选择 in-flight 仅由 `MemeBarrageService._ai_select_in_flight` 跟踪，W-MEDLOW-001）
- `_queue_low_watermark`
- `_queue_fallback_keep`
- `_reply_scene_count`
- `_reply_filler_count`
- `_queue_batch_size`
- `_batch_id`
- `_current_batch`
- `_pending`
- `_latest_displayed_round`

### 悬浮窗 V2（W-FP-V2-001 / W-FP-V2-002）

- `floating_panel_engine`
- `floating_panel_overlay`

`/api/status` 渲染模式字段：`danmu_render_mode`（`scrolling` / `floating_panel`）；**不含**遗留 `display_mode`。相关指标：`display_count`、`overlay_display_count`、`floating_panel_active_count`、`floating_panel_render_active`。

### 调度 / 状态对象

- `_request_scheduler`
- `_request_timing_service`
- `stats_state`
- `session_run_log`
- `lifetime_stats`
- `_lifetime_flush_timer`

### memory / 场景

- `_scene_generation`

### 失败与诊断

- `_local_fallback_active`
- `_consecutive_failures`
- `_capture_fail_streak`
- `_capture_error_active`
- `_failure_backoff_paused`
- `_last_error_message`
- `MAX_CONSECUTIVE_FAILURES`
- `_live_status_timer`

---

## 4. 所有权说明

### 继续归 `DanmuApp`

这些字段虽然写在 mixin 里，但所有权仍是 `DanmuApp`：

- `reply_buffer`
- `ai_in_flight`
- `mic_in_flight`
- `_pending_request_meta`
- `_latest_screenshot`
- `_scene_generation`
- 所有 `QTimer`

### 归属服务对象

以下不是“重新回到 `DanmuApp` 的私有字段”：

- `RequestScheduler.last_api_trigger_at`
- `RequestTimingService.request_started_at_by_id`
- `RequestTimingService.rtt_history`
- `StatsState` 内的计数与 token 总量
- `WebRuntimeState` 内的 Web 错误与 display cache

---

## 5. 维护规则

1. 新增运行态字段后，必须把字段名登记到本文
2. 如果字段实际放进 `StatsState` / `WebRuntimeState` / `RequestScheduler` / `RequestTimingService`，也要在本文说明归属
3. 不要再写过期行号、历史阶段注释或未来迁移猜想
4. 本文是**当前事实表**，不是重构 proposal
