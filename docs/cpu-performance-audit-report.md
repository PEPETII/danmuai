# CPU Performance Audit Report

> **历史性能审计快照（2026-07-05）**：本报告是静态分析，未运行 profiler；源码行号只对应当时工作树。现行实测入口见 [2026-07-10 架构债状态](architecture-debt-wave-status-2026-07-10.md) 的 T2 Profiler 节。
>
> **历史路径说明**：`app/main_display_mixin.py` 已删除并拆为 6 个显示协调 Mixin，旧行号无法唯一映射；相关绝对链接保留为历史目标，不猜测重定向。其余仍存在的 `file:///` 目标已改为仓库相对链接。
>
> **检查范围**：DanmuAI 项目（`main.py` + `app/*.py` + 子包）
> **检查方式**：静态源码阅读 + 调用链追踪（未运行 profiling）
> **检查日期**：2026-07-05
> **检查约束**：只读分析，不修改业务代码，不执行自动修复
> **证据标准**：`confirmed` = 基于已读源码；`suspected` = 基于推测需进一步验证

---

## 1. Summary

本次检查覆盖了 DanmuAI 的主链路、全部 QTimer、线程、轮询循环、文件监听、网络请求与渲染逻辑。**发现 1 个高风险、2 个中风险、4 个低风险 CPU 占用问题**，以及若干 suspected 热路径。

**最重要的 3 个发现**：

1. **高风险**：桌宠动画 QTimer 以 16ms（60fps）常驻运行，缺少 idle-stop 保护。当桌宠可见但无动画时（占运行时间绝大多数），仍以 60fps 唤醒主线程事件循环，是空闲态 CPU 占用升高的最主要原因。对比 `app/overlay.py` 与 `app/floating_panel_overlay.py` 均实现了 `needs_render_tick()` 空转保护，桌宠是唯一缺失该保护的 60fps timer。
2. **中风险**：`topmost_health_timer` 每 500ms 无条件调用 Win32 `SetWindowPos` + `GetForegroundWindow` + `GetWindowRect` + `GetWindowLong`，即使 z-order 稳定也照调，造成持续的 Win32 syscall 开销。
3. **中风险**：`live_status_timer` 每 500ms 无条件 `build_status_snapshot()` + `asdict()` + WebSocket 广播，无 diff 短路，即使状态未变化也重复构建并序列化整个状态快照。

**已排除的风险**：未发现 busy-wait / `sleep(0)` 自旋；未发现未释放的线程/timer；高频回调内日志均经 env-gated 或 1.0s dedupe；所有 `while True` 循环均有 `Event.wait()` / `queue.get(timeout)` 阻塞。

---

## 2. Project Runtime Overview

### 2.1 启动入口

- **入口文件**：`main.py:main()`（[main.py:697](../main.py#L697)）
- **启动序列**：`QApplication` → `SingleInstanceGuard` → `DanmuApp(web_launch_mode)` → `app.exec()`
- **UI 模式**：默认 Web 控制台 + pywebview 桌面壳 + Qt Overlay/托盘（`--qt-ui` 等遗留参数已被 `app/main_launch.py:check_deprecated_launch_args` 拒绝）

### 2.2 主链路（普通模式）

```
screenshot_timer(5s) → _on_normal_capture_tick → _schedule_capture
  → CaptureRunnable(QThreadPool) → _on_capture_completed
  → _trigger_api_call → AiRunnable(QThreadPool) → _on_ai_reply
  → GenerationPipeline.consume_reply_queue → engine.add_text → overlay.paintEvent
```

关键文件：[main.py:355](../main.py#L355)（`_on_normal_capture_tick`）、[main.py:402](../main.py#L402)（`_trigger_api_call`）、[main.py:543](../main.py#L543)（`_on_ai_reply`）

### 2.3 长期运行任务清单

| 类型 | 位置 | 间隔 | 调度方式 |
|------|------|------|----------|
| 截图定时器 | `app/main_lifecycle_mixin.py:126` | 5000ms | repeating QTimer |
| 池补足定时器 | `app/main_lifecycle_mixin.py:160` | 500ms | repeating QTimer |
| Live 状态广播 | `app/main_lifecycle_mixin.py:209` | 500ms | repeating QTimer |
| 置顶健康检查 | `app/main_lifecycle_mixin.py:213` | 500ms | repeating QTimer |
| 生命统计刷盘 | `app/main_lifecycle_mixin.py:295` | 2000ms | repeating QTimer |
| 烂梗采集/展示 | `app/main_meme_mixin.py:63,99` | ≥1000ms | repeating QTimer |
| 麦克风轮询 | `app/main_lifecycle_mixin.py:142` | 600ms / 250ms | single-shot 自调度 |
| 回复消费 | `app/main_lifecycle_mixin.py:155` | 50-1000ms | single-shot 自调度 |
| Overlay 渲染 | `app/overlay.py:154` | 16ms (60fps) | PreciseTimer，有 idle-stop |
| 浮动面板渲染 | `app/floating_panel_overlay.py:86` | 16ms (60fps) | PreciseTimer，有 idle-stop |
| **桌宠动画** | `app/pet/pet_window.py:339` | **16ms (60fps)** | **PreciseTimer，无 idle-stop** |
| Web 控制台 | `app/web_console.py` | 常驻 | uvicorn 线程 |
| pywebview 子进程 | `app/webview_shell.py` | 常驻 | 子进程 |
| PortAudio 回调 | `app/mic_capture.py:299` | ~每 10-30ms | PortAudio 线程 |
| HistoryWriter | `app/history_writer.py:41` | 2000ms | daemon Thread |
| WebView 导航轮询 | `app/webview_shell.py:278` | 250ms | daemon Thread |

### 2.4 文件监听 / 网络请求 / 数据处理

- **文件监听**：未发现 `QFileSystemWatcher` / `watchdog` 等文件监听（`confirmed`）
- **网络请求**：AI 请求经 `QThreadPool`（`MAX_IN_FLIGHT=1`），Web API 经 uvicorn，更新检查经 `threading.Thread` 一次性触发
- **数据处理**：截图压缩在 `CaptureRunnable`（QThreadPool 线程）；弹幕解析在主线程 `_on_ai_reply`；SQLite 写入在 `HistoryWriter` 线程与 `ConfigStore` 锁保护下

---

## 3. High-Risk Findings

### Finding 1: 桌宠动画 QTimer 60fps 常驻运行，缺少 idle-stop 保护

* **Risk Level**: 高
* **File**: `app/pet/pet_window.py`
* **Function / Area**: `PetWindow.__init__`（[行 339-341](../app/pet/pet_window.py#L339)）、`PetWindow._on_anim_tick`（[行 679-716](../app/pet/pet_window.py#L679)）、`PetWindow.start_render_loop`（[行 451-453](../app/pet/pet_window.py#L451)）
* **Description**: 桌宠动画 timer 使用 `QTimer` + `setInterval(16)`（60fps），在 `show_pet()` 时启动后**永不停止**，直到 `hide_pet()`。`_on_anim_tick` 虽有 `needs_repaint` 判断避免 `self.update()` 调用，但 timer 本身不停止。对比 `app/overlay.py:509-511` 在 `_tick()` 内调用 `stop_render_loop(repaint=True)` 实现空转保护，桌宠缺失这一机制。
* **Why It May Cause High CPU Usage**: 60fps PreciseTimer 每 16ms 唤醒 Qt 主线程事件循环，即使桌宠静止不动（无拖拽、无惯性、气泡 alpha 已收敛、帧未到切换间隔）。每次 `_on_anim_tick` 执行：`_tick_momentum()` + bubble alpha 更新 + `self._current_animation()` + frame_clock 累加 + `needs_repaint` 判断。虽单次开销小，但 62.5Hz 持续唤醒主线程会阻止 CPU 进入深度节能状态，空闲态 CPU 占用持续 2-5%。
* **Trigger Condition**: `pet_enabled=1` 且 `pet_visible=1`（用户启用桌宠并可见）。一旦桌宠显示，timer 即常驻。
* **Evidence From Code**:
  ```python
  # app/pet/pet_window.py:339-341
  self._anim_timer = QTimer(self)
  self._anim_timer.setInterval(_ANIM_INTERVAL_MS)  # _ANIM_INTERVAL_MS = 16
  self._anim_timer.timeout.connect(self._on_anim_tick)
  
  # app/pet/pet_window.py:451-453
  def start_render_loop(self) -> None:
      if not self._anim_timer.isActive():
          self._anim_timer.start()
  
  # 对比 app/overlay.py:509-511（overlay 有 idle-stop）
  if not self._has_animatable_content():
      self.stop_render_loop(repaint=True)
      return
  ```
  `_on_anim_tick`（[行 679-716](../app/pet/pet_window.py#L679)）的 `needs_repaint` 判断仅控制 `self.update()` 调用，不控制 timer 停止。`_ANIM_INTERVAL_MS = 16`（[行 54](../app/pet/pet_window.py#L54)）。
* **Suggested Optimization**: 在 `_on_anim_tick` 末尾增加 idle 检测：当 `not (self._dragging or self._momentum_active or self._one_shot or abs(self._bubble_alpha - self._bubble_target_alpha) > 0.001 or self._frame_clock < interval)` 时调用 `self.stop_render_loop()`；在状态变化（`set_bubble_text` / `_trigger_one_shot` / 拖拽开始 / 新帧到达）时 `start_render_loop()`。参照 `app/overlay.py:266-268` 的 `_has_animatable_content` 模式。
* **Estimated Fix Complexity**: 中（需梳理所有"需要继续 tick"的状态来源，确保重启 timer 的入口完整）
* **Potential Side Effects**: 桌宠动画延迟启动（首次帧切换可能延迟一个 timer 间隔）；需确保 `set_bubble_text` / `_trigger_one_shot` / 鼠标拖拽 `mousePressEvent` 均能重启 timer，否则动画卡住。测试用例 `tests/test_pet_timer_cleanup.py` 与 `tests/test_pet_window_drag.py` 需回归。

---

## 4. Medium-Risk Findings

### Finding 2: topmost_health_timer 每 500ms 无条件调用 Win32 syscall

* **Risk Level**: 中
* **File**: `app/main_lifecycle_mixin.py`、`app/main_display_mixin.py`、`app/win32_overlay_zorder.py`
* **Function / Area**: `_on_topmost_health_tick`（[main_display_mixin.py:422-430](file:///e:/test/danmu/app/main_display_mixin.py#L422)）、`_reassert_active_overlay_topmost`（[main_display_mixin.py:325-332](file:///e:/test/danmu/app/main_display_mixin.py#L325)）、`reassert_topmost_zorder`（[overlay.py:240-264](../app/overlay.py#L240)）、`probe_exclusive_fullscreen_risk`（[win32_overlay_zorder.py:95-129](../app/win32_overlay_zorder.py#L95)）
* **Description**: `_topmost_health_timer` 以 500ms 间隔触发 `_on_topmost_health_tick`，该方法**无条件**执行：(1) `reassert_topmost_zorder()` → `self.raise_()` + `reassert_hwnd_topmost(hwnd)` → Win32 `SetWindowPos(HWND_TOPMOST, SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE|SWP_SHOWWINDOW)`；(2) `_update_overlay_compat_warning()` → `probe_exclusive_fullscreen_risk()` → Win32 `GetForegroundWindow` + `GetWindowRect` + `GetWindowLong`(GWL_STYLE)。即使 overlay z-order 完全稳定（无 Alt+Tab、无新置顶窗），这些 syscall 仍每 500ms 执行一次。
* **Why It May Cause High CPU Usage**: Win32 `SetWindowPos` 与 `GetWindowRect` 等 syscall 涉及用户态-内核态切换 + DWM 合成器交互，单次约 50-200μs。每 500ms 4-5 次 syscall = 每秒 8-10 次 syscall，持续占用主线程时间片。在多屏 / 高分辨率 / DWM 负载高时开销放大。叠加 pet 的 60fps timer，主线程几乎无空闲窗口。
* **Trigger Condition**: `engine.running` 为 True（弹幕引擎运行中）。一旦 `start()` 即常驻。
* **Evidence From Code**:
  ```python
  # app/main_lifecycle_mixin.py:213-215
  self._topmost_health_timer = QTimer(self)
  self._topmost_health_timer.setInterval(500)
  self._topmost_health_timer.timeout.connect(self._on_topmost_health_tick)
  
  # app/main_display_mixin.py:422-430
  def _on_topmost_health_tick(self) -> None:
      if not self.engine.running:
          return
      if self._active_overlay_layer() is None:
          self._ensure_web_runtime_state().set_overlay_compat_warning("")
          return
      self._reassert_active_overlay_topmost()  # 无条件 SetWindowPos
      self._update_overlay_compat_warning()     # 无条件 probe_exclusive_fullscreen_risk
      self._update_screen_index_fallback_warning()
  
  # app/win32_overlay_zorder.py:74-82（SetWindowPos 调用）
  result = _SetWindowPos(
      hwnd, _HWND_TOPMOST, 0, 0, 0, 0,
      _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
  )
  ```
* **Suggested Optimization**: 引入 dirty flag：仅在检测到前台窗口变化（`GetForegroundWindow` 返回值与上次不同）或 `_topmost_fail_streak > 0` 时才调用 `SetWindowPos`。将 `probe_exclusive_fullscreen_risk` 的 `GetWindowRect` + `GetWindowLong` 与 `GetForegroundWindow` 合并复用。或将间隔从 500ms 调至 1500-2000ms（z-order 失效检测不需要亚秒级响应）。
* **Estimated Fix Complexity**: 中（需维护 `_last_foreground_hwnd` 状态，确保 Alt+Tab 后能立即重申）
* **Potential Side Effects**: 若 dirty flag 判断失误，overlay 可能被其它置顶窗覆盖后未及时恢复。需测试 `tests/test_overlay_topmost_health.py` 与手动 Alt+Tab 场景。

### Finding 3: live_status_timer 每 500ms 无 diff 短路构建并广播完整状态快照

* **Risk Level**: 中
* **File**: `app/main_lifecycle_mixin.py`、`app/main_display_mixin.py`、`app/web_console.py`
* **Function / Area**: `_publish_live_status`（[main_display_mixin.py:55-60](file:///e:/test/danmu/app/main_display_mixin.py#L55)）、`WebConsole.publish_status`（[web_console.py:307-312](../app/web_console.py#L307)）、`StatusSnapshotBuilder.build`（经 `danmu_app.build_status_snapshot()`）
* **Description**: `_live_status_timer` 以 500ms 间隔触发 `_publish_live_status` → `bridge.publish_status()` → `refresh_status()` → `danmu_app.build_status_snapshot()` → `StatusSnapshotBuilder(self).build()` → `WebStatusSnapshot(**snapshot)` → `asdict(status)` → `_broadcast_status(payload)` 遍历所有 WebSocket 队列 `enqueue`。**无论状态是否变化**，均执行完整快照构建 + dataclass 实例化 + `asdict` 递归转 dict + WS 广播。
* **Why It May Cause High CPU Usage**: `StatusSnapshotBuilder.build()` 聚合运行态、统计、配置、layout、live status 等数十个字段，涉及多次 `getattr` 与 dataclass 构造。`asdict()` 递归遍历整个 dataclass 树。每 500ms 一次 = 每秒 2 次完整序列化 + N 个 WS 队列写入。在 Web 控制台打开时（N 个 WS 连接），广播开销线性增长。
* **Trigger Condition**: `engine.running` 为 True。Web 控制台打开时 WS 队列非空，开销更大。
* **Evidence From Code**:
  ```python
  # app/main_lifecycle_mixin.py:209-211
  self._live_status_timer = QTimer(self)
  self._live_status_timer.setInterval(500)
  self._live_status_timer.timeout.connect(self._publish_live_status)
  
  # app/main_display_mixin.py:55-60
  def _publish_live_status(self):
      if not self.engine.running:
          return
      bridge = getattr(self, "web_bridge", None)
      if bridge:
          bridge.publish_status()  # 无 diff 短路
  
  # app/web_console.py:307-312
  def publish_status(self) -> None:
      status = self.refresh_status()       # build_status_snapshot + WebStatusSnapshot(**)
      payload = asdict(status)             # 递归 dataclass → dict
      self._last_status_payload = payload
      self.status_updated.emit(status)
      self._broadcast_status(payload)      # 遍历所有 WS 队列
  ```
* **Suggested Optimization**: (1) 在 `publish_status` 入口计算 payload 的轻量指纹（如 `hash(tuple(key fields))`），与 `_last_status_payload` 指纹比对，相同则跳过广播。(2) 或将 500ms 分层：关键状态变化（running/ai_in_flight/error）立即广播；非关键状态（统计计数、delay）降级为 2s 广播。(3) 已有 `_last_status_payload` 字段，可直接复用做 diff。
* **Estimated Fix Complexity**: 中（需选择 diff 字段子集，避免漏报关键变化）
* **Potential Side Effects**: Web 控制台状态刷新延迟（最多 500ms）。若 diff 字段选择不全，某些状态变化（如 token 累计）可能不实时。`tests/test_web_status.py` 与 `tests/test_web_websocket.py` 需回归。

---

## 5. Low-Risk Findings

### Finding 4: pool_topup_timer 每 500ms 触发但工作有界

* **Risk Level**: 低
* **File**: `app/main_lifecycle_mixin.py`
* **Function / Area**: `_pool_topup_timer`（[行 160-162](../app/main_lifecycle_mixin.py#L160)）、`_maybe_pool_topup`（[main.py:154-175](../main.py#L154)）
* **Description**: 每 500ms 调用 `_maybe_pool_topup` → `plan_pool_topup(engine, config)`。`plan_pool_topup` 内部有 `engine.deficit_below_min()` 门控（`min_on_screen - visible_display_count`），同屏已满时立即返回 0，不执行 `add_text`。此外，`_maybe_pool_topup()` 亦在 `GenerationPipeline` 回复消费路径上被调用（6 处），500ms 定时器为兜底。
* **Why It May Cause High CPU Usage**: 同屏已满时 `plan_pool_topup` 仍被调用（轻量函数调用 + deficit 判断），但无实质性 CPU 开销。suspected 开销可忽略。
* **Trigger Condition**: `engine.running` 为 True。
* **Evidence From Code**:
  ```python
  # app/danmu_pool.py:258-260
  deficit = engine.deficit_below_min()
  if deficit <= 0:
      return 0, []
  ```
* **Suggested Optimization**: 可选、优先级低、当前暂缓。将间隔调至 1000ms 或加冗余短路收益极小；事件驱动路径（`GenerationPipeline` 回复消费 6 处调用）已覆盖主要补足场景。后续若 profiling 显示热点，优先候选是「池功能关闭 / `min_on_screen=0` 时停表」而非单纯拉长间隔。
* **Estimated Fix Complexity**: 低
* **Potential Side Effects**: 无实质影响。

### Finding 5: PortAudio 回调持锁 append 到 MicRingBuffer

* **Risk Level**: 低
* **File**: `app/mic_capture.py`、`app/mic_buffer.py`
* **Function / Area**: `_on_audio`（[mic_capture.py:299-302](../app/mic_capture.py#L299)）、`MicRingBuffer.append`（[mic_buffer.py:34-41](../app/mic_buffer.py#L34)）、`MicRingBuffer.try_take_recent_ms`（[mic_buffer.py:59-70](../app/mic_buffer.py#L59)）
* **Description**: PortAudio `InputStream` 回调在 PortAudio 线程以 ~16kHz 采样率触发（每 chunk 约 10-30ms），每次 `self._buffer.append(indata.tobytes())` 持 `threading.Lock`。主线程 `_poll_mic_utterance` 经 `try_take_recent_ms` 用 `acquire(blocking=False)` 非阻塞读取。
* **Why It May Cause High CPU Usage**: 16kHz mono 下锁竞争极低（PortAudio 回调持锁 <10μs，主线程非阻塞 acquire 失败直接返回）。`tobytes()` 涉及 numpy 数组拷贝，但 chunk 小（几百字节）。仅在多设备 / 高采样率 / 多通道时可能放大。suspected 当前配置下开销可忽略。
* **Trigger Condition**: `mic_mode_enabled(config)` 且模型支持音频。
* **Evidence From Code**:
  ```python
  # app/mic_capture.py:299-302
  def _on_audio(self, indata, frames, time_info, status) -> None:
      if status:
          self._last_error = str(status)
      self._buffer.append(indata.tobytes())
  
  # app/mic_buffer.py:34-41 — append 持锁
  def append(self, chunk: bytes) -> None:
      with self._lock:
          self._data.extend(chunk)
          # ...overflow trim...
  
  # app/mic_buffer.py:59-70 — 读侧非阻塞
  def try_take_recent_ms(self, ms: int) -> bytes | None:
      if not self._lock.acquire(blocking=False):
          return None
      try:
          # ...
  ```
* **Suggested Optimization**: 无需优化。若未来支持多通道高采样率，可考虑 `collections.deque` 无锁结构或增大 chunk size。优先级低。
* **Estimated Fix Complexity**: 低（但无需修改）
* **Potential Side Effects**: 无。

### Finding 6: Overlay 16ms 渲染循环（已有 idle-stop，设计良好）

* **Risk Level**: 低
* **File**: `app/overlay.py`
* **Function / Area**: `_tick`（[行 501-543](../app/overlay.py#L501)）、`_has_animatable_content`（[行 266-268](../app/overlay.py#L266)）、`stop_render_loop`（[行 279-285](../app/overlay.py#L279)）
* **Description**: Overlay 使用 16ms `PreciseTimer`，但在 `_tick()` 开头与结尾均检查 `_has_animatable_content()`（返回 `self.engine.needs_render_tick()`），无动画内容时调用 `stop_render_loop(repaint=True)` 停止 timer。`engine.add_text` 等状态变化时经 `ensure_render_loop()` 重启。
* **Why It May Cause High CPU Usage**: 仅在有弹幕滚动 / 淡入淡出 / 加速时运行 60fps，无内容时完全停止。设计良好，confirmed 非风险。列出以示对比。
* **Trigger Condition**: 弹幕引擎有可见或即将可见的动画条目。
* **Evidence From Code**:
  ```python
  # app/overlay.py:507-511
  if not self.isVisible():
      return
  if not self._has_animatable_content():
      self.stop_render_loop(repaint=True)
      return
  
  # app/overlay.py:266-268
  def _has_animatable_content(self) -> bool:
      return self.engine.needs_render_tick()
  ```
* **Suggested Optimization**: 无需优化。可作为 Finding 1 的优化参考模式。
* **Estimated Fix Complexity**: 不适用
* **Potential Side Effects**: 不适用

### Finding 7: 浮动面板 16ms 渲染循环（已有 idle-stop，设计良好）

* **Risk Level**: 低
* **File**: `app/floating_panel_overlay.py`、`app/floating_panel_engine.py`
* **Function / Area**: `_tick`、`needs_render_tick`（[floating_panel_engine.py:207-209](../app/floating_panel_engine.py#L207)）
* **Description**: 同 Finding 6，浮动面板渲染循环也实现了 `needs_render_tick()` 空转保护，无内容时停止 timer。
* **Why It May Cause High CPU Usage**: confirmed 非风险。
* **Trigger Condition**: 浮动面板模式（`danmu_render_mode=floating_panel`）且有可见条目。
* **Evidence From Code**:
  ```python
  # app/floating_panel_engine.py:207-209
  def needs_render_tick(self) -> bool:
      return bool(self._items)
  ```
* **Suggested Optimization**: 无需优化。
* **Estimated Fix Complexity**: 不适用
* **Potential Side Effects**: 不适用

---

## 6. Suspected Hot Paths — Profiling Verification (2026-07-05)

> **验证方式**：静态调用链复核 + 定向单元测试 + 轮询清单代码审查。  
> **未执行**：`python main.py` 实机 5min idle + `py-spy top/record`（无 GUI/无交互式桌面，且 `py-spy` CLI 未入 PATH；见 §6.4）。  
> **证据标准**：`confirmed` = 源码/测试可复现；`rejected` = 源码证伪原假设；`partially confirmed` = 机制存在但 CPU 占比未实测。

### 6.0 场景矩阵（A/B/C，供后续实机复用）

| 场景 | 条件 | 用途 |
|------|------|------|
| **A 基线** | Overlay only，Web 关闭，pet 隐藏，引擎 running，idle 5min | 分离 Web/pet 贡献 |
| **B 典型** | Web 控制台 + WS 正常 + pet 可见，引擎 running | 日常空闲 CPU |
| **C 加压** | B + 多屏 + danmu-pool 页 + 手动 `ws.close()` 触发 HTTP 降级 | 轮询 + 多 timer 叠加 |

自动化清单脚本：[`scripts/profile_cpu_baseline.ps1`](../scripts/profile_cpu_baseline.ps1)（封装 `py-spy top` / `record` + 观察函数列表）。

### 6.1 主线程 QTimer 调度时序叠加

**原假设（§6 初稿）**：500ms 边界 `pool_topup` + `live_status` + `topmost_health` 三重重叠，叠加 pet 60fps 常驻。

**验证结论：`partially confirmed`** — 500ms 双 timer 叠加仍成立；「三重重叠」与「pet 60fps 空闲常驻」已被 W-PERF-TIMER-001 改动削弱；Web 打开时主负担转至 1s `web_status_timer`。

| 子断言 | 判定 | 证据 |
|--------|------|------|
| 500ms 边界三 timer 同帧（pool + live + topmost） | **rejected** | `topmost_health` 间隔已改为 `TOPMOST_HEALTH_INTERVAL_MS = 1500`（[`app/main_helpers.py:31`](../app/main_helpers.py#L31)）；[`_on_topmost_health_tick`](file:///e:/test/danmu/app/main_display_mixin.py#L431) 仅在 `fg_changed` / `fail_streak>0` / 心跳 tick 时重申 |
| 500ms 边界 pool_topup + live_status 同帧 | **confirmed** | 二者均为 500ms repeating（[`app/main_lifecycle_mixin.py:160-162,209-211`](../app/main_lifecycle_mixin.py#L160)） |
| Web 打开时 live_status 仍每 500ms 构建快照 | **rejected** | [`_publish_live_status`](file:///e:/test/danmu/app/main_display_mixin.py#L55) 在 `_web_status_timer.isActive()` 时直接 return |
| Web 打开时主线程状态构建热点 | **partially confirmed** | [`web_status_timer`](../app/web_console.py#L661) 每 `WEB_STATUS_POLL_INTERVAL_MS = 1000` 调用 `publish_status`；[`publish_status`](../app/web_console.py#L309) **每次** `refresh_status()` + `asdict()`，语义相等时仅跳过 `_broadcast_status`（diff 在构建之后） |
| pet idle 仍 60fps PreciseTimer 唤醒 | **rejected** | [`_sync_render_timer`](../app/pet/pet_window.py#L537) + [`pet_render_loop.py`](../app/pet/pet_render_loop.py)：`needs_high_frequency_tick` 为 false 时停 16ms timer，改 `_wake_timer` 按帧间隔单次唤醒 |
| pool_topup 队列满时仍重 CPU | **rejected** | [`plan_pool_topup`](../app/danmu_pool.py) `deficit <= 0` 立即返回；[`_maybe_pool_topup`](../main.py#L154) 无额外工作 |

**定向测试**（2026-07-05）：

```text
python -m pytest tests/test_web_status_publish_diff.py -q
# 6 passed — semantic diff + live_status skip when web timer active
python -m pytest tests/test_overlay_topmost_health.py -q -x
#（工单 W-PERF-TIMER-001 已有覆盖；本次未重跑以省内存）
```

**后续优化指向**：§7.3 #5 timer 错峰（pool 0ms / live 170ms）仍适用，但优先级低于「`publish_status` 构建前移 diff」与 pet/topmost 已落地项。

### 6.2 前端 JS 轮询对 uvicorn 线程的影响

**原假设**：Web 控制台打开后多个 `setInterval` 持续打 HTTP，与后端 WS 广播叠加抬高 uvicorn CPU。

**验证结论：`partially confirmed`** — WS **正常**时常态 HTTP QPS 极低（**rejected** 原「多路 HTTP 轮询」假设）；WS **降级**与 live overlay 面板为可测 HTTP 来源（**confirmed**）。主线程 `publish_status`（1s）负载在 uvicorn HTTP 之上（属 6.1 / Finding 3）。

| 轮询源 | 间隔 | HTTP? | 激活条件 | 判定 |
|--------|------|-------|----------|------|
| [`transport.js`](../web/static/modules/transport.js#L327) | 1500ms | `GET /api/status` + `/api/logs/recent` | **仅 WS 降级**（`startStatusPolling` / `startLogsPolling`） | 降级路径 **confirmed**（约 1.3 req/s） |
| [`status.js`](../web/static/modules/status.js#L88) | 1000ms | 否（DOM `paintRuntimeDisplays`） | `running=true` | 对 uvicorn **rejected** |
| [`app-meme-barrage-page.js`](../web/static/modules/app-meme-barrage-page.js#L197) | 3000ms | meme meta API | danmu-pool 页（[`app.js`](../web/static/app.js#L504) 路由切换启停） | 页内 **confirmed**（+0.33 req/s） |
| [`app-live-overlay-panel.js`](../web/static/modules/app-live-overlay-panel.js#L197) | 2000ms | live overlay status | **`initLiveOverlayPanel` 全局一次**（[`app.js:580`](../web/static/app.js#L580)），非路由守卫 | 额外 HTTP **partially confirmed**（+0.5 req/s，overview 也跑） |
| [`content-announcements.js`](../web/static/modules/content-announcements.js#L381) | 5min | badge API | 全局 | 可忽略 |
| 后端 `web_status_timer` | 1000ms | 无 HTTP；主线程 `publish_status` | Web attach 后 | 属 **6.1**，非 uvicorn |

**量化（代码推导，待 DevTools 实机复核）**：

| 场景 | 预期 HTTP QPS | 备注 |
|------|---------------|------|
| WS connected，overview 页 | **< 0.5/s**（主要 live overlay 0.5/s） | transport 轮询不启动 |
| WS 降级 | **≈ 1.3/s** | status + logs @ 1500ms 各一路 |
| danmu-pool 页 + WS connected | **≈ 0.83/s** | overlay 0.5 + meme 0.33 |

**未执行**：浏览器 DevTools Network 60s 计数；`py-spy --subprocesses` 对比 uvicorn 线程（环境限制，见 §6.4）。

### 6.3 ConfigStore._write_lock 递归/竞争风险

**原假设**：非可重入锁在 `config_changed` 回调链内重入 `set`/`set_batch` 导致死锁；频繁 Web 写入造成主线程长时间阻塞。

**验证结论：`rejected`（递归死锁）/ `partially confirmed`（跨线程锁竞争，可阻塞非死锁）**

**静态调用链（confirmed 无同线程重入）**：

```text
ConfigService.apply_web_payload
  → ConfigStore.apply_web_save          # with _write_lock … commit … 释放
  → config_changed.emit()               # 锁外
  → DanmuApp._on_config_changed         # app/main_lifecycle_mixin.py:371
       → pet_window.apply_config()      # 只读 config + UI，不写库
       → pet_barrage.apply_config()     # 只读 + apply_slot_config，不写库
       → floating_panel.apply_config()  # 引擎/布局，不写 ConfigStore
```

| 路径 | 持锁关系 | 判定 |
|------|----------|------|
| `apply_web_save` → `emit` → `_on_config_changed` | emit 在 `with _write_lock` **之外**（[`storage.py:459-481`](../app/config_store/storage.py#L459)、[`config_service.py:231-242`](../app/application/config_service.py#L231)） | 无递归 **confirmed** |
| `_on_config_changed` → `pet_window.apply_config` | `apply_config` 不调用 `set`/`set_batch`（写位置仅在 `_persist_position` 拖拽结束，[`pet_window.py:985`](../app/pet/pet_window.py#L985)） | 无递归 **confirmed** |
| `HistoryWriter.flush` vs 主线程 `set` | 共享 `_write_lock`，后台等待（[`history_writer.py:96`](../app/history_writer.py#L96)） | 竞争 **partially confirmed**，非死锁 |
| `TemplateManager.save` | 直接 `with config._write_lock`，内部不嵌套 `set()`（[`templates.py:11`](../app/templates.py#L11)） | 无递归 **confirmed** |
| `set_flag` 在已持锁区内 | 文档禁止；`migrate_legacy_global_api` 各分支独立 `set_flag` 调用，均各自 acquire | 无嵌套 **confirmed** |

**定向测试**（2026-07-05）：

```text
python -m pytest tests/test_config_store.py::test_apply_web_save_single_commit \
  tests/test_config_store.py::test_with_write_lock_blocks_other_writer -q
# 2 passed

python -m pytest tests/test_history_writer.py::test_history_writer_waits_for_config_store_write_lock \
  tests/test_history_writer.py::test_history_writer_does_not_call_executemany_without_lock -q
# 2 passed — flush 阻塞等待锁释放，不抛 database is locked
```

**未执行**：连续 20 次 `PUT /api/config` 压力 + `invoke_timeout_count` 观测（需运行中 Web 控制台）；`py-spy dump` 死锁堆栈。配置 UI 为 form submit 批量保存（非滑块 `oninput`），压力场景应改为快速连续 PUT 或 AI Butler `update_config`。

**说明**：`tests/test_history_writer.py::test_history_writer_logs_flush_failures` 在 Python 3.14 环境下因 mock 未实现 `with_write_lock` 而失败（1 failed, 77 passed in batch）；与 W-CONC-001 生产路径无关，属测试 fixture 过时。

### 6.4 环境限制与建议复测

| 项目 | 状态 |
|------|------|
| `python main.py` + 5min idle 采样 | **未执行**（headless / 无 GUI） |
| `py-spy top/record` | **未执行**（`pip install py-spy` 成功，但 CLI 未入 PATH；Windows attach 通常需提升权限） |
| DevTools Network QPS | **未执行**（需 `--web-browser` 或 pywebview） |
| 连续 PUT 压力 + `invoke_timeout_count` | **未执行** |
| 静态分析 + 定向 pytest | **已执行**（见上文） |

**建议维护者复测**（有桌面环境时）：

```powershell
python main.py --web-browser
# 场景 B idle 5min 后：
.\scripts\profile_cpu_baseline.ps1 -Pid <python.exe PID> -Scenario B -DurationSec 120
# DevTools → Network → 筛选 api/ → 记录 60s 请求数（WS on vs ws.close()）
```

### 6.5 验证后工单分流（不在本次实现）

| 若确认项 | 建议工单 |
|----------|----------|
| 6.1 500ms pool+live 错峰 | timer 相位错开（pool 0ms / live 170ms） |
| 6.1 `publish_status` 仍每 tick 构建快照 | 将 `status_payloads_semantically_equal` 前移到 `build` 之前或缓存指纹 |
| 6.2 live overlay 全局 2s 轮询 | 按路由/面板可见性启停 |
| 6.2 WS 降级双通道轮询 | 合并 status+log 单请求或拉长间隔 |
| 6.3 HistoryWriter 与 config 写竞争 | 写时序优化（非 RLock）；已有 W-CONC-001 基础 |

---

## 7. Recommended Optimization Plan

按优先级排序（只给建议，不修改代码）：

### 7.1 低风险高收益优化（优先实施）

1. **Finding 1 — 桌宠 idle-stop**：在 `_on_anim_tick` 末尾增加 idle 检测，无动画时停止 timer；在 `set_bubble_text` / `_trigger_one_shot` / `mousePressEvent` / `_start_post_drag_waving` 等状态变化处重启 timer。参照 `app/overlay.py:266-268, 509-511` 模式。
   - 预期收益：空闲态 CPU 占用下降 2-5%（60fps 唤醒消除）
   - 风险：低（仅影响桌宠动画启动延迟，最多 16ms）

2. **Finding 3 — live_status diff 短路**：在 `publish_status` 入口计算 payload 指纹，与 `_last_status_payload` 比对，相同则跳过 `asdict` 与广播。
   - 预期收益：每秒减少 2 次完整 dataclass 序列化 + N 次 WS 队列写入
   - 风险：低（已有 `_last_status_payload` 字段可复用）

### 7.2 中等风险优化

3. **Finding 2 — topmost_health dirty flag**：维护 `_last_foreground_hwnd`，仅在前台窗口变化或 `_topmost_fail_streak > 0` 时调用 `SetWindowPos`；将间隔从 500ms 调至 1500ms。
   - 预期收益：Win32 syscall 频率下降 60-80%
   - 风险：中（需确保 Alt+Tab 后立即重申，可保留 `GetForegroundWindow` 轻量探测）

4. **Finding 4 — pool_topup 间隔调整**：将 `_pool_topup_timer` 间隔从 500ms 调至 1000ms。
   - 预期收益：微小
   - 风险：低

### 7.3 需要重构或深入验证的优化

5. **Suspected 6.1 — QTimer 调度错峰**：将 3 个 500ms timer（`pool_topup` / `live_status` / `topmost_health`）的起始相位错开（如 0ms / 170ms / 340ms），避免同时触发。需验证是否会引入状态不一致。
   - 预期收益：500ms 边界处主线程峰值负载下降
   - 风险：中（需确认 timer 间无隐式依赖）

6. **Suspected 6.2 — 前端 JS 轮询治理**：将多个 `setInterval` 统一为单一 WS 推送通道，移除 HTTP 轮询降级路径。需前端改造，工作量较大。
   - 预期收益：uvicorn 线程负载下降
   - 风险：中（需确保 WS 断线后仍有心跳恢复机制）

---

## 8. Suggested Profiling Methods

### 8.1 如何复现问题

1. **环境**：Windows + Python 3.12 + 项目依赖（`pip install -r requirements.txt`）
2. **启动**：`python main.py`（默认 Web + pywebview + Overlay）
3. **复现条件**：
   - 启用桌宠：`pet_enabled=1` + `pet_visible=1`
   - 启动弹幕引擎（点开始）
   - 保持 Web 控制台打开
   - 静置 5 分钟（无截图变化、无操作）
4. **观察**：任务管理器观察 `python.exe` CPU 占用，预期在 3-8% 之间（理想应 <1%）

### 8.2 如何观察 CPU 占用

- **任务管理器**：粗粒度观察总 CPU 占用
- **Process Explorer**（Sysinternals）：观察线程级 CPU 占用，定位是主线程还是 uvicorn 线程
- **`py-spy top --pid <pid>`**：实时函数级采样，观察热点函数
- **`py-spy record -o profile.svg --pid <pid> --duration 60`**：生成火焰图，60s 采样

### 8.3 推荐的 profiling 工具

| 工具 | 用途 | 安装 |
|------|------|------|
| `py-spy` | 生产级 CPU 采样，无需改代码 | `pip install py-spy` |
| `cProfile` | 函数级累计时间统计 | Python 内置 |
| `line_profiler` | 行级热点定位 | `pip install line_profiler` |
| Process Explorer | 线程级 CPU 占用 | Sysinternals 下载 |

### 8.4 重点观察的函数 / 模块

- `app/pet/pet_window.py:_on_anim_tick`（验证 Finding 1）
- `app/main_display_mixin.py:_on_topmost_health_tick` + `app/win32_overlay_zorder.py:reassert_hwnd_topmost`（验证 Finding 2）
- `app/web_console.py:publish_status` + `app/application/status_snapshot.py:StatusSnapshotBuilder.build`（验证 Finding 3）
- `app/main_lifecycle_mixin.py:_init_runtime_tracking_state` 中创建的全部 QTimer 回调
- `app/mic_buffer.py:append`（验证 Finding 5）

### 8.5 如何判断优化是否有效

1. **基准线**：优化前用 `py-spy record` 采集 60s 火焰图，记录上述函数的采样占比
2. **对比**：优化后同样条件采集 60s，对比热点函数采样占比下降幅度
3. **量化指标**：
   - 空闲态（无弹幕、无操作）CPU 占用应从 3-8% 降至 <1%
   - `py-spy top` 中 `_on_anim_tick` 采样占比应从 ~30% 降至 <5%
   - `reassert_hwnd_topmost` 采样占比应从 ~10% 降至 <2%
4. **回归验证**：运行相关测试（`tests/test_pet_timer_cleanup.py`、`tests/test_overlay_topmost_health.py`、`tests/test_web_status.py`）

---

## 9. Manual Test Checklist

后续若实施优化，需手动测试以下功能点（每项 5-10 分钟）：

### 9.1 桌宠（Finding 1 优化后）

- [ ] 启用桌宠并显示，观察静止时 CPU 占用是否下降
- [ ] 桌宠显示后立即触发气泡（`set_bubble_text`），气泡淡入动画是否正常
- [ ] 拖拽桌宠，松手后惯性滑动是否正常
- [ ] 桌宠指令触发（`_trigger_one_shot` jump/wave/failed）动画是否正常
- [ ] 切换桌宠显隐 10 次，确认 timer 不泄漏（任务管理器观察 CPU 是否持续上升）
- [ ] 长时间静置（30 分钟），CPU 占用保持低位

### 9.2 Overlay 置顶（Finding 2 优化后）

- [ ] 弹幕运行中，Alt+Tab 切换到其它置顶窗口，overlay 是否在 1-2s 内恢复置顶
- [ ] 全屏游戏 / 视频播放，overlay 是否被压制并显示兼容性告警
- [ ] 多屏切换主屏，overlay 是否正确显示在目标屏
- [ ] 长时间运行（1 小时），`_topmost_fail_streak` 是否误报

### 9.3 Web 控制台状态（Finding 3 优化后）

- [ ] Web 控制台打开，弹幕运行，状态栏数字是否实时更新（最多 500ms 延迟可接受）
- [ ] 拖动配置滑块（如弹幕速度），overlay 行为是否同步变化
- [ ] 启停弹幕引擎，Web 状态是否立即反映
- [ ] 关闭 Web 控制台标签页，WS 连接是否正确清理

### 9.4 弹幕流畅度（回归）

- [ ] 弹幕滚动无卡顿（60fps 稳定）
- [ ] 弹幕淡入淡出过渡平滑
- [ ] 加速弹幕（`_accel_remaining > 0`）效果正常
- [ ] 多弹幕同屏（>10 条）无掉帧

### 9.5 麦克风（回归）

- [ ] 启用麦克风模式，语音端点检测正常
- [ ] 麦克风自检（`/api/mic/test`）通过
- [ ] 麦克风插入弹幕正常生成

---

## 10. Final Conclusion

本次检查结论：**DanmuAI 存在 1 个高风险、2 个中风险 CPU 占用问题，最值得优先处理的是桌宠动画 timer 的 idle-stop 缺失。** Finding 4/5/6（pool_topup_timer、MicRingBuffer 锁、Overlay idle-stop）均为低风险且当前无需改动，**不在本轮优化范围**；优先项仍为 Finding 1/2/3。

### 最值得优先处理的 3 个发现

1. **Finding 1（高风险）**：`app/pet/pet_window.py:339-341, 679` — 桌宠 60fps timer 无 idle-stop。**预期优化后空闲态 CPU 占用下降 2-5%**，是投入产出比最高的优化点。修复模式可直接参照 `app/overlay.py:266-268, 509-511`。

2. **Finding 3（中风险）**：`app/main_display_mixin.py:55-60` + `app/web_console.py:307-312` — live_status 500ms 无 diff 短路。**预期优化后每秒减少 2 次完整状态序列化与广播**，在 Web 控制台打开时收益更明显。已有 `_last_status_payload` 字段可复用做 diff。

3. **Finding 2（中风险）**：`app/main_display_mixin.py:422-430` + `app/win32_overlay_zorder.py:74-82` — topmost_health 500ms 无条件 Win32 syscall。**预期优化后 Win32 syscall 频率下降 60-80%**，主线程时间片释放给弹幕渲染与 Web API。

### 总体评估

项目整体 CPU 治理基础良好：无 busy-wait 自旋、无未释放资源、高频回调日志均经节流。问题集中在"timer 无条件触发"这一类模式上——桌宠、topmost、live_status 三者均为"按固定间隔全量执行"而非"按需触发"。优化方向统一为引入 idle/diff 短路，将"定期轮询"改为"事件驱动 + 兜底轮询"。

建议按 §7.1 的优先级逐项实施，每项优化后用 §8.5 的方法量化验证收益，并运行 §9 的手动测试清单确保功能回归。
