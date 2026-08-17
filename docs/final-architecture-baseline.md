# Final Architecture Baseline

DanmuAI 架构基线：Qt 主线程拥有 timer、截图槽位与回复队列；worker 经 QObject 信号回主线程。

## virtual_host_runtime

`VirtualHostRuntimeService` 挂载于 `DanmuApp.virtual_host_runtime`；场景视觉 HTTP 在
`ai_worker_pool` 执行，结果经 `SceneVisionCoordinator.completed` 回主线程。
`runtime_generation` 与 `_active_vision_model_id` 用于丢弃 stop/start 或换模后的过期结果。
主链路弹幕批次经 `on_danmu_batch_created` 写入 `VirtualHostSession`，与显示分发（overlay /
floating_panel / pet）解耦，不自动触发 Chat/TTS。
