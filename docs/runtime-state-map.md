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
| `_speech_logs` | Qt 主线程（接受 Chat 结果时） | Qt 主线程（Web façade 查询） | 当前进程最近 200 条虚拟主播说话内容；仅内存保留 |

**业务时间 vs 性能计时**：Session / TTL / Scheduler 业务时间戳一律使用 **wall clock**（`time.time()`），包括 `SceneContext.updated_at`、`DanmuBatchCreated.created_at`、`ResponseCandidateEvent.at`、`HostTurn.created_at`、`_last_spoke_at`。主链路 `captured_at`（`DanmuApp._latest_screenshot_time`，**monotonic**）仅用于截图→场景诊断耗时（`scene_latency_ms` 等），禁止写入 `SceneContext.updated_at` 或 `ResponseCandidateEvent.at`。
| `_vision_coordinator` | 构造时 | Qt 主线程 | `SceneVisionCoordinator` 信号桥 |
| `_chat_coordinator` | 构造时 | Qt 主线程 | `ChatResponseCoordinator` 信号桥 |
| `vision_request_count` | Qt 主线程（调度时） | 任意只读 | 累计视觉 HTTP 次数 |
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
floating panel、pet 显示面实际接受文本后才产生 `DanmuDisplayed`，并由
`VirtualHostRuntimeService.on_danmu_displayed` 送入 `VirtualHostSession`。因此裁剪、去重或显示面
拒绝的文本不会触发虚拟主播自主回应；事件只携带已规范化文本和 request/batch/generation/source，
不传递 AI 原始 response/JSON。

## 历史 DanmuApp 字段（节选）

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
