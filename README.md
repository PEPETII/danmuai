# DanmuAI

![Python](https://img.shields.io/badge/python-3.12%E6%8E%A8%E8%8D%90-blue)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-green)

DanmuAI 是一款面向 Windows 的桌面 AI 弹幕助手。它会按设定间隔截取指定显示器的画面，调用视觉模型理解当前内容并生成弹幕，再通过透明置顶的弹幕浮层展示。应用默认使用本地 Web 控制台进行配置和控制。

<img width="2487" height="1375" alt="Screenshot 2026-05-17 195301" src="https://github.com/user-attachments/assets/7a366c6c-1729-4852-b8df-c5755388fe60" />
<img width="2541" height="1408" alt="Screenshot 2026-05-17 195727" src="https://github.com/user-attachments/assets/655b778a-26c8-4c3b-8fd3-45eef7aac4a9" />
<img width="1159" height="610" alt="image" src="https://github.com/user-attachments/assets/0fa4f970-1493-4561-a504-7104a83c2e16" />


交流社区：<https://discord.gg/xQyx24ttK>

## 项目定位

DanmuAI 面向直播、录播和桌面内容展示场景，重点是轻量、可配置和本地优先：

- 截图在内存中压缩后再发送给模型，默认不会把截图写入磁盘。
- 配置、模型信息和密钥保存在本机的 `%APPDATA%/DanmuAI/` 目录中。
- 控制台、弹幕浮层和系统托盘各自承担明确职责，便于日常使用和调试。

## 当前状态

项目仍在持续开发中，接口和配置格式可能调整。当前默认入口是本地 Web 控制台、pywebview 桌面壳、Qt 弹幕浮层和系统托盘；旧版 Qt 主窗口入口已经移除。

## 快速开始

### 环境要求

- Windows
- Python 3.12（推荐）
- 可用的视觉模型服务及对应密钥
- WebView2 运行环境（使用默认桌面壳时需要）

### 安装与启动

```powershell
pip install -r requirements.txt
python main.py
```

如果希望使用外部浏览器访问控制台：

```powershell
python main.py --web-browser
```

启动后，可在控制台中配置模型、弹幕生成间隔、每批弹幕数量、显示器、人格、样式和其他运行参数。

## 核心能力

- **视觉弹幕生成**：按固定识别间隔截图并生成一批弹幕；上一轮请求仍在进行时，会跳过当前轮次，避免请求堆积。
- **透明置顶弹幕层**：通过 Qt Overlay 在目标显示器上滚动展示弹幕，不依赖 Web 控制台是否可见。
- **本地 Web 控制台**：提供运行概览、助手设置、人格管理、弹幕记录、自定义模型和相关显示配置。
- **AI 读弹幕 TTS V2**：统一目录与适配层支持 MiMo、阿里百炼 Qwen3、MiniMax 和豆包 V3；凭据按 provider 加密存储，音色目录支持缓存/刷新，试听可使用未保存的当前表单值。MiniMax 无凭据目录默认使用“推荐1”系统音色列表。
- **多显示器支持**：可选择截图和弹幕浮层所在的显示器；无效的显示器编号会回退到默认显示器。
- **多模型平台与自定义模型**：支持项目已适配的模型平台，也支持在控制台中管理自定义模型配置；具体能力以当前配置和模型平台支持为准。
- **浮动面板样式**：可配置从下到上的入场、顶推和退出动画；预览、Web 浮动面板和 Qt 备用渲染路径共享同一套时序语义。
- **自定义 CSS**：可在受管目录中选择并管理 CSS 主题，预览和 Web 浮动面板复用经过校验的样式；Qt 备用渲染器继续使用内置样式。
- **稳定性控制**：包含超时、连续失败退避、日志脱敏和弹幕去重等机制。
- **麦克风与扩展能力**：项目还包含麦克风输入、桌宠、烂梗弹幕、知识库等可选能力，是否启用取决于当前版本和控制台配置。

## 运行链路

```text
定时截图
  → 内存压缩
  → 视觉模型请求
  → 回复解析与校验
  → 回复队列
  → Qt 透明弹幕浮层
```

默认本地 Web 服务只监听 `127.0.0.1:18765`。Web 控制台通过应用内会话机制访问本地接口，配置和密钥不会因为启动本地服务而自动暴露到公网。

## 技术栈

| 组件 | 用途 |
| --- | --- |
| **Python 3.12** | 应用主体与运行编排 |
| **FastAPI + uvicorn** | 本地 Web API 与控制台服务 |
| **pywebview** | Windows 桌面 WebView2 壳 |
| **PyQt6** | 透明弹幕浮层与系统托盘 |
| **httpx** | AI API 请求 |
| **Pillow** | 截图压缩与图像处理 |
| **SQLite** | 本地配置、统计和相关数据存储 |
| **cryptography** | 本地密钥加密 |
| **keyboard** | 全局快捷键 |
| **python-Levenshtein** | 弹幕相似度与去重 |

## 目录说明

- `main.py`：应用入口、生命周期和主运行态。
- `app/web_api/`：Web API 路由与输入校验。
- `app/providers/`：模型平台、端点和能力适配。
- `app/overlay.py`、`app/danmu_engine/`：弹幕浮层和渲染引擎。
- `web/static/`：Web 控制台页面、模块和样式。
- `tests/`：单元测试、集成测试和边界检查。

## 隐私说明

DanmuAI 默认只在本机运行 Web 服务。截图会在发送前于内存中压缩，默认不落盘；模型请求是否离开本机取决于你配置的模型平台。请自行确认所使用平台的隐私政策，并妥善保管 API 密钥。

## 许可证

本项目采用 **GPL-3.0-or-later** 许可证，详见 [LICENSE](LICENSE)。

## 交流与反馈

欢迎通过 [Discord](https://discord.gg/xQyx24ttK) 交流使用体验、反馈问题或提出改进建议。提交问题时，请尽量附上操作步骤、相关日志摘要和运行环境信息，并先移除 API 密钥等敏感内容。
