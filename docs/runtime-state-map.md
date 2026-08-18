# Runtime State Map

本文件登记 `DanmuApp` 与附属运行时的字段所有权，供 Boundary Guard 与人工审查使用。
字段名以反引号列出（如 `field_name`）。

## DanmuApp 附属服务

- `virtual_host_runtime` — `VirtualHostRuntimeService`；Live2D 启动后挂载，停止时 `stop()`。

## virtual_host_runtime（`VirtualHostRuntimeService`）

| 字段 | 写入线程 | 读取线程 | 生命周期 |
|------|----------|----------|----------|
| `_running` | Qt 主线程（`start`/`stop`） | Qt 主线程 | Live2D start→stop |
| `_vision_in_flight` | Qt 主线程（调度/完成槽） | Qt 主线程 | 单次视觉 HTTP 在途 |
| `_chat_in_flight` | Qt 主线程（调度/完成槽） | Qt 主线程 | 单次 Chat HTTP 在途 |
| `_runtime_generation` | Qt 主线程（start/stop/模型切换/模式切换） | Qt 主线程 | 递增令牌，失效旧视觉/Chat 请求 |
| `_dialogue_enabled` | Qt 主线程（`refresh_mode_settings`） | Qt 主线程 | 虚拟主播对话模式开关（与弹幕适配互斥） |
| `_danmu_adapter_enabled` | Qt 主线程（`refresh_mode_settings`） | Qt 主线程 | AI 读弹幕适配模式开关（与对话互斥） |
| `_active_vision_model_id` | Qt 主线程（`refresh_model_bindings`） | Qt 主线程 | 当前绑定的视觉/Chat model_id |
| `_live2d_feedback` | Qt 主线程（Playback/Chat/生命周期回调） | Qt 主线程 | 当前 Live2D 模型的嘴型、表情、动作反馈层 |
| `_last_spoke_at` | Qt 主线程（Chat 完成） | Qt 主线程 | 上次自主发言时间（cooldown）；**wall clock**（`time.time()`） |

**业务时间 vs 性能计时**：Session / TTL / Scheduler 业务时间戳一律使用 **wall clock**（`time.time()`），包括 `SceneContext.updated_at`、`DanmuBatchCreated.created_at`、`ResponseCandidateEvent.at`、`HostTurn.created_at`、`_last_spoke_at`。主链路 `captured_at`（`DanmuApp._latest_screenshot_time`，**monotonic**）仅用于截图→场景诊断耗时（`scene_latency_ms` 等），禁止写入 `SceneContext.updated_at` 或 `ResponseCandidateEvent.at`。
| `_vision_coordinator` | 构造时 | Qt 主线程 | `SceneVisionCoordinator` 信号桥 |
| `_chat_coordinator` | 构造时 | Qt 主线程 | `ChatResponseCoordinator` 信号桥 |
| `vision_request_count` | Qt 主线程（调度时） | 任意只读 | 累计视觉 HTTP 次数 |
| `chat_request_count` | Qt 主线程（调度时） | 任意只读 | 累计 Chat HTTP 次数 |
| `tts_synthesize_count` | Qt 主线程（TTS 合成） | 任意只读 | 累计 TTS 次数 |

`VirtualHostSession` 内的 `_scene_context` / `_scene_generation` 由主线程 `_apply_scene_summary` 写入；
`_batches` / `_seen_batch_ids` 由主线程 `ingest_danmu_batch`（经 `on_danmu_batch_created` 或测试直调）写入。
worker 禁止直接修改 `VirtualHostRuntimeService` 或 `VirtualHostSession`。

## 主链路弹幕批次接入

`GenerationPipeline.handle_reply_parsed` → `DanmuBatchCreated` →
`VirtualHostRuntimeService.on_danmu_batch_created` → `VirtualHostSession.ingest_danmu_batch`。
仅传递已规范化 `normalized_items`，不传递 AI 原始 response/JSON。

## 历史 DanmuApp 字段（节选）

- `web_server`
- `_web_error_message`
- `stats_state`
- `web_runtime_state`
- `ai_in_flight`
- `reply_buffer`
- `_scene_generation`
- `_capture_in_flight`
- `_capture_session_epoch`
- `_capture_coordinator`
