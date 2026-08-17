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
| `_runtime_generation` | Qt 主线程（start/stop/模型切换） | Qt 主线程 | 递增令牌，失效旧视觉请求 |
| `_active_vision_model_id` | Qt 主线程（`refresh_model_bindings`） | Qt 主线程 | 当前绑定的视觉 model_id |
| `_vision_coordinator` | 构造时 | Qt 主线程 | `SceneVisionCoordinator` 信号桥 |
| `vision_request_count` | Qt 主线程（调度时） | 任意只读 | 累计视觉 HTTP 次数 |
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
