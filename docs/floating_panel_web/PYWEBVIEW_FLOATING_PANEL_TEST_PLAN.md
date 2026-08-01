# pywebview 浮动面板测试计划

> 文档定位：本文档为「pywebview + Edge WebView2 替换 `app/floating_panel_overlay.py` QPainter 渲染层」的**完整测试计划**，覆盖单测、集成测试与手动验证。
>
> **实施前必读**：
> - [PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)（可行性结论）
> - [PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md](PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md)（架构与协议）
> - [PYWEBVIEW_FLOATING_PANEL_IMPLEMENTATION_GUIDE.md](PYWEBVIEW_FLOATING_PANEL_IMPLEMENTATION_GUIDE.md)（实施步骤）
>
> **硬性约束**：
> - 测试不得引入 QWebEngineView、Electron 或新的浏览器运行时
> - 测试不得从非 UI 线程调用 `evaluate_js`（生产禁用，测试也禁用，避免误用）
> - 鼠标穿透相关测试**标注为可选**（不强求实现，对应配置项 `floating_panel_click_through`）
> - IDE Agent 本地测试必须遵守 [AGENTS.md §A.4.1](file:///e:/test/danmu/AGENTS.md)：分批 `-q -x`，**禁止全量 pytest**
> - 集成测试需要真实 WebView2 Runtime 环境，无 WebView2 时跳过并记录

---

> **迁移说明**：`prototype_floating_panel/` 原型目录已迁出源仓库，现位于 `E:\test\danmuai_external\prototype_floating_panel\`。本文档中的 `file:///` 链接和代码路径已同步更新。运行原型需设置 `$env:DANMUAI_SRC_ROOT='E:\test\danmu'`。

## 0. 关键修改说明（与测试相关）

| # | 项目 | 测试关注点 |
|---|------|------------|
| 1 | **从下到上（底锚堆积）模式** | 验证新条从底部进入、旧条上推；CSS 必须用 `flex-direction: column-reverse` 而非 `rotate: 180deg`；通过 `state-report.cardInfo.transform` 应为 `"none"`（不应出现 `matrix(-1, 0, 0, -1, ...)`） |
| 2 | **鼠标穿透（click-through）** | 默认 `floating_panel_click_through="0"`（关闭），窗口**应能接收鼠标**；启用 `floating_panel_click_through="1"` 后用 `WindowFromPoint` 5 点验证穿透；此项**可选**，未实现时跳过相关测试 |

---

## 1. 测试分类与执行策略

### 1.1 测试分类

| 类型 | 执行者 | 频率 | 备注 |
|------|--------|------|------|
| 单测（unit tests） | IDE Agent / CI | 每工单 | 分批 `-q -x`；测试文件 `tests/test_floating_panel_web_*.py` |
| 集成测试（手动） | 维护者 | 阶段完成 | 需要真实 WebView2 Runtime + 显示器 |
| 打包验证 | 维护者 | 发版前 | 需要完整 PyInstaller + Velopack 打包流程 |
| 长时间运行 | 维护者 | 阶段 3 完成 | 1 小时+ 高频弹幕推送 |

### 1.2 IDE Agent 分批测试（强制）

```bash
# 阶段 1 完成后，分批执行（每批 -q -x，失败即停）
python -m pytest tests/test_floating_panel_web_protocol.py -q -x
python -m pytest tests/test_floating_panel_web_bridge.py -q -x
python -m pytest tests/test_floating_panel_web_process.py -q -x

# 触达 Web API / DanmuApp 主链路时另跑
python scripts/boundary_guard.py
```

**禁止**：`pytest` / `pytest tests` / `python -m pytest tests/`（全量 700+ 用例会卡死 Windows 开发机，见 [AGENTS.md §7](file:///e:/test/danmu/AGENTS.md)）。

### 1.3 CI 全量（IDE Agent 禁止自动执行）

```bash
python -m pytest tests/ -q
```

---

## 2. 单元测试（阶段 1 必须完成）

### 2.1 `tests/test_floating_panel_web_protocol.py`

**目标**：验证 `app/floating_panel_web/panel_protocol.py` 的消息类型与字段契约。

| 用例 | 验证内容 |
|------|----------|
| `test_card_message_fields` | `card` 消息含 `type/id/username/content/persona_id/style/timestamp` 必填字段 |
| `test_config_message_fields` | `config` 消息含 `max_cards/stack_gap/panel_padding/entry_duration_ms/exit_duration_ms/panel_position/panel_width/panel_height` |
| `test_clear_message_reason_enum` | `clear.reason` 仅允许 `config_changed/user_action/scene_reset` |
| `test_ping_pong_timestamp` | `ping.t` 与 `pong.t` 类型一致（float 或 int） |
| `test_state_report_required_fields` | `state-report` 含 `cardsCount/cardInfo/bodyBg/htmlBg/panelBg/animationFrame/wsReceived/wsOpen/timestamp` |
| `test_auth_message_format` | `auth.token` 为字符串，非空 |
| `test_user_event_optional_fields` | `user-event.cardId` 可选，`event` 必填 |
| `test_error_message_stack_optional` | `error.stack` 可选，`message` 必填 |
| `test_reload_message_no_payload` | `reload` 消息无额外字段 |

**通过标准**：所有用例 PASS。

### 2.2 `tests/test_floating_panel_web_bridge.py`

**目标**：验证 `PanelBridge` 的缓冲区与 threadsafe 入队逻辑。

| 用例 | 验证内容 |
|------|----------|
| `test_enqueue_card_no_consumer_writes_buffer` | 无消费者时 `enqueue_card` 写入 `_backfill_buffer` |
| `test_enqueue_card_with_consumer_calls_soon_threadsafe` | 有消费者时调用 `loop.call_soon_threadsafe` |
| `test_buffer_maxlen_50` | 缓冲区满 50 条后丢弃最旧 |
| `test_register_consumer_flushes_buffer` | `register_panel_consumer` 后自动把缓冲区内容补推到新队列 |
| `test_unregister_consumer_removes_queue` | `unregister_panel_consumer` 从 `_ws_queues` 移除 |
| `test_shutdown_clears_buffer_and_queues` | `shutdown` 后缓冲区为空、队列为空 |
| `test_thread_safety_concurrent_enqueue` | 多线程并发 `enqueue_card` 不崩溃、不丢失（队列容量内） |

**通过标准**：所有用例 PASS。

### 2.3 `tests/test_floating_panel_web_process.py`

**目标**：验证 `PanelProcess` 的启动/终止/重启逻辑（mock webview，不实际启动窗口）。

| 用例 | 验证内容 |
|------|----------|
| `test_start_receives_loaded_signal` | mock 子进程 `ready_queue.put("loaded")` 后 `start()` 返回 True |
| `test_start_timeout_25s` | 25s 未收到 `loaded` 信号后 `start()` 返回 False 并记录日志 |
| `test_stop_terminates_process` | `stop()` 后 `is_alive() == False` |
| `test_stop_kill_after_terminate_timeout` | `terminate` 后 `join(timeout=3.0)` 仍存活，调用 `kill` |
| `test_restart_resets_restart_count` | `restart()` 成功后 `_restart_count` 归零 |
| `test_webview2_unavailable_returns_false` | mock `is_webview2_runtime_available()` 返回 False 时 `start()` 返回 False |
| `test_max_restarts_reached_falls_back` | 连续 3 次启动失败后 `_fallback_to_qpainter_called = True` |
| `test_click_through_disabled_by_default` | 默认 `floating_panel_click_through="0"`，调用 `apply_overlay_exstyles` 时 `click_through=False` |
| `test_click_through_enabled_when_config_on` | `floating_panel_click_through="1"` 时 `click_through=True`（可选测试，未实现时跳过） |

**通过标准**：除 `test_click_through_enabled_when_config_on`（标记 `@pytest.mark.skip(reason="可选功能")`）外，所有用例 PASS。

---

## 3. 集成测试（阶段 1 完成后手动执行）

### 3.1 单条与连续弹幕

**前置条件**：`python main.py` 已启动，浮动面板以 pywebview 窗口显示。

**测试步骤**：
1. 通过 Web 控制台「AI 管家」对话框触发 1 条弹幕
2. 观察浮动面板：1 张卡片从底部进入，位置贴底
3. 通过 WS 测试客户端发送 `{"type":"card","id":"test-1","username":"测试","content":"第一条","style":{...},"timestamp":...}`
4. 观察卡片渲染
5. 间隔 1s 连续发送 5 条不同 `id` 的卡片
6. 观察卡片按底锚堆积（最新贴底，旧条上推）

**通过标准**：
- 单条卡片正常渲染（有圆角、阴影、用户名、内容）
- 连续 5 条卡片按底锚堆积排列，无重叠、无溢出
- 卡片入场动画正常（`slideUp 0.25s`）
- 旧条上推动画平滑（无跳跃）

**验证点**：
- 通过 WS `get-state` 请求，页面返回 `state-report.cardsCount == 5`
- `state-report.cardInfo.transform == "none"`（确认未使用 `rotate: 180deg`）

### 3.2 高密度弹幕

**测试步骤**：
1. 用 Python `websockets` 客户端连接 `ws://127.0.0.1:18765/ws/panel?ws_token=<token>`
2. 鉴权后以 100 条/秒速率发送 `card` 消息，持续 10 秒（共 1000 条）
3. 观察浮动面板渲染

**通过标准**：
- 浮动面板不崩溃、不卡死
- 卡片数量受 `floating_panel_max_cards`（默认 6）限制，超过部分被移除
- 浏览器进程内存增长 < 100MB（10 秒内）
- WS 不阻塞、不丢连接

**待实施阶段验证**：100 条/秒是否为合理上限（取决于实际弹幕频率）。

### 3.3 长时间运行（阶段 3）

**测试步骤**：
1. 启动 `python main.py`
2. 通过测试客户端以 10 条/秒速率持续推送 `card` 消息，持续 1 小时（共 36000 条）
3. 每 10 分钟记录：
   - 主进程 RSS（`tasklist /fi "imagename eq python.exe"`）
   - pywebview 子进程 RSS
   - 浏览器进程 RSS（msedgewebview2.exe）
   - WS 消息延迟（`ping-pong` 往返时间）

**通过标准**：
- 1 小时后子进程 RSS 增长 < 200MB（无内存泄漏）
- WS 消息延迟 < 500ms
- 无崩溃、无 WS 断连（偶发断连后能自动重连）

**待实施阶段验证**：36000 条是否覆盖最坏场景。

---

## 4. WebSocket 断连重连

### 4.1 服务端主动断开

**测试步骤**：
1. 启动 `python main.py`，浮动面板正常显示
2. 在 Python 控制台执行 `danmu_app._panel_bridge._ws_panel_queues[0].put_nowait({"type":"clear"})` 后强制关闭 WS（或重启 FastAPI 服务）
3. 观察浮动面板 JS 控制台（通过 `state-report.error` 上报）
4. 等待页面自动重连（指数退避 1s → 30s）

**通过标准**：
- 页面 `ws.onclose` 触发，`status` 显示 `ws-closed:<code>`
- 重连尝试次数递增，间隔按 1s → 2s → 4s → 8s → 16s → 30s 递增
- 重连成功后 `status` 显示 `ws-open`，`reconnectAttempts` 归零
- 重连成功后能继续接收新 `card` 消息

### 4.2 页面崩溃

**测试步骤**：
1. 启动 `python main.py`，浮动面板正常显示
2. 通过 `taskkill /f /im msedgewebview2.exe`（仅 kill 浮动面板的 WebView2 进程，不影响 Web 控制台）

   > 注意：`msedgewebview2.exe` 可能有多个实例，需用 `tasklist /v` 找到浮动面板对应的 PID
3. 观察主进程 `PanelProcess._check_child_alive` 是否检测到子进程退出
4. 等待自动重启

**通过标准**：
- 主进程日志输出 `panel subprocess died: exitcode=<N>`
- 自动重启（`restart_count` 递增）
- 重启后浮动面板重新显示
- 连续 3 次崩溃后回退到 QPainter

### 4.3 重连后缓冲区补推

**测试步骤**：
1. 启动 `python main.py`，浮动面板正常显示
2. 强制断开 WS（同 4.1）
3. 在断开期间通过 Web 控制台发送 3 条弹幕（写入 `_backfill_buffer`）
4. 等待页面重连
5. 观察重连后是否补推 3 条卡片

**通过标准**：
- 重连后浮动面板出现断开期间的 3 条卡片
- 卡片顺序与发送顺序一致
- `_backfill_buffer` 清空（通过 `state-report` 或日志验证）

---

## 5. 页面启动慢与页面未就绪

### 5.1 模拟 WebView2 冷启动

**测试步骤**：
1. 修改 `app/floating_panel_web/panel_process.py`（或用环境变量）模拟 `loaded` 信号延迟 15s
2. 启动 `python main.py`
3. 在 0~15s 内通过 Web 控制台发送 5 条弹幕
4. 15s 后浮动面板显示

**通过标准**：
- 0~15s 内 `_backfill_buffer` 累积 5 条卡片（日志可见）
- 15s 后浮动面板出现 5 条补推卡片
- 缓冲区不溢出（`maxlen=50`）
- 主进程不阻塞

### 5.2 启动超时回退

**测试步骤**：
1. 修改 `app/floating_panel_web/panel_process.py`（或用环境变量）模拟 `loaded` 信号永不返回
2. 等待 25s（`_LOAD_TIMEOUT_SEC`）
3. 观察是否回退到 QPainter

**通过标准**：
- 25s 后日志输出 `panel start timeout, falling back to QPainter`
- 浮动面板以 `FloatingPanelOverlay`（QPainter）显示
- 后续弹幕通过 QPainter 渲染

---

## 6. WebView2 不可用时自动回退

### 6.1 模拟 WebView2 缺失

**测试步骤**：
1. 临时重命名注册表项 `HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`（或用 mock）
2. 启动 `python main.py`
3. 观察是否回退到 QPainter

**通过标准**：
- `is_webview2_runtime_available()` 返回 False
- 托盘气泡提示「WebView2 Runtime 缺失」
- 浮动面板以 `FloatingPanelOverlay`（QPainter）显示
- 日志记录 `reason=panel_webview2_missing`

**待实施阶段验证**：在干净 Win10 环境（无 WebView2 Runtime）实测。

---

## 7. DPI 缩放测试

### 7.1 100% 缩放（96 DPI）

**测试步骤**：
1. Windows 设置 → 显示 → 缩放设为 100%
2. 启动 `python main.py`
3. 通过 `state-report` 获取 `cardInfo.w/h`

**通过标准**：
- `initial-dpi == 96`
- 卡片尺寸与设计稿一致（如 280×60）
- 文字清晰、不模糊

### 7.2 125% 缩放（120 DPI）

**测试步骤**：
1. Windows 设置 → 显示 → 缩放设为 125%
2. 启动 `python main.py`
3. 通过 `state-report` 获取 `cardInfo.w/h`

**通过标准**：
- `initial-dpi == 120`
- 卡片尺寸按比例放大（如 350×75）
- 文字清晰、不模糊

### 7.3 150% 缩放（144 DPI）

**测试步骤**：
1. Windows 设置 → 显示 → 缩放设为 150%（原型已验证）
2. 启动 `python main.py`

**通过标准**：
- `initial-dpi == 144`
- 卡片尺寸按比例放大（如 420×90）
- 文字清晰、不模糊

### 7.4 200% 缩放（192 DPI）

**测试步骤**：
1. Windows 设置 → 显示 → 缩放设为 200%
2. 启动 `python main.py`

**通过标准**：
- `initial-dpi == 192`
- 卡片尺寸按比例放大（如 560×120）
- 文字清晰、不模糊

**待实施阶段验证**：200% 缩放下 WebView2 是否会启用高 DPI 渲染优化（影响内存）。

---

## 8. 多屏测试

### 8.1 单屏（基线）

**测试步骤**：
1. 仅启用主屏
2. 启动 `python main.py`
3. 通过 `state-report` 验证 `monitors-count == 1`

**通过标准**：浮动面板显示在主屏，位置正确（`floating_panel_position` 指定）。

### 8.2 双屏同 DPI

**测试步骤**：
1. 启用主屏 + 副屏，DPI 均为 144（150%）
2. 启动 `python main.py`
3. 修改 `screen_index` 配置为 0、1，分别测试

**通过标准**：
- `monitors-count == 2`
- 浮动面板按 `screen_index` 显示在对应屏幕
- 切换 `screen_index` 后位置正确

### 8.3 双屏混合 DPI（待实施阶段验证）

**测试步骤**：
1. 主屏 100%（96 DPI）+ 副屏 150%（144 DPI）
2. 启动 `python main.py`，浮动面板设在副屏
3. 将浮动面板移到主屏（或修改 `screen_index`）

**通过标准**：
- 浮动面板在两屏间切换时不变形
- DPI 变化时文字清晰
- 卡片尺寸按当前屏幕 DPI 缩放

**待实施阶段验证**：pywebview + WebView2 在混合 DPI 下的行为（是否需要重启子进程）。

---

## 9. 置顶与焦点测试

### 9.1 置顶（必测）

**测试步骤**：
1. 启动 `python main.py`，浮动面板正常显示
2. 打开其他全屏窗口（如浏览器全屏、视频播放器全屏）
3. 观察浮动面板是否仍可见

**通过标准**：
- 浮动面板始终在其他窗口之上
- `reassert_hwnd_topmost` 周期性调用（防被覆盖）

### 9.2 不抢焦点（必测）

**测试步骤**：
1. 启动 `python main.py`
2. 在 Web 控制台输入框聚焦时，触发浮动面板显示
3. 观察焦点是否仍留在输入框

**通过标准**：
- 浮动面板显示时不抢焦点
- 输入框光标不丢失
- 键盘输入仍进入输入框

### 9.3 鼠标穿透（可选，不强求）

> **此测试为可选项**。仅当 `floating_panel_click_through="1"` 时执行；默认 `"0"` 关闭时跳过。

**测试步骤**：
1. 配置 `floating_panel_click_through="1"`，重启 `python main.py`
2. 在浮动面板下方放置一个可点击窗口（如记事本）
3. 用鼠标点击浮动面板覆盖区域
4. 用 Win32 `WindowFromPoint` 工具（参考 `danmuai_external/prototype_floating_panel/win32_probe.py:155-205`）在 5 个点验证命中窗口

**通过标准**：
- 5 个点的 `WindowFromPoint` 全部返回非浮动面板 HWND
- 记事本接收鼠标点击（光标定位）

**未实现时跳过**：若 `floating_panel_click_through` 配置项或 `WS_EX_TRANSPARENT` 未实现，标记为 `@pytest.mark.skip`，不影响整体通过。

---

## 10. 退出测试

### 10.1 正常退出

**测试步骤**：
1. 启动 `python main.py`
2. 通过托盘菜单退出
3. 观察子进程退出

**通过标准**：
- `DanmuApp.quit()` 调用 `PanelProcess.stop()`
- `proc.terminate()` + `proc.join(timeout=3.0)`
- 若仍存活，`proc.kill()` + `proc.join(timeout=1.0)`
- `PanelBridge.shutdown()` 清空缓冲区
- 主进程退出后无残留 `msedgewebview2.exe`（与浮动面板对应的 PID）

### 10.2 强制退出主进程

**测试步骤**：
1. 启动 `python main.py`
2. 在任务管理器中 `taskkill /f /pid <主进程PID>`
3. 观察子进程

**通过标准**：
- 主进程被 kill 后，子进程（daemon=True）随之退出
- 无残留 `msedgewebview2.exe`

### 10.3 子进程残留检测

**测试步骤**：
1. 启动 `python main.py`
2. 强制 kill 主进程（同 10.2）
3. 用 `tasklist /fi "imagename eq msedgewebview2.exe"` 检查残留

**通过标准**：
- 5 秒内所有浮动面板相关的 `msedgewebview2.exe` 退出
- 若有残留，下一个 `python main.py` 启动时 `SingleInstanceGuard`（[app/single_instance.py](file:///e:/test/danmu/app/single_instance.py)）应检测并退出

**待实施阶段验证**：`SingleInstanceGuard` 是否能识别浮动面板子进程残留。

---

## 11. 打包后实际运行验证

### 11.1 PyInstaller onedir 验证

**测试步骤**：
1. 执行 `scripts/build_exe.ps1`
2. 检查 `<dist>/DanmuAI/web/static/floating_panel/` 是否存在
3. 检查 `<dist>/DanmuAI/web/static/floating_panel/index.html`、`app.js`、`style.css` 是否齐全
4. 启动 `<dist>/DanmuAI/DanmuAI.exe`
5. 观察浮动面板是否以 pywebview 窗口显示

**通过标准**：
- 静态资源全部打包到 onedir
- `DanmuAI.exe` 启动后浮动面板正常
- 无 `FileNotFoundError`（静态资源路径解析正确，参考 [app/bundle_paths.py](file:///e:/test/danmu/app/bundle_paths.py)）

### 11.2 Velopack 打包验证

**测试步骤**：
1. 执行 `scripts/velopack_pack.ps1`
2. 检查 `full.nupkg` 大小增量（应 < 1MB）
3. 安装 `Setup.exe`
4. 启动应用

**通过标准**：
- `full.nupkg` 增量与预期一致（+60KB~+550KB）
- 安装后应用正常启动
- 浮动面板正常显示

### 11.3 Delta 更新验证

**测试步骤**：
1. 安装旧版本（无浮动面板 web 资源）
2. 用 `vpk update` 应用 delta.nupkg
3. 启动应用

**通过标准**：
- Delta 更新成功
- 更新后浮动面板资源齐全
- 浮动面板正常显示

### 11.4 双 pywebview 子进程稳定性

**测试步骤**：
1. 启动打包后的 `DanmuAI.exe`
2. Web 控制台（pywebview 子进程 1）+ 浮动面板（pywebview 子进程 2）同时运行
3. 持续运行 1 小时，每 10 分钟记录两子进程 RSS

**通过标准**：
- 两子进程不互相干扰
- 1 小时内无崩溃
- 内存增长 < 200MB

**待实施阶段验证**：双 pywebview 子进程是否会争抢 WebView2 Runtime 资源。

### 11.5 代码签名验证

**测试步骤**：
1. 检查 `Setup.exe` 与 `DanmuAI.exe` 的数字签名
2. 在 SmartScreen 提示下选择「仍要运行」

**通过标准**：
- 数字签名有效（与现有 Velopack 签名配置一致）
- SmartScreen 不阻断（已建立信誉）

---

## 12. 测试清单总览

| # | 测试项 | 类型 | 必测/可选 | 阶段 |
|---|--------|------|-----------|------|
| 2.1 | 消息协议单测 | 单测 | 必测 | 阶段 1 |
| 2.2 | PanelBridge 单测 | 单测 | 必测 | 阶段 1 |
| 2.3 | PanelProcess 单测 | 单测 | 必测 | 阶段 1 |
| 3.1 | 单条与连续弹幕 | 集成 | 必测 | 阶段 1 |
| 3.2 | 高密度弹幕 | 集成 | 必测 | 阶段 3 |
| 3.3 | 长时间运行 | 集成 | 必测 | 阶段 3 |
| 4.1 | WS 服务端主动断开 | 集成 | 必测 | 阶段 1 |
| 4.2 | 页面崩溃 | 集成 | 必测 | 阶段 3 |
| 4.3 | 重连后缓冲区补推 | 集成 | 必测 | 阶段 1 |
| 5.1 | WebView2 冷启动 | 集成 | 必测 | 阶段 1 |
| 5.2 | 启动超时回退 | 集成 | 必测 | 阶段 1 |
| 6.1 | WebView2 不可用回退 | 集成 | 必测 | 阶段 1 |
| 7.1 | 100% DPI | 集成 | 必测 | 阶段 1 |
| 7.2 | 125% DPI | 集成 | 必测 | 阶段 1 |
| 7.3 | 150% DPI | 集成 | 必测 | 阶段 1 |
| 7.4 | 200% DPI | 集成 | 必测 | 阶段 3 |
| 8.1 | 单屏 | 集成 | 必测 | 阶段 1 |
| 8.2 | 双屏同 DPI | 集成 | 必测 | 阶段 3 |
| 8.3 | 双屏混合 DPI | 集成 | 必测 | 阶段 3 |
| 9.1 | 置顶 | 集成 | 必测 | 阶段 1 |
| 9.2 | 不抢焦点 | 集成 | 必测 | 阶段 1 |
| 9.3 | 鼠标穿透 | 集成 | **可选** | 阶段 3 |
| 10.1 | 正常退出 | 集成 | 必测 | 阶段 1 |
| 10.2 | 强制退出主进程 | 集成 | 必测 | 阶段 1 |
| 10.3 | 子进程残留检测 | 集成 | 必测 | 阶段 3 |
| 11.1 | PyInstaller onedir | 打包 | 必测 | 阶段 1 |
| 11.2 | Velopack 打包 | 打包 | 必测 | 阶段 1 |
| 11.3 | Delta 更新 | 打包 | 必测 | 阶段 3 |
| 11.4 | 双 pywebview 子进程稳定性 | 打包 | 必测 | 阶段 3 |
| 11.5 | 代码签名 | 打包 | 必测 | 阶段 3 |

---

## 13. 引用文件索引

### 必读文档
- [AGENTS.md](file:///e:/test/danmu/AGENTS.md) §7（验证规则）、§A.4（测试策略）
- [PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md](PYWEBVIEW_FLOATING_PANEL_FEASIBILITY.md)
- [PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md](PYWEBVIEW_FLOATING_PANEL_ARCHITECTURE.md)
- [PYWEBVIEW_FLOATING_PANEL_IMPLEMENTATION_GUIDE.md](PYWEBVIEW_FLOATING_PANEL_IMPLEMENTATION_GUIDE.md)

### 测试参考
- [prototype_floating_panel/win32_probe.py](file:///e:/test/danmuai_external/prototype_floating_panel/win32_probe.py) — Win32 探针函数
- [prototype_floating_panel/TEST_RESULTS.md](file:///e:/test/danmuai_external/prototype_floating_panel/TEST_RESULTS.md) — 原型测试结果（PASS 基线）

### 生产代码
- [app/floating_panel_overlay.py](file:///e:/test/danmu/app/floating_panel_overlay.py) — QPainter fallback
- [app/floating_panel_engine.py](file:///e:/test/danmu/app/floating_panel_engine.py) — 底锚堆积算法（保留）
- [app/win32_overlay_zorder.py](file:///e:/test/danmu/app/win32_overlay_zorder.py) — Win32 exstyle + topmost
- [app/webview2_runtime.py](file:///e:/test/danmu/app/webview2_runtime.py) — WebView2 探测
- [app/bundle_paths.py](file:///e:/test/danmu/app/bundle_paths.py) — PyInstaller 路径解析
- [app/single_instance.py](file:///e:/test/danmu/app/single_instance.py) — 单实例锁

### 打包脚本
- [DanmuAI.spec](file:///e:/test/danmu/DanmuAI.spec)
- [scripts/build_exe.ps1](file:///e:/test/danmu/scripts/build_exe.ps1)
- [scripts/velopack_pack.ps1](file:///e:/test/danmu/scripts/velopack_pack.ps1)
- [scripts/publish_windows_release.ps1](file:///e:/test/danmu/scripts/publish_windows_release.ps1)
