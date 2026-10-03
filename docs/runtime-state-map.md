# Runtime State Map

本文件登记 `DanmuApp` 与附属运行时的字段所有权，供 Boundary Guard 与人工审查使用。
字段名以反引号列出（如 `field_name`）。

## DanmuApp 附属服务

## knowledge_runtime lifecycle (P2-13)

| field/state | owner/write thread | readers | lifetime/contract |
|------|----------|----------|----------|
| `KnowledgeRuntimeService._lifecycle_state` | Qt lifecycle owner (`begin_shutdown`/`poll_shutdown`) | Qt lifecycle and diagnostics | `accepting -> draining -> closed/timeout`; timeout never closes an in-use DB |
| `KnowledgeRuntimeService._shutdown_deadline_at` | Qt lifecycle owner | Qt lifecycle | monotonic hard deadline for observation; it is not a worker cancellation guarantee |
| `ImportOrchestrator._futures` | knowledge-import worker callbacks under its lock | lifecycle observer | import worker ownership; DB close is forbidden until empty |
| `KnowledgeRouteExecutor._futures` | route executor callbacks under its lock | lifecycle observer | route-adapter worker ownership; queued work is cancelled at drain start |
| `KnowledgeRuntimeService._retrieval_futures` | `knowledge-retrieval` worker callbacks under its lock | Qt lifecycle observer | retrieval prefetch and usage-write ownership; late scene/deadline results are discarded |
| `KnowledgeRuntimeService._retrieval_cache` | retrieval worker publication and pruning under its lock | Qt main thread | completed immutable payloads; at most 64 entries, generation matched, TTL 180 seconds |
| `KnowledgeRuntimeService._retrieval_pending_keys` | query admission/completion under `_retrieval_lock` | Qt/HTTP/worker under the same lock | at most eight queries, at most six visual queries |
| `KnowledgeRuntimeService._usage_pending` | Qt admission and retrieval worker drain under `_retrieval_lock` | retrieval worker | at most 64 events, each retains generation/deadline; cleared at shutdown |
| `KnowledgeRuntimeService._usage_drain_future` | admission/completion under `_retrieval_lock` | lifecycle observer under lock | at most one drain Future on the existing retrieval executor |
| `KnowledgeRuntimeService._retrieval_rejected_count/_retrieval_merged_count/_usage_rejected_count/_usage_expired_count` | admission/drain under `_retrieval_lock` | scalar pressure snapshot under lock | application lifetime; expose counts without queries, content or IDs |
| `KnowledgeRetriever._query_timings/_query_diagnostics` | retrieval executor | copied read-only snapshot | at most 128 timing samples; backend/fallback rate/keyword count/p95 only |

Close order is owned by `KnowledgeRuntimeService`: route executor, import
executor, retrieval executor, then `knowledge.db`. Retrieval work must not
reuse either the route-adapter or import executor.

- `virtual_host_runtime` — `VirtualHostRuntimeService`；Live2D 启动后挂载，停止时 `stop()`。

## virtual_host_runtime（`VirtualHostRuntimeService`）

| 字段 | 写入线程 | 读取线程 | 生命周期 |
|------|----------|----------|----------|
| `_running` | Qt 主线程（`start`/`stop`） | Qt 主线程 | Live2D start→stop |
| `_vision_in_flight` | Qt 主线程（调度/完成槽） | Qt 主线程 | 单次视觉 HTTP 在途 |
| `_vision_cancel_event` | Qt 主线程创建、置位与释放 | scene worker 只读 Event | 每个场景任务独立；代际切换取消，提交失败或主线程完成时释放 |
| `_chat_in_flight` | Qt 主线程（调度/完成槽） | Qt 主线程 | 单次 Chat HTTP 在途 |
| `_runtime_generation` | Qt 主线程（start/stop/模型切换/模式切换） | Qt 主线程 | 递增令牌，失效旧视觉/Chat 请求 |
| `_dialogue_enabled` | Qt 主线程（`refresh_mode_settings`） | Qt 主线程 | 虚拟主播对话模式开关（与弹幕适配互斥） |
| `_danmu_adapter_enabled` | Qt 主线程（`refresh_mode_settings`） | Qt 主线程 | AI 读弹幕适配模式开关（与对话互斥） |
| `_active_vision_model_id` | Qt 主线程（`refresh_model_bindings`） | Qt 主线程 | 当前绑定的视觉/Chat model_id |
| `_live2d_feedback` | Qt 主线程（Playback/Chat/生命周期回调） | Qt 主线程 | 当前 Live2D 模型的嘴型、表情、动作反馈层 |
| `_last_spoke_at` | Qt 主线程（Chat 完成） | Qt 主线程 | 上次自主发言时间（cooldown）；**wall clock**（`time.time()`） |
| `_speech_logs` | Qt 主线程（接受 Chat 结果时） | Qt 主线程（Web façade 查询） | 当前进程最近 200 条虚拟主播说话内容；仅内存保留 |

**业务时间 vs 性能计时**：Session / TTL / Scheduler 业务时间戳一律使用 **wall clock**（`time.time()`），包括 `SceneContext.updated_at`、`DanmuBatchCreated.created_at`、`ResponseCandidateEvent.at`、`HostTurn.created_at`、`_last_spoke_at`。主链路 `captured_at`（`DanmuApp._latest_screenshot_time`，**monotonic**）仅用于截图→场景诊断耗时（`scene_latency_ms` 等），禁止写入 `SceneContext.updated_at` 或 `ResponseCandidateEvent.at`。
| `_vision_coordinator` | 构造时 | Qt 主线程 | `SceneVisionCoordinator` 信号桥 |
| `_chat_coordinator` | 构造时 | Qt 主线程 | `ChatResponseCoordinator` 信号桥 |
| `vision_request_count` | Qt 主线程（完成槽，request_started 为真） | 任意只读 | 累计实际开始的视觉 HTTP；排队取消/压缩失败不计数，HTTP 失败仍计数 |
| `chat_request_count` | Qt 主线程（调度时） | 任意只读 | 累计 Chat HTTP 次数 |
| `tts_synthesize_count` | Qt 主线程（TTS 合成） | 任意只读 | 累计 TTS 次数 |

`VirtualHostSession` 内的 `_scene_context` 由主线程 `_apply_scene_summary` 写入；`_scene_generation`
由主线程的 `DanmuApp.get_scene_generation_snapshot()` 与变更通知同步。generation 前进或 reset
会原子清空旧 scene/batch 上下文，随后才允许新 batch 接受。`_batches` 与有界、TTL 关联的
`_seen_display_event_ids` 仅由主线程 `ingest_danmu_batch` 写入，诊断只暴露 retained 数量。
worker 禁止直接修改 `VirtualHostRuntimeService` 或 `VirtualHostSession`，virtual host 也禁止直接
读取 `DanmuApp._*` 私有字段。

## 主链路弹幕批次接入

`GenerationPipeline.handle_reply_parsed` 只产生 `DanmuGenerated` / `DanmuQueued`；每个 overlay、
floating panel 显示面实际接受文本后才产生 `DanmuDisplayed`，并由
`VirtualHostRuntimeService.on_danmu_displayed` 送入 `VirtualHostSession`。因此裁剪、去重或显示面
拒绝的文本不会触发虚拟主播自主回应；事件只携带已规范化文本和 request/batch/generation/source，
不传递 AI 原始 response/JSON。

## 主链路生命周期幂等（P1-04）

| 字段 | 写入线程 | 读取线程 | 生命周期 |
|------|----------|----------|----------|
| `_duplicate_start_log_at` | Qt 主线程（`DanmuApp._note_duplicate_start`） | Qt 主线程 | 进程内；最近一次“运行中重复 start”限频诊断的 `time.monotonic()` 时间戳 |

`DanmuApp.start()` 的第一项业务门禁是主线程运行态检查 `_visual_session_active()`
（读取主线程专属的 `engine.running`）。`engine.running` 只由 Qt 主线程的
`engine.start()`/`engine.stop()` 写入，故无需额外同步原语，也不是跨线程无锁布尔值。
引擎已在运行时，重复 `start()` 是无副作用 no-op：不递增 `_capture_session_epoch`、
不清空 `_pending_request_meta`、不重启定时器、不再次触发 `_on_normal_capture_tick()`。
需要重启的调用者必须显式 `stop()` 后再 `start()`。

## 主链路业务空解析预算与暂停（P1-05）

| 字段 | 写入线程 | 读取线程 | 生命周期 |
|------|----------|----------|----------|
| `_consecutive_empty_parses` | Qt 主线程（`DanmuApp._handle_visual_empty_parse_failure`） | Qt 主线程；诊断快照经 `__dict__` 只读投影 | 会话内；连续业务空解析（`empty_parse`）计数，有效入队或 `start`/`stop` 清零 |
| `_empty_parse_paused` | Qt 主线程（业务失败入口；`_reset_empty_parse_backoff_if_needed` / `start` / `stop`） | Qt 主线程；诊断快照只读投影 | 布尔；达阈值置真，表示因“响应格式不可用”暂停截图调度 |
| `EMPTY_PARSE_FAILURE_THRESHOLD` | 主线程（`_init_runtime_tracking_state` / `start`，覆盖类属性） | 主线程；诊断快照只读投影 | 会话常量（默认 `EMPTY_PARSE_FAILURE_THRESHOLD = 5`），阈值依据见完成报告 |

`GenerationPipeline.handle_reply_parsed_outcome` 返回显式 `VisualReplyOutcome`
（`enqueued` / `empty_parse` / `gate_dropped`）：`enqueued` 时清零业务空计数并按既有
退避合同恢复；`empty_parse` 时由 `DanmuApp._handle_visual_empty_parse_failure`（post-transport
业务失败入口）累计一次业务空计数，达阈值后置 `_empty_parse_paused`、复用 `_failure_backoff_paused`
停止 `screenshot_timer`，并上报 problem 码 `AI-FORMAT-001`（“响应格式不可用”），
不与网络/连接错误共用文案。该入口**不**释放 in-flight/meta/timing、**不**重复计 token、
**不**累计传输失败 `_consecutive_failures`。`gate_dropped`（scene/meta 门禁）与 mic
回复、provider 错误均不参与业务空计数。

## 历史 DanmuApp 字段（节选）

## 视觉请求档案公开投影（P2-02/P2-03）

| 字段 | 写入线程 | 读取线程 | 生命周期 |
|------|----------|----------|----------|
| `_pending_request_meta[*].request_context` | Qt 主线程派发前登记；内容来自冻结 context 的 `public_projection()` | Qt 主线程错误处理、status/diagnostic 快照 | 单个 request_id；不含 API key、完整 endpoint、图片 |
| `_last_request_context_public` | Qt 主线程派发前登记 | Qt 主线程；Web 只读快照经 façade 投影 | 进程内最近一次视觉请求；会话停止后可被下一次请求替换 |

`ResolvedRequestContext` 在 provider dispatch 前冻结 profile/model/provider/API family、endpoint host、
max_tokens、temperature 和 thinking。公开 projection 只允许进入 request metadata、status/diagnostics
及 problem context；不得从可变全局配置重新猜测已发请求的档案，也不得投影凭据或完整请求正文。

- `web_server`
- `_web_error_message`
- `stats_state`
- `web_runtime_state`
- `ai_in_flight`
- `reply_buffer`
- `_scene_generation`
- `get_scene_generation_snapshot()` — Qt 主线程只读 façade；virtual host 通过它取得代际快照。
- `_capture_in_flight`
- `_capture_session_epoch`
- `_capture_coordinator`
