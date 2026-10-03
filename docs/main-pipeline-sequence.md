# Main Pipeline Sequence

主链路、线程池与 Qt 信号回主线程的调度登记。

## Knowledge import and quit drain (P2-13)

HTTP import admission uses the route-adapter owner and then submits to the
single `knowledge-import` owner. During application quit, route/import
admission changes from `accepting` to `draining`; route queued calls are
cancelled and import jobs receive cooperative cancellation Events. The Qt
main thread does not call an unbounded executor wait. It observes
`KnowledgeRuntimeService.poll_shutdown()` on a short `QTimer` until either:

1. route, import, and retrieval Future sets are empty, then close
   `route executor -> import executor -> retrieval executor -> knowledge.db` once;
2. the monotonic deadline is reached, then enter `timeout`, keep still-used workers and DB open, and defer process exit until a later drain observation.

The route owner here is only the import API adapter. Retrieval and
`mark_items_used` have a separate `knowledge-retrieval` owner; this drain does
not reuse either route or import executor.

## Knowledge retrieval prefetch and usage writes (P2-14)

Before a visual or microphone request is dispatched, the Qt thread only builds
the semantic query and checks a completed in-memory result. A dedicated
single-worker retrieval owner performs SQLite retrieval and usage-count writes.
The first request with a new semantic key continues with no knowledge while the
worker prefetches; a later request may use the result only when its scene
generation is still current. Every worker publication and count write has a
monotonic deadline; late results are discarded and never enter a newer scene.

Reply-consumption count updates are queued to the same owner. Knowledge preview
uses that owner from the HTTP thread with a bounded wait and no `invoke_main`
call. The retrieval Future set is included in the quit drain before
`knowledge.db` closes.

## 主链路 start 幂等门禁（P1-04）

`DanmuApp.start()` 在 Qt 主线程执行，其第一项业务门禁是主线程运行态检查
（`engine.running`）。引擎已在运行时，重复 `start()`（托盘/热键/`/api/start` 的
`bridge.start_requested` 信号）直接返回并记录限频诊断，不重试知识运行时、不递增
`_capture_session_epoch`、不调用 `engine.start()`、不重置统计/定时器、不清空
`_pending_request_meta`、不触发 `_on_normal_capture_tick()`，因此在途视觉请求与
capture 管道保持不变。完整 `stop()` → `start()` 仍按原顺序重建会话。`/api/start`
保持异步 `{"ok": true}`，幂等由主线程门禁保证，前端禁用按钮只是辅助保护。

## 视觉回复 outcome 分发与业务空解析暂停（P1-05）

视觉回复在 `DanmuApp._on_ai_reply`（Qt 主线程，`ai_worker.finished` 回调）中先经
scene/meta 门禁（`_abort_ai_reply_early` → `gate_dropped`，早退），再一次性释放
in-flight、统计 token、消费 timing，然后调用
`GenerationPipeline.handle_reply_parsed_outcome`，得到显式 `VisualReplyOutcome`：

- `enqueued`：`DanmuApp` 清零 `_consecutive_empty_parses` 并复位失败退避；
- `empty_parse`：`DanmuApp._handle_visual_empty_parse_failure` 累计一次业务空计数；
  达 `EMPTY_PARSE_FAILURE_THRESHOLD` 后停止 `screenshot_timer` 并上报
  `AI-FORMAT-001`（“响应格式不可用”）。

该分发**不**新增线程/定时器：仍属 Qt 主线程，`screenshot_timer`/`reply_timer` 所有权
不变，`GenerationPipeline` 只返回 outcome、不反向触发主链。业务空暂停复用既有
`_failure_backoff_paused` 门禁（`_schedule_capture` / `_on_capture_completed` /
`_try_scene_refresh` 已在暂停时早退），恢复路径为有效入队或 `stop()` → `start()`。

## 截图 capture worker

Qt GUI 主线程完成 QApplication/QScreen/QPixmap capture，并在投递前转换为不可变、线程安全的图像
载荷；`CaptureRunnable` 在 `capture_worker_pool` 仅处理该载荷，结果经 `CaptureCoordinator.completed` /
`CaptureCoordinator.failed` 队列回主线程 `_on_capture_completed` / `_on_capture_failed`。

## 视觉 AI worker

`AiRunnable` 在 `ai_worker_pool` 对线程安全载荷压缩并执行 `AiWorker._request()`，经 `finished`/`error`
信号回主线程。每个 runnable 捕获不可复用的 session token；stop 使旧 token 失效，压缩、HTTP 与回调
投递前均验证它，因此 stop/start 后排队的旧任务不会发起 provider HTTP。

视觉 runnable 派发前冻结 `ResolvedRequestContext`，并把不含凭据的 `public_projection()` 登记到
`_pending_request_meta`；同一 context 随 runnable 进入 `AiWorker._request()`，provider path 不再
重新读取全局 token/temperature。status、diagnostics 与错误 problem context 优先读取该 request
projection，因此展示的 profile/model/provider/API family 与实际 dispatch 保持一致。

## 虚拟主播场景视觉 worker

`VirtualHostRuntimeService` 在 `on_capture_completed`（主线程）只取得 QImage 快照，将 `_SceneVisionRunnable`
投递至有界 `virtual_host_worker_pool`；worker 检查取消 Event，压缩后释放原图，再检查取消并调用
`request_scene_summary`，经 `SceneVisionCoordinator.completed`（含 request_started）
信号回主线程 `_on_scene_vision_completed` → `_complete_scene_vision`。禁止 worker 直接修改
`VirtualHostRuntimeService` / `VirtualHostSession` 状态。

stop/start、模型/模式/场景代际变化置位本任务 Event；旧任务完成之前保留在途门禁，随后由
主线程释放并丢弃旧结果。拒绝提交与提交异常立即释放图像和门禁；压缩失败经同一信号回
主线程。此路径不新增 timer/pool；`vision_request_count` 在完成槽仅按实际开始的 HTTP 累加。

知识检索继续使用已有单 worker 的 `knowledge-retrieval` executor。查询入场最多八个，其中
视觉预取最多六个；相同语义键合并，余量留给 Web preview。使用计数以最多 64 个独立事件
进入单个 drain Future，按原始 deadline/generation 丢弃过期事件，关闭时先停止入场并清空
待消费事件，再等所有已拥有 Future 排空后关闭数据库。缓存最多 64 项、TTL 180 秒，不新增 Qt 触发点。
每个 usage drain 批次最多处理 64 个事件，然后把下一批排在已有查询之后，持续写入不会独占检索 worker。

`QThreadPool` / `QTimer` 触发点：截图 timer、`ai_worker_pool().start`（主视觉/麦克风）和
`virtual_host_worker_pool` 的有界投递（虚拟主播 scene/chat/ASR/TTS）。后者记录 pending/in-flight/
rejected，不能占用主视觉的两个 worker slot。

## 主链路弹幕批次 → 虚拟主播会话

`GenerationPipeline.handle_reply_parsed`（Qt 主线程，`ai_worker.finished` 回调链）在入队时仅产生
`DanmuGenerated` / `DanmuQueued`。overlay、floating panel 仅在自己实际接受文本时发出
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
