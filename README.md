# DanmuAI

![Python](https://img.shields.io/badge/python-3.12%E6%8E%A8%E8%8D%90-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

DanmuAI 是一个 Windows 桌面弹幕工具：截取**所选显示器全屏**，调用视觉模型生成 5 条弹幕，并以 Qt 透明置顶浮层滚动展示。默认通过 **温馨 Web 控制台**（pywebview 桌面壳）配置与启停；Qt 仅负责弹幕 Overlay 与系统托盘。

<img width="2487" height="1375" alt="屏幕截图 2026-05-17 195301" src="https://github.com/user-attachments/assets/7a366c6c-1729-4852-b8df-c5755388fe60" />
<img width="2541" height="1408" alt="屏幕截图 2026-05-17 195727" src="https://github.com/user-attachments/assets/655b778a-26c8-4c3b-8fd3-45eef7aac4a9" />
<img width="2526" height="1391" alt="屏幕截图 2026-05-17 195659" src="https://github.com/user-attachments/assets/ab2aff3c-c1d0-44bc-b507-7a42921dbb48" />

**项目定位**：为直播主播提供轻量、隐私友好的 AI 弹幕助手。截图在内存中压缩后发送模型，默认不落盘；配置与密钥存于本机 `%APPDATA%/DanmuAI/`。

## 项目状态

早期活跃开发中，API 和配置格式可能变动。控制台 UI 为 Web；遗留 Qt 主窗（`--qt-ui`）已移除。

**当前 UI 事实（以 `main.py` 为准）**

- 默认：`python main.py` → Web 控制台 + pywebview + Qt Overlay/托盘
- 新功能落点：`web/static/`、`app/web_api/`（在 `routes.py` 注册）
- Overlay：`app/overlay.py`、`app/danmu_engine.py` 始终运行

详见 [docs/WEB_CONSOLE.md](docs/WEB_CONSOLE.md)、[docs/ROADMAP.md](docs/ROADMAP.md)、[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 技术栈

| 组件 | 用途 |
|------|------|
| **Python** 3.12（推荐） | 主语言 |
| **FastAPI** + **uvicorn** | 本地 Web API（`127.0.0.1:18765`） |
| **pywebview** | 桌面壳（Windows WebView2） |
| **PyQt6** | 弹幕 Overlay、系统托盘 |
| **httpx** | HTTP/2 客户端，AI API 请求 |
| **Pillow** | 图像压缩（JPEG quality 默认 85，max_width 768，Base64 data URI） |
| **SQLite** | 配置存储（WAL 模式） |
| **cryptography** | API Key 加密（Fernet） |
| **keyboard** | 全局快捷键 |
| **python-Levenshtein** | 弹幕去重相似度计算 |

## 功能特性

- 弹幕生成：**固定识图间隔**（`normal_recognition_interval_sec`，默认 5 秒）+ **每批条数**（`normal_reply_count`，默认 5 条）；上一请求 in-flight 时跳过本轮
- 主线程截图，线程池压缩和 AI 请求，避免 UI 阻塞
- 连续失败退避、超时控制、日志脱敏
- **多屏**：`screen_index` 选择截图与 Overlay 目标屏（无效索引回退 0）
- 截图在内存中压缩后发送给 AI，**默认不落盘**；只保存弹幕文本历史
- **Web 控制台**：运行概览（会话统计 + 持久累计：生成总弹幕、运行总时长、消耗总 Token）、助手设置、人格工坊、弹幕日记；自定义模型 CRUD、图像压缩预览
- **服务商预设**：火山方舟、阿里云百炼、智谱、Moonshot、硅基流动、**小米 MiMo** 等；带目录的平台可在助手设置中选模型 ID（豆包 / 百炼 / 硅基流动 / MiMo）

## 环境要求

- **Python** 3.12（推荐）
- **平台**：Windows（WebView2 用于 pywebview 壳）

### 主要依赖

| 包 | 用途 |
|----|------|
| [requirements.txt](requirements.txt) | 运行时：PyQt6、FastAPI、uvicorn、httpx、Pillow、cryptography 等 |
| [requirements-dev.txt](requirements-dev.txt) | 开发/测试：pytest、pytest-qt、ruff 等 |

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 可选，跑测试/lint
> 说明：当前仓库在 Windows + Python 3.14 环境下未验证 `PyQt6.QtNetwork` 测试路径；如需稳定回归，优先使用 Python 3.12。

## 运行方式

```bash
python main.py                         # 默认：pywebview + Web 控制台 + 托盘 + Qt 弹幕 Overlay
python main.py --web-browser           # 用系统浏览器打开控制台
```

## 打包为 Windows exe

桌面壳为 **pywebview**（WebView2）。构建与排错见 **[docs/PACKAGING_WINDOWS.md](docs/PACKAGING_WINDOWS.md)**（含 PyInstaller 步骤、已知问题与 `startup.log` 诊断）。

```powershell
pip install -r requirements.txt -r requirements-dev.txt
.\scripts\build_exe.ps1
```

产物：整个 `dist\DanmuAI\` 目录（勿只分发单个 exe）。运行诊断：`%APPDATA%\DanmuAI\startup.log`。

| 环境变量 | 说明 |
|----------|------|
| `DANMU_WEB_LAUNCH=browser` | 强制系统浏览器（等同 `--web-browser`） |
| `DANMU_DEDUP_PROFILE=1` | 开启弹幕去重统计（`/api/status.dedup_profile` 与 debug 汇总） |
| `DANMU_IMAGE_METRICS=1` | 压缩路径 debug 指标（不落盘 Base64） |

更多运行时细节见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)、[docs/CONTRIBUTING_ARCHITECTURE.md](docs/CONTRIBUTING_ARCHITECTURE.md)。

控制台地址：`http://127.0.0.1:18765`（仅本机；修改配置需会话 Bearer token）。

首次启动若本地配置不存在，程序会自动创建配置库。请在 Web「助手设置」中检查 API Key 等基础项。

## 如何配置 API Key

1. 启动程序后，在 Web 控制台打开 **助手设置**（或浏览器访问上述地址）。
2. 填写 `API Endpoint`、`API Key`、`Model`；在「服务商预设」中选平台（如 **小米 MiMo**）可自动填入默认地址；有模型目录时可从下拉选 `mimo-v2.5` 等。
3. 在「节奏与截图策略」「图像压缩预览」中调整参数；多屏时在「显示器」下拉选择目标屏。

**常用预设**

| 预设 | 默认 Endpoint | 协议 | 截图弹幕模型示例 |
|------|----------------|------|------------------|
| 火山方舟 | `https://ark.cn-beijing.volces.com/api/v3` | 豆包 Responses | `doubao-seed-1-6-flash-250828` |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI 兼容 | `qwen-vl-max` |
| 小米 MiMo | `https://api.xiaomimimo.com/v1` | OpenAI 兼容 | `mimo-v2.5`（MiMo-V2.5） |
| 硅基流动 | `https://api.siliconflow.cn/v1` | OpenAI 兼容 | `Qwen/Qwen3-VL-8B-Instruct` |

完整列表见 `app/model_providers.py`；带价格/徽章的目录见 `app/model_catalog.py` 与 `GET /api/model-catalog`。
4. 点击 **保存配置**，再在 **温馨控制台** 点击 **生成弹幕**。

人格与提示词在侧栏 **人格工坊**；自定义模型在设置页「自定义模型」卡片中管理。

项目提供 [`.env.example`](.env.example) 作参考。**注意**：桌面应用默认通过 Web/设置写入 `%APPDATA%/DanmuAI/config.db`，不会自动加载 `.env`。

## 隐私提醒

- 本工具会截取**所选显示器全屏**，并把截图发送给你选择的 AI 服务商。
- 截图在内存中压缩，**默认不会落盘**，也不会把截图原文写入日志。
- 请确保目标屏幕上没有密码框、聊天记录、支付页面、内部文档等敏感内容。
- API Key 存储在 `%APPDATA%/DanmuAI/config.db`，优先 Fernet 加密；缺少 `cryptography` 时退化为 base64 并警告。
- Web API 仅监听 `127.0.0.1`；写操作需 Bearer token。

更多说明见 [docs/PRIVACY.md](docs/PRIVACY.md)、[docs/WEB_CONSOLE.md](docs/WEB_CONSOLE.md)。

## 常见问题

### 为什么启动后没有弹幕？

- 常见原因：API Key 未配置、截图失败，或连续失败进入退避。
- 在 Web「助手设置」检查 API，在「弹幕日记」查看错误日志。

### 为什么旧画面的弹幕没显示出来？

- **当前普通模式策略**：不做场景代际（`scene_generation`）检查，也不因过期 `screenshot_id` 或新鲜度 TTL 硬丢弃 AI 回复；慢模型下弹幕可能相对画面略有滞后，优先保证弹幕连续性。
- 若仍看不到弹幕，常见原因包括：API/截图失败、连续失败退避、去重拒绝、轨道已满导致 `add_text` 暂不上屏等。可在「弹幕日记」查看错误日志。

### 程序会保存截图吗？

- 默认不会。只保存弹幕文本历史，不落盘截图。

### Max Tokens 设得很低会怎样？

- 固定 5 条弹幕需要完整 JSON/列表输出；过低会导致截断或解析失败。
- 请求前有下限保护（**≥512**）；程序对所有 API 请求固定关闭思考模式（`thinking: disabled`）。

### 小米 MiMo 报「AI 返回为空」？

- 请使用 **OpenAI 兼容** 模式 + 预设 endpoint，模型优先 **`mimo-v2.5`**。
- 应用已强制关闭思考模式；若仍为空，检查 Key 权限、配额与模型 ID 是否在控制台开通。

### 开麦模式能用 MiMo 吗？

- **不能**。麦克风音频仅豆包 Responses（`input_audio`）路径发送；OpenAI 兼容预设（含 MiMo）仅截图 + 文本。请用 `doubao-seed-2-0-mini-260428` 等全模态豆包模型开麦。

### Web 控制台打不开？

- 确认 `127.0.0.1:18765` 未被占用；可试 `--web-browser`。
- Windows 需 WebView2 运行时（pywebview 壳）。

## 已知限制

- `region_*` 需手动填写相对所选屏幕的坐标；可视化框选器仍在 [ROADMAP.md](docs/ROADMAP.md) 规划中。
- 进行中的网络请求无法强制中断，退出时会等待线程池短暂收尾。
- Web 控制台 UI 为中文（`<html lang="zh-CN">`）；后端 `language` 字段保留供 Overlay/托盘等 Qt 文案，**暂无完整英文 Web UI**。
- 样式使用内置 [`web/static/tailwindcdn.js`](web/static/tailwindcdn.js)（离线 bundle，不依赖外网 CDN）。

## 贡献方式

- 提交 Issue 前阅读 [SECURITY.md](SECURITY.md) 和 [docs/OPEN_SOURCE_AUDIT.md](docs/OPEN_SOURCE_AUDIT.md)。
- 参与社区请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
- 提交代码前请运行测试集（见 [CONTRIBUTING.md](CONTRIBUTING.md)）。
- 新功能默认在 **Web**（`web/static/`、`app/web_api/`）实现。

**商标说明**：DanmuAI 为本项目名称，与 Bilibili、字节跳动、阿里巴巴、Qwen 等第三方无隶属关系；文档与原型中的第三方产品名仅作技术或设计参考。

## 界面与文档

| 资源 | 说明 |
|------|------|
| [docs/README.md](docs/README.md) | 文档索引（按受众分类） |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构总览 |
| [docs/CONTRIBUTING_ARCHITECTURE.md](docs/CONTRIBUTING_ARCHITECTURE.md) | 贡献者架构边界 |
| [docs/WEB_CONSOLE.md](docs/WEB_CONSOLE.md) | Web API、页面地图、启动方式 |
| [docs/MAIN_PIPELINE.md](docs/MAIN_PIPELINE.md) | 主链路（截图 → AI → 弹幕） |
| [prototype/Qwen_html_20260524_481u8vlmv.html](prototype/Qwen_html_20260524_481u8vlmv.html) | 当前 Web UI 视觉原型 |
| [prototype/README.md](prototype/README.md) | 原型目录说明 |

改 Web UI 前对照 Qwen 温馨原型与 `web/static/warm-tokens.css`。

## 目录结构

```text
.
├─ app/                 核心逻辑（AI、配置、弹幕、截图、托盘）
│  ├─ web_console.py    FastAPI + WebSocket
│  ├─ webview_shell.py  pywebview 桌面壳
│  ├─ web_api/          人格、自定义模型、压缩预览等扩展 API
│  └─ image_compress.py 内存 JPEG 压缩（Web 预览与运行时共用逻辑）
├─ web/static/          默认 Web 控制台（index.html、app.js、warm-tokens.css）
├─ tests/               pytest
├─ docs/                架构、隐私、Web 控制台、变更日志
├─ prototype/           Web UI 原型（Qwen HTML/MD）
├─ scripts/             本地工具（如 JPEG 质量基准，见 [scripts/README.md](scripts/README.md)）
├─ main.py              入口（DanmuApp、`compress_screenshot`）
└─ requirements.txt
```

## License

SPDX-License-Identifier: `GPL-3.0-or-later`

本项目基于 [GNU General Public License v3.0 或更新版本](LICENSE) 开源。

第三方组件许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [docs/OPEN_SOURCE_AUDIT.md](docs/OPEN_SOURCE_AUDIT.md)。弹幕语料子集归因见 [data/ATTRIBUTION.md](data/ATTRIBUTION.md)。

英文概要：[README.en.md](README.en.md)
