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
| 扩展路由 | `app/web_api/routes.py` | 人格、自定义模型、压缩预览 |
| 静态页 | `web/static/` | Qwen 温馨风格 |
| 桌面壳 | `app/webview_shell.py` | pywebview（Windows WebView2） |
| Overlay | `app/overlay.py` | Qt 透明置顶弹幕 |

## 页面地图

| 侧栏 | 能力 |
|------|------|
| 运行概览 | 启停、状态、会话统计与持久累计（生成总弹幕、运行总时长、消耗总 Token） |
| 助手设置 | 全局配置、节奏/截图、图像压缩预览、自定义模型 |
| 人格工坊 | 提示词编辑、版本回滚预览、新建/删除自定义人格 |
| 弹幕日记 | 多级别过滤、复制可见、自动滚动 |

## API 摘要

### 会话与核心

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/session` | 否 | 返回 `token`、`base_url` |
| GET | `/api/status` | 否 | 运行态与统计（含 `lifetime_danmu_count`、`lifetime_runtime_sec`、`lifetime_total_tokens`）；`DANMU_DEDUP_PROFILE=1` 时额外含 `dedup_profile` |
| GET/PUT | `/api/config` | PUT 需 Bearer | `WEB_CONFIG_KEYS` 子集；GET 返回掩码后的 `api_key` 与 `custom_models[].apiKey` |
| GET | `/api/screens` | 否 | 显示器列表 |
| GET | `/api/providers` | 否 | 服务商预设 |
| GET | `/api/model-catalog` | 否 | 视觉模型平台目录（模型 ID、价格、最便宜/麦克风标记） |
| GET | `/api/meta` | 否 | UI 模式、快捷键等 |

**视觉模型（助手设置 · API 页）**：选择带目录的服务商（火山方舟、阿里云百炼/DashScope、轨迹流动/SiliconFlow 等）后，列表仅展示模型 ID；「本平台最便宜」「支持麦克风」等标识显示在 info 图标左侧，悬停 info 可查看名称与价格详情。无目录或自定义 ID 时使用「其他」文本框。扩展新平台时只需在 `app/model_catalog.py` 追加数据。
| GET | `/api/personae` | 否 | 人格列表与激活状态 |
| POST | `/api/start` `/api/stop` `/api/toggle` | Bearer | 生成/停止弹幕 |
| POST | `/api/probe` | Bearer | 全局 API 连接测试 |
| WS | `/ws/logs` `/ws/status` | Query `ws_token` | 日志与状态推送（与 session token 相同） |

### 人格与提示词（`app/web_api/persona.py`）

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET | `/api/personae/{name}/template` | 否 | 契约、system/user、builtin 标志 |
| GET | `/api/personae/{name}/versions` | 否 | 历史版本列表 |
| PUT | `/api/personae/{name}/template` | Bearer | 保存；内置人格仅更新 user 提示 |
| POST | `/api/personae/{name}/rollback` | 否 | body `{version}`，加载到编辑器预览 |
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

节奏与图像相关键：`freq_mode`、`capture_mode`、`min_on_screen`（默认 **5**，可见弹幕不足时从 `danmu_pool_zh.json` 补足；**0** 关闭）、`eviction_mode`、`image_max_width`、`image_quality`（默认 **85**，未写入 config 时生效），以及 `drop_stale`、`empty_accel` 复选框。

弹幕显示 · **显示模式** `danmu_display_mode`：`realtime`（默认，1 秒截图 + 200ms 节奏预触发）或 `normal`（按 `normal_recognition_interval_sec` 秒：截图后**立即**触发 AI，默认 **5** 秒，范围 1–60；每次 `normal_reply_count` 条弹幕，默认 **5**，范围 1–20）。普通模式不探测场景跳变、不启用 rhythm/场景 gate/场景后本地 fallback；上一请求 in-flight 时跳过本轮；入队为 append。

实时模式 · 每次生成弹幕数：`reply_scene_count`（画面强相关，默认 **2**，范围 2–7）、`reply_filler_count`（泛用氛围，默认 **3**，范围 2–7）。普通模式使用单一总数契约，不拆分 scene/filler。

记忆（助手设置 · API 页）：`memory_mode`（`off` / `dedup_only` / `scene_card` / `strong`，默认 `off`）、`memory_window`（1–20，默认 **10**）、`memory_clear_policy`（`strict` / `medium` / `loose`，默认 `medium`）。进程内短记忆，不持久化；详见 [MEMORY_SYSTEM_PLAN.md](MEMORY_SYSTEM_PLAN.md)。

保存后更新人格工坊「输出契约」与运行时 AI 批次条数；`GET /api/config` 另返回只读 `reply_batch_total`（实时为 x+y，普通为 `normal_reply_count`）。

## 视觉规范

- 原型 HTML：`prototype/Qwen_html_20260524_481u8vlmv.html`
- 设计系统：`prototype/Qwen_markdown_20260525_4vyxmv819.md`
- 令牌 CSS：`web/static/warm-tokens.css`

## 测试

```bash
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_image_compress.py tests/test_ui_mode.py -v
```
