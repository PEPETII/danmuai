# Runtime State Map

> **Maintainer registry** (Boundary Guard reads backtick field names here). Human overview: [RUNTIME_STATE.md](RUNTIME_STATE.md).  
> Normal mode only; `_rhythm_check_timer` / `_check_rhythm_trigger` removed with realtime mode.

## 说明

本文只整理 `main.py` 中 `DanmuApp` 的运行态字段，不整理长期依赖对象本身，例如 `config`、`logger`、`personae`、`templates`、`history`、`history_writer`、`capturer`、`engine`、`overlay`、`tray`、`hotkey`、`ai_worker`。

整理目标：

- 说明当前运行态分布在哪里。
- 给后续 `RuntimeState` 设计提供基线。
- 标出可迁移字段、部分可迁移字段和不应迁移的 Qt/服务对象引用。

迁移判定规则：

- `是`：纯运行态，与 Qt 对象生命周期弱耦合，可抽成集中状态对象。
- `部分`：可迁移元数据，但引用对象本身仍需留在 `DanmuApp`。
- `否`：Qt 定时器、服务实例、UI 壳对象、依赖对象引用。

## 分类总览

| 类别 | 代表字段 | 说明 |
| --- | --- | --- |
| 截图状态 | `screenshot_timer`、`_latest_screenshot`、`_latest_screenshot_time`、`_latest_screenshot_id`、`_screenshot_backoff_level` | 管理截图触发、当前帧缓存、截图节流与退避。 |
| 请求状态 | `ai_in_flight`、`mic_in_flight`、`_is_generating`、`screenshot_round`、`_pending_request_meta`、`_request_started_at_by_id`、`_inflight_*`、`MAX_*`、`_last_api_trigger_at` | 管理视觉/麦克风请求在途状态、请求编号、耗时统计与失败暂停。 |
| 场景状态 | `_active_scene_probe_size`、`_scene_generation`、`_scene_generation_bumped_at`、`_scene_memory`、`_activity_state`、`_last_activity_collect_at` | 场景代际键、探测尺寸元数据、活动观察与记忆（W-019：已移除未接线的 hash/gate 死状态；场景探测恢复见 ISSUE-014）。 |
| 队列状态 | `reply_buffer`、`danmu_queue`、`reply_timer`、`_current_batch`、`_batch_id`、`_queue_*`、`_reply_*`、`_latest_*_screenshot_id` | 管理回复入队、批次节奏与可见库存。 |
| 麦克风状态 | `_mic_request_seq`、`_mic_batch_id`、`_mic_utterance_detector`、`_mic_poll_timer`、`_mic_poll_ms`、`_mic_service` | 管理语音端点检测、轮询窗口和麦克风插入请求。 |
| 读弹幕 TTS | `_danmu_read_service` | MiMo TTS 定时朗读屏上弹幕（`QTimer` + 池线程 HTTP + 本地播放）；与视觉/麦克风独立。 |
| UI 状态 | `web_server`、`web_bridge`、`webview_shell`、`web_runtime_state`、`_live_status_timer`、`_region_selector`、`_region_selection_state`、`_region_selection_screen_index` | 管理控制台桥接、Web 展示态对象、live status 定时器与识图区域框选 UI。 |
| 服务对象 | `stats_state`、`_request_scheduler`、`_request_timing_service` | `StatsState`、调度与 timing 服务（非 `RuntimeState` 投影字段）。 |
| 统计状态 | `danmu_count`、`_total_input_tokens`、`_total_output_tokens`、`_start_time`、`_rtt_history`、`session_run_log`、`lifetime_stats`、`_lifetime_flush_timer` | 管理会话统计、累计统计和延迟样本。 |

## 截图状态

| 字段名 | 当前定义位置 | 用途 | 主要写入位置 | 主要读取位置 | 是否可迁移到 `RuntimeState` | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `screenshot_timer` | `main.py:157` | 驱动主截图节奏的 `QTimer`。 | `main.py::start()`、`main.py::_on_config_changed()`、`main.py::_apply_screenshot_interval_backoff()`、`main.py::stop()` | `main.py::_on_screenshot_timer()`、`main.py::_on_ai_error()` | 否 | Qt 定时器对象，应保留在 `DanmuApp`。 |
| `_latest_screenshot` | `main.py:175` | 缓存最新一帧 `QPixmap`，供视觉请求或麦克风插入复用。 | `main.py::_capture_screenshot()`、`main.py::start()` | `main.py::_trigger_api_call()`、`main.py::_trigger_mic_api_call()` | 部分 | 元数据可迁移，但 `QPixmap` 对象本身不宜放入纯状态对象。 |
| `_latest_screenshot_time` | `main.py:176` | 记录最新截图的 `monotonic` 时间。 | `main.py::_capture_screenshot()`、`main.py::start()` | `main.py::_current_danmu_delay_sec()`、`main.py::_trigger_api_call()`、`main.py::_maybe_refill_after_scene_change()` | 是 | 纯时间戳。 |
| `_latest_screenshot_id` | `main.py:212` | 当前缓存帧的单调递增编号（仅**有效** pixmap 接受后递增；无效帧 `reason=invalid_pixmap` 不递增）。 | `main.py::_capture_screenshot()` | `main.py::_trigger_api_call()`、`main.py::_trigger_mic_api_call()` | 是 | RTT/请求元数据；当前不参与 stale 硬丢弃。 |
| `_inflight_screenshot_id` | `main.py:236` | 当前在途视觉请求绑定的截图编号。 | `main.py::_trigger_api_call()`、`main.py::_release_inflight_for_source()`、`main.py::start()`、`main.py::stop()` | 日志/调试 | 是 | 纯请求元数据。 |
| `_inflight_started_at` | `main.py:237` | 当前在途视觉请求开始时间。 | `main.py::_trigger_api_call()`、`main.py::_release_inflight_for_source()`、`main.py::start()`、`main.py::stop()` | `main.py::_current_danmu_delay_sec()`、`main.py::_build_live_status_snapshot()` | 是 | 可用于未来统一延迟状态。 |
| `_stale_drop_count` | `main.py:238` | stale 丢弃累计（扩展预留；`_is_reply_stale` 当前不触发，通常为 0）。 | `main.py::_record_stale_drop()`、`main.py::start()` | `main.py::_build_live_status_snapshot()` | 是 | dormant 统计。 |
| `_stale_drop_times` | `main.py:239` | stale 丢弃时间窗口（扩展预留；退避逻辑 dormant）。 | `main.py::_record_stale_drop()`、`main.py::start()` | `main.py::_record_stale_drop()` | 是 | dormant。 |
| `_screenshot_backoff_level` | `main.py:240` | 当前截图退避级别。 | `main.py::_record_stale_drop()`、`main.py::_on_ai_reply()`、`main.py::start()` | `main.py::_apply_screenshot_interval_backoff()` → `live_freshness.screenshot_interval_ms()` | 是 | 成功回复可降级；stale 突发退避当前少见。 |

## 请求状态

| 字段名 | 当前定义位置 | 用途 | 主要写入位置 | 主要读取位置 | 是否可迁移到 `RuntimeState` | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `screenshot_round` | `main.py:156` | 视觉请求轮次计数，也用于 prompt 中的 `{round}`。 | `main.py::_trigger_api_call()` | `main.py::_trigger_api_call()`、`main.py::_trigger_mic_api_call()` | 是 | 与 `request_round` 直接相关。 |
| `ai_in_flight` | `main.py:160` | 在途视觉请求计数。 | `main.py::_trigger_api_call()`、`main.py::_release_inflight_for_source()`、`main.py::start()`、`main.py::stop()` | `main.py::_has_visual_request_in_flight()` | 是 | 可集中化。 |
| `MAX_IN_FLIGHT` | `main.py:161` | 视觉请求并发上限。 | `main.py::__init__()`、`main.py::_on_config_changed()` | 当前仅作为约束常量保留 | 是 | 更像运行期策略参数。 |
| `mic_in_flight` | `main.py:162` | 在途麦克风插入请求计数。 | `main.py::_trigger_mic_api_call()`、`main.py::_release_inflight_for_source()`、`main.py::stop()` | `main.py::_has_mic_request_in_flight()` | 是 | 与视觉请求并行。 |
| `MAX_MIC_IN_FLIGHT` | `main.py:163` | 麦克风请求并发上限。 | `main.py::__init__()` | 当前未直接读取 | 是 | 目前更接近配置常量。 |
| `_is_generating` | `main.py:177` | 视觉生成中的显式布尔标记。 | `main.py::_trigger_api_call()`、`main.py::_release_inflight_for_source()`、`main.py::start()`、`main.py::stop()` | `main.py::_has_visual_request_in_flight()` | 是 | 与 `ai_in_flight` 共同表达在途态。 |
| `_request_started_at_by_id` | `RequestTimingService`（经 façade） | 按复合键 `{request_round}:{screenshot_id}:{scene_generation}` 记录请求起始时间，用于 RTT 统计（视觉/麦克风不共用键）。 | `RequestTimingService.mark_started()` / `clear_started()` | `RequestTimingService.consume_timing()` | 否 | 真实所有权在 `RequestTimingService`；`DanmuApp` 仅兼容 façade。 |
| `_pending_request_meta` | `main.py:166` | 以 `request_round:screenshot_id:scene_generation` 为键记录请求来源，如 `visual`、`mic`。 | `main.py::_register_request_meta()`、`main.py::_pop_request_meta()`、`main.py::start()`、`main.py::stop()` | `main.py::_on_ai_reply()`、`main.py::_on_ai_error()` | 是 | 纯元数据。 |
| `_inflight_scene_generation` | `main.py:209` | 在途视觉请求对应的场景代际。 | `main.py::_trigger_api_call()`、`main.py::_release_inflight_for_source()`、`main.py::start()`、`main.py::stop()` | 当前主要通过日志/调试间接使用 | 是 | 与 `screenshot_id` 类似。 |
| `_last_api_trigger_at` | `RequestScheduler`（经 façade） | 最近一次视觉 API 触发时间。 | `RequestScheduler.record_trigger_time()` | `RequestScheduler.block_reason()` | 否 | 真实所有权在 `RequestScheduler`；`DanmuApp` 仅兼容 façade。 |
| `_consecutive_failures` | `main.py:230` | 连续失败计数。 | `main.py::_on_ai_reply()`、`main.py::_on_ai_error()`、`main.py::start()` | `main.py::_on_ai_error()` | 是 | 纯失败策略状态。 |
| `_failure_backoff_paused` | `main.py:231` | 因连续失败或致命错误而暂停视觉链路。 | `main.py::_on_ai_reply()`、`main.py::_on_ai_error()`、`main.py::start()` | `main.py::_capture_screenshot()`、`_on_normal_capture_tick()` | 是 | 纯布尔门控。 |
| `_last_error_message` | `main.py:232` | 最近一次视觉错误文本。 | `main.py::_on_ai_reply()`、`main.py::_on_ai_error()`、`main.py::start()` | 当前主要作为错误状态缓存 | 是 | 纯字符串状态。 |
| `MAX_CONSECUTIVE_FAILURES` | `main.py:233` | 连续失败暂停阈值。 | `main.py::__init__()` | `main.py::_on_ai_error()` | 是 | 运行策略参数。 |
## 场景状态

| 字段名 | 当前定义位置 | 用途 | 主要写入位置 | 主要读取位置 | 是否可迁移到 `RuntimeState` | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `_active_scene_probe_size` | `main.py` | 当前生效的场景探测采样尺寸（诊断/配置同步）。 | `main.py::_sync_scene_probe_size()` | `GenerationPipelineState`、`_scene_probe_size()` | 是 | W-019：无运行时 hash 比较。 |
| `_scene_generation` | `main.py` | 场景代际键（**运行期恒为 0**；产品策略不推进代际，仅随请求/记忆携带）。 | `main.py::start()`、`main.py::stop()` | `main.py::_trigger_api_call()`、`main.py::_on_ai_reply()`、`main.py::_append_scene_memory_to_user_pt()` | 是 | `_is_reply_stale` 恒不丢弃。 |
| `_stale_scene_inflight_drop_count` | `main.py` | 场景切换在途丢弃计数（扩展预留；当前不触发）。 | `main.py::_log_reply_drop()`、`main.py::start()` | `main.py::_log_reply_drop()` | 是 | dormant。 |
| `_stale_scene_consume_drop_count` | `main.py` | 场景切换消费丢弃计数（扩展预留；当前不触发）。 | `main.py::_log_reply_drop()`、`main.py::start()` | `main.py::_log_reply_drop()` | 是 | dormant。 |
| `_scene_generation_bumped_at` | `main.py` | 最近一次代际推进时间（诊断投影；当前无写入方）。 | `main.py::start()` | `GenerationPipelineState` | 是 | 诊断只读。 |
| `_scene_memory` | `main.py:222` | 当前场景记忆存储对象。 | `main.py::__init__()`、`main.py::_on_ai_reply()`、`main.py::_record_scene_memory_display()`、`main.py::start()` | `main.py::_append_scene_memory_to_user_pt()`、`main.py::_record_scene_memory_display()` | 部分 | 记忆对象引用建议保留在服务层，元数据可迁移。 |
| `_activity_state` | `main.py:223` | 前台窗口/活动观察状态对象，用于把近期活动线索拼接进 prompt。 | `main.py::__init__()`、`main.py::_collect_activity_observation()`、`main.py::start()` | `main.py::_append_scene_memory_to_user_pt()`、`main.py::_collect_activity_observation()` | 部分 | 对象引用建议保留在编排层，投影元数据可后续迁移。 |
| `_last_activity_collect_at` | `main.py:224` | 最近一次采集活动观察的 `monotonic` 时间。 | `main.py::_collect_activity_observation()`、`main.py::start()` | `main.py::_collect_activity_observation()` | 是 | 纯时间戳，可并入未来 `RuntimeState`。 |

## 队列状态

| 字段名 | 当前定义位置 | 用途 | 主要写入位置 | 主要读取位置 | 是否可迁移到 `RuntimeState` | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `reply_buffer` | `main.py:184` | 回复缓冲区主对象，当前类型是 `AIReplyFIFOBuffer`。 | `main.py::__init__()`、`main.py::_enqueue_reply_batch()`、`main.py::start()`、`main.py::stop()` | `main.py::_consume_reply_queue()`、`_log_api_schedule()` | 部分 | 队列对象引用本身不应进入纯状态；其元数据可迁移。 |
| `danmu_queue` | `main.py:185` | `reply_buffer` 的别名。 | `main.py::__init__()` | 当前无独立主路径使用 | 否 | 明确的别名字段，应作为遗留项记录。 |
| `reply_timer` | `main.py:186` | 控制逐条出队上屏节奏的 `QTimer`。 | `main.py::__init__()`、`main.py::_on_ai_reply()`、`main.py::_handle_mic_ai_reply()`、`main.py::_consume_reply_queue()`、`main.py::start()`、`main.py::stop()` | `main.py::_consume_reply_queue()` | 否 | Qt 定时器对象。 |
| `_pool_topup_timer` | `main.py:191` | 驱动本地弹幕库补足逻辑的 `QTimer`。 | `main.py::__init__()`、`main.py::start()`、`main.py::stop()` | `main.py::_maybe_pool_topup()` | 否 | Qt 定时器对象。 |
| `_queue_low_watermark` | `main.py:195` | 回复缓冲区低水位阈值。 | `main.py::_sync_reply_batch_config()` | `main.py::_on_ai_reply()` | 是 | 纯策略参数。 |
| `_queue_fallback_keep` | `main.py:196` | 预留给已有回复的保留数量，用于 `prepend_batch()`。 | `main.py::__init__()` | `main.py::_queue_capacity()`、`main.py::_enqueue_reply_batch()` | 是 | 可迁移。 |
| `_reply_scene_count` | `main.py:198` | 当前批次中场景相关回复数量。 | `main.py::_sync_reply_batch_config()` | `main.py::_enqueue_reply_batch()`、`main.py::_on_ai_reply()`、`main.py::_handle_mic_ai_reply()` | 是 | 纯批次策略状态。 |
| `_reply_filler_count` | `main.py:199` | 当前批次中 filler 回复数量。 | `main.py::_sync_reply_batch_config()` | 同上 | 是 | 纯批次策略状态。 |
| `_queue_batch_size` | `main.py:200` | 当前批次理论总大小。 | `main.py::_sync_reply_batch_config()` | `main.py::_queue_capacity()` | 是 | 可迁移。 |
| `_pending` | `main.py:202` | 遗留布尔标志，当前仅在初始化和 `stop()` 中重置。 | `main.py::__init__()`、`main.py::stop()` | 当前无关键读路径 | 是 | 需后续验证是否还需要。 |
| `_latest_displayed_round` | `main.py:203` | 已显示回复的最新 `screenshot_round`。 | `main.py::_consume_reply_queue()` | 当前仅写入，未形成核心控制分支 | 是 | 更像统计/调试状态。 |
| `_current_batch` | `main.py:179` | 当前视觉批次 `BatchTracker`（锚点弹幕 + `next_generation_time`，供 debug/调度日志）。 | `main.py::_trigger_api_call()`、`main.py::_enqueue_reply_batch()`、`main.py::_on_ai_reply()`、`main.py::_on_ai_error()`、`main.py::start()`、`main.py::stop()` | `main.py::_consume_reply_queue()`、`_log_api_schedule()` | 部分 | 元数据可迁移；对象本身建议后续转成独立数据结构。 |
| `_batch_id` | `main.py:178` | 视觉批次编号。 | `main.py::_trigger_api_call()`、`main.py::start()` | `main.py::_enqueue_reply_batch()` | 是 | 批次主键。 |
| `_latest_requested_screenshot_id` | `main.py:213` | 最近一次已发请求的截图编号。 | `main.py::_trigger_api_call()`、`main.py::start()`、`main.py::stop()` | 观测/扩展 | 是 | 仍更新；当前不参与 stale 判定。 |
| `_latest_queued_screenshot_id` | `main.py:214` | 最近一次已成功入队的截图编号。 | `main.py::_enqueue_reply_batch()`、`main.py::start()`、`main.py::stop()` | 观测/扩展 | 是 | 仍更新；当前不参与 stale 判定。 |
| `_latest_displayed_screenshot_id` | `main.py:215` | 最近一次已上屏的截图编号。 | `main.py::_consume_reply_queue()`、`main.py::start()`、`main.py::stop()` | 当前主要作为状态观测值 | 是 | 可集中化。 |
## 麦克风状态

| 字段名 | 当前定义位置 | 用途 | 主要写入位置 | 主要读取位置 | 是否可迁移到 `RuntimeState` | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `_mic_request_seq` | `main.py:164` | 麦克风插入请求自增序号，生成负值 `request_round`。 | `main.py::_trigger_mic_api_call()`、`main.py::start()` | `main.py::_trigger_mic_api_call()` 日志与请求编号构造 | 是 | 纯序号状态。 |
| `_mic_batch_id` | `main.py:165` | 麦克风插入批次编号。 | `main.py::_enqueue_reply_batch()`、`main.py::start()` | `main.py::_enqueue_reply_batch()` | 是 | 纯批次元数据。 |
| `_mic_utterance_detector` | `main.py:167` | 语音端点检测器对象。 | `main.py::_start_mic_utterance_detector()`、`main.py::_stop_mic_utterance_detector()` | `main.py::_poll_mic_utterance()`、`main.py::_calibrate_mic_noise_floor()` | 部分 | 对象引用不应直接迁移，但其状态可拆。 |
| `_mic_poll_timer` | `main.py:168` | 驱动麦克风 PCM 轮询的 `QTimer`。 | `main.py::_start_mic_utterance_detector()`、`main.py::_stop_mic_utterance_detector()` | `main.py::_poll_mic_utterance()` | 否 | Qt 定时器对象。 |
| `_mic_poll_ms` | `main.py:169` | 麦克风轮询窗口长度，毫秒。 | `main.py::__init__()` | `main.py::_poll_mic_utterance()`、`main.py::_calibrate_mic_noise_floor()` | 是 | 可迁移为运行策略字段。 |
| `_mic_service` | `main.py:223` | 麦克风采集服务对象。 | `main.py::__init__()`、`main.py::_sync_mic_service()`、`main.py::stop()` | `main.py::_poll_mic_utterance()`、`main.py::_on_mic_utterance_end()`、`main.py::_calibrate_mic_noise_floor()` | 部分 | 服务引用保留在编排层，运行元数据后续可拆。 |
| `_danmu_read_service` | `main.py:277` | 读弹幕 TTS 服务（`DanmuReadService`：定时器、合成 in-flight、播放 busy）。 | `main.py::__init__()`、`main.py::apply_danmu_read_config()` | `main.py::start()` → `on_engine_started()`、`main.py::stop()` → `on_engine_stopped()`、`main.py::run_danmu_read_probe()` | 部分 | 配置键 `danmu_read_*` / `tts_*`；HTTP 在 `QThreadPool`。 |

## UI 状态

| 字段名 | 当前定义位置 | 用途 | 主要写入位置 | 主要读取位置 | 是否可迁移到 `RuntimeState` | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `web_server` | `main.py:126` | 本地 FastAPI/WS 控制台 server 引用。 | `main.py::__init__()` | `main.py::start()`、`main.py::_open_web_console()`、`main.py::quit()` | 否 | UI/集成对象。 |
| `web_bridge` | `main.py:127` | Web 控制台 Qt bridge 引用。 | `main.py::__init__()` | `main.py::_set_error_status_safe()`、`main.py::_publish_live_status()` | 否 | UI bridge 对象。 |
| `webview_shell` | `main.py:128` | pywebview 壳对象引用。 | `main.py::__init__()`、`app/webview_shell.py::attach_webview_shell()` | `main.py::_open_web_console()`、`main.py::quit()` | 否 | 桌面壳对象。 |
| `_web_error_message` | `main.py:129` | Web 控制台上一次错误/状态消息。 | `main.py::_set_error_status_safe()` | `app/web_console.py::WebConsoleBridge.refresh_status()` | 是 | 纯字符串 UI 状态。 |
| `_web_error_is_error` | `main.py:130` | Web 错误消息的严重级别标记。 | `main.py::_set_error_status_safe()` | `app/web_console.py::WebConsoleBridge.refresh_status()` | 是 | 纯布尔 UI 状态。 |
| `_cached_danmu_lines` | `main.py:147` | 缓存上一次 `danmu_lines` 配置，便于决定是否重建轨道。 | `main.py::__init__()`、`main.py::_on_config_changed()` | `main.py::_on_config_changed()` | 是 | UI/布局缓存值。 |
| `_cached_layout_mode` | `main.py:148` | 缓存上一次 `layout_mode` 配置，便于决定是否刷新 overlay。 | `main.py::__init__()`、`main.py::_on_config_changed()` | `main.py::_on_config_changed()` | 是 | 可迁移。 |
| `_live_status_timer` | `main.py:243` | 定时推送 Web live status 的 `QTimer`。 | `main.py::__init__()`、`main.py::start()`、`main.py::stop()` | `main.py::_publish_live_status()` | 否 | Qt 定时器对象。 |

## 统计状态

| 字段名 | 当前定义位置 | 用途 | 主要写入位置 | 主要读取位置 | 是否可迁移到 `RuntimeState` | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| `_rtt_history` | `RequestTimingService.rtt_history` | 最近请求 RTT 样本列表。 | `main.py::_consume_request_timing()` | `main.py::_rtt_avg()`、`main.py::_smart_cooldown_ms()` | 是 | Phase 4-F 已迁入 `RequestTimingService`，`DanmuApp` 仅保留兼容 façade。 |
| `danmu_count` | `main.py:252` | 当前会话成功上屏的弹幕总数。 | `main.py::_update_stats()`、`main.py::start()` | `main.py::_maybe_log_dedup_profile()`、`main.py::stop()` | 是 | 纯统计状态。 |
| `session_run_log` | `main.py:255` | 会话运行日志对象。 | `main.py::__init__()`、`main.py::start()`、`main.py::stop()` | `app/web_console.py::WebConsoleBridge.refresh_status()` | 部分 | 对象应保留在服务层，元数据可投影到状态快照。 |
| `lifetime_stats` | `main.py:256` | 持久累计统计对象。 | `main.py::__init__()`、`main.py::_on_ai_reply()`、`main.py::_update_stats()`、`main.py::_flush_session_runtime_to_lifetime()` | `app/web_console.py::WebConsoleBridge.refresh_status()` | 部分 | 服务引用本身不迁移。 |
| `_lifetime_flush_timer` | `main.py:257` | 驱动累计统计刷盘的 `QTimer`。 | `main.py::__init__()`、`main.py::start()`、`main.py::stop()` | `lifetime_stats.flush_pending` | 否 | Qt 定时器对象。 |
| `_total_input_tokens` | `main.py:225` | 当前会话累计输入 token。 | `main.py::_on_ai_reply()`、`main.py::start()` | `app/web_console.py::WebConsoleBridge.refresh_status()`、`main.py::stop()` | 是 | 纯累计数值。 |
| `_total_output_tokens` | `main.py:226` | 当前会话累计输出 token。 | `main.py::_on_ai_reply()`、`main.py::start()` | 同上 | 是 | 纯累计数值。 |
| `_start_time` | `main.py:227` | 当前会话开始时间的 `monotonic` 时间戳。 | `main.py::start()`、`main.py::_flush_session_runtime_to_lifetime()` | `app/web_console.py::WebConsoleBridge.refresh_status()`、`main.py::_flush_session_runtime_to_lifetime()` | 是 | 纯时间戳。 |

## 可迁移建议摘要

### 优先可迁移到 `RuntimeState`

- 纯编号、计数、布尔和时间戳字段：
  - `screenshot_round`
  - `ai_in_flight`
  - `mic_in_flight`
  - `_is_generating`
  - `_latest_screenshot_time`
  - `_latest_screenshot_id`
  - `_inflight_screenshot_id`
  - `_inflight_started_at`
  - `_scene_generation`
  - `_queue_low_watermark`
  - `_reply_scene_count`
  - `_reply_filler_count`
  - `_latest_requested_screenshot_id`
  - `_latest_queued_screenshot_id`
  - `_latest_displayed_screenshot_id`
  - `_total_input_tokens`
  - `_total_output_tokens`
  - `_start_time`

### 适合“对象留外、元数据内迁”

- `reply_buffer`
- `_current_batch`
- `_scene_memory`
- `_mic_utterance_detector`
- `_mic_service`
- `session_run_log`
- `lifetime_stats`
- `_latest_screenshot`

### 建议保留在 `DanmuApp`

- 全部 `QTimer`
- `web_server`
- `web_bridge`
- `webview_shell`

## 暂不迁移项

以下字段在 Phase 0 只做标记，不建议直接迁移：

- `screenshot_timer`
- `reply_timer`
- `_pool_topup_timer`
- `_mic_poll_timer`
- `_live_status_timer`
- `_lifetime_flush_timer`
- `web_server`
- `web_bridge`
- `webview_shell`

以下字段需要 Phase 1 先确认是否仍有存在价值：

- `danmu_queue`
- `_pending`
- `_latest_displayed_round`

## Phase 2 补充

### Status Snapshot 收口

- `main.py::DanmuApp.build_status_snapshot()` 继续保留为公开 façade。
- 快照拼装逻辑已下沉到：
  - `app/application/runtime_state.py`
  - `app/application/status_snapshot.py`
- Web 层仍只允许通过 `build_status_snapshot()` 读取状态，不能直接拼装 `RuntimeState` 内部字段。

### Web 状态轮询 timer

| 字段名 | 当前归属 | 用途 | 生命周期入口 | 备注 |
| --- | --- | --- | --- | --- |
| `_web_status_timer` | `DanmuApp`（由 Web 控制台 attach） | 500ms 推送 Web 状态快照 | `attach_web_status_timer()` / `detach_web_status_timer()` / `stop_web_status_timer()` | Phase 2 从 `app/web_console.py` 私有字段直写收口为公开 API；interval 与推送行为不变 |

### 所有权迁移设计

- Phase 2.5 新增 [archive/architecture-phases/runtime-ownership-plan.md](archive/architecture-phases/runtime-ownership-plan.md)，只定义未来字段归属与迁移阶段，不迁移真实字段所有权。

## Phase 3-A 已落地

- `DanmuApp.__init__()` 现已新增 `stats_state` 与 `web_runtime_state` 两个运行态对象。
- `stats_state` 当前实际持有：
  - `danmu_count`
  - `total_input_tokens`
  - `total_output_tokens`
  - `start_time`
- `web_runtime_state` 当前实际持有：
  - `error_message`
  - `is_error`
- 为了保持兼容，`DanmuApp` 继续保留以下 façade 属性，并转发到新状态对象：
  - `danmu_count`
  - `_total_input_tokens`
  - `_total_output_tokens`
  - `_start_time`
  - `_web_error_message`
  - `_web_error_is_error`
- `RuntimeState.from_app()` 已改为优先读取 `stats_state` / `web_runtime_state`，仅在兼容场景下回退旧字段。
- 本阶段刻意暂缓：
  - `_cached_danmu_lines`
  - `_cached_layout_mode`
  - 所有 `QTimer`
  - 所有 `QThreadPool` 相关状态
  - `ai_in_flight`
  - `_pending_request_meta`
  - `_inflight_screenshot_id`
  - `_scene_generation`

## Phase 3-B 已落地

- `web_runtime_state` 当前实际持有字段扩展为：
  - `error_message`
  - `is_error`
  - `cached_danmu_lines`
  - `cached_layout_mode`
- `DanmuApp` 继续保留兼容 façade 属性，并转发到 `WebRuntimeState`：
  - `_cached_danmu_lines`
  - `_cached_layout_mode`
- `RuntimeState.from_app()` 现已优先读取 `web_runtime_state.cached_danmu_lines` 与 `web_runtime_state.cached_layout_mode`，但这些字段仍不对外暴露到 Web 状态返回结构。
- `_active_scene_probe_size` 仍保留在 `DanmuApp`，本阶段只登记为“未来只读投影候选”，不迁移真实所有权。
## Phase 3-C（已落地）

- `GenerationPipelineState` 只读投影：`app/application/generation_pipeline_state.py`。
- 候选字段经 `GenerationPipelineState.from_app(app)` 集中读取；真实所有权仍在 `DanmuApp`。
- `RuntimeState.from_app()` 通过 `GenerationPipelineState` 读取投影，禁止散落的 `getattr(app, "_latest_*")`。

## Phase 4-A 范围调整

- `_last_api_trigger_at` 与 `_request_started_at_by_id` 仅登记为 `GenerationPipelineState` 候选，只允许只读投影。
- 这两个字段的真实写路径、读取消费路径和清理路径当前都继续留在 `DanmuApp`。
- 它们都不允许迁入 `StatsState` 或 `WebRuntimeState`：
  - `_last_api_trigger_at` 属于请求节流元数据，参与 `_api_schedule_block_reason()`。
  - `_request_started_at_by_id` 属于 RTT 采样索引，影响 `_consume_request_timing()`、`_rtt_history`、`_rtt_avg()` 和 `_smart_cooldown_ms()`。
- 如果未来要迁移，前置条件是先设计 `RequestScheduler` / `RequestTimingService`，再补调度回归测试。
- `StatusSnapshotBuilder` 对外字段无变更；投影字段不直接暴露到 Web 快照。

## Phase 4-B 设计与回归测试

- Phase 4-B 新增了：
  - [archive/architecture-phases/request-scheduler-plan.md](archive/architecture-phases/request-scheduler-plan.md)
  - [archive/architecture-phases/request-timing-service-plan.md](archive/architecture-phases/request-timing-service-plan.md)
- 这两个文档只定义未来服务边界，不改变本表中字段的当前真实所有权。
- `_last_api_trigger_at` 仍是 `DanmuApp` 持有的请求节流元数据。
- `_request_started_at_by_id` 仍是 `DanmuApp` 持有的 RTT 采样索引。
- 真正迁移这两个字段的真实所有权，不得早于 Phase 4-D。

## Phase 4-C 薄服务壳

- Phase 4-C 已新增：
  - `app/application/request_scheduler.py`
  - `app/application/request_timing_service.py`
- 当前只是兼容委托，不改变本表字段的真实所有权。
- `_last_api_trigger_at` 仍由 `DanmuApp` 持有，只是通过 `RequestScheduler` 包装调度判断与写入。
- `_request_started_at_by_id` 仍由 `DanmuApp` 持有，只是通过 `RequestTimingService` 包装 timing 记录与消费。
- `_rtt_history` 仍由 `DanmuApp` 持有，只是通过 `RequestTimingService` 包装 RTT 聚合与 cooldown 计算。
- Phase 4-D 才能评估是否做真实字段所有权迁移。
## Phase 4-D Ownership Update

- `_request_scheduler` is now a runtime service field on `DanmuApp`, and its real responsibility is owning `_last_api_trigger_at`.
- `_last_api_trigger_at` remains available as a compatibility facade on `DanmuApp`, but the underlying state now lives in `RequestScheduler`.
- `_request_started_at_by_id` still remains in `DanmuApp`.
- `_rtt_history` ownership moved to `RequestTimingService` in Phase 4-F.
- `StatsState` and `WebRuntimeState` still must not own `_last_api_trigger_at` or `_request_started_at_by_id`.
## Phase 4-E Ownership Update

- `_request_timing_service` is now a runtime service field on `DanmuApp`, and its real responsibility is owning `_request_started_at_by_id`.
- `_request_started_at_by_id` remains available as a compatibility facade on `DanmuApp`, but the underlying state now lives in `RequestTimingService`.
- `_rtt_history` ownership moved to `RequestTimingService` in Phase 4-F.
- `_rtt_avg()` and `_smart_cooldown_ms()` remain compatibility delegates and keep their current results.
- `StatsState` and `WebRuntimeState` still must not own `_request_started_at_by_id`.
## Phase 4-F Ownership Update

- `_request_timing_service` now owns both `_request_started_at_by_id` and `_rtt_history`.
- `_rtt_history` remains available as a compatibility facade on `DanmuApp`, but the underlying state now lives in `RequestTimingService`.
- `_rtt_avg()` and `_smart_cooldown_ms()` remain compatibility delegates and keep their current results.
- `StatsState` and `WebRuntimeState` must not own `_rtt_history`.
- Phase 4-G is the earliest phase that may evaluate further consolidation of timing/cooldown facades.
## Phase 4-G Freeze

## Phase 5-A Diagnostics Snapshot

- `app/application/diagnostic_snapshot.py` is a read-only diagnostics layer.
- It may summarize:
  - `RequestScheduler.last_api_trigger_at`
  - `RequestTimingService.request_started_at_by_id`
  - `RequestTimingService.rtt_history`
  - `StatsState`
  - `WebRuntimeState`
  - `GenerationPipelineState.from_app(app)`
- It does not become a new runtime owner.
- It does not change `/api/status`.
- It does not expose diagnostics through Web/API in this phase.
- `DanmuApp.build_diagnostic_snapshot()` is the compatibility facade for future internal callers.

- Phase 4 结束后，`DanmuApp` 中与请求调度/timing 相关的稳定 façade 为：
  - `_last_api_trigger_at`
  - `_request_started_at_by_id`
  - `_rtt_history`
  - `_api_schedule_block_reason()`
  - `_consume_request_timing()`
  - `_rtt_avg()`
  - `_smart_cooldown_ms()`
- 它们的真实状态所有权已经冻结到 `RequestScheduler` / `RequestTimingService`，不再回流到 `DanmuApp`。

**脚注：** `VISUAL_INFLIGHT_WARN_SEC`（45s in-flight 告警阈值）为 [`main.py`](../main.py) **模块常量**，不是 `DanmuApp` 运行态字段；勿登记进本表或 `__init__` 以免 boundary_guard 失败。
