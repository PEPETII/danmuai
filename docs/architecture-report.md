# DanmuAI 架构分析报告

> **分析日期**：2026-07-08
> **仓库路径**：`e:\test\danmu`
> **分析方式**：只读源码核查（未修改任何文件）
> **证据约定**：所有断言附 `文件:行号` 证据，均来自实际源码阅读
> **范围**：仅分析与记录，不提供修复方案

> **历史快照 / 已漂移（2026-07-10）**：本报告为 2026-07-08 只读快照，多处已与当前源码不符。Mixin 装配、显示层拆分等**以当前源码为准**，见：
> - [`docs/architecture-analysis-report-2026-07-10.md`](architecture-analysis-report-2026-07-10.md)（§0、§6.1）
> - [`AGENTS.md`](../AGENTS.md) 附录 A.3.2（13 个 Mixin；`main_display_mixin` 已拆分为 RenderCoordinator / Pet / Overlay / FloatingPanel / BililiveDm / ScreenTopology）
>
> 典型漂移：下文「8 Mixin / `DanmuAppDisplayMixin`」等描述**不再反映现行代码**。

---

## 一、架构概览

### 1.1 入口与 DanmuApp 装配

#### 入口流程

`python main.py` → `main()`（`main.py:702-773`）按以下顺序执行：

1. `multiprocessing.freeze_support()` + `mark_app_start()`（`main.py:706-707`）
2. `check_deprecated_launch_args()` 拒绝 `--qt-ui` / `--legacy-ui` / `DANMU_QT_UI=1` / `DANMU_WEB_CONSOLE=0`（`main.py:709`，实现在 `app/main_launch.py`）
3. `QApplication(sys.argv)` + `app.setQuitOnLastWindowClosed(False)`（`main.py:713-714`）—— **无 Qt 主窗**，仅托盘 + Overlay + Web 控制台
4. `SingleInstanceGuard.try_acquire()`（`main.py:717-752`）—— 激活失败重试 3 次，仍失败 `sys.exit(2)`
5. `DanmuApp(web_launch_mode=launch_mode)`（`main.py:760`）
6. `app.exec()` 进入 Qt 事件循环（`main.py:772`）

#### DanmuApp 的 8 Mixin 装配

`DanmuApp` 通过多继承由 8 个 Mixin + `QObject` 装配（`main.py:94-104`）：

```python
class DanmuApp(
    DanmuAppLaunchMixin,          # 启动编排
    DanmuAppWebFacadeMixin,       # 对外 Web façade
    DanmuAppStateMixin,           # 状态代理（RequestScheduler/TimingService/StatsState 访问器）
    DanmuAppMicMixin,             # 麦克风链路（MIC_POLL_MS=600）
    DanmuAppDisplayMixin,         # overlay/floating panel/pet 显隐
    DanmuAppRequestContextMixin,  # request meta、RTT、scene_generation_lagged 判定
    DanmuAppMemeMixin,            # 烂梗弹幕
    DanmuAppLifecycleMixin,       # 生命周期、config_changed、start/stop/quit
    QObject,
):
```

`DanmuApp.__init__`（`main.py:126-154`）按 6 阶段顺序初始化，全部在 **Qt 主线程**：

1. `_init_runtime_bridge_state` —— web_bridge/web_server 占位
2. `_init_core_subsystems` —— ConfigStore / PersonaManager / DanmuEngine / DanmuOverlay / TrayManager / HotkeyManager / FloatingPanelEngine
3. `_init_request_pipeline_state` —— reply_buffer / reply_timer / ai_worker / screenshot_timer
4. `_init_runtime_tracking_state` —— screenshot_id / scene_generation / inflight 状态
5. `_init_startup_services` —— tray.show + 延迟迁移
6. `_start_web_console_stack` —— `attach_web_console` + pywebview 子进程

### 1.2 主链路数据流

主链路在 `main.py` 模块 docstring 中明确声明（`main.py:8-10`）：

```
screenshot_timer → _on_normal_capture_tick → _schedule_capture → CaptureRunnable
→ _on_capture_completed → _trigger_api_call → AiRunnable → _on_ai_reply → ...
```

#### 各阶段函数定位

| 阶段 | 函数 | 位置 | 线程 | 关键副作用 |
|------|------|------|------|-----------|
| 1. 定时器触发 | `_on_screenshot_timer` | `main.py:356-358` | 主线程 | 转发到 `_on_normal_capture_tick` |
| 2. 闸门检查 | `_on_normal_capture_tick` | `main.py:360-392` | 主线程 | 检查 `_has_visual_request_in_flight()`；超 `VISUAL_INFLIGHT_WARN_SEC=45s` 告警（`reason=inflight_watchdog_warn`）；超 `VISUAL_INFLIGHT_RECOVER_SEC=48s` 调 `_try_recover_stale_visual_inflight()` 强制释放 |
| 3. 截图调度 | `_schedule_capture` | `main.py:312-335` | 主线程 | 投递 `CaptureRunnable` 到 `capture_worker_pool()`（QThreadPool） |
| 4. 截图回调 | `_on_capture_completed` | `main.py:337-354` | 主线程 | `_apply_capture_result` 校验 pixmap（无效记 `reason=null_pixmap`，不递增 `screenshot_id`）→ 调 `_trigger_api_call` |
| 5. API 触发 | `_trigger_api_call` | `main.py:407-526` | 主线程 | 注册 `_pending_request_meta`（复合键 `{request_round}:{screenshot_id}:{scene_generation}`）→ `RequestTimingService.mark_started` → `_acquire_visual_inflight` → `ai_worker_pool().start(AiRunnable)` |
| 6. AI 回复 | `_on_ai_reply` | `main.py:548-691` | 主线程（ai_worker.finished 信号回调） | 释放在途 → `_visual_reply_stale_reason` 门控 → token 统计 → 委托 `GenerationPipeline.handle_reply_parsed` |
| 7. 队列消费 | `_consume_reply_queue` | `main.py:693-695` | 主线程 | 委托 `self._generation_pipeline.consume_reply_queue()`（保留签名兼容 `reply_timer.timeout`） |

#### 三路分发

`GenerationPipeline.consume_reply_queue`（`app/application/generation_pipeline.py:40-53`）按 render mode 分发，**无 fall-through**：

- `_pet_barrage_mode_enabled()` → `_dispatch_to_pet`
- `_danmu_render_mode() == "floating_panel"` → `_dispatch_to_floating_panel`
- 否则 → `_dispatch_to_overlay`

`GenerationPipeline` 治理边界（`app/application/generation_pipeline.py:1-10`）：禁止实例化 QTimer/QThreadPool/QPixmap，禁止调用主链路触发函数；`reply_timer` / `reply_buffer` 所有权仍属 DanmuApp。

### 1.3 子系统与 DanmuApp 的连接

#### 1.3.1 `app/danmu_engine/`（多轨道弹幕引擎）

包结构（`app/danmu_engine/__init__.py:23-44`）：

- `track.py` —— `DanmuEngine` 类主定义（轨道/去重/容量）
- `screen.py` —— 屏幕适配模块级函数 + 挂载方法
- `render.py` —— 渲染常量 + 渲染/可见性方法

调用关系：

- `DanmuApp.add_text()` → `engine.add_text()`（`main_lifecycle_mixin.py:76` 实例化）
- `DanmuOverlay._tick()` → `engine.update()`（`overlay.py:154` timer 连接）

轨道分配 `_pick_track` 三段策略（`app/danmu_engine/__init__.py:6-9` docstring）：空闲优先 → 入口区逆密度加权随机 → 全满 fallback。

#### 1.3.2 `app/overlay.py`（Qt 透明置顶层）

`DanmuOverlay(QWidget)`（`overlay.py:110-154`）：

- 窗口标志（`overlay.py:122-127`）：`FramelessWindowHint | WindowStaysOnTopHint | Tool | BypassWindowManagerHint`
- 60fps 脏区重绘（`_INTERVAL_MS = 16`，`PreciseTimer`，`overlay.py:33,153`）
- Win32 鼠标穿透经 `app/win32_overlay_zorder.py:apply_overlay_exstyles` 应用 `WS_EX_LAYERED | WS_EX_TRANSPARENT`（`overlay.py:31` import）
- **不含**调度/AI/ConfigStore 写入；无动画时 `_target_interval_ms` 返回 0 停表省电

#### 1.3.3 `app/web_console.py` + `app/web_api/`（FastAPI 服务端）

`WebConsoleBridge(QObject)`（`web_console.py:126-403`）是 **HTTP/WS 线程与 Qt 主线程之间的唯一写入口**：

- 信号（`web_console.py:136-146`）：`start_requested` / `stop_requested` / `toggle_requested` / `save_config_requested` / `region_select_requested` / `region_reset_requested` / `sync_invoke_requested`
- 槽连接（`web_console.py:170-179`）：`start_requested.connect(danmu_app.start)` 等
- `invoke_on_main`（`web_console.py:191-243`）：从 uvicorn 线程经 `sync_invoke_requested` 信号（`QueuedConnection`）+ `threading.Event.wait` 同步等待主线程执行；超时抛 `MainThreadInvokeTimeout`，计数累加供 `/api/diagnostics` 读取

`WebConsoleServer`（`web_console.py:406-537`）在 daemon 线程跑 uvicorn，默认 `127.0.0.1:18765`，启动 token `secrets.token_urlsafe(24)`。

`app/web_api/routes.py:register_web_routes`（`routes.py:58`）注册约 65 条路由，分三类线程模型（`routes.py:3-17` docstring）：

- GET 路由：HTTP 线程直接执行（只读快照）
- `PUT /api/config`：经 `save_config_via_bridge`（pyqtSignal + Event.wait）
- 其他写路由：经 `bridge.invoke_on_main`（QueuedConnection + Event.wait），超时返回 504

边界约束（`routes.py:10-17`）：必须使用 `DanmuApp` 公开 façade（`build_status_snapshot` / `apply_web_config_payload` / `start` / `stop`），**禁止**访问下划线私有属性。

#### 1.3.4 `app/webview_shell.py`（pywebview 子进程）

- `_LOAD_TIMEOUT_SEC=25` / `_FROZEN_LOAD_TIMEOUT_SEC=25`（`webview_shell.py:23-24`）—— WebView2 冷启动可能 >12s
- `preferred_webview_gui()` 返回 `edgechromium`（win32）/ `cocoa`（mac）/ `gtk`（其他）（`webview_shell.py:42-47`）
- `wait_for_http_server` 探测 `GET /api/status`（`webview_shell.py:48-63`）
- **关键**：pywebview 拉起到**子进程**，与 Qt 主线程不在同一进程

#### 1.3.5 `app/providers/`（模型适配器）

`app/providers/__init__.py` 导出（`providers/__init__.py:5-38`）：

- `DefaultOpenAIAdapter`（默认，OpenAI 兼容）
- `MimoOpenAIAdapter`（小米 MiMo 专用）
- `get_openai_adapter(endpoint, api_mode)` —— `guess_provider_from_endpoint` 命中 `mimo` 返回 MiMo 适配器，否则 default

`app/providers/registry.py:1-13`：`HOST_ENTRIES` 由 `PROVIDERS` 预设 `default_endpoint` 提取 netloc 片段去重，按片段长度降序排序（更长优先匹配）。`guess_provider_from_endpoint` 先 host 匹配，未命中按 `api_mode` 回退 `custom_doubao`，否则 `DEFAULT_PROVIDER_ID`。

#### 1.3.6 `app/application/`（编排层 / 边界收口层）

`app/application/__init__.py:1-15` 明确定位：

- **只读投影、状态快照与 Web 配置写入**
- 例外：`generation_pipeline.py` 承载回复消费与三路分发，经 `app.reply_timer.start()` 驱动
- 层级约束：禁止 `getattr` 读 DanmuApp 下划线属性；禁止 `__dict__` 直读私有字段；只读数据须经公开 property 或 `DanmuAppWebFacadeMixin` 方法

关键模块：

| 模块 | 职责 |
|------|------|
| `config_service.py` | `PUT /api/config` 写入入口，`WEB_CONFIG_KEYS` 白名单，`scene_version_fingerprint` |
| `request_scheduler.py` | 视觉 API 触发节流，拥有 `last_api_trigger_at`，`block_reason()` 判断；**不**发起 HTTP |
| `request_timing_service.py` | RTT 样本，复合键 `{request_round}:{screenshot_id}:{scene_generation}`，仅 Qt 主线程访问 |
| `status_snapshot.py` | `StatusSnapshotBuilder` 组装 `/api/status` JSON 唯一数据源 |
| `stats_state.py` | 会话内统计真实所有者；`DanmuApp.danmu_count` 等 @property 仅为兼容 façade |
| `diagnostics_hub.py` | SSE 订阅管理；主线程 `broadcast_snapshot`，uvicorn 线程经 `asyncio.Queue` 推送 |
| `generation_pipeline.py` | 回复消费与三路分发（pet/floating_panel/overlay） |

#### 1.3.7 `app/config_store/`（SQLite 持久化）

`app/config_store/__init__.py:1-52` 是重新导出薄壳，实现分布在：

- `storage.py` —— `ConfigStore` 类主体（`config_store/storage.py:1-79`）
  - `%APPDATA%/DanmuAI/config.db` + `%APPDATA%/DanmuAI/.key`（`storage.py:75-77`）
  - `PRAGMA journal_mode=WAL` + `busy_timeout=5000`
  - `self._write_lock = threading.Lock()`（**非** RLock，递归会死锁）
  - Fernet 加密 API Key；密钥丢失不可恢复；密钥损坏时 best-effort 备份为 `.key.bak.<timestamp>`
- `crypto.py` —— Fernet 辅助、密钥管理
- `pool.py` —— 自定义弹幕池 CRUD 重新导出（实现仍在 `app/danmu_pool.py`）

#### 1.3.8 `app/pet/`（桌宠子系统）

`app/pet/pet_facade.py:1-58` 是 façade helpers 入口：

- `_pet_window(app)` / `_pet_barrage_controller(app)` / `_pet_command_service(app)` 经 `app.__dict__.get` 取实例（避免 `getattr` 触发属性描述符）
- `PET_CONFIG_KEYS`（`pet_facade.py:25-45`）枚举所有 pet_ 配置键
- `_maybe_ensure_pet_components` 懒初始化桌宠组件

9 文件结构：`pet_window.py` / `pet_state.py` / `pet_animation_mapper.py` / `pet_barrage.py` / `pet_prompt.py` / `pet_command_service.py` / `pet_assets.py` / `pet_facade.py` + `app/web_api/pet.py` 路由。

#### 1.3.9 `app/mic_*.py`（麦克风子系统，10 文件）

线程模型（`app/mic_capture.py:1-12` docstring）：

- `MicCaptureService.start()` 在主线程创建 `sounddevice.InputStream`，由 PortAudio 内部回调线程持续写入 `MicRingBuffer`
- `try_snapshot_pcm_ms` 在任意线程读取缓冲；`MicRingBuffer` 内部 `threading.Lock` 保护读写
- 音频仅驻留内存，**不**写磁盘；超 `capacity_sec`（默认 10s）自动滚出

主线程消费（`app/main_mic_mixin.py`）：

- `MIC_POLL_MS = 600` / `MIC_POLL_PHASE_MS = 250`（`main_mic_mixin.py:36`）
- `_poll_mic_utterance`（`main_mic_mixin.py:89`）—— 主线程 QTimer 定期消费
- `_handle_mic_ai_reply`（`main_mic_mixin.py:192`）—— 麦克风回复独立路径，`request_round` 为负数以区分视觉请求

10 文件：`mic_service.py`（门面）/ `mic_buffer.py`（`MicRingBuffer`）/ `mic_capture.py`（InputStream）/ `mic_encode.py`（PCM→WAV data URI）/ `mic_utterance.py`（RMS 端点检测，4 状态机）/ `mic_prompt.py` / `mic_orchestrator.py` / `mic_test.py` / `mic_test_send.py` + `app/web_api/mic_test.py` 路由。

#### 1.3.10 `app/meme_barrage/`（烂梗弹幕）

`MemeBarrageService`（`app/meme_barrage/service.py:23-50`）：

- 主线程持有：展示 FIFO 队列（`_display_queue`）+ 采集分页游标
- `_display_queue` 的 enqueue/pop 仅在 Qt 主线程定时器内调用，无跨线程写入
- 经 `app/main_meme_mixin.py` 接入 DanmuApp；`app/web_api/meme_barrage.py` 提供 `/api/meme-barrage/*` 路由

#### 1.3.11 TTS 子系统

`app/danmu_tts_playback.py:1-100`：

- `DanmuTtsPlayback(QObject)` 提供**互斥播放**（同一时间只允许一段 TTS）
- `play_wav_bytes`（`danmu_tts_playback.py:62-67`）：`_set_busy(True)` → `threading.Thread(target=self._play_worker, daemon=True).start()`
- `_play_worker`（`danmu_tts_playback.py:69-100`）：`sd.play(blocking=True)` → `sd.wait()` → `_set_busy(False)` → **跨线程投递**：

```python
QMetaObject.invokeMethod(
    self, "playback_finished", Qt.ConnectionType.QueuedConnection
)
```

  等价于 `QTimer.singleShot(0, ...)`，将 `playback_finished` 信号投递到主线程事件循环

`app/danmu_read_service.py` 的 probe 合成经 `QThreadPool.globalInstance().start(runnable)` 提交，不阻塞主线程。

### 1.4 线程模型

DanmuAI 运行时共 6 类线程/进程：

| 线程/进程 | 持有者 | 职责 | 与主线程通信 |
|-----------|--------|------|-------------|
| **Qt 主线程** | `DanmuApp` | 截图定时、回复出队、Qt 对象操作、`_on_ai_reply`、`_consume_reply_queue` | — |
| **QThreadPool（capture）** | `capture_worker_pool()` | `CaptureRunnable` 抓屏 | `CaptureCoordinator.completed` 信号回主线程 |
| **QThreadPool（AI）** | `ai_worker_pool()` | `AiRunnable` → `AiWorker` HTTP 请求（`MAX_IN_FLIGHT=1`） | `ai_worker.finished` 信号回主线程 |
| **PortAudio 线程** | `sounddevice.InputStream` | 麦克风 PCM 回调写入 `MicRingBuffer` | 主线程 `_poll_mic_utterance()` 经 `MicRingBuffer.try_take_recent_ms` 读取 |
| **threading.Thread（TTS）** | `DanmuTtsPlayback._play_worker` | `sd.play(blocking=True)` 播放 WAV | `QMetaObject.invokeMethod` + `QueuedConnection` 投递 `playback_finished` |
| **uvicorn 线程** | `WebConsoleServer._thread`（daemon） | FastAPI HTTP/WS 路由 | `WebConsoleBridge` pyqtSignal 或 `invoke_on_main`（QueuedConnection + Event.wait） |
| **pywebview 子进程** | `app/webview_shell.py` 拉起 | WebView2 桌面壳 | 进程间隔离，HTTP 探测 `/api/status` |

**关键约束**（AGENTS.md §9.1）：HTTP 线程写 Qt 对象**必须**经 `WebConsoleBridge` 信号或 `QTimer.singleShot(0, ...)`；`web_console.py:6-8` 进一步警告：`QTimer.singleShot` 在 uvicorn 线程常不触发，写操作必须用 `bridge.save_config_requested.emit(...)` 或 `invoke_on_main`。

### 1.5 信号 / Bridge 模式

#### 1.5.1 `WebConsoleBridge`（`web_console.py:126-403`）

- **唯一写入口**模式：uvicorn 路由里只 `bridge.xxx_requested.emit(...)`；槽在主线程调 DanmuApp（`web_console.py:127-134` docstring）
- `invoke_on_main`（`web_console.py:191-243`）：
  - 主线程调用时直接 `fn(*args, **kwargs)`
  - 其他线程：`sync_invoke_requested.emit(runner)`（`QueuedConnection`）+ `threading.Event.wait(timeout=10s)`
  - 超时：`aborted.set()` 标记，已排队未执行的 runner 检查后跳过；`_invoke_timeout_count += 1`；抛 `MainThreadInvokeTimeout`
  - **fn 已启动则无法中断**

#### 1.5.2 `QTimer.singleShot(0, ...)`

用于将操作投递到主线程事件循环下一轮：

- `_on_scene_generation_bumped`（`main_lifecycle_mixin.py:256`）：`QTimer.singleShot(0, self._try_scene_refresh)`
- `web_console.py:647`：ready deadline 检查
- `webview_shell.py:116`：`notify_web_console_failure` 的 `_show` 弹窗

#### 1.5.3 `QMetaObject.invokeMethod` + `QueuedConnection`

- `DanmuTtsPlayback._play_worker`（`danmu_tts_playback.py:98-100`）：跨线程投递 `playback_finished` 信号，等价 `QTimer.singleShot(0, ...)`

### 1.6 scene_generation / screenshot_id 超越机制

#### 1.6.1 两个 ID 的语义（`main.py:13-15` docstring）

- **`screenshot_id`**：每帧截图递增（`main.py:294` `self._latest_screenshot_id += 1`），用于「更新帧优于在途回复」的 supersede 判定。**无效帧不递增**（`main.py:265-290`，`reason=null_pixmap`）
- **`scene_generation`**：场景配置指纹版本。`live_topic` / `user_nickname` / `screen_index` / `region_*` 变更时递增；`start/stop` 重置；**截图不推进**

#### 1.6.2 scene_generation 递增逻辑（`app/main_lifecycle_mixin.py:224-256`）

- `_reset_scene_generation_baseline`（`main_lifecycle_mixin.py:224-228`）：`_scene_generation = 0`，记录初始指纹
- `_maybe_bump_scene_generation_on_config`（`main_lifecycle_mixin.py:230-244`）：
  - 计算 `scene_version_fingerprint(self.config)`（实现在 `app/application/config_service.py`）
  - 与 `self._scene_version_fingerprint` 比较；不同则 `_scene_generation += 1`，记 `reason=scene_config_changed`
  - 由 `_on_config_changed`（`main_lifecycle_mixin.py:369-372`）调用
- `_on_scene_generation_bumped`（`main_lifecycle_mixin.py:246-256`）：
  - `reply_buffer.purge_stale_by_generation(gen)` 清理队列内落后 ai/fallback（**mic 保留**，见 `reply_queue.py:28` `_STALE_VISUAL_SOURCES = frozenset({"ai", "fallback"})`）
  - `engine.drop_pending_below_generation(gen)` 清理引擎待上屏
  - `_scene_refresh_wanted = True` + `QTimer.singleShot(0, self._try_scene_refresh)`

#### 1.6.3 回复到达时的 stale 判定（`app/main_request_context_mixin.py:70-75`）

```python
def _visual_reply_stale_reason(self, scene_generation: int) -> str | None:
    current = int(getattr(self, "_scene_generation", 0))
    if int(scene_generation) < current:
        return "scene_generation_lagged"
    return None
```

在 `_on_ai_reply`（`main.py:593-626`）中：视觉回复若 `stale_reason` 非空 → 释放在途 + 消费 timing + 记 `dropped_as_stale=True` + 记 `reason=scene_generation_lagged` + 调 `_try_scene_refresh` → **不入队**。

#### 1.6.4 复合键（`app/main_request_context_mixin.py:30-35`）

```python
def format_reply_request_id(request_round, screenshot_id, scene_generation) -> str:
    return f"{int(request_round)}:{int(screenshot_id)}:{int(scene_generation)}"
```

由 `app/main_helpers.py:reply_request_id` 组装，用于 `_pending_request_meta` 字典键与 `RequestTimingService` RTT 跟踪。

#### 1.6.5 第二道防线（`main.py:560-589`）

`_pop_request_meta` 返回空 dict（`request_meta_missing` warning）时，`_on_ai_reply` 判定 `not meta` → 视为 stop() 后到位的陈旧 reply → `dropped_as_stale=True` + `reason=meta_missing_after_stop` → 既不释放新会话 in-flight 槽位，也不入队。

### 1.7 依赖方向图

```
main.py (DanmuApp)
 ├─→ app/main_*mixin.py (8 mixins)
 ├─→ app/application/ (边界收口层，只读投影 + generation_pipeline 行为层)
 │    └─→ app/main_request_context_mixin.py (reply_request_id 复合键)
 ├─→ app/web_console.py (WebConsoleBridge + WebConsoleServer)
 │    ├─→ app/web_api/routes.py (register_web_routes, ~65 路由)
 │    └─→ app/web_console_runtime.py + web_console_support.py + web_console_ws.py
 ├─→ app/webview_shell.py (pywebview 子进程)
 ├─→ app/overlay.py (DanmuOverlay QWidget)
 │    └─→ app/danmu_engine/ (track.py / screen.py / render.py)
 │    └─→ app/win32_overlay_zorder.py (WS_EX_LAYERED | WS_EX_TRANSPARENT)
 ├─→ app/config_store/ (storage.py / crypto.py / pool.py, SQLite + Fernet)
 ├─→ app/providers/ (registry.py + adapters/{default_openai.py, mimo.py})
 ├─→ app/ai_client.py (AiWorker, doubao Responses / openai Chat Completions)
 ├─→ app/mic_*.py (10 文件, PortAudio 线程 → MicRingBuffer → 主线程)
 ├─→ app/pet/ (9 文件, pet_facade.py 入口)
 ├─→ app/meme_barrage/ (service.py / store.py / client.py / runnable.py)
 ├─→ app/danmu_tts*.py + app/tts_*.py + app/danmu_read_service.py
 └─→ app/reply_queue.py (AIReplyFIFOBuffer, max_items=8)
```

**关键依赖方向约束**：

- `app/web_api/*` → `DanmuApp` 公开 façade（**禁止**读私有字段）
- `app/application/*` → `DanmuApp` 公开 property 或 façade（**禁止** `getattr` 下划线属性）
- `app/application/generation_pipeline.py` 例外：可写回 DanmuApp 字段（由 `boundary_guard` 的 `check_generation_pipeline_service` 规则治理）
- HTTP 线程 → Qt 主线程：**必须**经 `WebConsoleBridge` 信号或 `invoke_on_main`，**禁止** `QTimer.singleShot`（uvicorn 线程常不触发）
- TTS worker 线程 → Qt 主线程：`QMetaObject.invokeMethod` + `QueuedConnection`

---

## 二、问题清单

### 2.1 重复逻辑

| # | 问题 | 证据（file:line） | 原因 |
|---|------|------------------|------|
| 2.1.1 | AI 客户端四方法纯委托样板 | `app/ai_client.py:328-442`（`_request_doubao`/`_stream_doubao`/`_request_openai`/`_stream_openai` 仅原样转发给 `ai_client_requests.py` 同名函数） | 为保留 `worker._request_xxx()` 调用点兼容层，产生 ~115 行纯委托代码，无附加逻辑 |
| 2.1.2 | `request_doubao` 与 `request_openai` 平行实现 | `app/ai_client_requests.py:240-439` vs `480-688`（~200 行对称：相同重试循环、相同三段异常处理、相同 wall_clock 检查与 `_deliver_outcome` 模式，差异仅在请求体构造） | 双 API 平行展开而非提取共用骨架，维护时需同步改两处 |
| 2.1.3 | 流式解析拆分标准不一致 | `stream_doubao`（`ai_client_requests.py:442-477`）委托独立文件 `app/doubao_responses_stream.py`；`stream_openai`（`ai_client_requests.py:691-779`）解析逻辑内联 | 同类 SSE 解析一个外提、一个内联，拆分标准不统一 |
| 2.1.4 | 图像压缩两条平行管线 | `app/image_compress.py:18-40`（bytes → PIL → `jpeg_resize.resize_rgb_to_jpeg_bytes` → base64）vs `app/screenshot_compress.py:19-49`（QPixmap → QImage → `scaledToWidth` → `QImageWriter` → base64） | 同一「resize 到 max_width → JPEG → base64 data URI」契约的两套后端实现（PIL vs Qt）；`jpeg_resize.py` 仅被 `image_compress.py` 使用，`screenshot_compress.py` 完全不走 `jpeg_resize` |
| 2.1.5 | 脱敏正则跨模块重复（6 个相同正则） | `app/ai_client_support.py:76-88`（`sanitize_provider_error_snippet`）vs `app/web_console_support.py:104-116`（`summarize_config_save_error`） | 两处都从 `app.logger` 导入相同 6 个 pattern（`API_KEY_PATTERN`/`BASE64_IMAGE_PATTERN`/`BASE64_AUDIO_PATTERN`/`AUTH_HEADER_PATTERN`/`ENCRYPTED_KEY_PATTERN`/`GENERIC_API_KEY_PATTERN`）做相同 sub + 截断，是应抽到单一 helper 的跨模块重复 |
| 2.1.6 | HTTP 错误解析重复 | `app/tts_providers.py:72-92`（`_extract_http_error_message`）vs `app/ai_client_support.py:54-73`（`_http_error_message_and_code`） | 都解析 `httpx.HTTPStatusError` 响应 JSON 的 `message`/`error.message`/`error.code` 字段，逻辑近乎一致 |
| 2.1.7 | TTS 兼容 re-export 垫片 | `app/danmu_tts.py:1-6`（注释明确「仅作为 re-export 兼容层」），10-37 行从 `tts_providers` 导入并 `__all__` 重导出，仅 `synthesize_mimo_tts`（40-69）薄包装 | 实际实现全在 `tts_providers.py`（576 行），垫片增加导入路径模糊性 |
| 2.1.8 | persona 兼容 re-export 垫片 | `app/personae.py:1-5`（注释明确「仅作为 re-export 兼容层」），14-53 行从 `persona_builtin`/`persona_contract`/`persona_manager` 导入，`__all__`（90-131）重导出 41 个符号 | 仅保留 4 个小 helper 在本文件，其余 41 符号是搬运，导入路径模糊 |
| 2.1.9 | `web_console.py` 巨型 `__all__` re-export | `app/web_console.py:62-88`（26 符号，含 `_SAVE_DONE_EVENT_KEY`/`_enqueue_ws`/`_ws_token_valid` 等带下划线「私有」符号） | 从子模块搬运的兼容层，含私有符号重导出 |
| 2.1.10 | `DisplayMixin` 职责混杂 | `app/main_display_mixin.py:30-665`（约 40 方法，混合桌宠 ~12 个、Overlay 可见性、浮动面板、bililive DM 推送 `615-662`、屏幕拓扑/置顶健康 `269-463`） | 桌宠和 bililive DM 与「显示」关系不大，被塞进最近的 mixin，职责边界模糊 |

### 2.2 死代码与遗留负担

> **澄清**：以下文件经核实**仍在使用**，非死代码：
> - `app/danmu_pool_overlay.py` —— 被 `app/meme_barrage/service.py:8` 与 `app/web_api/danmu_pool.py:20` 导入（`is_overlay_safe` 脏话/安全过滤）
> - `app/live_overlay_hub.py` —— 被 `app/web_console.py:32,419` 与 `app/web_api/live_overlay.py:25` 导入
> - `app/danmu_engine_models.py` —— 被 `danmu_engine/__init__.py:47`、`screen.py:11`、`track.py:25-26`、`main_display_mixin.py:17`、`generation_pipeline.py:333,430,498` 导入
> - `app/runnable.py` —— 被 `main.py:327,508`、`main_lifecycle_mixin.py:137`、`main_mic_mixin.py:171` 导入；与 `worker_pools.py` **互补非重复**（`runnable.py` 定义 `QRunnable` 单元，`worker_pools.py` 管理 `QThreadPool` 实例池）

| # | 项 | 证据（file:line） | 状态 |
|---|----|------------------|------|
| 2.2.1 | `persona_version_history.py` 过度碎片化 | `app/persona_version_history.py`（整文件仅 9 行，唯一函数 `list_versions`（8-9）是 `return templates.versions(name)` 一行委托） | 为一行函数单开模块，过度碎片化 |
| 2.2.2 | `persona_contract.py` 10 个历史契约正则堆积 | `app/persona_contract.py:47-122`（`_CONTRACT_ZH_RE`/`_CONTRACT_NORMAL_ZH_V2_RE`/`_CONTRACT_NORMAL_ZH_LEGACY_RE` 等 10 个正则）用于 `strip_reply_contract`（310-328）剥离历史格式契约段落 | 多年格式演进留下的兼容堆积，维护负担高 |
| 2.2.3 | legacy API 迁移代码 ~140 行 | `app/config_store/storage.py:1057-1196`（`_maybe_migrate_legacy_api_to_custom_models`，含 `legacy_api_migrated_v1` flag 与多分支） | 处理旧全局 API 配置迁移到 custom_models 档案，一次性迁移逻辑长期驻留 |
| 2.2.4 | legacy 配置迁移函数群 | `app/config_store/storage.py:139-166`（`_migrate_legacy_image_max_width`/`_migrate_legacy_display_mode_to_render_mode`/`_normalize_legacy_display_mode`）；`app/config_defaults.py:40-41,223-259`（`LEGACY_IMAGE_MAX_WIDTH=768`/`LEGACY_DANMU_MAX_CHARS_FACTORY="15"`/3 个 `migrate_legacy_*` 函数）；`app/danmu_engine/screen.py:21,153-161`（`_LEGACY_FACTORY_DANMU_MAX_CHARS=15`） | 历史默认值与字段名演进的兼容迁移代码散布多处 |
| 2.2.5 | 废弃启动参数守卫 | `app/main_launch.py:45-59`（`check_deprecated_launch_args` 对 `--qt-ui`/`--legacy-ui`/`DANMU_QT_UI=1`/`DANMU_WEB_CONSOLE=0` 检测后 `sys.exit(2)`） | 为已移除的 Qt 主窗功能保留的拒绝守卫，非死代码但属遗留兼容负担 |
| 2.2.6 | `noqa: F401` 测试 monkeypatch 依赖的重导出（14 处） | `app/config_store/__init__.py:18-19`（`os`/`subprocess`）；`app/danmu_engine/__init__.py:29-30,33,36,47,52,61,97`；`app/danmu_engine/track.py:16,25`；`app/danmu_engine_dedup.py:3`（`time`）；`app/web_console_runtime.py:50`（`websockets`） | 这些 import 仅为保留模块属性路径供测试 `monkeypatch`，属测试设计导致的「不可删除 import」 |
| 2.2.7 | 兼容 re-export 垫片（半死代码） | `app/danmu_tts.py:1-6`、`app/personae.py:1-5`、`app/web_console.py:62-88` | 纯搬运，实际实现在子模块；垫片本身非死代码但增加导入路径模糊性 |

### 2.3 过于复杂的模块

| # | 模块 | 规模证据 | 复杂度原因 |
|---|------|---------|-----------|
| 2.3.1 | `ConfigStore` God class | `app/config_store/storage.py`（1207 行，`ConfigStore` 单类 `storage.py:82-1196` 约 75 个方法） | 单类混合 5 类职责：① KV get/set（`get`/`set`/`set_batch`/`get_int`/`get_float`/`get_json`/`set_json`，313-573）；② Fernet 加密密钥（`_init_fernet`/`_encrypted_get`/`_encrypted_set`/`get_api_key`/`get_mic_api_key`/`get_tts_api_key` + 自定义模型 apiKey，217-667、706-753）；③ 自定义弹幕库 CRUD（`custom_danmu_count`/`custom_danmu_list`/`custom_danmu_insert_many`/`custom_danmu_delete_ids`/`custom_danmu_random_sample`/`custom_danmu_contains_text`/`custom_danmu_enabled_ids`/`custom_danmu_texts_by_ids`/`get_custom_danmu_pool`/`set_custom_danmu_pool`，802-862）；④ 烂梗库 CRUD（`meme_barrage_library_count`/`clear`/`insert_many`/`all_texts`/`contains_text`/`fetch_batch`/`_trim_*`，882-992）；⑤ 迁移与 flags（`_maybe_migrate_legacy_api_to_custom_models`/`get_flag`/`set_flag`，1009-1196）。一个类同时管 KV、加密、两张业务表、一次性迁移 flag，职责过载 |
| 2.3.2 | `DanmuApp` God class | `main.py:94-104`（8 Mixin + QObject）；`main.py` 自身约 21 方法，叠加各 mixin（lifecycle 22、display 40、state 30+、launch 9、mic、meme、request_context、web_facade）合计 100+ 方法聚集于单实例 | 8 Mixin 装配虽分离文件，但运行期仍是单实例 God class；`DisplayMixin` 职责混杂（见 2.1.10） |
| 2.3.3 | 超大方法 | `_on_ai_reply`（`main.py:548-692`，约 145 行）；`_trigger_api_call`（`main.py:407-527`，约 120 行） | 单方法承担过多分支（释放在途、stale 判定、token 统计、三路分发委托、错误处理），可读性低 |
| 2.3.4 | `routes.py` 单文件 66 路由 | `app/web_api/routes.py`（781 行，`register_web_routes`（58 行）内 66 个 `@app.get/@app.put/@app.post/@app.delete` 装饰器内联注册） | 路由注册枢纽集中单文件，虽是注册中心但 781 行 + 66 路由内联影响可读性 |
| 2.3.5 | `DisplayMixin` 5 类职责混合 | `app/main_display_mixin.py:30-665`（约 40 方法） | 混合桌宠（`show_pet`/`hide_pet`/`close_pet`/`submit_pet_command`/`import_pet_asset_via_dialog`/`set_pet_barrage_slot_asset` 等 ~12 个，147-221）、Overlay 可见性、浮动面板、bililive DM 推送（`_schedule_bililive_dm_push`/`_schedule_bililive_dm_push_items`/`_schedule_bililive_dm_formula_push`，615-662）、屏幕拓扑/置顶健康（`_on_screen_topology_changed`/`_on_topmost_health_tick`/`_reassert_active_overlay_topmost`，269-463）。桌宠和 bililive DM 与「显示」关系不大 |
| 2.3.6 | 大文件集中 | `app/ai_client_requests.py`（779 行，双 API 平行实现）；`app/web_console.py`（695 行，bridge + server + attach）；`app/overlay.py`（744 行） | 多个核心文件接近或超过 700 行，单文件承担多职责 |

### 2.4 性能瓶颈

| # | 位置 | 证据（file:line） | 影响 | 现有缓解 |
|---|------|------------------|------|---------|
| 2.4.1 | `get_custom_danmu_pool_for_store` 全表主线程同步读 | `app/danmu_pool.py:603-612`（`SELECT text FROM custom_danmu_pool_entries ORDER BY id ASC LIMIT 20000` + `fetchall()`，无分页）；调用链 `load_custom_danmu_pool`（`danmu_pool.py:59-69`）、`_custom_pool_text_list` 回退（`danmu_pool.py:90-104`）、`is_stored_custom_pool_text` 回退（`danmu_pool.py:220-223`） | `LIMIT 20000`（`CUSTOM_DANMU_POOL_MAX`）一次性 `fetchall` 到内存，主线程同步 SQLite 读；AGENTS.md §A.5.1 警告「在主线程调用时窗口化渲染可能 hang」 | 热路径 `_sample_custom_pool_texts`（`danmu_pool.py:121-150`）走 id 缓存 + 分块 `custom_danmu_texts_by_ids`；但回退路径仍是全表同步读 |
| 2.4.2 | 去重 O(n²) Levenshtein 纯 Python 回退 | `app/danmu_engine_dedup.py`：`is_duplicate_in_recent`（216-273）对 `deque(30)` 逐项调用 `similarity`；`similarity`（133-172）纯 Python 回退是 O(m×n) | 30 项窗口 × 80 字符弹幕时纯 Python 回退仍有主线程压力 | 已有缓解：`_FALLBACK_MAX_LEN=32` 截断（25、151-154）；长度剪枝（246-251）；`recent_exact_set` 精确命中快路径（230）；优先 C 扩展（`python-Levenshtein`/`rapidfuzz`，112-119）。属已知风险点而非未处理隐患 |
| 2.4.3 | 主线程同步 I/O 风险 | 上述 `get_custom_danmu_pool_for_store` 全表读在主线程 | 窗口化渲染可能 hang | — |

**澄清（非瓶颈）**：

- **截图压缩**：已在 `QThreadPool` worker 中执行（`app/runnable.py:104` 的 `self.compress_fn(self.pixmap)`），**不在主线程**——正确
- **Web 配置保存**：`web_console_support.py:346-369` `save_config_via_bridge` 在 HTTP 线程 `threading.Event.wait`，经 bridge 信号到主线程，**未阻塞主线程**——正确
- **内存缓存**：`app/web_console.py:152` `_log_ring = deque(maxlen=500)` 有界；`app/danmu_pool.py:22-28` `WeakKeyDictionary` 随 config 生命周期回收——均有界，无无界增长

---

## 三、方法说明与证据基础

### 3.1 分析方式

本报告基于对 `e:\test\danmu` 仓库的**只读源码核查**，未修改任何文件。分析过程：

1. 直接阅读关键入口与编排文件：`main.py`、`app/application/__init__.py`、`app/web_console.py`、`app/web_api/routes.py`、`app/overlay.py`、`app/danmu_engine/__init__.py`、`app/providers/__init__.py`、`app/config_store/__init__.py` 等
2. 两个 search agent 并行核查：一个负责架构与数据流追踪，一个负责重复逻辑/死代码/复杂度/性能问题识别
3. 所有 `file:line` 引用均来自实际源码阅读

### 3.2 已确认 vs 待确认声明

本报告所有断言均为**已确认**，证据为正文中标注的 `文件:行号` 引用，均来自实际源码读取。未发现需要进一步验证的待确认断言。

### 3.3 相关文件路径清单

核心文件（绝对路径）：

- `e:\test\danmu\main.py`
- `e:\test\danmu\app\application\__init__.py`
- `e:\test\danmu\app\application\generation_pipeline.py`
- `e:\test\danmu\app\web_console.py`
- `e:\test\danmu\app\web_api\routes.py`
- `e:\test\danmu\app\overlay.py`
- `e:\test\danmu\app\danmu_engine\__init__.py`
- `e:\test\danmu\app\providers\__init__.py`
- `e:\test\danmu\app\providers\registry.py`
- `e:\test\danmu\app\config_store\__init__.py`
- `e:\test\danmu\app\config_store\storage.py`
- `e:\test\danmu\app\webview_shell.py`
- `e:\test\danmu\app\main_request_context_mixin.py`
- `e:\test\danmu\app\main_lifecycle_mixin.py`
- `e:\test\danmu\app\main_state_mixin.py`
- `e:\test\danmu\app\main_mic_mixin.py`
- `e:\test\danmu\app\main_display_mixin.py`
- `e:\test\danmu\app\danmu_tts_playback.py`
- `e:\test\danmu\app\mic_capture.py`
- `e:\test\danmu\app\reply_queue.py`
- `e:\test\danmu\app\pet\pet_facade.py`
- `e:\test\danmu\app\meme_barrage\service.py`
- `e:\test\danmu\app\ai_client.py`
- `e:\test\danmu\app\ai_client_requests.py`
- `e:\test\danmu\app\ai_client_support.py`
- `e:\test\danmu\app\image_compress.py`
- `e:\test\danmu\app\screenshot_compress.py`
- `e:\test\danmu\app\danmu_pool.py`
- `e:\test\danmu\app\danmu_engine_dedup.py`
- `e:\test\danmu\app\personae.py`
- `e:\test\danmu\app\persona_contract.py`
- `e:\test\danmu\app\persona_version_history.py`
- `e:\test\danmu\app\main_launch.py`
- `e:\test\danmu\app\tts_providers.py`
- `e:\test\danmu\app\web_console_support.py`

### 3.4 汇总：最值得关注的 5 项

1. **跨模块脱敏逻辑重复**（2.1.5）—— `ai_client_support.py:76-88` vs `web_console_support.py:104-116`，6 个相同正则跨模块重复
2. **`ConfigStore` God class**（2.3.1）—— `storage.py` 1207 行、~75 方法、5 类职责混合
3. **`request_doubao`/`request_openai` 平行实现**（2.1.2）—— `ai_client_requests.py:240-439` vs `480-688`，~200 行对称代码
4. **`get_custom_danmu_pool_for_store` 全表主线程读**（2.4.1）—— `danmu_pool.py:603-612`，回退路径仍可能 hang 渲染
5. **兼容 re-export 垫片堆积**（2.1.7/2.1.8/2.1.9）—— `danmu_tts.py`/`personae.py`/`web_console.py __all__` 增加导入路径模糊性
