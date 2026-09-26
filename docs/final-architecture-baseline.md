# Final Architecture Baseline

DanmuAI 架构基线：Qt 主线程拥有 timer、截图槽位与回复队列；worker 经 QObject 信号回主线程。

## Knowledge runtime shutdown ownership (P2-13)

`KnowledgeRuntimeService` owns the knowledge database, repository, import
orchestrator, retriever, and the knowledge route-adapter executor as one
application-lifetime boundary. Its lifecycle is `accepting -> draining ->
closed` or `timeout`.

`begin_shutdown()` rejects new import/route/retrieval work and requests
cooperative cancellation. `poll_shutdown()` is observed by the Qt lifecycle
code; only empty route, import, and retrieval Future sets may call the close
sequence `route executor -> import executor -> retrieval executor ->
knowledge.db`. On a hard deadline the state becomes `timeout`, the DB and
still-used executors remain open, and the application does not report a
completed close. Repeated shutdown calls are idempotent and finalization is
guarded to run once.

The dedicated `knowledge-retrieval` executor owns retrieval prefetch,
scene-generation publication gates, and use-count writes. The Qt prompt path
only reads a completed in-memory result or schedules prefetch; it does not
perform synchronous SQLite work. Web preview waits in the HTTP thread under a
deadline and does not invoke the Qt bridge.

## virtual_host_runtime

`VirtualHostRuntimeService` 挂载于 `DanmuApp.virtual_host_runtime`；虚拟主播 scene/chat/ASR/TTS
任务在有界 `virtual_host_worker_pool` 执行，主视觉/麦克风保留原 `ai_worker_pool` 容量；结果经
协调器信号回主线程。
`runtime_generation` 与 `_active_vision_model_id` 用于丢弃 stop/start 或换模后的过期结果。
主链路只在显示面实际接受文本后，经 `on_danmu_displayed` 将 `DanmuDisplayed` 写入
`VirtualHostSession`；`VirtualHostResponseScheduler` 评分达标后才经 `virtual_host_chat` 自主回应。
session generation 通过 `DanmuApp.get_scene_generation_snapshot()` / 主线程通知同步，virtual host
不得读取 `DanmuApp._*`；generation 变化原子清空旧 scene/batch 上下文。

**时间域**：业务 freshness / TTL / cooldown 使用 `time.time()`；HTTP / 场景 / Chat / TTS / 播放耗时统计使用 `time.monotonic()`。主链路 `captured_at` 为 monotonic，不得混入 Session 业务时间戳。
