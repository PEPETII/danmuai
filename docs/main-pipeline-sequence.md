# Main Pipeline Sequence

主链路、线程池与 Qt 信号回主线程的调度登记。

## 截图 capture worker

Qt GUI 主线程完成 QApplication/QScreen/QPixmap capture，并在投递前转换为不可变、线程安全的图像
载荷；`CaptureRunnable` 在 `capture_worker_pool` 仅处理该载荷，结果经 `CaptureCoordinator.completed` /
`CaptureCoordinator.failed` 队列回主线程 `_on_capture_completed` / `_on_capture_failed`。

## 视觉 AI worker

`AiRunnable` 在 `ai_worker_pool` 对线程安全载荷压缩并执行 `AiWorker._request()`，经 `finished`/`error`
信号回主线程。每个 runnable 捕获不可复用的 session token；stop 使旧 token 失效，压缩、HTTP 与回调
投递前均验证它，因此 stop/start 后排队的旧任务不会发起 provider HTTP。

## 虚拟主播场景视觉 worker

`VirtualHostRuntimeService` 在 `on_capture_completed`（主线程）压缩截图后，将 `_SceneVisionRunnable`
投递至有界 `virtual_host_worker_pool`；worker 仅调用 `request_scene_summary`，经 `SceneVisionCoordinator.completed`
信号回主线程 `_on_scene_vision_completed` → `_complete_scene_vision`。禁止 worker 直接修改
`VirtualHostRuntimeService` / `VirtualHostSession` 状态。

`QThreadPool` / `QTimer` 触发点：截图 timer、`ai_worker_pool().start`（主视觉/麦克风）和
`virtual_host_worker_pool` 的有界投递（虚拟主播 scene/chat/ASR/TTS）。后者记录 pending/in-flight/
rejected，不能占用主视觉的两个 worker slot。

## 主链路弹幕批次 → 虚拟主播会话

`GenerationPipeline.handle_reply_parsed`（Qt 主线程，`ai_worker.finished` 回调链）在入队时仅产生
`DanmuGenerated` / `DanmuQueued`。overlay、floating panel、pet 仅在自己实际接受文本时发出
`DanmuDisplayed`；该事件才经 `VirtualHostRuntimeService.on_danmu_displayed` 调用
`VirtualHostSession.ingest_danmu_batch`。runtime 通过 `DanmuApp.get_scene_generation_snapshot()` 读取
generation，并由主线程变更通知原子清空旧上下文；runtime 未 `running` 时拒绝，不触发 Chat/TTS。

## 虚拟主播 TTS → Live2D 反馈层

`HostTurnResult` 在 Qt 主线程完成校验后，经 `VirtualHostRuntimeService` 消费
`emotion/actions`；其中 expression/gesture 只在当前桌面模型已发现的
Expression/Motion 中匹配，look_at 只使用受管参数别名，idle 清理临时状态。
TTS `PlaybackQueue` 的 `start`/`pause`/`interrupted`/`end` 事件经同一主线程回调
驱动口型；口型 tick 复用 Live2D 桌面窗口已有的 16 ms render timer，不新增线程或
并行播放链路。`item_id` 与 `runtime_generation` 门控旧播放事件，stop/模型切换时
反馈层先恢复 idle。

单测中 `threading.Thread` 仅用于直接调用 `CaptureRunnable` / `_SceneVisionRunnable.run()` 验证信号投递线程归属，不属于产品运行时调度。
