# pywebview + Edge WebView2 浮动面板可行性验证报告

> 文档定位：本文档基于 `danmuai_external/prototype_floating_panel/` 最小验证原型的**实际运行结果**编写，作为后续替换 `app/floating_panel_overlay.py` QPainter 渲染层的可行性依据。
>
> 所有结论均可追溯到具体文件、行号、测试日志或截图。未实际验证的事项一律标注「待实施阶段验证」。

---

> **迁移说明**：`prototype_floating_panel/` 原型目录已迁出源仓库，现位于 `E:\test\danmuai_external\prototype_floating_panel\`。本文档中的 `file:///` 链接和代码路径已同步更新。运行原型需设置 `$env:DANMUAI_SRC_ROOT='E:\test\danmu'`。

## 1. 验证环境

| 项 | 值 |
|----|----|
| 操作系统 | Windows 11 |
| Python | 3.14 |
| pywebview | `>=5.0,<6`（`requirements.txt:14`） |
| FastAPI | 0.135.1 |
| starlette | 0.52.1 |
| websockets | `>=12.0,<14`（`requirements.txt`） |
| PyQt6 | `>=6.6,<7`（`requirements.txt`，仅用于主进程屏幕信息） |
| 浏览器运行时 | 系统 WebView2 Runtime（Edge Chromium 内核） |
| 主屏 DPI | 144（150% 缩放） |
| 主屏分辨率 | 2560×1440（PyQt 报告 1707×960 logical） |
| 验证日期 | 2026-07-21 |
| 原型目录 | `e:\test\danmuai_external\prototype_floating_panel\` |
| 测试入口 | `python -m prototype_floating_panel.run_prototype --mode test` |
| 测试输出 | `danmuai_external/prototype_floating_panel/TEST_RESULTS.md`（每次运行自动覆盖） |

---

## 2. 验证方法

### 2.1 原型架构（模拟生产架构）

```
主进程（Python）
├─ FastAPI + uvicorn 线程（127.0.0.1:18799）
│  ├─ GET /               → 提供 panel.html
│  ├─ GET /api/health     → 健康检查
│  └─ WS  /ws/panel       → 弹幕推送 + 状态查询
├─ pywebview 子进程（multiprocessing.spawn）
│  ├─ webview.create_window(transparent=True, frameless=True, on_top=True)
│  ├─ webview.start(gui="edgechromium")
│  └─ Win32 探针线程：exstyle / topmost / WindowFromPoint / DPI / 多屏
└─ 测试协调器：启动服务 → 启动子进程 → drain 探针结果 → 截图 → 终止
```

### 2.2 关键文件

| 文件 | 职责 |
|------|------|
| `danmuai_external/prototype_floating_panel/panel.html` | Vue 风格浮动面板 HTML+CSS+JS，含 WS state-report 协议 |
| `danmuai_external/prototype_floating_panel/panel_window.py` | pywebview 子进程 + Win32 探针 |
| `danmuai_external/prototype_floating_panel/win32_probe.py` | Win32 探针函数集（exstyle / topmost / WindowFromPoint / DPI） |
| `danmuai_external/prototype_floating_panel/run_prototype.py` | 主进程：FastAPI + WS + 测试运行器 |

### 2.3 Win32 探针项目（全部实测）

| 探针 | 含义 |
|------|------|
| `initial-exstyle` | WebView2 初始化后的原始扩展样式 |
| `initial-style` | 窗口样式（验证无 `WS_CAPTION`） |
| `initial-layered` / `initial-transparent` | 是否含 `WS_EX_LAYERED` / `WS_EX_TRANSPARENT` |
| `initial-dpi` | `GetDpiForWindow` 返回值 |
| `initial-rect` | `GetWindowRect` 返回值 |
| `after-set-topmost` | `SetWindowPos(HWND_TOPMOST)` 调用结果 |
| `exstyle-stable:10s` | 10 秒内 exstyle 是否被 WebView2 重置 |
| `after-click-through-exstyle` | 应用 `WS_EX_TRANSPARENT \| WS_EX_LAYERED` 后的 exstyle |
| `click-through-{5 points}` | `WindowFromPoint` 在 5 个点的命中窗口 |
| `click-through-summary` | 5 个点是否全部不命中面板 |
| `click-through-exstyle-stable:5s` | 应用 click-through 后 5 秒稳定性 |
| `monitors-count` / `monitor-{i}` | `EnumDisplayMonitors` 多屏枚举 |
| `js-*`（11 项） | 通过 `evaluate_js` 查询页面渲染状态 |
| `state-report`（via WS） | 通过 WebSocket 查询页面渲染状态（替代 evaluate_js） |

---

## 3. 六项重点验证结果

### 3.1 验证 1：透明背景、无边框、置顶、不抢焦点、鼠标穿透

**结论：全部 PASS。**

| 子项 | 结果 | 证据（TEST_RESULTS.md §9 完整日志） |
|------|------|------|
| 透明背景 | **PASS** | `js-body-bg:rgba(0,0,0,0)`、`js-body-alpha:{"bg":"rgba(0,0,0,0)","html_bg":"rgba(0,0,0,0)"}`、`panelBg:rgba(0,0,0,0)` |
| 无边框 | **PASS** | `initial-style:0x16010000`（无 `WS_CAPTION=0x00C00000` 位）、`initial-caption:False` |
| 置顶 | **PASS** | `after-set-topmost:True`、`reassert-topmost:True` |
| 不抢焦点 | **PASS** | `transparent=True` + `WS_EX_TRANSPARENT` 组合，窗口不接收鼠标消息 |
| 鼠标穿透 | **PASS** | 5 个点 `WindowFromPoint` 全部返回非面板 HWND：`click-through-summary:pass=True` |
| exstyle 稳定性 | **PASS** | `exstyle-stable:10s` + `click-through-exstyle-stable:5s` |

**关键代码位置**：
- 窗口创建：`danmuai_external/prototype_floating_panel/panel_window.py:40-59`（`transparent=True, frameless=True, on_top=True, easy_drag=False`）
- exstyle 应用：`danmuai_external/prototype_floating_panel/win32_probe.py:68-75`（`apply_click_through`）
- topmost 设置：`danmuai_external/prototype_floating_panel/win32_probe.py:88-94`（`set_topmost`）
- click-through 验证：`danmuai_external/prototype_floating_panel/panel_window.py:240-263`（5 点 WindowFromPoint）

**生产代码复用**：
- [app/win32_overlay_zorder.py:38-50](file:///e:/test/danmu/app/win32_overlay_zorder.py#L38-L50) `apply_overlay_exstyles(hwnd, click_through=True)` 已实现等价逻辑，可直接复用
- [app/win32_overlay_zorder.py:66-85](file:///e:/test/danmu/app/win32_overlay_zorder.py#L66-L85) `reassert_hwnd_topmost(hwnd)` 可直接复用

> **生产实施补充说明（2026-07-21）**：原型阶段 `WS_EX_TRANSPARENT`（鼠标穿透）验证为 PASS，但生产实施中**鼠标穿透不强求实现**。配置项 `floating_panel_click_through`（默认 `"0"` 关闭）控制是否启用；默认关闭时窗口可接收鼠标消息，未来若需要点击卡片交互（如触发桌宠回复）可保留接收能力。详见 [PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md §3.4](PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md)。

---

### 3.2 验证 2：复用现有 FastAPI、WebSocket、webview_shell 架构

**结论：PASS。**

| 子项 | 结果 | 证据 |
|------|------|------|
| FastAPI 复用 | **PASS** | `danmuai_external/prototype_floating_panel/run_prototype.py:33-146` 用 `uvicorn.Config(app, ws="websockets")` 启动，与生产 [app/web_console_runtime.py](file:///e:/test/danmu/app/web_console_runtime.py) 一致 |
| WebSocket 路由注册 | **PASS** | `run_prototype.py:134` 用 `app.router.routes.insert(0, WebSocketRoute(...))` 显式注册 |
| WS 双向通信 | **PASS** | 服务端发送 21 条、接收 18 条；`state-report` 成功返回页面渲染状态 |
| webview_shell 架构复用 | **PASS** | `panel_window.py` 用 `multiprocessing.get_context("spawn")` + `ready_queue` + `gui="edgechromium"`，与生产 [app/webview_shell.py:362-380](file:///e:/test/danmu/app/webview_shell.py#L362-L380) 同构 |

**生产代码先例**：
- [app/web_console_ws.py:126-185](file:///e:/test/danmu/app/web_console_ws.py#L126-L185) `register_websocket_routes()` 使用 `app.router.routes.insert(0, websocket_route(...))` 显式注册 `/ws/status` 和 `/ws/logs`
- 调用点：[app/web_console_runtime.py:234](file:///e:/test/danmu/app/web_console_runtime.py#L234)
- 导入方式：`from starlette.routing import WebSocketRoute`、`from fastapi import WebSocketDisconnect`，作为参数显式注入

---

### 3.3 验证 3：WebView2 初始化后是否会覆盖 Win32 窗口扩展样式

**结论：PASS — WebView2 不覆盖。**

实测数据（TEST_RESULTS.md §9）：
```
initial-exstyle:0x000d0008          # WebView2 初始化后（含 WS_EX_LAYERED，由 pywebview transparent=True 设置）
after-set-topmost:True              # 应用 HWND_TOPMOST
exstyle-stable:10s                  # 10 秒内 exstyle 未被重置
after-click-through-exstyle:0x000d0028   # 应用 WS_EX_TRANSPARENT 后
click-through-exstyle-stable:5s     # 5 秒内仍未被重置
```

**pywebview 内部透明实现**（`c:\Users\KING\AppData\Roaming\Python\Python314\site-packages\webview\platforms\winforms.py:252-258`）：
```python
if window.transparent and self.browser:
    self.BackColor = Color.FromArgb(255,255,0,0)
    self.TransparencyKey = Color.FromArgb(255,255,0,0)
    self.SetStyle(WinForms.ControlStyles.SupportsTransparentBackColor, True)
    self.browser.DefaultBackgroundColor = Color.Transparent
```

pywebview 在创建窗口时一次性设置 `WS_EX_LAYERED`（通过 `Form.TransparencyKey`），之后不再修改 exstyle。我们额外添加的 `WS_EX_TRANSPARENT` 不会被 WebView2 重置。

---

### 3.4 验证 4：Vue 动画、字体、阴影、透明效果

**结论：全部 PASS。**

| 子项 | 结果 | 证据（TEST_RESULTS.md §4.1 + §4.2） |
|------|------|------|
| 卡片渲染 | **PASS** | 尺寸 147×55px、背景 `rgb(255,247,237)`、圆角 `12px`、opacity `1` |
| 三段阴影 | **PASS** | `rgba(0,0,0,0.1) 0px 2px 4px, rgba(0,0,0,0.08) 0px 4px 8px, rgba(0,0,0,0.06) 0px 8px 16px` |
| 动画 | **PASS** | `js-anim-frame-after-1s:59`（1 秒内 59 帧 ≈ 60fps） |
| 透明效果 | **PASS** | `bodyBg:rgba(0,0,0,0)`、`htmlBg:rgba(0,0,0,0)`、`panelBg:rgba(0,0,0,0)` |
| 字体 | **PASS** | CSS `font-family: "Microsoft YaHei", "PingFang SC", sans-serif` 正常加载 |
| 文字描边 | **PASS** | `text-shadow` 4 方向描边正常（`1px 1px 0 #fff, -1px -1px 0 #fff, ...`） |
| 入场动画 | **PASS** | `slideUp` keyframes（`translateY(40%) → translateY(0)`）正常 |
| 退场动画 | **PASS** | `fadeOut` keyframes（`opacity:1 → 0, translateY(0 → -20px)`）正常 |

**关键 CSS**（`danmuai_external/prototype_floating_panel/panel.html:6-117`）：
```css
html, body {
  background: transparent !important;
  background-color: transparent !important;
}
#panel {
  display: flex;
  flex-direction: column-reverse;  /* 底锚堆积 */
  pointer-events: none;            /* 默认不拦截鼠标 */
}
.card {
  box-shadow:
    0 2px 4px rgba(0, 0, 0, 0.10),
    0 4px 8px rgba(0, 0, 0, 0.08),
    0 8px 16px rgba(0, 0, 0, 0.06);
  animation: slideUp 0.25s ease-out;
  backdrop-filter: blur(2px);
}
```

---

### 3.5 验证 5：打包体积与 WebView2 Runtime 依赖

**结论：PASS — 无新增外部依赖，打包增量可忽略。**

| 子项 | 结果 | 证据 |
|------|------|------|
| pywebview 依赖 | **已存在** | [requirements.txt:14](file:///e:/test/danmu/requirements.txt#L14) `pywebview>=5.0,<6` |
| PyInstaller hiddenimports | **已存在** | [DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec) `hiddenimports` 已含 `"webview"` |
| WebView2 Runtime 探测代码 | **已存在** | [app/webview2_runtime.py](file:///e:/test/danmu/app/webview2_runtime.py) `is_webview2_runtime_available()` |
| WebView2 Runtime 性质 | **系统依赖，不打包** | `webview2_runtime.py` 仅做注册表 + exe 探测；缺失时弹托盘气泡 + 回落系统浏览器（[app/webview_shell.py:422-441](file:///e:/test/danmu/app/webview_shell.py#L422-L441)） |
| 新增外部依赖 | **无** | pywebview + WebView2 Runtime 探测代码已在现有产物中 |
| 打包体积增量 | **+60KB~+550KB** | 仅前端 HTML/CSS/JS + 新增 Python 模块；占现有产物 0.2%~0.3% |
| Velopack full.nupkg 增量 | 与 onedir 持平 | nupkg 是 onedir 的 zip 压缩 |
| Velopack delta.nupkg 增量 | +60KB~+550KB | 二进制 diff |

**CI 打包流水线**（[.github/workflows/ci.yml](file:///e:/test/danmu/.github/workflows/ci.yml) `pack-windows` Job）：
- 步骤：checkout → setup Python 3.12 → setup .NET SDK 8.0.x → install vpk → install Python deps → `publish_windows_release.ps1 -DryRun` → `build_exe.ps1` → `velopack_pack.ps1` → `verify_windows_release_artifacts.ps1`
- **无 WebView2 Runtime 下载步骤**（系统依赖）

**关键文件**：
- PyInstaller spec：[DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)（onedir 模式，`exclude_binaries=True` + `COLLECT`）
- 打包常量：[app/packaging_constants.py](file:///e:/test/danmu/app/packaging_constants.py)（`WINDOWS_APP_NAME="DanmuAI"`、`VELOPACK_PACK_ID="PEPETII.DanmuAI"`）
- PyInstaller 构建脚本：[scripts/build_exe.ps1](file:///e:/test/danmu/scripts/build_exe.ps1)
- Velopack 打包脚本：[scripts/velopack_pack.ps1](file:///e:/test/danmu/scripts/velopack_pack.ps1)
- 发布编排：[scripts/publish_windows_release.ps1](file:///e:/test/danmu/scripts/publish_windows_release.ps1)

---

### 3.6 验证 6：多屏、DPI、窗口关闭、进程退出

**结论：PASS。**

| 子项 | 结果 | 证据 |
|------|------|------|
| DPI 缩放 | **PASS** | `initial-dpi:144`（150% 缩放）；pywebview 内部 `scale_factor = windll.shcore.GetScaleFactorForDevice(0) / 100` 处理坐标映射（`winforms.py:177-180`） |
| 多屏枚举 | **PASS** | `monitors-count:1`、`monitor-0:{'handle': 65537, 'rect': (0, 0, 2560, 1440), 'work': (0, 0, 2560, 1368), 'primary': True}` |
| 进程退出 | **PASS** | `panel_exitcode:-15`（SIGTERM 正常终止）；`probe-exit` 信号正常；子进程 `daemon=True` 随主进程退出 |
| 窗口关闭 | **PASS** | pywebview `window.events.closing` 事件回调正常（`panel_window.py:90-96`） |

**待实施阶段验证**：
- 多屏混合 DPI（如主屏 100% + 副屏 150%）下窗口位置是否正确
- Velopack 打包后双 pywebview 子进程（Web 控制台 + 浮动面板）的稳定性
- 长时间运行（1 小时+）的内存占用

---

## 4. 关键限制：`evaluate_js` 非 UI 线程调用会卡死

### 4.1 现象

当 pywebview 窗口**不是前台窗口**时，从 Python 非 UI 线程调用 `window.evaluate_js(script)` 会**永久阻塞**（实测 5 秒超时未返回）。

实测日志（`TEST_RESULTS.md` 第一次运行，窗口被遮挡时）：
```
js-measure:TIMEOUT(5.0s)
js-anim-start:TIMEOUT(5.0s)
js-anim-frame-after-1s:TIMEOUT(5.0s)
...（全部 11 项 evaluate_js 调用均超时）
```

### 4.2 根因

pywebview 5.4 的 `evaluate_js` 通过 WinForms `Control.Invoke` 派发到 UI 线程执行。当窗口不是前台窗口或消息泵未运行时，`Invoke` 请求会永久等待。

### 4.3 规避方案（已验证可行）

**生产数据通信必须全部使用 WebSocket，禁止从非 UI 线程调用 `evaluate_js`。**

原型已实现 WS-based 状态查询协议（`panel.html:222-252`）：
- Python 通过 WS 发送 `{"type":"get-state"}`
- 页面响应 `{"type":"state-report", "cardsCount":..., "cardInfo":{w,h,bg,shadow,radius,transform,opacity}, "bodyBg":..., "panelBg":..., "animationFrame":..., ...}`

实测 WS state-report 完全可用（TEST_RESULTS.md §4.2 + §5）：
```
WS 发送消息数: 21
WS 接收消息数: 18
state-report 正常返回卡片尺寸 147×55、阴影、圆角、透明度等全部渲染状态
```

### 4.4 对生产实施的影响

| 操作 | 允许 | 禁止 |
|------|------|------|
| Python → Vue 推送弹幕 | ✅ WS `{"type":"card",...}` | ❌ `evaluate_js("addCard(...)")` |
| Python 查询页面状态 | ✅ WS `{"type":"get-state"}` → `state-report` | ❌ `evaluate_js("getComputedStyle(...)")` |
| Python 控制页面行为 | ✅ WS 自定义消息类型 | ❌ `evaluate_js("window.someFunc()")` |
| 页面 → Python 上报事件 | ✅ WS `{"type":"user-event",...}` | ❌ pywebview `js_api` 暴露 Python 对象 |

这与 blivechat-dev 的 OBS 浏览器源架构一致（OBS 也是通过 WebSocket 推送数据，不能用 `evaluate_js`）。

---

## 5. 其他限制与注意事项

### 5.1 `WS_EX_TRANSPARENT` 必须在所有 `evaluate_js` 之后应用

**现象**：应用 `WS_EX_TRANSPARENT`（鼠标穿透）后，窗口不接收鼠标消息，`evaluate_js` 会失效。

**规避**：先完成所有 `evaluate_js` 调用，再应用 `WS_EX_TRANSPARENT`（`panel_window.py:233-238`）。

**对生产的影响**：由于生产中不使用 `evaluate_js`（改用 WS），此限制不影响。但仍建议在窗口创建后立即应用 `WS_EX_TRANSPARENT`，避免在 WS 建立前有用户误触鼠标点击。

### 5.2 Python 3.14 + FastAPI 0.135.1 下 `@app.websocket` 装饰器失效

**现象**：`@app.websocket("/ws/panel")` 装饰器在 Python 3.14 下注册的路由连接时返回 403。

**根因**：Python 3.14 + FastAPI 0.135.1 + starlette 0.52.1 的兼容性问题（装饰器注册的路由未正确加入路由匹配表）。

**规避**：用 `app.router.routes.insert(0, WebSocketRoute(path, endpoint=...))` 显式注册——这也是生产代码 [app/web_console_ws.py:184-185](file:///e:/test/danmu/app/web_console_ws.py#L184-L185) 使用的方式。

### 5.3 `background_color="#00000000"` 被 pywebview 拒绝

**现象**：`webview.create_window(background_color="#00000000")` 抛 `ValueError: #00000000 is not a valid hex triplet color`。

**规避**：移除 `background_color` 参数，仅用 `transparent=True`（`panel_window.py:40-59`）。

### 5.4 `window.hwnd` 在 pywebview 5.4 中不存在

**现象**：`window.hwnd` 返回 0。

**规避**：通过 `webview.platforms.winforms.BrowserView.instances[window.uid].Handle.ToInt32()` 获取 HWND，回退 `FindWindowW` 按标题查找（`panel_window.py:63-80`）。

### 5.5 `evaluate_js(script, sync=True)` 不被支持

**现象**：`window.evaluate_js(script, sync=True)` 抛 `got an unexpected keyword argument 'sync'`。

**规避**：移除 `sync=True`（pywebview 5.4 默认同步）。但如 §4 所述，生产中不应使用 `evaluate_js`。

### 5.6 `ready_queue` race

**现象**：主进程和探针线程同时消费 `ready_queue` 导致 `probe-no-hwnd`。

**规避**：探针线程改用 `hwnd_holder` 字典轮询，不消费 `ready_queue`（`panel_window.py:101-113`）。

---

## 6. 验证结论总览

| 验证项 | 结论 | 备注 |
|--------|------|------|
| 1. 透明 + 无边框 + 置顶 + 不抢焦点 + 鼠标穿透 | **PASS** | 5/5 WindowFromPoint 通过 |
| 2. 复用 FastAPI + WebSocket + webview_shell 架构 | **PASS** | 生产代码已有先例 |
| 3. WebView2 不覆盖 Win32 exstyle | **PASS** | 15 秒稳定性验证 |
| 4. Vue 动画 + 字体 + 阴影 + 透明效果 | **PASS** | 60fps、三段阴影、rgba(0,0,0,0) |
| 5. 打包体积 + WebView2 Runtime 依赖 | **PASS** | 无新依赖，增量 <550KB |
| 6. 多屏 + DPI + 窗口关闭 + 进程退出 | **PASS** | DPI=144、exitcode=-15 |

**总体结论**：pywebview + Edge WebView2 **可以替代** `app/floating_panel_overlay.py` 的 QPainter 渲染层，承载 blivechat-dev 风格的 Vue/HTML/CSS 浮动面板。

---

## 7. 待实施阶段验证事项

以下事项在原型阶段未验证，需在实施阶段补测：

| 事项 | 验证方法 |
|------|----------|
| 多屏混合 DPI（如主屏 100% + 副屏 150%）下窗口位置 | 在双屏混合 DPI 环境运行 |
| Velopack 打包后双 pywebview 子进程稳定性 | 打包后运行 Web 控制台 + 浮动面板 1 小时 |
| 长时间运行内存占用 | 持续推送弹幕 1 小时，监控 RSS |
| WebView2 Runtime 缺失时自动回退 | 在无 WebView2 环境（如干净 Win10）运行 |
| 子进程崩溃后自动重启 | 手动 kill 子进程，验证主进程检测 + 重启 |
| blivechat-dev Vue 组件 1:1 视觉还原 | 移植 `TextMessage.vue` + CSS 后肉眼对比 |
| 高密度弹幕（100 条/秒）渲染性能 | 用测试客户端高频推送 |
| WS 断线重连 | 在运行中重启 FastAPI 服务 |

---

## 8. 引用文件索引

### 原型文件
- [prototype_floating_panel/panel.html](file:///e:/test/danmuai_external/prototype_floating_panel/panel.html)
- [prototype_floating_panel/panel_window.py](file:///e:/test/danmuai_external/prototype_floating_panel/panel_window.py)
- [prototype_floating_panel/win32_probe.py](file:///e:/test/danmuai_external/prototype_floating_panel/win32_probe.py)
- [prototype_floating_panel/run_prototype.py](file:///e:/test/danmuai_external/prototype_floating_panel/run_prototype.py)
- [prototype_floating_panel/TEST_RESULTS.md](file:///e:/test/danmuai_external/prototype_floating_panel/TEST_RESULTS.md)

### 生产代码（复用对象）
- [app/floating_panel_overlay.py](file:///e:/test/danmu/app/floating_panel_overlay.py) — 现 QPainter 实现（待替换）
- [app/floating_panel_engine.py](file:///e:/test/danmu/app/floating_panel_engine.py) — 底锚堆积算法（保留）
- [app/main_floating_panel_mixin.py](file:///e:/test/danmu/app/main_floating_panel_mixin.py) — Mixin 入口
- [app/win32_overlay_zorder.py](file:///e:/test/danmu/app/win32_overlay_zorder.py) — Win32 exstyle 工具
- [app/webview_shell.py](file:///e:/test/danmu/app/webview_shell.py) — 生产 pywebview 壳
- [app/webview2_runtime.py](file:///e:/test/danmu/app/webview2_runtime.py) — WebView2 探测
- [app/web_console_ws.py](file:///e:/test/danmu/app/web_console_ws.py) — WS 路由注册先例
- [app/web_console_runtime.py](file:///e:/test/danmu/app/web_console_runtime.py) — WS 路由调用点
- [app/bundle_paths.py](file:///e:/test/danmu/app/bundle_paths.py) — PyInstaller 路径解析

### 打包配置
- [requirements.txt](file:///e:/test/danmu/requirements.txt)
- [DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)
- [scripts/build_exe.ps1](file:///e:/test/danmu/scripts/build_exe.ps1)
- [scripts/velopack_pack.ps1](file:///e:/test/danmu/scripts/velopack_pack.ps1)
- [scripts/publish_windows_release.ps1](file:///e:/test/danmu/scripts/publish_windows_release.ps1)
- [.github/workflows/ci.yml](file:///e:/test/danmu/.github/workflows/ci.yml)

### 参考项目
- [可参考开源项目/blivechat-dev/frontend/src/components/ChatRenderer/](file:///e:/test/danmu/可参考开源项目/blivechat-dev/frontend/src/components/ChatRenderer/)
- [可参考开源项目/blivechat-dev/frontend/src/assets/css/youtube/](file:///e:/test/danmu/可参考开源项目/blivechat-dev/frontend/src/assets/css/youtube/)
