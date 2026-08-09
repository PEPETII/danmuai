# Main Pipeline Sequence

> Maintainer registry for Boundary Guard `check_thread_trigger_docs`.
> Threading / timer triggers introduced outside `main.py` must be listed here.
> Shared terms: [glossary.md](glossary.md).

## End-to-end visual flow

```text
Qt main thread: capture tick
  -> capture_worker_pool: capture/compress
  -> Qt main thread: _trigger_api_call
  -> ai_worker_pool: provider HTTP stream
  -> Qt main thread: _on_ai_reply
       -> reject missing metadata or stale scene_generation
       -> GenerationPipeline.handle_reply_parsed
       -> parse_ai_reply_payload / normalize_reply_batch
       -> enqueue_reply_batch_for_pipeline
       -> reply_timer.timeout
       -> GenerationPipeline.consume_reply_queue
       -> pet / floating_panel / overlay dispatch
```

### Capture result freshness and session boundary

Each scheduled `CaptureRunnable` carries the current `_capture_session_epoch`.
The worker returns that epoch with both `completed` and `failed` signals; the
Qt main-thread callback drops a stale epoch before changing `_capture_in_flight`
or any screenshot state. `_apply_capture_result()` returns success only after
the current pixmap passes the `None` / `isNull()` / zero-size checks, and only
that successful result may trigger `_trigger_api_call()`.

### Terminal and retry paths

| Path | Result | Observable evidence |
|------|--------|---------------------|
| metadata missing after stop | reply dropped, in-flight released by stop path | `reason=meta_missing_after_stop` |
| `scene_generation` lagged | visual reply dropped | `reason=scene_generation_lagged` |
| parse result empty | no enqueue; failure/undisplayed accounting | `reason=empty_parse` |
| queue accepted | reply items enter FIFO and `reply_timer` drives display | `enqueued=true` pipeline log |
| application quit | wait worker pools, close meme client, stop Web, close config | shutdown logs and process exit |

## Prompt construction steps in `_build_visual_prompts` (BUG-AI-DEDUP-CONTEXT-001)

`_trigger_api_call` 在主线程调用 `_build_visual_prompts` 构造 system/user prompt。`system_pt` 按顺序追加：persona base prompt → 昵称（`append_nickname_to_system_pt`，W-NICKNAME-001）→ 直播主题（`append_live_topic_to_system_pt`，W-LIVE-TOPIC-001）→ 桌宠指令（可选）→ 知识包检索（`_inject_knowledge_prompt`，Phase B / Wave 7 B2）→ **最近已发送弹幕注入**（如下表，新增于知识包注入之后、`_build_visual_prompts` 返回前）。

| Step | Location | Thread | Notes |
|------|----------|--------|-------|
| 最近已发送弹幕注入（AI 反重复上下文） | `main.py:_build_visual_prompts` + `app/main_render_coordinator_mixin.py:_recent_sent_danmu_for_prompt` | Qt main thread | **BUG-AI-DEDUP-CONTEXT-001**：在知识包注入之后、`_build_visual_prompts` 返回前调用 `self._recent_sent_danmu_for_prompt(10)`。取最近 10 条已发送弹幕（最近在前），追加 `\n最近已发送的弹幕（请勿重复上述内容）：a \| b \| c` 到 `system_pt` 末尾。数据源：`DanmuEngine.recent`（scrolling 模式）或 `FloatingPanelEngine.recent_sent_view()`（floating_panel 模式）。空列表跳过；异常隔离不阻塞。配套：v2 回复契约（`persona_contract.py build_normal_reply_contract_zh/en`）已恢复"避免重复"提示行。 |

## Worker thread pools (W-WORKERPOOL-LOCK-001)

| Trigger | Location | Thread | Notes |
|---------|----------|--------|-------|
| `QThreadPool` | `app/worker_pools.py:ai_worker_pool` | pool (maxThreadCount=2) | AI visual recognition requests (`MAX_IN_FLIGHT=1`)。懒加载单例 + double-checked locking（`_pool_lock`）。 |
| `QThreadPool` | `app/worker_pools.py:capture_worker_pool` | pool (maxThreadCount=1) | 截图捕获任务。懒加载单例 + double-checked locking。 |
| `QThreadPool` | `app/worker_pools.py:meme_ai_pool` | pool (maxThreadCount=1) | 烂梗 AI 选梗隔离池（`MAX_IN_FLIGHT=1`）。懒加载单例 + double-checked locking。 |
| `QThreadPool` | `app/worker_pools.py:meme_fetch_pool` | pool (maxThreadCount=1) | 烂梗远程采集隔离池。`quit()` 须在 `close_meme_barrage_client()` 与 `config.close()` 前 `waitForDone`（ISSUE-072 / BUG-G-008）。 |

```text
main thread / QThreadPool:
  ai_worker_pool()  -> QThreadPool(maxThreadCount=2)  # visual AI
  capture_worker_pool() -> QThreadPool(maxThreadCount=1)  # screenshot
  meme_ai_pool() -> QThreadPool(maxThreadCount=1)  # meme AI select
  meme_fetch_pool() -> QThreadPool(maxThreadCount=1)  # meme remote fetch
```

quit() 时序：`quit()` 分别对 capture/ai/meme_ai/meme_fetch 四个独立池各调 `waitForDone(2000)`，再对 `QThreadPool.globalInstance()` 调 `waitForDone(2000)`（W-TEARDOWN-RES-001）；**之后**调用 `close_meme_barrage_client()` 释放烂梗 httpx 客户端（BUG-G-008，避免在途 `MemeFetchRunnable` 使用已关闭 client）；再停 Web 控制台并在 `config.close()` 前完成 uvicorn 关停（W-QUIT-TEARDOWN-001）。

## Background threads and subprocesses

| Trigger | Location | Thread | Notes |
|---------|----------|--------|-------|
| `threading.Thread` | `app/web_console.py:442` | uvicorn / Web API | FastAPI 独立线程；HTTP 写 Qt 须经 `WebConsoleBridge` |
| `multiprocessing.Process` | `app/webview_shell.py:366` | pywebview 子进程 | spawn 桌面壳，非 Qt 主线程 |
| `multiprocessing.Process` | `app/floating_panel_web/panel_process.py` | pywebview 浮动面板子进程 | spawn + `gui=edgechromium`；透明/无边框/置顶；数据经 FastAPI `/ws/panel`（禁止非 UI 线程 `evaluate_js`）；失败回退 `FloatingPanelOverlay` |
| WS `/ws/panel` | `app/web_console_ws.py` + `app/floating_panel_web/panel_bridge.py` | uvicorn 线程 | 主线程 `PanelBridge.enqueue_card` → `loop.call_soon_threadsafe`；最多 1 消费者；鉴权复用 `_authenticate_websocket`；endpoint 内 `asyncio.create_task` 并行 heartbeat / sender / receiver（连接结束 cancel） |
| `threading.Thread` | `app/danmu_tts_playback.py:66` | TTS play worker | daemon；`playback_finished` 经 QueuedConnection 回主线程 |
| `threading.Thread` | `app/update_service.py:398` | update download | 后台下载安装包 |
| `threading.Thread` | `app/tray.py:121` | tray update check | daemon `tray-update-check` |
| `QThreadPool.globalInstance` | `app/danmu_read_service.py:319` | danmu read probe | TTS probe 合成，结果经 Qt 信号回主线程 |
| `threading.Thread` | `app/history_writer.py:41` | HistoryWriter | daemon；弹幕历史异步批量写入 SQLite |
| `threading.Thread` | `app/floating_panel_web/panel_process.py:167` | fp-panel-styles | daemon；浮动面板启动后延迟应用 Win32 样式 |

## QTimer registry

> 所有在运行时代码中实例化的 `QTimer`（含 `QTimer(self)` 和 `QTimer()`），按模块归类。  
> `QTimer.singleShot` 为一次性调用，不在此登记；tests / prototype 除外。

| Trigger | Location | Thread | Notes |
|---------|----------|--------|-------|
| `screenshot_timer` | `app/main_lifecycle_mixin.py:129` | Qt main thread | 视觉截图 tick；timeout → `_on_screenshot_timer` |
| `_mic_poll_timer` | `app/main_lifecycle_mixin.py:146` | Qt main thread | 麦克风 utterance 轮询；`setSingleShot(True)` |
| `reply_timer` | `app/main_lifecycle_mixin.py:159` | Qt main thread | 回复队列消费；`setSingleShot(True)`；timeout → `_consume_reply_queue` → `GenerationPipeline.consume_reply_queue`（详见 W-GENPIPELINE-EXTRACT） |
| `_pool_topup_timer` | `app/main_lifecycle_mixin.py:164` | Qt main thread | 弹幕池低水位自动补满；timeout → `_maybe_pool_topup` |
| `_live_status_timer` | `app/main_lifecycle_mixin.py:215` | Qt main thread | 直播状态周期性发布；timeout → `_publish_live_status` |
| `_topmost_health_timer` | `app/main_lifecycle_mixin.py:219` | Qt main thread | Overlay / 浮动面板置顶健康检查；timeout → `_on_topmost_health_tick` |
| `_lifetime_flush_timer` | `app/main_lifecycle_mixin.py:304` | Qt main thread | 生命周期统计 pending flush；timeout → `lifetime_stats.flush_pending` |
| `_meme_collect_timer` | `app/main_meme_mixin.py:63` | Qt main thread | 烂梗远程采集触发；timeout → `_meme_collect_tick` |
| `_meme_display_timer` | `app/main_meme_mixin.py:66` | Qt main thread | 烂梗显示队列消费；timeout → `_meme_display_tick` |
| `web_status_timer` | `app/web_console.py:673` | Qt main thread | Web 控制台状态轮询；attach 时创建，timeout → 发布 Web 状态 |
| `DanmuReadService._timer` | `app/danmu_read_service.py:137` | Qt main thread | 读弹幕服务调度 tick；timeout → `_on_tick` |
| `DanmuOverlay.timer` | `app/overlay.py:152` | Qt main thread | 弹幕引擎渲染 tick；`PreciseTimer`；timeout → `_tick` |
| `FloatingPanelOverlay.timer` | `app/floating_panel_overlay.py:214` | Qt main thread | 浮动面板渲染 tick；`PreciseTimer`；timeout → `_tick` |
| `PetWindow._anim_timer` | `app/pet/pet_window.py:344` | Qt main thread | 桌宠动画 tick；timeout → `_on_anim_tick` |
| `PetWindow._wake_timer` | `app/pet/pet_window.py:347` | Qt main thread | 桌宠 scheduled wake；`setSingleShot(True)` |
| `Tray._update_poll_timer` | `app/tray.py:178` | Qt main thread | 托盘更新下载进度轮询；下载开始时创建 |

## Reply consume delegation (W-GENPIPELINE-EXTRACT)

| Trigger | Location | Thread | Notes |
|---------|----------|--------|-------|
| `reply_timer.timeout` → `DanmuApp._consume_reply_queue` → `GenerationPipeline.consume_reply_queue` | `app/application/generation_pipeline.py`（逻辑承载）+ `app/main_lifecycle_mixin.py:155-158`（QTimer 实例所有权） | Qt main thread | **W-GENPIPELINE-EXTRACT 已完成**：回复消费与三路分发迁移至 GenerationPipeline；QTimer 实例属 `main_lifecycle_mixin`，服务经 `self._app.reply_timer.start()` 驱动。由 `check_generation_pipeline_service` 规则治理。 |

```text
Qt main thread: reply_timer.timeout
  -> DanmuApp._consume_reply_queue (façade)
  -> GenerationPipeline.consume_reply_queue
  -> _dispatch_to_pet / _dispatch_to_floating_panel / _dispatch_to_overlay
  -> app.reply_timer.start(delay)  # QTimer 实例属 main_lifecycle_mixin（DanmuApp）
```

## DanmuApp Mixin Registry (W-ARCH-DANMUAPP-SPLIT-001)

`main.py` 中 `DanmuApp` 由以下 12 个 Mixin + `QObject` 装配（MRO 自上而下）：

| Mixin | 模块 | 职责 |
|-------|------|------|
| `DanmuAppLaunchMixin` | `app/main_launch_mixin.py` | 启动编排 |
| `DanmuAppWebFacadeMixin` | `app/main_web_facade_mixin.py` | Web 公开 façade |
| `DanmuAppStateMixin` | `app/main_state_mixin.py` | 运行态字段 |
| `DanmuAppMicMixin` | `app/main_mic_mixin.py` | 麦克风轨 |
| `DanmuAppRenderCoordinatorMixin` | `app/main_render_coordinator_mixin.py` | render mode / live status / 上屏路由 / 测试注入 |
| `DanmuAppPetMixin` | `app/main_pet_mixin.py` | 桌宠显隐与 Web façade |
| `DanmuAppOverlayMixin` | `app/main_overlay_mixin.py` | 横向 Overlay 可见性 |
| `DanmuAppFloatingPanelMixin` | `app/main_floating_panel_mixin.py` | 浮动面板显隐与上屏 |
| `DanmuAppScreenTopologyMixin` | `app/main_screen_topology_mixin.py` | 屏幕拓扑与置顶健康 |
| `DanmuAppRequestContextMixin` | `app/main_request_context_mixin.py` | request meta / timing / 队列辅助 |
| `DanmuAppMemeMixin` | `app/main_meme_mixin.py` | 烂梗弹幕 |
| `DanmuAppLifecycleMixin` | `app/main_lifecycle_mixin.py` | start/stop/quit 与 QTimer 所有权 |

原 `app/main_display_mixin.py`（W-ARCH-DANMUAPP-SPLIT-001）已删除，职责拆入上表显示相关 Mixin。`DanmuAppBililiveDmMixin` 已于 W-BILILIVE-DM-REMOVE-001 移除（本地备份见 `danmuji_backup/`）。
