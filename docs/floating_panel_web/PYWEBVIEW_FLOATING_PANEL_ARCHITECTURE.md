# pywebview 浮动面板架构设计

> 文档定位：本文档定义「pywebview + Edge WebView2 替换 `app/floating_panel_overlay.py` QPainter 渲染层」的目标架构、职责边界、协议契约与异常处理。
>
> 与 [PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md) 互补：前者证明可行，本文档定义怎么做。
>
> **未在原型阶段验证的架构决策一律标注「待实施阶段验证」。**

---

## 1. 当前 QPainter 架构（基线）

### 1.1 模块组成

```
DanmuApp
├─ app/main_floating_panel_mixin.py    （Mixin：显隐 + 上屏入口）
├─ app/floating_panel_overlay.py       （QPainter 渲染层，834 行）
│   └─ FloatingPanelOverlay(QWidget)
│       ├─ WindowFlags: FramelessWindowHint | WindowStaysOnTopHint | Tool | BypassWindowManagerHint
│       ├─ WA_TranslucentBackground | WA_TransparentForMouseEvents
│       ├─ _render_card_pixmap()      （预渲染单条卡片为 QPixmap：圆角/尾巴/阴影/边框/文字）
│       └─ paintEvent()               （drawPixmap）
├─ app/floating_panel_engine.py        （纯数据/算法层，538 行）
│   └─ FloatingPanelEngine
│       ├─ _items: list[FloatingPanelItem]
│       ├─ _compute_targets_bottom_up()  （底锚堆积算法）
│       ├─ can_accept_new_item()
│       └─ estimate_entry_delay_ms()
├─ app/floating_panel_style.py         （样式快照：颜色/字号/边距）
│   ├─ FloatingPanelStyleSnapshot
│   ├─ WECHAT_CARD_COLORS / WECHAT_TEXT_COLOR
│   └─ style_snapshot_from_mapping()
└─ app/win32_overlay_zorder.py         （Win32 exstyle + topmost）
    ├─ apply_overlay_exstyles(hwnd, click_through=True)
    ├─ reassert_hwnd_topmost(hwnd)
    └─ get_foreground_hwnd()
```

### 1.2 数据流（当前）

```
AI 回复队列消费 (_consume_reply_queue)
  ↓
_display_floating_panel_text(content, persona_id, batch_id, scene_generation, skip_dedup)
  ↓
FloatingPanelOverlay.add_danmu_text(...)
  ↓
FloatingPanelEngine.can_accept_new_item() → True/False
  ↓ (True)
FloatingPanelEngine.add_item(...) → FloatingPanelItem
  ↓
FloatingPanelOverlay._render_card_pixmap(item) → QPixmap
  ↓
QTimer 16ms tick → FloatingPanelOverlay.paintEvent → QPainter.drawPixmap
```

### 1.3 关键限制

- **QPainter 手动布局**：圆角、阴影、尾巴、边框、文字换行均需代码计算（`_render_card_pixmap` L474-708）
- **样式硬编码**：除 `floating_panel_style.py` 提供的快照外，其余样式（如阴影偏移、动画曲线）在 `floating_panel_overlay.py` 常量中
- **无法 1:1 还原 blivechat-dev**：blivechat-dev 使用浏览器排版引擎（flex/animation/filter），QPainter 难以等价复刻

---

## 2. 目标 pywebview / WebView2 架构

### 2.1 模块组成（目标）

```
DanmuApp
├─ app/main_floating_panel_mixin.py    （修改：改为启动 pywebview 子进程 + WS 推送）
├─ app/floating_panel_engine.py        （保留：底锚堆积算法不变）
├─ app/floating_panel_style.py         （保留：样式快照不变）
├─ app/floating_panel_overlay.py       （保留为 fallback，待后续工单移除）
│
├─ app/floating_panel_web/             （新增子包）
│   ├─ __init__.py
│   ├─ panel_process.py                （pywebview 子进程管理：spawn + ready queue）
│   ├─ panel_bridge.py                 （主进程 ↔ WS 桥接：缓存 + 推送 + 状态查询）
│   └─ panel_protocol.py               （WS 消息格式定义）
│
├─ app/web_console_ws.py               （修改：追加 /ws/panel 路由注册）
│   └─ register_websocket_routes()
│       ├─ /ws/status   （已有）
│      ├─ /ws/logs     （已有）
│      └─ /ws/panel    （新增：浮动面板弹幕推送 + 心跳 + 状态查询）
│
├─ app/win32_overlay_zorder.py         （保留：复用 apply_overlay_exstyles + reassert_hwnd_topmost）
├─ app/webview2_runtime.py             （保留：复用 is_webview2_runtime_available）
├─ app/bundle_paths.py                 （保留：复用 is_frozen / project_root）
│
└─ web/static/floating_panel/          （新增前端资源目录）
    ├─ index.html                      （入口 HTML）
    ├─ app.js                          （WS 客户端 + 渲染逻辑）
    ├─ style.css                       （卡片样式 + 动画）
    ├─ vendor/                         （可选：Vue 3 运行时 vue.runtime.global.js ~100KB）
    └─ assets/                         （字体/图片）
```

### 2.2 数据流（目标）

```
AI 回复队列消费 (_consume_reply_queue)
  ↓
_display_floating_panel_text(content, persona_id, batch_id, scene_generation, skip_dedup)
  ↓
FloatingPanelEngine.can_accept_new_item() → True/False   （保留算法）
  ↓ (True)
FloatingPanelEngine.add_item(...) → FloatingPanelItem     （保留算法）
  ↓
PanelBridge.enqueue_card(item) → asyncio.Queue            （主线程 → uvicorn 线程）
  ↓ (loop.call_soon_threadsafe)
WS /ws/panel.send_json({"type":"card", ...})              （uvicorn 线程 → 子进程页面）
  ↓
Vue 页面 addCard(msg) → DOM 渲染                          （浏览器排版引擎）
```

### 2.3 进程与线程模型

```
主进程（DanmuApp, Qt 主线程）
├─ Qt 主线程
│   ├─ _on_screenshot_timer（截图 + AI）
│   ├─ _consume_reply_queue → _display_floating_panel_text
│   │                          → PanelBridge.enqueue_card (threadsafe 入队)
│   └─ QTimer 16ms 心跳检测子进程存活
│
├─ uvicorn 线程（FastAPI 服务，127.0.0.1:18765）
│   ├─ HTTP 路由（已有）
│   └─ WS /ws/panel endpoint
│       ├─ accept + 鉴权（复用 _authenticate_websocket 模式）
│       ├─ 心跳推送（每 2s 发 ping）
│       ├─ 接收 state-report / pong / user-event
│       └─ 推送 card / clear / config / style 消息
│
└─ pywebview 子进程（multiprocessing.spawn，daemon=True）
    ├─ webview.create_window(transparent=True, frameless=True, on_top=True, easy_drag=False)
    ├─ webview.start(gui="edgechromium")
    ├─ Win32 探针线程（仅启动期一次性应用 exstyle + topmost）
    └─ 页面 JS：WS 客户端 + Vue/原生渲染
```

**关键约束**（来自 [PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md §4](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)）：
- 主线程不调用 `evaluate_js`（会 hang）
- uvicorn 线程不直接操作 Qt 对象
- 子进程不直接读 DanmuApp 私有字段，全部通过 WS 接收数据

---

## 3. 职责边界

### 3.1 Python（主进程）

| 职责 | 模块 | 说明 |
|------|------|------|
| 弹幕堆积算法 | `app/floating_panel_engine.py` | `FloatingPanelEngine._compute_targets_bottom_up` 决定哪些条目上屏 |
| 去重 | `app/floating_panel_engine.py` | `is_duplicate_in_recent`（保留，不前端去重） |
| 样式快照读取 | `app/floating_panel_style.py` | `style_snapshot_from_mapping` 从 ConfigStore 读取 |
| 子进程生命周期 | `app/floating_panel_web/panel_process.py` | spawn + ready queue + 终止 + 重启 |
| WS 桥接 | `app/floating_panel_web/panel_bridge.py` | 主线程 → uvicorn 线程的 threadsafe 入队 |
| 消息协议定义 | `app/floating_panel_web/panel_protocol.py` | 消息类型 + 字段契约 |
| Win32 exstyle | `app/win32_overlay_zorder.py` | `apply_overlay_exstyles(hwnd, click_through=True)` |
| WebView2 探测 | `app/webview2_runtime.py` | `is_webview2_runtime_available()` |
| 显隐控制 | `app/main_floating_panel_mixin.py` | `_sync_floating_panel_visibility` 改为启动/停止子进程 |
| 上屏入口 | `app/main_floating_panel_mixin.py` | `_display_floating_panel_text` 改为 `PanelBridge.enqueue_card` |

### 3.2 FastAPI / WebSocket（uvicorn 线程）

| 职责 | 位置 | 说明 |
|------|------|------|
| WS 路由注册 | `app/web_console_ws.py:register_websocket_routes` | 追加 `/ws/panel`，用 `app.router.routes.insert(0, WebSocketRoute(...))` 显式注册 |
| 鉴权 | 复用 `_authenticate_websocket` | 首条消息认证 `{"type":"auth","token":"..."}`，兼容 query `ws_token` |
| 限流 | `_WS_MAX_PANEL_CONSUMERS = 1` | 浮动面板只允许 1 个 WS 客户端（子进程页面） |
| 心跳 | 服务端每 2s 发 `{"type":"ping","t":...}` | 客户端响应 `{"type":"pong","t":...}` |
| 推送 | `PanelBridge` 通过 `loop.call_soon_threadsafe` 入队 | 主线程 → uvicorn 线程安全 |
| 状态查询 | 收 `{"type":"get-state"}` → 广播给页面 → 页面回 `state-report` | 用于测试与诊断 |

### 3.3 Web 页面（pywebview 子进程内）

| 职责 | 位置 | 说明 |
|------|------|------|
| WS 客户端 | `web/static/floating_panel/app.js` | 连接 `ws://127.0.0.1:18765/ws/panel?ws_token=...` |
| 渲染 | `web/static/floating_panel/app.js` + `style.css` | 原生 DOM 或 Vue 3 运行时（可选） |
| 卡片布局 | CSS `#panel { flex-direction: column-reverse; }` | 底锚堆积，与 `FloatingPanelEngine._compute_targets_bottom_up` 语义一致 |
| 动画 | CSS `@keyframes slideUp/fadeOut` | 入场 `slideUp 0.25s`，退场 `fadeOut 0.25s` |
| 样式应用 | CSS 变量 `--card-bg` / `--card-border` / `--username-color` 等 | 通过 WS `config` 消息动态注入 |
| 状态上报 | `state-report` 响应 `get-state` | 含 `cardsCount`、`cardInfo`、`bodyBg`、`animationFrame` 等 |
| 重连 | WS `onclose` 后 `setTimeout(reconnect, getReconnectInterval())` | 指数退避，最大 10 次后放弃 |
| 心跳响应 | 收 `ping` → 回 `pong` | 5 秒内未收到 `ping` 视为断线 |

### 3.4 窗口子进程（pywebview）

| 职责 | 位置 | 说明 |
|------|------|------|
| 窗口创建 | `app/floating_panel_web/panel_process.py` | `transparent=True, frameless=True, on_top=True, easy_drag=False` |
| 子进程入口 | `_webview_worker` | `webview.start(gui="edgechromium")` |
| HWND 获取 | `BrowserView.instances[window.uid].Handle.ToInt32()` | pywebview 5.4 无 `window.hwnd` |
| exstyle 应用 | 启动期一次性 | `apply_overlay_exstyles(hwnd, click_through=...)`，**click_through 参数可选**（见下方说明） |
| topmost 断言 | 启动期 + 周期性（可选） | `reassert_hwnd_topmost(hwnd)` |
| ready 信号 | `ready_queue.put("loaded")` + `ready_queue.put(f"hwnd:{hwnd}")` | 主进程等待 |
| 终止 | 主进程 `proc.terminate()` + `proc.join(timeout=3.0)` | daemon=True 随主进程退出 |

**鼠标穿透（click-through）说明**：
- 原型已验证 `WS_EX_TRANSPARENT | WS_EX_LAYERED` 可实现鼠标穿透（5/5 WindowFromPoint 通过，见 [FEASIBILITY §3.1](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)）
- **但本架构不强求实现鼠标穿透**：浮动面板作为辅助显示层，允许接收鼠标（如未来需要点击卡片交互）
- 配置项 `floating_panel_click_through`（默认 `"0"` 关闭）控制是否启用：
  - `"0"`（默认）：不应用 `WS_EX_TRANSPARENT`，窗口可接收鼠标
  - `"1"`：应用 `WS_EX_TRANSPARENT`，鼠标穿透到下层窗口
- 若启用 click-through，必须**在所有 `evaluate_js` 调用之后**应用（见 [FEASIBILITY §5.1](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)）；由于生产中不使用 `evaluate_js`，此限制不影响

**待实施阶段验证**：关闭 click-through 时浮动面板是否能正常显示且不影响主窗口焦点。

---

## 4. WebSocket 消息格式

### 4.1 服务端 → 页面

#### 4.1.1 `card` — 推送单条弹幕

```json
{
  "type": "card",
  "id": "uuid-或自增id",
  "username": "AI 管家",
  "content": "你好，欢迎来到直播间~",
  "persona_id": "butler",
  "style": {
    "card_bg": "#fff7ed",
    "card_border": "#fbbf24",
    "username_color": "#f59e0b",
    "content_color": "#1f2937",
    "outline_color": "#ffffff",
    "font_family": "Microsoft YaHei, PingFang SC, sans-serif",
    "font_size_username": 12,
    "font_size_content": 14,
    "border_radius": 12,
    "max_width": 280,
    "box_shadow": "2px 2px 12px rgba(0,0,0,0.30)",
    "shape": "bubble",
    "card_opacity": 88,
    "border_enabled": true,
    "border_width": 1,
    "border_opacity": 40,
    "outline_enabled": false,
    "outline_width": 2,
    "shadow_enabled": true,
    "padding_x": 14,
    "padding_y": 10,
    "tail_enabled": true,
    "tail_style": "round",
    "tail_width": 8,
    "tail_height": 10,
    "tail_offset_y": 38,
    "username_enabled": true,
    "username_weight": 700,
    "username_separator": "：",
    "content_weight": 400,
    "content_line_height": 140,
    "gap_username_content": 4,
    "font_bold": false
  },
  "timestamp": 1784630753352
}
```

**字段说明**：
- `id`：卡片唯一标识（用于去重与移除）
- `username`：用户名/AI 名（已做 `escapeHtml` 的原始文本，前端负责转义）
- `content`：弹幕内容（已做 `normalize_danmu_display_text` strip，前端负责转义）
- `persona_id`：人格 ID（用于头像映射，可选）
- `style`：单卡完整样式（来自 `style_snapshot_from_mapping` + 按条选色）；前端写到**该卡 DOM** CSS 变量，不得写 `document.documentElement`
- `timestamp`：服务端时间戳（ms，用于排序与超时清理）
- 扩展字段（W-FP-WEB-STYLE-PARITY-001）：`shape` / `card_opacity` / border·outline·tail·username·content 细调；缺省时 `CardStyle` 默认值兜底

**契约**：
- Python 侧已完成去重（`FloatingPanelEngine._recent`），前端不再去重
- Python 侧已完成堆积算法（`_compute_targets_bottom_up`），前端只负责渲染收到的卡片
- `style` 字段每次推送都包含完整快照（避免增量同步状态）
- 选色：`pick_palette_color`（equal / weighted + style_index），与 Qt Overlay 一致

#### 4.1.2 `config` — 全局样式/行为配置

```json
{
  "type": "config",
  "max_cards": 6,
  "stack_gap": 8,
  "panel_padding": 16,
  "entry_duration_ms": 250,
  "exit_duration_ms": 250,
  "panel_position": "bottom-left",
  "panel_width": 360,
  "panel_height": 600,
  "panel_opacity": 85
}
```

**触发时机**：
- 页面连接成功后立即推送一次
- 用户在 Web 控制台修改浮动面板配置后推送

#### 4.1.3 `clear` — 清空所有卡片

```json
{
  "type": "clear",
  "reason": "config_changed | user_action | scene_reset"
}
```

#### 4.1.4 `ping` — 心跳

```json
{
  "type": "ping",
  "t": 1784630753.349
}
```

**频率**：每 2 秒一次。

#### 4.1.5 `get-state` — 请求页面状态

```json
{
  "type": "get-state"
}
```

**响应**：页面立即回 `state-report`（见 §4.2.1）。

#### 4.1.6 `reload` — 请求页面重新加载

```json
{
  "type": "reload"
}
```

页面收到后 `location.reload()`，用于样式或脚本更新后强制刷新。

### 4.2 页面 → 服务端

#### 4.2.1 `state-report` — 页面状态上报

```json
{
  "type": "state-report",
  "cardsCount": 3,
  "cardInfo": {
    "w": 147,
    "h": 55,
    "bg": "rgb(255, 247, 237)",
    "shadow": "rgba(0, 0, 0, 0.1) 0px 2px 4px 0px, ...",
    "radius": "12px",
    "transform": "none",
    "opacity": "1"
  },
  "bodyBg": "rgba(0, 0, 0, 0)",
  "htmlBg": "rgba(0, 0, 0, 0)",
  "panelBg": "rgba(0, 0, 0, 0)",
  "animationFrame": 59,
  "wsReceived": 17,
  "wsOpen": true,
  "timestamp": 1784630754155
}
```

**触发**：收到 `get-state` 后立即响应。

**用途**：
- 测试与诊断（替代 `evaluate_js`）
- 验证透明背景是否生效（`bodyBg=rgba(0,0,0,0)`）
- 验证卡片渲染是否正常（`cardInfo.w/h/shadow/radius`）
- 验证动画是否运行（`animationFrame` 递增）

#### 4.2.2 `pong` — 心跳响应

```json
{
  "type": "pong",
  "t": 1784630753352
}
```

#### 4.2.3 `auth` — 鉴权（首条消息）

```json
{
  "type": "auth",
  "token": "Bearer xxxxx"
}
```

#### 4.2.4 `user-event` — 用户交互事件（可选）

```json
{
  "type": "user-event",
  "event": "card-clicked",
  "cardId": "uuid-xxx",
  "timestamp": 1784630753352
}
```

**注**：浮动面板默认 `pointer-events: none`，不接收鼠标。若未来需要交互（如点击卡片触发操作），需在 CSS 中对特定元素启用 `pointer-events: auto`，并通过此消息上报。**待实施阶段验证**。

#### 4.2.5 `error` — 页面错误上报

```json
{
  "type": "error",
  "message": "WebSocket connection failed",
  "stack": "Error: ...",
  "timestamp": 1784630753352
}
```

页面 `window.onerror` 与 `unhandledrejection` 捕获后上报，主进程记录到日志。

---

## 5. 异常处理与可靠性

### 5.1 页面未就绪时缓存

**场景**：pywebview 子进程启动慢（WebView2 冷启动可能 >12s，见 [app/webview_shell.py:23-24](file:///e:/test/danmu/app/webview_shell.py#L23-L24) `_LOAD_TIMEOUT_SEC=25`），期间 Python 已开始推送弹幕。

**处理**：
- `PanelBridge` 在主线程维护一个 `deque(maxlen=50)` 缓冲区
- `enqueue_card` 时：若 WS 客户端数 == 0，写入缓冲区；若 > 0，直接 `call_soon_threadsafe` 入 asyncio.Queue
- WS 连接建立时：服务端先把缓冲区中的卡片按顺序补推（带 `id` 字段，前端去重）
- 缓冲区满时丢弃最旧（记录日志 `reason=panel_buffer_overflow`）

**待实施阶段验证**：缓冲区大小 50 是否合理（取决于 WebView2 冷启动时间与弹幕频率）。

### 5.2 断线恢复

**场景**：WS 连接断开（网络抖动、服务重启、页面崩溃）。

**服务端**：
- 检测 `WebSocketDisconnect`，从 `active_ws` 集合移除
- 不主动重连（服务端是被动的）
- 缓冲区继续累积，等下次连接时补推

**页面**（`app.js` 实现）：
```javascript
ws.onclose = (e) => {
  setStatus(`ws-closed:${e.code}`);
  scheduleReconnect();
};

function scheduleReconnect() {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    reportError({message: 'Max reconnect attempts reached'});
    return;
  }
  const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
  reconnectAttempts++;
  setTimeout(connectWS, delay);
}

ws.onopen = () => {
  reconnectAttempts = 0;
  // 请求补推缓冲区
  ws.send(JSON.stringify({type: 'auth', token: wsToken}));
  ws.send(JSON.stringify({type: 'request-backfill'}));
};
```

**指数退避**：1s → 2s → 4s → 8s → 16s → 30s（上限），最大 10 次后放弃并上报 `error`。

**待实施阶段验证**：`request-backfill` 协议是否必要（如果 5.1 的连接建立时自动补推已足够，则不需要显式请求）。

### 5.3 子进程异常退出

**场景**：pywebview 子进程崩溃（WebView2 Runtime 异常、OOM、用户误杀）。

**主进程检测**：
```python
# PanelProcess 装饰 QTimer 16ms 心跳
def _check_child_alive(self):
    if self._process and not self._process.is_alive():
        exitcode = self._process.exitcode
        self.logger.warning(f"panel subprocess died: exitcode={exitcode}")
        self._on_panel_died(exitcode)

def _on_panel_died(self, exitcode):
    if self._restart_count < MAX_RESTARTS:
        self._restart_count += 1
        self.logger.info(f"restarting panel ({self._restart_count}/{MAX_RESTARTS})")
        self._launch_child_process(...)
    else:
        self.logger.error("panel restart limit reached, falling back to QPainter")
        self._fallback_to_qpainter()
```

**MAX_RESTARTS**：3 次（待实施阶段验证）。

### 5.4 旧 QPainter 回退机制

**触发条件**（任一）：
1. `is_webview2_runtime_available() == False`（系统无 WebView2 Runtime）
2. 子进程启动超时（25s 未收到 `loaded` 信号）
3. 子进程连续崩溃 3 次后仍失败

**回退实现**：
```python
# app/main_floating_panel_mixin.py
def _sync_floating_panel_visibility(self):
    if not self.engine.running:
        return
    if self._floating_panel_v2_enabled():
        if self._should_use_web_panel():
            self._start_web_panel()    # 启动 pywebview 子进程
        else:
            self._start_qpainter_panel()  # 回退到 FloatingPanelOverlay
    else:
        self._stop_all_panels()
```

**`_should_use_web_panel()` 判断**：
```python
def _should_use_web_panel(self) -> bool:
    # 1. WebView2 Runtime 必须可用
    if not is_webview2_runtime_available():
        return False
    # 2. 配置开关（新增 config key: floating_panel_use_web）
    if not self.config.get("floating_panel_use_web", "1") == "1":
        return False
    # 3. 子进程连续崩溃次数未超限
    if self._panel_restart_count >= MAX_RESTARTS:
        return False
    return True
```

**待实施阶段验证**：
- 回退时 `FloatingPanelOverlay` 与 `PanelProcess` 的状态切换是否干净
- 回退后再次满足条件时是否能切回 Web 面板（不推荐自动切回，需用户手动重启）

### 5.5 正常退出清理

**主进程 `DanmuApp.quit()`**：
1. `PanelProcess.stop()` → `proc.terminate()` + `proc.join(timeout=3.0)`
2. 若 `proc.is_alive()` → `proc.kill()` + `proc.join(timeout=1.0)`
3. `PanelBridge.shutdown()` → 清空缓冲区，关闭 WS 连接
4. `FloatingPanelEngine.stop()` → 清空 `_items`

**子进程 `window.events.closing`**：
- 不主动 close（由主进程 terminate）
- `closing` 回调返回 `True` 允许关闭

---

## 6. 关键契约（不可违反）

### 6.1 数据通信

| 规则 | 说明 |
|------|------|
| ✅ 所有 Python → 页面数据必须通过 WS | 禁止 `evaluate_js`（会 hang，见 [FEASIBILITY §4](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)） |
| ✅ 所有页面 → Python 数据必须通过 WS | 禁止 pywebview `js_api` 暴露 Python 对象 |
| ✅ WS 鉴权必须复用生产模式 | `app/web_console_ws.py:_authenticate_websocket` |
| ✅ WS 路由必须用 `app.router.routes.insert(0, WebSocketRoute(...))` 显式注册 | `@app.websocket` 在 Python 3.14 下失效 |

### 6.2 线程安全

| 规则 | 说明 |
|------|------|
| ✅ 主线程 → uvicorn 线程必须用 `loop.call_soon_threadsafe` | 参考 `app/web_console_ws.py:_enqueue_ws` |
| ✅ uvicorn 线程不直接操作 Qt 对象 | 通过 `WebConsoleBridge` 信号或 `QTimer.singleShot(0, ...)` |
| ✅ 子进程不直接读 DanmuApp 私有字段 | 全部通过 WS 接收数据 |

### 6.3 窗口属性

| 规则 | 说明 |
|------|------|
| ✅ 窗口必须 `transparent=True, frameless=True, on_top=True, easy_drag=False` | 验证已通过（[FEASIBILITY §3.1](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)） |
| ✅ 必须应用 `WS_EX_LAYERED` 保证透明 | 复用 `app/win32_overlay_zorder.py:apply_overlay_exstyles` |
| ⚠️ 鼠标穿透（`WS_EX_TRANSPARENT`）**可选，不强求** | 由配置项 `floating_panel_click_through`（默认 `"0"` 关闭）控制；启用时需在 `evaluate_js` 调用之后应用 |
| ✅ 必须周期性 `reassert_hwnd_topmost` | 防止被其他置顶窗口覆盖 |
| ❌ 不得使用 `background_color="#00000000"` | pywebview 5.4 拒绝（`ValueError`） |
| ❌ 不得使用 `window.hwnd` 属性 | pywebview 5.4 不存在，用 `BrowserView.instances[uid].Handle` |

### 6.4 禁止事项

| 规则 | 说明 |
|------|------|
| ❌ 不得引入 QWebEngineView | 体积大（+200MB）、与 pywebview 架构冲突 |
| ❌ 不得引入 Electron | 体积过大、架构完全不同 |
| ❌ 不得引入新的浏览器运行时（CEF、NW.js 等） | 系统已有 WebView2 Runtime，无需额外依赖 |
| ❌ 不得在 `app/web_api/*` 中直接读 `danmu_app._…` 私有字段 | 使用 DanmuApp 公开 façade |
| ❌ 不得在子进程内直接 import PyQt6 | 子进程是 pywebview + WebView2，不应依赖 Qt |

---

## 7. 配置项（新增）

以下配置项将添加到 ConfigStore（`floating_panel_use_web` 之外的项待实施阶段确认）：

| Key | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `floating_panel_use_web` | str("0"/"1") | "1" | 是否使用 pywebview 浮动面板（"0" 强制回退 QPainter） |
| `floating_panel_max_cards` | int | 6 | 最大同时显示卡片数 |
| `floating_panel_stack_gap` | int | 8 | 卡片间距（px） |
| `floating_panel_width` | int | 360 | 面板宽度（px，逻辑像素） |
| `floating_panel_height` | int | 600 | 面板高度（px，逻辑像素） |
| `floating_panel_position` | str | "bottom-left" | 面板位置（bottom-left/bottom-right/top-left/top-right） |

**待实施阶段验证**：是否需要 `floating_panel_position` 或直接复用 `screen_index` + `region_*`。

---

## 8. 与现有架构的集成点

### 8.1 DanmuApp Mixin

[app/main_floating_panel_mixin.py](file:///e:/test/danmu/app/main_floating_panel_mixin.py) `DanmuAppFloatingPanelMixin` 修改：

- `_sync_floating_panel_visibility`：改为根据 `_should_use_web_panel()` 启动 `PanelProcess` 或 `FloatingPanelOverlay`
- `_display_floating_panel_text`：改为 `PanelBridge.enqueue_card` 或 `FloatingPanelOverlay.add_danmu_text`

### 8.2 WebSocket 路由注册

[app/web_console_ws.py:126-185](file:///e:/test/danmu/app/web_console_ws.py#L126-L185) `register_websocket_routes` 追加：

```python
async def _ws_panel_endpoint(websocket):
    await websocket.accept()
    if not await _authenticate_websocket(websocket, token, timeout_sec=_WS_AUTH_TIMEOUT_SEC):
        return
    if len(bridge._ws_panel_queues) >= _WS_MAX_PANEL_CONSUMERS:
        await websocket.close(code=1008, reason="连接数已满")
        return
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    try:
        bridge.register_panel_consumer(queue)
        # 补推缓冲区
        for cached in bridge._panel_backfill_buffer:
            if not await _send_json_with_timeout(websocket, cached):
                return
        while True:
            item = await queue.get()
            if not await _send_json_with_timeout(websocket, item):
                break
    except websocket_disconnect:
        pass
    finally:
        bridge.unregister_panel_consumer(queue)

app.router.routes.insert(0, websocket_route("/ws/panel", endpoint=_ws_panel_endpoint))
```

调用点 [app/web_console_runtime.py:234](file:///e:/test/danmu/app/web_console_runtime.py#L234) 不变（`register_websocket_routes` 内部追加）。

### 8.3 WebConsoleBridge 扩展

`WebConsoleBridge` 需新增字段（在 [app/web_console.py](file:///e:/test/danmu/app/web_console.py) 或对应 mixin 中）：
- `_ws_panel_queues: list[asyncio.Queue]` — 浮动面板 WS 消费者队列
- `_panel_backfill_buffer: deque` — 页面未就绪时的卡片缓冲区
- `register_panel_consumer(queue)` / `unregister_panel_consumer(queue)`
- `enqueue_panel_card(card_dict)` — 主线程调用，`call_soon_threadsafe` 入队

**待实施阶段验证**：`WebConsoleBridge` 的具体修改位置（可能需要新增 `app/web_console_panel_bridge.py` 而非直接改 `WebConsoleBridge`）。

### 8.4 打包配置

[DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec) 修改：
- `hiddenimports` 追加：`app.floating_panel_web`、`app.floating_panel_web.panel_process`、`app.floating_panel_web.panel_bridge`、`app.floating_panel_web.panel_protocol`
- `datas` 追加：`('web/static/floating_panel', 'web/static/floating_panel')`

[scripts/build_exe.ps1](file:///e:/test/danmu/scripts/build_exe.ps1) 不变（PyInstaller 自动按 spec 收集）。

[scripts/velopack_pack.ps1](file:///e:/test/danmu/scripts/velopack_pack.ps1) 不变（onedir 已含前端资源）。

---

## 9. 待实施阶段验证事项

| 事项 | 验证方法 |
|------|----------|
| `PanelBridge` 缓冲区大小 50 是否合理 | 模拟 WebView2 冷启动 25s + 高频弹幕 |
| 子进程重启次数上限 3 是否合理 | 故意 kill 子进程 5 次，观察回退时机 |
| 回退到 QPainter 后是否能再次切回 Web 面板 | 修改 `floating_panel_use_web` 配置后重启 |
| `request-backfill` 协议是否必要 | 测试连接建立时自动补推是否覆盖所有场景 |
| `floating_panel_position` 配置项是否需要 | 评估与 `screen_index` + `region_*` 的重叠 |
| `WebConsoleBridge` 是否需新增子模块 | 评估直接改 `WebConsoleBridge` vs 新建 `panel_bridge.py` |
| 双 pywebview 子进程（Web 控制台 + 浮动面板）的稳定性 | 打包后同时运行 1 小时 |

---

## 10. 引用文件索引

### 现有生产代码
- [app/floating_panel_overlay.py](file:///e:/test/danmu/app/floating_panel_overlay.py)
- [app/floating_panel_engine.py](file:///e:/test/danmu/app/floating_panel_engine.py)
- [app/floating_panel_style.py](file:///e:/test/danmu/app/floating_panel_style.py)
- [app/main_floating_panel_mixin.py](file:///e:/test/danmu/app/main_floating_panel_mixin.py)
- [app/win32_overlay_zorder.py](file:///e:/test/danmu/app/win32_overlay_zorder.py)
- [app/webview_shell.py](file:///e:/test/danmu/app/webview_shell.py)
- [app/webview2_runtime.py](file:///e:/test/danmu/app/webview2_runtime.py)
- [app/web_console_ws.py](file:///e:/test/danmu/app/web_console_ws.py)
- [app/web_console_runtime.py](file:///e:/test/danmu/app/web_console_runtime.py)
- [app/bundle_paths.py](file:///e:/test/danmu/app/bundle_paths.py)
- [DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)

### 原型参考
- [prototype_floating_panel/panel.html](file:///e:/test/danmu/prototype_floating_panel/panel.html)
- [prototype_floating_panel/panel_window.py](file:///e:/test/danmu/prototype_floating_panel/panel_window.py)
- [prototype_floating_panel/run_prototype.py](file:///e:/test/danmu/prototype_floating_panel/run_prototype.py)

### 配套文档
- [PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)
- [PYWEBVIEW_FLOATING_PANEL_IMPLEMENTATION_GUIDE.md](PYWEBVIEW_FLOATING_PANEL_IMPLEMENTATION_GUIDE.md)
- [PYWEBVIEW_FLOATING_PANEL_TEST_PLAN.md](PYWEBVIEW_FLOATING_PANEL_TEST_PLAN.md)
