# pywebview 浮动面板实施指南

> 文档定位：本文档为 Codex / IDE Agent 提供「pywebview + Edge WebView2 替换 `app/floating_panel_overlay.py` QPainter 渲染层」的分阶段实施步骤、文件清单与完成标准。
>
> **实施前必读**：
> - [AGENTS.md](file:///e:/test/danmu/AGENTS.md) §1-§10（协作与边界）
> - [PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)（可行性结论）
> - [PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md](PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md)（目标架构）
>
> **硬性约束**：
> - 生产数据通信必须全部使用 WebSocket，禁止从非 UI 线程调用 `evaluate_js`
> - 不得引入 QWebEngineView、Electron 或新的浏览器运行时（CEF、NW.js 等）
> - 暂时不要修改正式业务代码（除工单明确授权外）
> - 每个阶段完成后必须按 [AGENTS.md §6](file:///e:/test/danmu/AGENTS.md) 输出完成报告

---

> **迁移说明**：`prototype_floating_panel/` 原型目录已迁出源仓库，现位于 `E:\test\danmuai_external\prototype_floating_panel\`。本文档中的 `file:///` 链接和代码路径已同步更新。运行原型需设置 `$env:DANMUAI_SRC_ROOT='E:\test\danmu'`。

## 0. 关键修改说明（移植必读）

本节列出移植 blivechat-dev 时**必须修改**的关键点，避免照搬照抄：

| # | 项目 | 原项目做法 | 本项目做法 | 必须修改原因 |
|---|------|------------|------------|--------------|
| 1 | **从下到上（底锚堆积）模式** | `rotate: 180deg` + `backface-visibility: hidden`（`blivechat-dev/frontend/src/views/StyleGenerator/common.js:169-179`） | CSS `#panel { display: flex; flex-direction: column-reverse; }`（原型 `danmuai_external/prototype_floating_panel/panel.html:14-18` 已验证） | `rotate: 180deg` 会把整个容器连同子元素一起翻转 180°，影响事件坐标与文本方向；DanmuAI 仅需"新条从底部进入、旧条上推"的视觉语义，`column-reverse` 即可实现且不翻转内容 |
| 2 | **鼠标穿透（click-through）** | OBS 浏览器源模式下 OBS 宿主负责 | **不强求实现**，配置项 `floating_panel_click_through`（默认 `"0"` 关闭）控制是否应用 `WS_EX_TRANSPARENT` | 浮动面板作为辅助显示层，未来可能需要点击卡片交互；默认不应用穿透，保留鼠标接收能力 |
| 3 | **数据通信** | blivechat-dev 前端 `ChatClientRelay.js` 用 `new WebSocket(url)` 直连 B站 | 同样用 WebSocket，但连接本地 FastAPI `/ws/panel`，消息格式由 `panel_protocol.py` 定义 | 不能复用 blivechat-dev 的 API 客户端（`api/chat/ChatClient*.js`、`api/chat/models.js`） |
| 4 | **样式来源** | `StyleGenerator` 页面生成 CSS 字符串 | `app/floating_panel_style.py:style_snapshot_from_mapping` 从 ConfigStore 读取后通过 WS `config` 消息下发 | 不能复用 `views/StyleGenerator/*` |
| 5 | **后端** | blivechat-dev 自己的 aiohttp 服务器 + 模型 | 复用本项目 `app/web_console.py` 的 FastAPI（127.0.0.1:18765） | 不能复制 `backend/*` / `api/*` / `services/*` / `models/*` |

**核心提示**：从下到上模式（第 1 项）是视觉关键。blivechat-dev 的 `messageReverseScroll` 配置项**不要**移植到本项目——本项目浮动面板**始终是底锚堆积模式**（与 `app/floating_panel_engine.py:_compute_targets_bottom_up` 语义一致），无需配置切换。

---

## 1. 文件清单

### 1.1 新增文件

| 路径 | 用途 | 阶段 |
|------|------|------|
| `app/floating_panel_web/__init__.py` | 子包初始化（声明边界收口层定位） | 阶段 1 |
| `app/floating_panel_web/panel_process.py` | pywebview 子进程管理（spawn + ready queue + 终止 + 重启） | 阶段 1 |
| `app/floating_panel_web/panel_bridge.py` | 主进程 ↔ WS 桥接（缓冲区 + threadsafe 入队 + 状态查询） | 阶段 1 |
| `app/floating_panel_web/panel_protocol.py` | WS 消息格式定义（card / config / clear / ping / get-state / state-report 等） | 阶段 1 |
| `web/static/floating_panel/index.html` | 浮动面板入口 HTML | 阶段 1 |
| `web/static/floating_panel/app.js` | WS 客户端 + 渲染逻辑（原生 DOM 或 Vue 3 运行时） | 阶段 1 |
| `web/static/floating_panel/style.css` | 卡片样式 + 动画 + 透明背景 | 阶段 1 |
| `tests/test_floating_panel_web_protocol.py` | WS 消息协议单测 | 阶段 1 |
| `tests/test_floating_panel_web_bridge.py` | PanelBridge 缓冲区与 threadsafe 入队单测 | 阶段 1 |
| `tests/test_floating_panel_web_process.py` | PanelProcess 启动/终止/重启单测（mock webview） | 阶段 1 |
| `web/static/floating_panel/vendor/vue.runtime.global.js` | Vue 3 运行时（可选，~100KB） | 阶段 2 |
| `web/static/floating_panel/components/TextMessage.js` | 从 blivechat-dev 移植的卡片组件 | 阶段 2 |
| `web/static/floating_panel/components/AuthorChip.js` | 用户名 + 徽章组件 | 阶段 2 |
| `web/static/floating_panel/components/ImgShadow.js` | 头像阴影组件 | 阶段 2 |
| `web/static/floating_panel/assets/css/yt-live-chat-text-message-renderer.css` | YouTube 风格消息样式 | 阶段 2 |
| `web/static/floating_panel/assets/css/yt-live-chat-paid-message-renderer.css` | SC 付费消息样式 | 阶段 2 |

### 1.2 修改文件

| 路径 | 修改内容 | 阶段 |
|------|----------|------|
| [app/main_floating_panel_mixin.py](file:///e:/test/danmu/app/main_floating_panel_mixin.py) | `_sync_floating_panel_visibility` 改为启动 `PanelProcess` 或回退 `FloatingPanelOverlay`；`_display_floating_panel_text` 改为 `PanelBridge.enqueue_card` | 阶段 1 |
| [app/web_console_ws.py](file:///e:/test/danmu/app/web_console_ws.py) | `register_websocket_routes` 追加 `/ws/panel` 路由 | 阶段 1 |
| [DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec) | `hiddenimports` 追加 `app.floating_panel_web.*`；`datas` 追加 `web/static/floating_panel` | 阶段 1 |
| [docs/main-pipeline-sequence.md](file:///e:/test/danmu/docs/main-pipeline-sequence.md) | 登记 pywebview 浮动面板子进程 | 阶段 1 |
| [docs/runtime-state-map.md](file:///e:/test/danmu/docs/runtime-state-map.md) | 登记浮动面板运行态（PanelProcess / PanelBridge） | 阶段 1 |
| `app/web_console.py` 或新增 `app/web_console_panel_bridge.py` | 扩展 `WebConsoleBridge` 添加 `_ws_panel_queues` / `_panel_backfill_buffer` / `register_panel_consumer` | 阶段 1 |
| [web/static/build_index_html.py](file:///e:/test/danmu/web/static/build_index_html.py) | 若浮动面板 HTML 需要构建脚本（仅当采用模板化构建时） | 阶段 1（视需要） |

### 1.3 保留文件（不修改）

| 路径 | 保留原因 |
|------|----------|
| [app/floating_panel_engine.py](file:///e:/test/danmu/app/floating_panel_engine.py) | 纯数据/算法层（`_compute_targets_bottom_up` 底锚堆积算法），Web 面板复用 |
| [app/floating_panel_style.py](file:///e:/test/danmu/app/floating_panel_style.py) | 样式快照，Web 面板通过 WS `config` 消息读取 |
| [app/floating_panel_overlay.py](file:///e:/test/danmu/app/floating_panel_overlay.py) | QPainter 实现，保留为 fallback（后续工单移除） |
| [app/win32_overlay_zorder.py](file:///e:/test/danmu/app/win32_overlay_zorder.py) | 复用 `apply_overlay_exstyles` + `reassert_hwnd_topmost` |
| [app/webview_shell.py](file:///e:/test/danmu/app/webview_shell.py) | 生产 pywebview 壳，复用架构模式但不修改 |
| [app/webview2_runtime.py](file:///e:/test/danmu/app/webview2_runtime.py) | WebView2 探测逻辑，直接复用 |
| [app/bundle_paths.py](file:///e:/test/danmu/app/bundle_paths.py) | PyInstaller 路径解析，直接复用 |
| [requirements.txt](file:///e:/test/danmu/requirements.txt) | 无新依赖（pywebview 已在） |

### 1.4 禁止直接复制或改动的无关模块

| 路径 | 原因 |
|------|------|
| `app/pet/*` | 桌宠子系统，仅作架构参考（spawn 子进程 + routes 注册模式），不得复制代码 |
| `app/meme_barrage/*` | 烂梗子系统，同上 |
| `app/danmu_read_service.py` / `app/web_api/danmu_read*.py` | TTS / 读弹幕，仅参考 WS 路由模式 |
| `app/providers/*` | 模型适配器，与浮动面板无关 |
| `app/mic_*.py` | 麦克风子系统，与浮动面板无关 |
| `可参考开源项目/blivechat-dev/api/*` | blivechat-dev 后端 API，不复制（我们用自己的 FastAPI） |
| `可参考开源项目/blivechat-dev/frontend/src/api/*` | blivechat-dev 前端 API 客户端（ChatClient*.js），不复制（我们用 WS 直连） |
| `可参考开源项目/blivechat-dev/frontend/src/views/StyleGenerator/*` | 样式生成器，不复制（我们用 `floating_panel_style.py`） |
| `可参考开源项目/blivechat-dev/frontend/src/lang/*` | 多语言文件，不复制（浮动面板仅中文） |
| `可参考开源项目/blivechat-dev/frontend/src/views/Home/*` / `Room.vue` / `Help.vue` / `Plugins.vue` / `NotFound.vue` | blivechat-dev 页面，不复制（我们只要 ChatRenderer 组件） |
| `可参考开源项目/blivechat-dev/frontend/src/layout/*` | 布局组件，不复制 |
| `可参考开源项目/blivechat-dev/plugins/*` | blivechat-dev 插件，不复制 |
| `可参考开源项目/blivechat-dev/services/*` | blivechat-dev 服务端，不复制 |
| `可参考开源项目/blivechat-dev/models/*` | blivechat-dev 数据模型，不复制 |

---

## 2. 分阶段实施步骤

### 2.1 阶段 1：最小可行版本（MVP）

**目标**：用 pywebview + WebView2 替换 QPainter 渲染，保留 `floating_panel_engine.py` 底锚堆积算法，实现 WS 数据通信。

**预计工单数**：4-6 个（每个工单 5-10 分钟可验收）

#### 工单 1.1：新建 `app/floating_panel_web/` 子包骨架

**允许修改的区域**：
- `app/floating_panel_web/__init__.py`
- `app/floating_panel_web/panel_protocol.py`

**禁止修改的区域**：所有其他文件

**实施步骤**：
1. 创建 `app/floating_panel_web/__init__.py`（声明边界收口层定位，参考 `app/application/__init__.py`）
2. 创建 `app/floating_panel_web/panel_protocol.py`，定义所有 WS 消息类型（card / config / clear / ping / get-state / state-report / pong / auth / user-event / error / reload）的 dataclass 或 TypedDict

**验收标准**：
- `python -c "from app.floating_panel_web import panel_protocol"` 无 ImportError
- `panel_protocol` 中定义了所有 [ARCHITECTURE §4](PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md) 列出的消息类型
- 单测 `tests/test_floating_panel_web_protocol.py` PASS

**手动验证**：
```bash
python -m pytest tests/test_floating_panel_web_protocol.py -q -x
```

---

#### 工单 1.2：实现 `PanelBridge`（主进程 ↔ WS 桥接）

**允许修改的区域**：
- `app/floating_panel_web/panel_bridge.py`

**禁止修改的区域**：所有其他文件

**实施步骤**：
1. 创建 `PanelBridge` 类，含：
   - `_backfill_buffer: deque(maxlen=50)` — 页面未就绪时缓存
   - `_ws_queues: list[asyncio.Queue]` — 活跃 WS 消费者队列
   - `_loop: asyncio.AbstractEventLoop` — uvicorn 事件循环引用
   - `enqueue_card(card_dict)` — 主线程调用，`loop.call_soon_threadsafe` 入队（若无消费者则写入缓冲区）
   - `register_panel_consumer(queue)` / `unregister_panel_consumer(queue)` — WS endpoint 调用
   - `flush_backfill_to_queue(queue)` — 连接建立时补推缓冲区
   - `shutdown()` — 清空缓冲区与队列

2. 参考原型：`danmuai_external/prototype_floating_panel/run_prototype.py:48-132`（WS 服务端逻辑）

**验收标准**：
- `python -c "from app.floating_panel_web.panel_bridge import PanelBridge"` 无 ImportError
- 单测 `tests/test_floating_panel_web_bridge.py` PASS：
  - 无消费者时 `enqueue_card` 写入缓冲区
  - 有消费者时 `enqueue_card` 入 asyncio.Queue
  - `register_panel_consumer` 后自动补推缓冲区
  - `shutdown` 清空所有状态

**手动验证**：
```bash
python -m pytest tests/test_floating_panel_web_bridge.py -q -x
```

---

#### 工单 1.3：实现 `PanelProcess`（pywebview 子进程管理）

**允许修改的区域**：
- `app/floating_panel_web/panel_process.py`

**禁止修改的区域**：所有其他文件

**实施步骤**：
1. 创建 `PanelProcess` 类，含：
   - `start(html_url, width, height, x, y)` — spawn 子进程，等待 `loaded` 信号（25s 超时）
   - `stop()` — terminate + join + kill
   - `is_alive()` — 子进程存活检测
   - `restart()` — 停止后重新启动
   - `_launch_child_process(html_url, gui)` — 参考 `app/webview_shell.py:362-380`

2. 子进程入口 `_webview_worker`，参考原型 `danmuai_external/prototype_floating_panel/panel_window.py:16-315`：
   - `webview.create_window(transparent=True, frameless=True, on_top=True, easy_drag=False)`
   - `webview.start(gui="edgechromium")`
   - HWND 获取：`webview.platforms.winforms.BrowserView.instances[window.uid].Handle.ToInt32()`
   - Win32 exstyle 应用：`app.win32_overlay_zorder.apply_overlay_exstyles(hwnd, click_through=True)`
   - topmost 断言：`app.win32_overlay_zorder.reassert_hwnd_topmost(hwnd)`

3. WebView2 Runtime 缺失检测：调用 `app.webview2_runtime.is_webview2_runtime_available()`

**验收标准**：
- `python -c "from app.floating_panel_web.panel_process import PanelProcess"` 无 ImportError
- 单测 `tests/test_floating_panel_web_process.py` PASS（mock webview，不实际启动窗口）：
  - `start` 成功收到 `loaded` 信号
  - `stop` 后 `is_alive() == False`
  - `restart` 重置 restart_count
  - WebView2 不可用时抛 `PanelProcessError` 或返回 False

**手动验证**：
```bash
python -m pytest tests/test_floating_panel_web_process.py -q -x
```

---

#### 工单 1.4：实现前端资源（HTML/CSS/JS）

**允许修改的区域**：
- `web/static/floating_panel/index.html`
- `web/static/floating_panel/app.js`
- `web/static/floating_panel/style.css`

**禁止修改的区域**：所有其他文件

**实施步骤**：
1. 创建 `index.html`：最小骨架，引用 `app.js` + `style.css`
2. 创建 `style.css`：
   - `html, body { background: transparent !important; }`（透明背景，必须）
   - `#panel { display: flex; flex-direction: column-reverse; pointer-events: none; }`（底锚堆积 + 鼠标穿透）
   - `.card { box-shadow: ...; animation: slideUp 0.25s ease-out; }`
   - `@keyframes slideUp / fadeOut`
   - 参考 `danmuai_external/prototype_floating_panel/panel.html:6-117`
3. 创建 `app.js`：
   - WS 客户端：连接 `ws://127.0.0.1:18765/ws/panel?ws_token=<token>`（token 从 query 或 cookie 取）
   - 消息处理：`card` → `addCard()`、`config` → `applyConfig()`、`clear` → `clearCards()`、`ping` → `sendPong()`、`get-state` → `sendStateReport()`
   - 重连：指数退避 1s → 30s，最大 10 次
   - 状态上报：`state-report` 含 `cardsCount`、`cardInfo`、`bodyBg`、`panelBg`、`animationFrame`、`wsReceived`、`wsOpen`
   - 错误上报：`window.onerror` → `sendError()`
   - 参考 `danmuai_external/prototype_floating_panel/panel.html:124-261`

**验收标准**：
- `index.html` 在浏览器（Chrome/Edge）打开无 JS 错误
- WS 连接成功后收到 `card` 消息能正常渲染卡片
- `bodyBg` computed style 为 `rgba(0,0,0,0)`（透明生效）
- 卡片有 `box-shadow` + `border-radius` + `slideUp` 动画

**手动验证**：
```bash
# 启动生产 FastAPI（需先注册 /ws/panel 路由，见工单 1.5）
python main.py
# 在浏览器打开 http://127.0.0.1:18765/floating_panel/
# 用 ws_token 连接 WS，发送 {"type":"card","username":"测试","content":"hello"}
# 观察卡片渲染
```

---

#### 工单 1.5：注册 `/ws/panel` WS 路由

**允许修改的区域**：
- [app/web_console_ws.py](file:///e:/test/danmu/app/web_console_ws.py)

**禁止修改的区域**：所有其他文件

**实施步骤**：
1. 在 `register_websocket_routes` 函数末尾追加 `_ws_panel_endpoint`
2. 端点逻辑：
   - `await websocket.accept()`
   - `await _authenticate_websocket(websocket, token, timeout_sec=_WS_AUTH_TIMEOUT_SEC)`（复用现有鉴权）
   - 限流：`if len(bridge._ws_panel_queues) >= _WS_MAX_PANEL_CONSUMERS: close(1008)`
   - `bridge.register_panel_consumer(queue)`
   - 补推缓冲区：`for cached in bridge._panel_backfill_buffer: await _send_json_with_timeout(websocket, cached)`
   - 循环：`item = await queue.get(); await _send_json_with_timeout(websocket, item)`
   - `finally: bridge.unregister_panel_consumer(queue)`
3. 注册：`app.router.routes.insert(0, websocket_route("/ws/panel", endpoint=_ws_panel_endpoint))`
4. 新增常量 `_WS_MAX_PANEL_CONSUMERS = 1`（浮动面板只允许 1 个客户端）

**验收标准**：
- `python -c "from app.web_console_ws import register_websocket_routes"` 无 ImportError
- 用 `websockets` 库连接 `ws://127.0.0.1:18765/ws/panel` 能成功（鉴权通过后）
- 第 2 个连接被拒绝（1008 关闭码）

**手动验证**：
```bash
# 启动生产 FastAPI
python main.py
# 用 wscat 或 Python websockets 连接
python -c "
import asyncio, websockets, json
async def test():
    async with websockets.connect('ws://127.0.0.1:18765/ws/panel?ws_token=<token>') as ws:
        await ws.send(json.dumps({'type':'auth','token':'<token>'}))
        print(await ws.recv())
asyncio.run(test())
"
```

---

#### 工单 1.6：集成到 `DanmuAppFloatingPanelMixin` + 打包配置

**允许修改的区域**：
- [app/main_floating_panel_mixin.py](file:///e:/test/danmu/app/main_floating_panel_mixin.py)
- [DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)
- [docs/main-pipeline-sequence.md](file:///e:/test/danmu/docs/main-pipeline-sequence.md)
- [docs/runtime-state-map.md](file:///e:/test/danmu/docs/runtime-state-map.md)

**禁止修改的区域**：所有其他文件（包括 `app/floating_panel_overlay.py`、`app/floating_panel_engine.py`）

**实施步骤**：
1. 修改 `_sync_floating_panel_visibility`：
   - 新增 `_should_use_web_panel()` 判断（WebView2 可用 + 配置开关 + 重启次数未超限）
   - True → `self._panel_process.start(...)` 或 `self._panel_process.stop()`
   - False → 保留原 `FloatingPanelOverlay` 逻辑（fallback）

2. 修改 `_display_floating_panel_text`：
   - 仍调用 `FloatingPanelEngine.add_item(...)` 保留堆积算法
   - 新增：若 `_should_use_web_panel()`，调用 `self._panel_bridge.enqueue_card(card_dict)` 推送到 WS
   - 否则保留原 `FloatingPanelOverlay.add_danmu_text(...)`

3. 修改 `DanmuAI.spec`：
   - `hiddenimports` 追加：`app.floating_panel_web`、`app.floating_panel_web.panel_process`、`app.floating_panel_web.panel_bridge`、`app.floating_panel_web.panel_protocol`
   - `datas` 追加：`('web/static/floating_panel', 'web/static/floating_panel')`

4. 更新 `docs/main-pipeline-sequence.md`：登记 `PanelProcess` 子进程与 WS 推送链路

5. 更新 `docs/runtime-state-map.md`：登记 `PanelProcess` / `PanelBridge` 运行态

**验收标准**：
- `python main.py` 启动后浮动面板以 pywebview 窗口显示（若 WebView2 可用）
- 关闭浮动面板配置后回退到 QPainter
- `python scripts/boundary_guard.py` PASS
- 打包后（PyInstaller onedir）`web/static/floating_panel/` 存在
- 分批测试 PASS（参考 [AGENTS.md §A.4.2](file:///e:/test/danmu/AGENTS.md)）

**手动验证**：
```bash
# 启动应用
python main.py
# 观察浮动面板是否为 pywebview 窗口（透明 + 无边框 + 置顶 + 鼠标穿透）
# 发送弹幕触发 _display_floating_panel_text
# 验证卡片在 pywebview 窗口内渲染

# 分批测试
python -m pytest tests/test_floating_panel_web_protocol.py tests/test_floating_panel_web_bridge.py tests/test_floating_panel_web_process.py -q -x
python scripts/boundary_guard.py
```

---

### 2.2 阶段 1 完成标准

| 标准 | 验证方法 |
|------|----------|
| pywebview 浮动面板窗口正常显示（透明 + 无边框 + 置顶 + 鼠标穿透） | 肉眼观察 + WindowFromPoint 验证 |
| 弹幕通过 WS 推送到页面并渲染 | 发送测试弹幕，观察卡片出现 |
| `FloatingPanelEngine` 底锚堆积算法保留 | 多条弹幕按底锚堆积，旧条上推 |
| WebView2 不可用时回退到 QPainter | 设置 `floating_panel_use_web=0` 后重启 |
| 子进程崩溃后自动重启（3 次） | 手动 kill 子进程，观察重启 |
| 打包后浮动面板资源存在 | PyInstaller onedir 中有 `web/static/floating_panel/` |
| 所有单测 PASS | 分批 `python -m pytest tests/test_floating_panel_web_*.py -q -x` |
| `boundary_guard.py` PASS | `python scripts/boundary_guard.py` |
| 文档已更新 | `main-pipeline-sequence.md` + `runtime-state-map.md` |

---

### 2.3 阶段 2：blivechat-dev Vue 组件移植与 1:1 视觉还原

**目标**：将 blivechat-dev 的 Vue 组件、CSS、字体、动画资源移植到 `web/static/floating_panel/`，实现 1:1 视觉还原。

**前置条件**：阶段 1 全部完成并通过验收。

#### 可复用的 blivechat-dev 资源

| 资源路径 | 用途 | 移植方式 |
|----------|------|----------|
| `frontend/src/components/ChatRenderer/TextMessage.vue` | 文本消息组件（含头像、用户名、内容、徽章、表情） | 改写为 Vue 3 SFC 或原生 JS 组件 |
| `frontend/src/components/ChatRenderer/AuthorChip.vue` | 用户名 + 类型徽章 | 同上 |
| `frontend/src/components/ChatRenderer/AuthorBadge.vue` | 房管/舰长徽章 | 同上 |
| `frontend/src/components/ChatRenderer/ImgShadow.vue` | 头像阴影 | 同上 |
| `frontend/src/components/ChatRenderer/PaidMessage.vue` | SC 付费消息（可选） | 同上 |
| `frontend/src/components/ChatRenderer/MembershipItem.vue` | 上舰消息（可选） | 同上 |
| `frontend/src/components/ChatRenderer/Ticker.vue` | SC 滚动条（可选） | 同上 |
| `frontend/src/components/ChatRenderer/index.vue` | ChatRenderer 主组件 | 改写为底锚堆积模式 |
| `frontend/src/components/ChatRenderer/constants.js` | 常量（CONTENT_PART_TYPE 等） | 直接复制 |
| `frontend/src/assets/css/youtube/yt-html.css` | YouTube 风格基础样式 | 直接复制 |
| `frontend/src/assets/css/youtube/yt-live-chat-renderer.css` | 聊天容器样式 | 直接复制 |
| `frontend/src/assets/css/youtube/yt-live-chat-item-list-renderer.css` | 消息列表样式 | 直接复制 |
| `frontend/src/assets/css/youtube/yt-live-chat-text-message-renderer.css` | 文本消息样式 | 直接复制 |
| `frontend/src/assets/css/youtube/yt-live-chat-author-chip.css` | 用户名样式 | 直接复制 |
| `frontend/src/assets/css/youtube/yt-live-chat-author-badge-renderer.css` | 徽章样式 | 直接复制 |
| `frontend/src/assets/css/youtube/yt-img-shadow.css` | 头像阴影样式 | 直接复制 |
| `frontend/src/assets/css/youtube/yt-live-chat-paid-message-renderer.css` | SC 样式（可选） | 直接复制 |
| `frontend/public/static/img/icons/guard-level-{1,2,3}.png` | 舰长徽章图标（可选） | 直接复制 |
| `frontend/public/static/img/emoticons/*.png` | B站表情图（可选） | 直接复制 |

#### 不可复用的 blivechat-dev 资源

| 资源路径 | 原因 |
|----------|------|
| `frontend/src/api/chat/ChatClient*.js` | blivechat-dev 的 B站 WS 客户端，我们用自己的 FastAPI WS |
| `frontend/src/api/chat/models.js` | blivechat-dev 的消息模型，我们用 `panel_protocol.py` |
| `frontend/src/views/StyleGenerator/*` | 样式生成器，我们用 `floating_panel_style.py` |
| `frontend/src/views/Room.vue` | 房间页面，我们只要 ChatRenderer |
| `frontend/src/layout/*` | 侧边栏布局，不需要 |
| `frontend/src/lang/*` | 多语言，浮动面板仅中文 |
| `frontend/src/utils/pronunciation/*` | 发音字典，与浮动面板无关 |
| `frontend/src/api/main.js` / `plugins.js` | blivechat-dev 主 API，不复制 |
| `backend/*` / `api/*` / `services/*` / `models/*` | blivechat-dev 后端，不复制 |

#### 关键改造：底锚堆积 vs 反向滚动

blivechat-dev 的「反向滚动」模式（`messageReverseScroll`）使用 CSS `rotate: 180deg` 实现（`frontend/src/views/StyleGenerator/common.js:169-179`）：
```css
yt-live-chat-item-list-renderer,
yt-live-chat-item-list-renderer #items > * {
  rotate: 180deg;
  backface-visibility: hidden;
}
```

DanmuAI 的「底锚堆积」模式（`FloatingPanelEngine._compute_targets_bottom_up`）语义不同：
- 新条从底部进入，旧条在新消息到达时整体上移
- 空闲静止，仅完全越顶后移除

**移植时必须**：
- 移除 `rotate: 180deg` 相关样式
- 改用 `#panel { display: flex; flex-direction: column-reverse; }`（原型已验证可行）
- 不使用 blivechat-dev 的 `messageReverseScroll` 配置项

#### 工单 2.1-2.4（建议拆分）

- 工单 2.1：移植 CSS 资源（`yt-*.css`）到 `web/static/floating_panel/assets/css/`
- 工单 2.2：移植 `TextMessage.vue` + `AuthorChip.vue` + `ImgShadow.vue` 为 Vue 3 SFC 或原生 JS
- 工单 2.3：移植图标资源（`guard-level-*.png`、`emoticons/*.png`）
- 工单 2.4：集成到 `index.html` + `app.js`，验证 1:1 视觉还原

---

### 2.4 阶段 3：生产加固

**目标**：补全异常处理、性能优化、多屏适配、长时间运行稳定性。

#### 工单 3.1-3.6（建议拆分）

- 工单 3.1：子进程崩溃检测 + 自动重启（3 次后回退 QPainter）
- 工单 3.2：WS 断线重连（页面侧指数退避）
- 工单 3.3：页面未就绪时缓冲区补推
- 工单 3.4：多屏混合 DPI 适配
- 工单 3.5：长时间运行内存监控（1 小时 + 高频弹幕）
- 工单 3.6：打包后双 pywebview 子进程稳定性验证

---

## 3. PyInstaller / Velopack / 静态资源收集注意事项

### 3.1 PyInstaller hiddenimports

[DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec) 的 `hiddenimports` 必须追加：

```python
hiddenimports = [
    # ... 已有的 ...
    'app.floating_panel_web',
    'app.floating_panel_web.panel_process',
    'app.floating_panel_web.panel_bridge',
    'app.floating_panel_web.panel_protocol',
]
```

**原因**：PyInstaller 静态分析无法识别 `multiprocessing.spawn` 子进程入口的动态导入。

### 3.2 PyInstaller datas

[DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec) 的 `datas` 必须追加：

```python
datas = [
    # ... 已有的 ...
    ('web/static/floating_panel', 'web/static/floating_panel'),
]
```

**注意**：
- 源路径相对于仓库根目录
- 目标路径在 onedir 产物中为 `<dist>/DanmuAI/web/static/floating_panel/`
- 打包后通过 `app/bundle_paths.py:project_root()` 解析绝对路径

### 3.3 Velopack

[scripts/velopack_pack.ps1](file:///e:/test/danmu/scripts/velopack_pack.ps1) **无需修改**：
- Velopack 直接打包 PyInstaller onedir 产物
- `web/static/floating_panel/` 已在 onedir 中，自动包含

[scripts/publish_windows_release.ps1](file:///e:/test/danmu/scripts/publish_windows_release.ps1) **无需修改**：
- 编排脚本不感知具体资源文件

### 3.4 静态资源加载路径

**开发环境**（`python main.py`）：
- FastAPI 通过 `app/web_console.py` 或 `app/web_console_runtime.py` 挂载 `web/static/` 为静态文件目录
- 浮动面板访问 `http://127.0.0.1:18765/floating_panel/index.html`

**打包环境**（PyInstaller onedir）：
- 通过 `app/bundle_paths.py:is_frozen()` 判断
- `project_root()` 返回 `<dist>/DanmuAI/` 或 `sys._MEIPASS`
- FastAPI 静态文件挂载路径需用 `project_root() / 'web' / 'static'`

**待实施阶段验证**：打包后 `http://127.0.0.1:18765/floating_panel/index.html` 能否正常访问。

### 3.5 WebView2 Runtime 缺失处理

打包后用户机器可能无 WebView2 Runtime。处理流程（复用 [app/webview_shell.py:422-441](file:///e:/test/danmu/app/webview_shell.py#L422-L441)）：

1. `PanelProcess.start()` 调用 `app.webview2_runtime.is_webview2_runtime_available()`
2. 若 False：
   - 弹托盘气泡：`notify_web_console_failure(..., "web_console.webview2_missing", install_url=WEBVIEW2_INSTALL_URL)`
   - 回退到 `FloatingPanelOverlay`（QPainter）
   - 记录日志 `reason=panel_webview2_missing`

**待实施阶段验证**：在无 WebView2 的干净 Win10 环境测试回退。

### 3.6 代码签名

代码签名由 Velopack `--signParams` 或 `--azureTrustedSignFile` 在 `vpk pack` 阶段处理，浮动面板无需额外配置。

---

## 4. 测试策略

### 4.1 单测（每批 `-q -x`，禁止全量）

```bash
# 阶段 1 完成后
python -m pytest tests/test_floating_panel_web_protocol.py -q -x
python -m pytest tests/test_floating_panel_web_bridge.py -q -x
python -m pytest tests/test_floating_panel_web_process.py -q -x

# 触达 Web API / DanmuApp 主链路时
python scripts/boundary_guard.py
```

### 4.2 集成测试

参考 [PYWEBVIEW_FLOATING_PANEL_TEST_PLAN.md](PYWEBVIEW_FLOATING_PANEL_TEST_PLAN.md) 执行：
- 单条与连续弹幕
- 高密度弹幕
- WS 断连重连
- 页面启动慢
- WebView2 不可用回退
- DPI 缩放（100%/125%/150%/200%）
- 多屏
- 置顶 + 鼠标穿透 + 焦点
- 正常退出 + 强制退出 + 子进程残留
- 打包后实际运行

### 4.3 原型测试入口

原型测试脚本保留在 `danmuai_external/prototype_floating_panel/`，可作为回归参考：
```bash
python -m prototype_floating_panel.run_prototype --mode test
```

---

## 5. 完成报告要求

每个工单完成后必须按 [AGENTS.md §6](file:///e:/test/danmu/AGENTS.md) 输出完成报告，至少包含：

1. 修改摘要
2. **修改的文件列表**（完整路径）
3. 未修改的关键区域（证明未越界）
4. 运行的命令
5. 构建/测试结果
6. 手动验证步骤与结果
7. 风险与注意事项
8. **发现但未处理的问题**（应已写入 [.local-ai/workorders/已知问题与后续事项.md](file:///e:/test/danmu/.local-ai/workorders/已知问题与后续事项.md)）
9. 已更新的文档（`main-pipeline-sequence.md` / `runtime-state-map.md`）
10. 建议下一个工单（可选，不擅自实现）

---

## 6. 引用文件索引

### 必读文档
- [AGENTS.md](file:///e:/test/danmu/AGENTS.md)
- [PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)
- [PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md](PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md)
- [PYWEBVIEW_FLOATING_PANEL_TEST_PLAN.md](PYWEBVIEW_FLOATING_PANEL_TEST_PLAN.md)

### 原型参考
- [prototype_floating_panel/panel.html](file:///e:/test/danmuai_external/prototype_floating_panel/panel.html)
- [prototype_floating_panel/panel_window.py](file:///e:/test/danmuai_external/prototype_floating_panel/panel_window.py)
- [prototype_floating_panel/run_prototype.py](file:///e:/test/danmuai_external/prototype_floating_panel/run_prototype.py)
- [prototype_floating_panel/win32_probe.py](file:///e:/test/danmuai_external/prototype_floating_panel/win32_probe.py)
- [prototype_floating_panel/TEST_RESULTS.md](file:///e:/test/danmuai_external/prototype_floating_panel/TEST_RESULTS.md)

### 生产代码（复用对象）
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

### 打包配置
- [DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)
- [scripts/build_exe.ps1](file:///e:/test/danmu/scripts/build_exe.ps1)
- [scripts/velopack_pack.ps1](file:///e:/test/danmu/scripts/velopack_pack.ps1)
- [scripts/publish_windows_release.ps1](file:///e:/test/danmu/scripts/publish_windows_release.ps1)
- [.github/workflows/ci.yml](file:///e:/test/danmu/.github/workflows/ci.yml)

### blivechat-dev 参考资源
- [可参考开源项目/blivechat-dev/frontend/src/components/ChatRenderer/](file:///e:/test/danmu/可参考开源项目/blivechat-dev/frontend/src/components/ChatRenderer/)
- [可参考开源项目/blivechat-dev/frontend/src/assets/css/youtube/](file:///e:/test/danmu/可参考开源项目/blivechat-dev/frontend/src/assets/css/youtube/)
- [可参考开源项目/blivechat-dev/frontend/public/static/img/](file:///e:/test/danmu/可参考开源项目/blivechat-dev/frontend/public/static/img/)
