# Web 控制台

DanmuAI 当前默认通过 **本地 Web 控制台 + pywebview 桌面壳**运行；Qt 只保留 Overlay、托盘和主线程编排。

---

## 1. 启动方式

```bash
python main.py
python main.py --web-browser
```

### 当前事实

- 默认：本地 Web 控制台 + pywebview 壳 + Overlay
- `--web-browser`：系统浏览器打开控制台
- 已移除旧 Qt 主窗；`--qt-ui` / `--legacy-ui` / `DANMU_QT_UI` / `DANMU_WEB_CONSOLE=0` 都应失败退出
- **W-STARTUP-NONBLOCK-001**：`attach_web_console` 主线程仅短等 `web_console_ready_timeout()`（dev 0.5s / frozen 1.5s）；pywebview `begin_start` 内 `_ensure_server_ready` 同样短探测，慢启动由 `open_web_console_when_ready` QTimer 重试，避免 12s 冻结。退出时 `quit()` 对 uvicorn 线程 `join(3s)`（frozen 非 daemon 收尾，S-002）。
- **W-OPEN-CONSOLE-RECOVERY-002**：托盘单击/双击均可打开设置；用户打开时若 uvicorn `failed` 则经 `maybe_restart_web_console` + `GET /api/status` 探测，仍失败则自动打开系统浏览器（`_browser_launch_opened` 去重）；pywebview 握手失败后用户再次打开则自动浏览器兜底。

---

## 2. 架构分层

| 层 | 路径 | 说明 |
|----|------|------|
| HTTP / WS / SSE | `app/web_console.py` | 会话 token、`/api/status`、基础桥接 |
| 路由注册器 | `app/web_api/routes.py` | 其余 API 注册与主线程薄适配 |
| 路由实现 | `app/web_api/*` | 人格、模型、识图区域、读弹幕、诊断等 |
| 前端入口 | `web/static/app.js` | 页面编排与跨模块依赖注入 |
| 前端模块 | `web/static/modules/*` | settings、status、logs、diagnostics、content pages 等 |
| 字段提示 | `web/static/modules/settings-hints.js` | 助手设置、温馨控制台、人格工坊、公式化弹幕库、桌宠共用 ℹ️ 悬浮说明（`initSettingsFieldHints` / `initContentPageFieldHints`） |
| 样式 | `web/static/warm-tokens.css` + 分层 CSS | 控制台样式入口 |
| 桌面壳 | `app/webview_shell.py` | pywebview 子进程与导航握手 |

---

## 3. 页面地图

当前控制台包含这些一级页面：

- 温馨控制台 / 运行概览（顶部公告条下含全局「提示内容」`live_topic` 与「昵称」`user_nickname`，经 `PUT /api/config` 保存并注入 AI system 提示词）
- 助手设置
- 人格工坊（人格选择与系统提示编辑；全局提示内容/昵称已迁至温馨控制台）
- 公式化弹幕库
- 桌宠
- 弹幕日记
- 教程
- 公告
- 问题反馈
- 助手设置内「AI读弹幕」页签（TTS 朗读配置）

此外还有：

- 直播网页弹幕层 `/live-overlay`
- 运行概览「直播输出」接入助手（复制网页源地址、检测连接数、发送测试弹幕）
- 诊断面板
- 版本更新提示
- 赞赏弹窗

---

## 4. Web 边界

### 必须遵守

1. Web/API 不直接读 `danmu_app._*`
2. Qt 对象修改必须回主线程
3. `/api/status` 只能走 `build_status_snapshot()`
4. `/api/diagnostics` 只能走 `build_diagnostic_snapshot()`
5. 配置写入只能走 `apply_web_config_payload()`

### 如果缺能力

先在 `DanmuApp` 增加公开 façade，再让路由使用。

---

## 5. 当前核心 API

### 会话与状态

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/session` | 返回 token 与 base_url（需同源 loopback 握手或 Bearer Token；详见 [§鉴权](#鉴权)） |
| GET | `/api/status` | 运行态只读快照 |
| GET | `/api/diagnostics` | 调度 / RTT / runtime 诊断快照（需 Bearer Token） |
| POST | `/api/start` | 开始生成弹幕 |
| POST | `/api/stop` | 停止 |
| POST | `/api/toggle` | 切换 |

### 配置 / 模型 / 人格

| 方法 | 路径 | 说明 |
|------|------|------|
| GET / PUT | `/api/config` | Web 配置读取与保存 |
| GET | `/api/config/defaults` | 恢复默认值来源 |
| GET | `/api/providers` | 服务商预设 |
| GET | `/api/model-catalog` | 模型目录 |
| GET | `/api/personae` | 人格列表 |
| POST | `/api/probe` | API 连通性测试 |

### 功能页

| 路径 | 说明 |
|------|------|
| `/api/custom-models*` | 模型配置档案（用户界面名称；路由仍为 `custom-models`；含可选字段 `supportsMic`：声明 OpenAI 兼容网关模型支持 `input_audio`，供麦克风模式本地门控） |
| `/api/capture-region*` | 识图区域框选与状态 |
| `/api/danmu-pool*` | 自定义公式化弹幕库 |
| `/api/meme-barrage*` | 烂梗公式化（采集/展示配置、标签、本地库清除） |
| `/api/danmu-read/config` | 读弹幕配置 |
| `/api/danmu-read/catalog` | 读弹幕 TTS 平台/模型/音色目录（只读） |
| `/api/danmu-read/probe` | 读弹幕试听 |
| `/api/pet/settings` | 桌宠配置读/写（GET 只读；POST 写，Bearer） |
| `/api/pet/show` / `hide` / `close` | 桌宠显隐与关闭（POST，Bearer） |
| `/api/pet/command` | 提交桌宠临时弹幕指令（POST，Bearer；注入下一次视觉请求） |
| `/api/pet/status` | 桌宠轻量状态（动画态、pending 摘要） |
| `/api/announcements-read-state` | 公告已读状态 |
| `/api/app-update-state` | 版本弹窗忽略状态 |
| `/api/version` | 当前构建版本（公开） |
| `/api/update/channels` | 更新元数据（公开只读）：Supabase `app_updates` + 镜像渠道目录 |
| `/api/update/status` | Velopack 运行态（Bearer） |
| `POST /api/update/check` \| `download` \| `restart` | Velopack 检查/下载/重启（Bearer） |

### 直播网页弹幕层

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/live-overlay` | 透明网页弹幕层页面 |
| GET | `/api/live-overlay/status` | live overlay 状态 |
| POST | `/api/live-overlay/test` | 注入测试弹幕 |

### 鉴权

W-SEC-001 修复后，`/api/session` 不再无条件返回 Bearer Token。请求需满足下列条件之一：

1. **携带正确 Token**：`Authorization: Bearer <token>` 头匹配 `server.token`；不要求同源 / loopback。**已掌握 token 的调用方属于已鉴权。**
2. **同源 loopback 握手**：`Origin` 或 `Referer` 与 `Host` 同为 loopback（`127.0.0.1` / `localhost` / `::1`）。**仅供控制台页面启动 handshake**（`web/static/modules/transport.js::refreshSession()`）使用。

其他情况一律 `401`（缺/格式错） / `403`（来源不匹配 / token 错误）。curl 等无 `Origin` 头的进程调用必然被拒绝。

实现：[app/web_console_session_auth.py](../app/web_console_session_auth.py) `enforce_session_authorization()`。

#### 鉴权策略（W-MEDLOW-002）

服务绑定 `127.0.0.1`，默认仅本机可访问。路由分三类：

| 类别 | 说明 | 示例 |
|------|------|------|
| **A. 首屏开放 GET** | 控制台 / pywebview 握手前可无 token 读取元数据与配置投影 | `/api/status`、`/api/config`、`/api/version`、`/api/update/channels`、`/api/personae`、`/api/providers`、`/api/model-catalog`、`/api/danmu-pool/meta`、`/api/danmu-pool/custom`（只读列表）、`/api/meme-barrage/meta`、`/api/meme-barrage/tags`、`/api/danmu-read/config`、`/api/danmu-read/catalog`、`/api/pet/status`、`/api/live-overlay/status` |
| **B. 敏感读** | 调度 / RTT / 运行态诊断，需 Bearer | `/api/diagnostics`、`/api/diagnostics/events`（SSE 用 query `token`）、`/api/update/status` |
| **C. 写操作** | 改配置、探测、注入、桌宠控制等，需 Bearer + `invoke_on_main` | `PUT/POST` 类路由（含 `PUT /api/config`、`POST /api/start` 等，后者在 `web_console_runtime.py`） |

**设计依据**：A 类避免 pywebview 首屏在 `refreshSession()` 完成前无法渲染设置页；B 类暴露调度与 in-flight 细节；C 类触达 Qt / ConfigStore / 主链路。

写路由经 `routes._invoke_main` 同步到主线程，错误语义如下（**W-WEB-BRIDGE-HIGH-001**）：

| 情况 | HTTP | 响应体 |
|------|------|--------|
| 业务校验 / 运行态错误 | **400** | `{"detail": "<message>"}`（`ValueError` / `PermissionError` / `RuntimeError`） |
| 未预期内部错误 | **500** | `{"detail": "internal error"}` |
| `invoke_on_main` 主线程超时 | **504** | `{"detail": {"ok": false, "error": "main_thread_timeout", "detail": "主线程操作超时，请稍后重试。"}}` |
| `PUT /api/config` 保存超时 | **504** | `{"ok": false, "error": "save_timeout", "detail": "..."}`（顶层 JSON，不经 `detail` 嵌套） |

- `invoke_on_main` 默认超时 **10s**（`INVOKE_ON_MAIN_TIMEOUT_SEC`，与 `SAVE_CONFIG_TIMEOUT_SEC` 同级）；可通过 `invoke_on_main(..., timeout_sec=)` 覆盖。
- 机制：`QueuedConnection` 排队到主线程 + HTTP 线程 `threading.Event.wait(timeout)`；成功路径仍阻塞至主线程完成，不退回异步“假成功”。
- **注意**：超时**不取消**已排队的主线程槽；极端情况下 HTTP 已返回 504 但主线程操作仍可能稍后完成（与 config save 相同）。

## 6. 直接依赖 Supabase 的前端能力

以下能力是前端直连 Supabase，不经过本地 FastAPI：

- 公告内容读取
- 反馈提交
- 错误自动反馈
- 教程页视频链接（`tutorial_links` 表；`url` 为 `https://...` 时可点击，否则显示占位文案）

**版本更新元数据**已改由后端 `GET /api/update/channels` 提供（读取 Supabase `app_updates`）；前端 `app-update-banner.js` **不再**调用 `DanmuSupabase.fetchAppUpdate()`。

本地 API 负责：

- 已读 / 忽略状态落本地 `config.db`（`/api/app-update-state`）
- 从 Supabase 拉取并缓存的更新元数据（`/api/update/channels`）
- 当前应用版本（`/api/version`）

**应用内 Velopack 更新进度**（`W-UPDATE-PROGRESS-001`）：`POST /api/update/download` 在后台线程下载；前端通过 `GET /api/update/status` 轮询（约 400ms）。`check` / `download` / `status` 响应均含：

| 字段 | 说明 |
|------|------|
| `download_phase` | `idle` \| `downloading` \| `ready` \| `applying` \| `error` |
| `download_progress` | 0–100（Velopack `progress_callback`） |
| `package_size_bytes` | 估算包大小（优先 `DeltasToTarget` 之和，否则 `TargetFullRelease.Size`） |
| `downloaded_bytes` | `package_size_bytes * download_progress / 100` |
| `downloading` | 是否正在下载 |

Web 侧栏与更新弹窗共用 `app-update-banner.js` 进度面板（进度条 + 百分比 + 大小）。

### 问题反馈（`feedback`）

| 项目 | 说明 |
|------|------|
| 入口 | Web 控制台侧栏「问题反馈」页 |
| 用户必填 | 仅 `content`（反馈内容，≤2000 字） |
| 用户可选 | `contact`（联系方式，≤200 字） |
| 自动附带 | `context_json`（结构化运行上下文）、`logs_excerpt`（最近日志摘录，≤8000 字）、`app_version`、`platform`、`locale` |
| 额度 | 每客户端每 3 小时最多 2 条（Supabase RLS + `feedback_quota` RPC） |

`context_json` 由 `web/static/modules/feedback-context.js::collectFeedbackContext()` 统一采集，固定包含以下 8 个字段：

- `current_model_name`：当前模型显示名（无显示名时回退到模型 ID）
- `api_endpoint`：当前 API endpoint，已轻度脱敏（仅保留 `scheme + host + path`，不含 query、fragment、userinfo 或 token/key 片段）
- `provider_id`：当前服务商平台 ID
- `api_mode`：当前 API 模式（如 `doubao` / `openai-compatible`）
- `recent_logs`：最近日志摘录（长度上限 8000 字符）
- `app_version`：当前应用版本号
- `reported_at`：上报时间（ISO 8601）
- `error_message`：当前错误文案（无错误时为 `null`）

页面文案已增加轻量提示：「提交时会自动附带当前运行信息（已脱敏），便于定位问题。」

### 错误自动反馈（`error_reports`）

| 项目 | 说明 |
|------|------|
| 触发 | 运行态 `is_error=true` 时自动弹窗；或运行概览 error 横幅「反馈此问题」手动打开 |
| 自动附带 | `summary`、脱敏日志摘录 `logs_excerpt`、`diagnostics_json`（调度/RTT/配置上下文）、`error_fingerprint`、`app_version` |
| 用户可填 | `user_note`（补充说明，可选）、`contact`（联系方式，可选） |
| 额度 | 每客户端每 3 小时最多 3 条（Supabase RLS + `error_reports_quota` RPC） |
| 去重 | 自动弹窗：同错误摘要 fingerprint 24h 内不重复提示；手动入口不受此限 |
| 与「问题反馈」区别 | 问题反馈走 `feedback` 表，自动附带同样的最小运行上下文；错误报告专为运行时异常排障，额外保留诊断报告与指纹 |

错误自动反馈复用同一套上下文采集逻辑：`web/static/modules/feedback-context.js::collectFeedbackContext()`。`diagnostics_json.config_context` 在原有 `active_model_id`、`provider_id`、`api_endpoint_host`、`api_mode` 基础上，补齐了与普通反馈一致的 8 个字段：

- `current_model_name`
- `api_endpoint`（已轻度脱敏）
- `provider_id`
- `api_mode`
- `recent_logs`
- `app_version`
- `reported_at`
- `error_message`

`api_endpoint` 脱敏规则与普通反馈一致：移除 query、fragment、userinfo，仅保留 `scheme + host + path`。`logs_excerpt` 继续受 8000 字符上限保护。

实现：`web/static/modules/app-error-reporting.js`、`web/static/modules/feedback-context.js`、`web/static/supabase-client.js`。排障规范见 [IDE_AGENT_RULES.md](IDE_AGENT_RULES.md) §9。

---

## 7. 配置写入规则

`PUT /api/config` 的真实写入路径：

```text
HTTP handler
-> bridge / main-thread dispatch
-> DanmuApp.apply_web_config_payload()
-> ConfigService / apply_web_config_patch()
-> ConfigStore
```

因此：

- 不要在 HTTP 线程直接碰 `ConfigStore` 的 Qt 相关后效
- 不要把 `region_*` 这类识图区域字段混进普通配置保存路径
- 不要让路由自己拼 `config.set(...)` 替代 `apply_web_config_payload()`

---

## 8. 当前前端结构提醒

- `index.html` 已模板片段化，但运行产物仍是单文件静态 DOM
- `app.js` 现在是 orchestration 层，不要再把大块业务逻辑堆回去
- `settings.js` 已拆成多个模块，不要重新合并
- `warm-tokens.css` 是聚合入口，新增样式应落到分层 CSS 文件

---

## 9. 改 Web 前先确认

1. 这是页面逻辑，还是路由逻辑，还是运行态 façade？
2. 是否会让 Web 层直接读私有字段？
3. 是否会让 HTTP 线程直接写 Qt 对象？
4. 是否会改 `/api/status` 或 `/api/diagnostics` 的构造方式？

只要其中一项答案不清楚，就先停下来补边界设计。
