# Web 控制台

DanmuAI 默认通过 **本地 Web UI + pywebview 桌面壳** 运行，Qt 仅保留弹幕 Overlay 与托盘。

> 遗留 Qt 主窗（`--qt-ui` / `ui/`）已移除；传入 `--qt-ui`、`DANMU_QT_UI`、`DANMU_WEB_CONSOLE=0` 将报错退出。

## 启动

```bash
pip install -r requirements.txt
python main.py                  # pywebview + http://127.0.0.1:18765
python main.py --web-browser    # 系统浏览器
```

| 环境变量 | 说明 |
|----------|------|
| `DANMU_WEB_LAUNCH=browser` | 系统浏览器打开控制台 |
| `DANMU_DEDUP_PROFILE=1` | `/api/status` 含 `dedup_profile`，日志周期性汇总 |
| `DANMU_IMAGE_METRICS=1` | 运行时压缩 debug 指标 |
| `DANMU_SCENE_DEBUG=1` | 场景指纹探测日志 |

详见 [README.md](../README.md)、[AGENTS.md](../AGENTS.md)。

## 架构

| 组件 | 路径 | 说明 |
|------|------|------|
| HTTP API | `app/web_console.py` | FastAPI，`127.0.0.1:18765`，Bearer 鉴权 |
| 扩展路由 | `app/web_api/routes.py` | 人格、自定义模型、公式化弹幕库、读弹幕（TTS）、压缩预览 |
| 静态页 | `web/static/` | Qwen 温馨风格 |
| 桌面壳 | `app/webview_shell.py` | pywebview 子进程 + `nav_queue` 跨进程导航；失败回退系统浏览器 |
| 单实例 | `app/single_instance.py` | `QLocalServer`；二次启动激活已有窗口并退出 |
| Overlay | `app/overlay.py` | Qt 透明置顶弹幕 |

## 页面地图

| 侧栏 | 能力 |
|------|------|
| 运行概览 | 启停、状态、会话统计与持久累计（生成总弹幕、运行总时长、消耗总 Token）；**弹幕场次记录**（每轮启停，本机 `config.db` 最近 100 条）；**直播输出**（OBS/直播伴侣浏览器源 URL、SSE 连接数、测试弹幕）；诊断面板默认隐藏，`GET /api/diagnostics` 仍可供调试 |
| 助手设置 | 全局配置、节奏/截图、图像压缩预览、自定义模型；**恢复默认**（仅改表单，须再点保存） |
| 公式化弹幕库 | 内置/自定义公式化短句开关、最小同屏补足、自定义句增删 |
| 读弹幕 | 小米 MiMo `mimo-v2.5-tts`：独立 TTS API Key、间隔、预置音色、风格指令；**仅在已开始生成且屏上有可见弹幕时**定时随机朗读；试听 |
| AI 管家 | 使用说明与排障问答（模型/连接/DeepSeek 等）+ 自然语言建议「助手设置」可调项；复用已保存视觉 API；配置 patch 须用户点「应用修改」后才 `POST /api/config` |
| 人格工坊 | 提示词编辑、版本回滚预览、新建/删除自定义人格 |
| 弹幕日记 | 多级别过滤、复制可见、自动滚动 |
| 教程 | 飞书文档外链 |
| 社区 | 介绍页 + **进入社区** / **在浏览器中打开**（外链 Vercel 社区站；URL 见 `GET /api/community-site` 或 `DANMU_COMMUNITY_SITE_URL`；见 [community/DESKTOP-ENTRY.md](community/DESKTOP-ENTRY.md)） |
| 公告 | Supabase 已发布公告列表（置顶优先；需 `web/static/supabase-config.js`）；**温馨控制台**顶栏可显示最新公告「标题：正文」前 30 字，可关闭 |
| 侧栏左下角 | **赞赏**（微信赞赏码弹窗）；当前版本 / 最新版本（`GET /api/version` + Supabase `app_updates`） |
| 问题反馈 | 在线反馈表单（Supabase）、社群说明、QQ 群二维码 |
| 错误自动反馈 | `is_error=true` 时弹出确认框，确认后提交 `error_reports`（日志摘录 + 诊断 JSON，已脱敏） |

### Supabase（公告、反馈、错误报告与版本更新）

前端直连 Supabase PostgREST（不经本地 FastAPI）。首次开发请将 [`web/static/supabase-config.example.js`](../web/static/supabase-config.example.js) 复制为 `supabase-config.js` 并填入项目的 **URL** 与 **anon**（或 publishable）密钥；`supabase-config.js` 建议不提交公开仓库。

| 能力 | 说明 |
|------|------|
| 公告 | `announcements` 表，`published=true` 且在 `starts_at`/`ends_at` 窗口内可对 anon 只读 |
| 控制台顶栏 | 列表首条简略展示（`title：body` 截 30 字）；`overviewBannerDismissedId` 持久化于本机 `config.db`（`announcements_read_state`），`localStorage` 双写回退；新公告成为首条后再次显示；与侧栏未读红点（`readIds` / `lastSeenMs`）独立 |
| 版本更新 | `app_updates` 表；侧栏左下角展示当前版本（`GET /api/version` → `app/version.py`）与最新版本；`latest_version` 大于当前时启动弹窗；点「否」后 `dismissedLatestVersion` 写入 `config.db`（`app_update_state`）+ `localStorage`；Supabase 失败仅显示「检查失败」，不阻塞启动 |
| 反馈 | `feedback` 表，anon 仅 INSERT；每 `client_id`（`localStorage`）3 小时内最多 2 条 |
| 错误自动反馈 | `error_reports` 表；`is_error=true` 时 Web 弹窗确认后提交日志摘录与诊断 JSON；每 `client_id` 3 小时内最多 3 条 |
| 管理 | Supabase Dashboard → Table Editor 发布公告、维护 `app_updates`、查看反馈与错误报告 |

数据库迁移见 [`supabase/migrations/001_announcements_feedback.sql`](../supabase/migrations/001_announcements_feedback.sql)、[`002_error_reports.sql`](../supabase/migrations/002_error_reports.sql)、[`003_app_updates.sql`](../supabase/migrations/003_app_updates.sql)。`app_updates` 运维说明见 [`supabase/README.md`](../supabase/README.md)。

## API 摘要

### 会话与核心

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/session` | 否 | 返回 `token`、`base_url` |
| GET | `/api/status` | 否 | 运行态与统计（含 `lifetime_danmu_count`、`lifetime_runtime_sec`、`lifetime_total_tokens`）；另含只读模型投影：`active_model_id`、`inferred_provider_id`、`model_display_name`、`uses_custom_credentials`、`model_source`（`catalog`/`custom`/`freeform`/`unknown`）、`provider_model_mismatch`；`DANMU_DEDUP_PROFILE=1` 时额外含 `dedup_profile` |
| GET/PUT | `/api/config` | PUT 需 Bearer | `WEB_CONFIG_KEYS` 子集；GET 返回掩码后的 `api_key`、`custom_models[].apiKey` 及与 status 同构的模型投影字段；PUT 会校验 endpoint 与 catalog model 是否匹配（见下方 **配置保存**） |
| GET | `/api/config/defaults` | 否 | 助手设置「恢复默认」只读来源：覆盖 `WEB_CONFIG_KEYS` 工厂默认值；**不含** `api_key`、自定义模型、人格、识图区域 |
| GET | `/api/screens` | 否 | 显示器列表 |
| GET | `/api/providers` | 否 | 服务商预设 |
| GET | `/api/model-catalog` | 否 | 视觉模型平台目录（模型 ID、价格、最便宜/麦克风标记） |
| GET | `/api/meta` | 否 | UI 模式、快捷键等 |
| GET | `/api/community-site` | 否 | 社区 Vercel 外链 URL（`DANMU_COMMUNITY_SITE_URL` 或默认常量） |
| GET | `/api/version` | 否 | 本地构建版本 `{ current_version }`（[`app/version.py`](../app/version.py)） |
| GET | `/api/app-update-state` | 否 | 更新弹窗忽略状态 `{ dismissedLatestVersion }`，持久化于 `config.db` 键 `app_update_state` |
| PUT | `/api/app-update-state` | Bearer | 写入忽略状态；非空 `dismissedLatestVersion` 须为合法版本字符串 |
| GET | `/api/announcements-read-state` | 否 | 公告已读状态（`readIds`、`lastSeenMs`、`overviewBannerDismissedId`），持久化于本机 `config.db` 键 `announcements_read_state` |
| PUT | `/api/announcements-read-state` | Bearer | 写入公告已读状态；`readIds` 为公告 UUID 数组（最多 200），`lastSeenMs` 为非负整数，`overviewBannerDismissedId` 为已关闭顶栏简略条的公告 UUID 或空字符串 |

**视觉模型（助手设置 · API 页）**：选择带目录的服务商（火山方舟、阿里云百炼/DashScope、硅基流动/SiliconFlow、小米 MiMo 等）后，列表主文案为模型展示名，副文案为 model ID；悬停 info 可查看名称、ID 与价格。视觉模型目录由当前 **API 地址** 推断平台（非仅服务商下拉框）；手动改地址后会同步下拉框并刷新列表。切换服务商预设时会重置为该平台默认视觉模型（目录中最便宜项）并清空 API 密钥输入框；保存时若 endpoint 与 model 目录不匹配将拒绝保存。无目录平台或自选 ID 时使用「自定义模型」行。默认模型若来自「自定义模型 → 设为默认」，页面会提示全局 API 地址/密钥不用于生成弹幕。
| GET | `/api/personae` | 否 | 人格列表与激活状态 |
| POST | `/api/start` `/api/stop` `/api/toggle` | Bearer | 生成/停止弹幕 |
| POST | `/api/probe` | Bearer | 全局 API 连接测试 |
| POST | `/api/ai-butler/chat` | Bearer | AI 管家对话；body `{ message, history? }`；复用助手设置 API；返回 `reply`、`patch`、`reasons`、`needs_confirmation`、`current_values`、`discarded_fields`；**不写配置** |
| WS | `/ws/logs` `/ws/status` | Query `ws_token` | 日志与状态推送（与 session token 相同） |

### 直播网页弹幕层（`app/web_api/live_overlay.py`）

供 OBS、抖音直播伴侣等以**浏览器源 / 网页源**采集透明背景弹幕；与 Qt Overlay **并行**，不替代桌面叠加层。

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/live-overlay` | 否 | 透明背景弹幕页（`web/static/live-overlay.html`） |
| GET | `/api/live-overlay/events` | 否 | SSE：`event: hello` 后推送 `danmu_item`（`text`、`y`、`screen_width`、`screen_height`、`speed`）；新连接回放最近 80 条 |
| GET | `/api/live-overlay/status` | 否 | `connections`、`last_broadcast_at`、`overlay_url` |
| POST | `/api/live-overlay/test` | Bearer | 发送测试弹幕（不调 AI）；body 可选 `{ "items": ["…"] }` |

**OBS / 直播伴侣配置（本机）**

1. 启动 `python main.py`，在控制台「运行概览 → 直播输出」复制地址（默认 `http://127.0.0.1:18765/live-overlay`）。
2. 添加浏览器源，宽高建议 1920×1080，勾选**透明背景**（若软件支持）。
3. 在控制台点「发送测试弹幕」，确认网页源出现滚动白字。
4. 正常启停生成后，AI 弹幕在 Qt 上屏时经 `danmu_item` 同步到网页层（视觉 AI + 开麦 AI）；无 SSE 连接时不影响主链路。OBS 更新后须刷新浏览器源以加载最新 `live-overlay.js`。

### 人格与提示词（`app/web_api/persona.py`）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/personae/{name}/template` | 否 | 契约、system/user、builtin 标志 |
| GET | `/api/personae/{name}/versions` | 否 | 历史版本列表 |
| PUT | `/api/personae/{name}/template` | Bearer | 保存；内置人格仅更新 user 提示 |
| POST | `/api/personae/{name}/rollback` | 是 | body `{version}`，加载到编辑器预览 |
| POST | `/api/personae/{name}/restore` | Bearer | 内置人格恢复默认 |
| POST | `/api/personae` | Bearer | body `{name}`，创建自定义人格 |
| DELETE | `/api/personae/{name}` | Bearer | 删除非内置人格 |
| PUT | `/api/personae/active` | Bearer | body `{active: string[]}` |

### 自定义模型（`app/web_api/custom_models.py`）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/custom-models` | 否 | 列表（`apiKey` 掩码，`complete` 标志） |
| POST | `/api/custom-models` | Bearer | 新增 |
| PUT | `/api/custom-models/{index}` | Bearer | 按列表下标更新；掩码 key 保留原值 |
| DELETE | `/api/custom-models/{index}` | Bearer | 删除；默认模型自动回退 |
| POST | `/api/custom-models/{index}/default` | Bearer | 设为默认并写入全局 `model` |
| POST | `/api/custom-models/probe` | Bearer | 单模型连接测试 |

### 公式化弹幕库（`app/web_api/danmu_pool.py`）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/danmu-pool/meta` | 否 | 内置/自定义开关、`min_on_screen`、库条数、`effective_pool_enabled` |
| PUT | `/api/danmu-pool/settings` | Bearer | body `{builtin_enabled, custom_enabled, min_on_screen}` → `danmu_pool_enabled` / `danmu_pool_use_custom` / `min_on_screen` |
| GET | `/api/danmu-pool/custom` | 否 | 自定义句列表 |
| POST | `/api/danmu-pool/custom` | Bearer | 批量追加（`text` 多行或 `items`）；返回 `added` / `skipped` |
| DELETE | `/api/danmu-pool/custom` | Bearer | body `{texts: string[]}` 按文本删除 |

自定义句存 SQLite `custom_danmu_pool`（JSON），**不**经 `PUT /api/config`。补足条件：内置库 **或** 自定义库任一开启时 `min_on_screen` 生效；合并池见 `app/danmu_pool.py`。

**行为说明**

- **双来源 OR**：内置库（`data/danmu_pool_zh.json`，Web 只读开关）与自定义库可独立开启；运行时合并为同一抽样池。
- **同屏补足**：`min_on_screen` 默认 **5**；设为 **0** 关闭补足。任一库开启且 `min_on_screen > 0` 时，当屏上弹幕不足则从合并池随机补位（`main._maybe_pool_topup`）。
- **自定义句**：侧栏页批量追加/多选删除；不在 Web 中编辑内置 JSON 全文。
- **与助手设置分离**：`danmu_pool_*` / `min_on_screen` 仅通过 `/api/danmu-pool/*` 读写，勿写入 `PUT /api/config`。

### AI 管家（`app/web_api/ai_butler.py`）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/api/ai-butler/chat` | Bearer | body `{ message, history? }`；纯文本请求（不经主链路）；系统提示词注入产品知识（预设服务商、视觉模型要求、DeepSeek 路径等）；问答时 `patch` 为空，调参建议须用户确认保存 |

**响应示例**

```json
{
  "reply": "可以把弹幕速度调低一些。",
  "patch": { "danmu_speed": "1.5" },
  "reasons": { "danmu_speed": "降低横向滚动速度" },
  "needs_confirmation": true,
  "current_values": { "danmu_speed": "2" },
  "discarded_fields": []
}
```

**安全与保存**

- `patch` 仅允许 17 个助手设置子集字段（如 `danmu_speed`、`normal_reply_count`、`image_quality` 等）；禁止 `api_key`、`model`、热键、识图区域、人格等。
- 非法字段进入 `discarded_fields`，不会返回给前端保存。
- 应用修改：Web 页「应用修改」→ `POST /api/config`（与助手设置相同），**管家接口不直接写库**。

### 读弹幕 / TTS（`app/web_api/danmu_read.py`）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/danmu-read/config` | 否 | `enabled`、`interval_sec`（3–120）、`voice`、`style_prompt`、掩码 `api_key`；只读 `model`=`mimo-v2.5-tts`、`endpoint` |
| PUT | `/api/danmu-read/config` | Bearer | 写 `danmu_read_*` / `tts_*` / `tts_api_key_encrypted`；主线程 `apply_danmu_read_config` 并同步定时器 |
| POST | `/api/danmu-read/probe` | Bearer | 固定短句试听（`TTS_PROBE_TEXT`），不落盘 |

**行为说明**

- **模型固定**：仅 `mimo-v2.5-tts` 预置音色；暂不支持 voicedesign / voiceclone / 自定义模型 ID。
- **TTS Key 独立**：`ConfigStore.get_tts_api_key()`，与视觉 `api_key` 分离。
- **触发条件**：`danmu_read_enabled` 且 `engine.running`；从 `DanmuEngine.visible_display_texts()` 随机抽样；播放或合成进行中跳过本 tick。
- **实现**：`app/danmu_read_service.py`（`QTimer` + `QThreadPool` HTTP + `sounddevice` 播放 WAV）；合成 in-flight 保持至 `playback_finished`；播放前约 80ms 淡出 + 1s 静音尾韵（`app/danmu_tts_playback.py`）。
- **勿写入** `PUT /api/config` / `WEB_CONFIG_KEYS`。

### 识图区域（鼠标框选）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/capture-region` | 否 | `mode`（`full`/`custom`）、`region`（`x/y/w/h` 相对识图显示器左上角）、`selection_state`（`idle`/`selecting`/`saved`/`cancelled`/`invalid`） |
| POST | `/api/capture-region/select` | Bearer | 触发主线程 Qt 全屏框选层；立即返回 `{ok, selection_state: selecting}`，不阻塞 |
| POST | `/api/capture-region/reset` | Bearer | 恢复全屏（`region_*` 置 0）并关闭进行中的框选 |

`region_*` 持久化在 SQLite，**不**经 `PUT /api/config`。`/api/status` 与 WS 亦投影 `capture_region_mode`、`region_*`、`region_selection_state`。框选坐标由 [`app/snipper.py`](../app/snipper.py) 在截图时裁剪；非法 `region_*` 会回退全屏并打 info 日志（`reason=region_*`）。

### 配置保存（`PUT /api/config`）

1. HTTP 线程校验 payload（`validate_web_config_patch`）。
2. `WebConsoleBridge.save_config_requested.emit(data)` → 主线程 `_on_save_config` → `apply_web_config_payload`。
3. HTTP 立即返回 `{"ok": true}`；**不**等待主线程写入完成。成功时主线程 `logger.info`；失败时 `logger.error` + `set_web_error_status`（运行概览错误区）。UI toast 以 HTTP 200 为准时，存在极短异步窗口。
4. 状态降级轮询失败时前端 toast；未捕获的 Promise  rejection 也会 toast（[`web/static/app.js`](../web/static/app.js)）。

### 扩展路由写操作（`app/web_api/routes.py`）

需**同步返回**且会写入 `ConfigStore`、调用 `DanmuApp` 公开方法或 `config_changed.emit()` 的路由（人格、弹幕库、自定义模型、公告已读、麦克风测试等）统一经 `WebConsoleBridge.invoke_on_main(fn, *args, **kwargs)`：uvicorn 线程 `emit` + `BlockingQueuedConnection`，阻塞直至主线程槽执行完毕并返回结果。

| 模式 | 适用 | 示例 |
|------|------|------|
| `invoke_on_main` | 写操作且 HTTP 需等待返回值 | `PUT /api/personae/active`、`POST /api/mic/test` |
| `xxx_requested.emit`（异步） | 写操作且 HTTP 可立即 `{"ok":true}` | `PUT /api/config`、`POST /api/start` |
| 直接调用（HTTP 线程） | 只读 | `GET /api/personae/{name}/template`、`POST /api/probe`（仅读 config + 出站 HTTP） |

勿在 uvicorn 线程对 `invoke_on_main` 使用 `QTimer.singleShot`（槽常不触发，与 `save_config` 注释同源）。

### 图像压缩预览

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/api/preview/compress` | Bearer | `multipart/form-data`：`file`、`max_width`、`quality`；返回尺寸与 `preview_data_url`（不落盘，上限 10MB） |

**实现（双入口，参数一致）**

- 运行时：`main.compress_screenshot()`（`QPixmap` → JPEG Base64 data URI）
- Web 预览：`app/image_compress.compress_image_bytes()`（上传字节 → 同 scale/quality 逻辑）

本地调 JPEG 质量（不调用 AI、不写仓库图片）：[`scripts/bench_jpeg_quality.py`](../scripts/bench_jpeg_quality.py)，说明见 [scripts/README.md](../scripts/README.md)。

## 配置字段（Web 表单）

除 `WEB_CONFIG_KEYS` 外，表单还通过 `PUT /api/config` 提交 `api_key`（掩码不覆盖）、`active_personae`。

图像相关键：`eviction_mode`、`image_max_width`、`image_quality`（默认 **85**，未写入 config 时生效），以及 `empty_accel` 复选框。

公式化弹幕库（专用 API，不在 `WEB_CONFIG_KEYS`）：`danmu_pool_enabled`（内置库）、`danmu_pool_use_custom`（自定义库）、`min_on_screen`（默认 **5**，任一库开启且值 **>0** 时从合并池补足；两库都关则运行时不补足）。

弹幕生成 · `normal_recognition_interval_sec`（识图间隔，默认 **5** 秒，范围 1–60；截图后**立即**触发 AI）、`normal_reply_count`（每批弹幕条数，默认 **5**，范围 1–20）。上一请求 in-flight 时跳过本轮截图；回复入队为 append。

温度（助手设置 · API 页，**简化/全面模式均显示**）：`temperature`（0–2，步进 0.1，默认 **0.7**）。`max_tokens` 等高级项仅在全面模式显示。

记忆（助手设置 · API 页，**简化/全面模式均显示**）：`memory_mode`（`off` / `dedup_only` / `scene_card` / `strong`，默认 `off`）、`memory_window`（1–20，默认 **10**）。进程内短记忆，不持久化；详见 [ARCHITECTURE.md](ARCHITECTURE.md#memory-modes)。

保存后更新人格工坊「输出契约」与运行时 AI 批次条数；`GET /api/config` 另返回只读 `reply_batch_total`（等于 `normal_reply_count`）。数据库中遗留的 `danmu_display_mode=realtime` 会在启动或 Web 保存时规范为普通模式行为。

## 视觉规范

- 原型 HTML：`prototype/Qwen_html_20260524_481u8vlmv.html`
- 设计系统：`prototype/Qwen_markdown_20260525_4vyxmv819.md`
- 令牌 CSS：`web/static/warm-tokens.css`

## 测试

```bash
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py -v
```
