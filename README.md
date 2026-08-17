# DanmuAI

<p align="center">
  <strong>让屏幕内容拥有自己的 AI 弹幕</strong><br>
  Windows 桌面 AI 弹幕助手：看懂画面、生成弹幕、读出声音，并把回应显示在屏幕上。
</p>

<p align="center">
  <a href="https://github.com/PEPETII/danmuai/releases/latest"><img src="https://img.shields.io/github/v/release/PEPETII/danmuai?label=最新版本" alt="最新版本"></a>
  <a href="https://github.com/PEPETII/danmuai/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0--or--later-green" alt="许可证"></a>
  <a href="https://github.com/PEPETII/danmuai"><img src="https://img.shields.io/github/stars/PEPETII/danmuai?style=flat&label=Stars" alt="GitHub Stars"></a>
</p>

<p align="center">
  <a href="https://github.com/PEPETII/danmuai/releases/latest">📥 下载最新版本</a> ·
  <a href="https://discord.gg/xQyx24ttK">💬 加入 Discord</a> ·
  <a href="https://github.com/PEPETII/danmuai/issues">🐛 报告问题</a> ·
  <a href="CONTRIBUTING.md">🛠️ 参与贡献</a>
</p>

DanmuAI 会按设定间隔截取指定显示器的画面，调用视觉模型理解当前内容并生成弹幕，再通过透明置顶的弹幕浮层展示。你可以在本地 Web 控制台中配置模型、人格、显示器、弹幕样式和运行参数。

## 你可以用 DanmuAI 做什么

我们希望让直播、录播、游戏和桌面内容拥有一个会观察、会吐槽、会说话的 AI 观众。

1. 🧠 **视觉弹幕**：定时截取屏幕，将画面交给视觉模型，生成一批与当前内容相关的弹幕。
2. 🎭 **自定义人格与模型**：配置人格、模型平台、端点和自定义模型，让弹幕保持你喜欢的语气。
3. 🖥️ **透明置顶弹幕层**：在指定显示器上滚动展示弹幕，不依赖 Web 控制台是否保持打开。
4. 🎧 **AI 读弹幕 TTS V2**：支持 MiMo、阿里百炼 Qwen3、MiniMax 和豆包 V3，并提供音色目录、缓存、刷新和试听能力。
5. 🎨 **弹幕外观可调**：支持浮动面板动画、内置样式和受管 CSS 主题；预览与实际显示保持同一套时序语义。
6. 🖥️ **多显示器支持**：分别选择截图和弹幕浮层所在的显示器，适合边看内容边在另一块屏幕管理配置。
7. 🧩 **可选扩展能力**：包含麦克风输入、桌宠、烂梗弹幕和知识库等模块，按当前版本与配置启用。
8. 🔒 **本地优先**：控制台默认只监听本机，截图默认在内存中压缩，不主动写入磁盘；是否把画面或文本发送到外部服务取决于你配置的模型平台。

## 📸 实机画面

<p align="center">
  <img src="https://github.com/user-attachments/assets/7a366c6c-1729-4852-b8df-c5755388fe60" alt="DanmuAI Web 控制台概览" width="49%">
  <img src="https://github.com/user-attachments/assets/655b778a-26c8-4c3b-8fd3-45eef7aac4a9" alt="DanmuAI 配置界面" width="49%">
</p>
<p align="center">
  <img src="https://github.com/user-attachments/assets/0fa4f970-1493-4561-a504-7104a83c2e16" alt="DanmuAI 弹幕展示效果" width="62%">
</p>

## 🚀 快速上手

### 方式一：下载 Windows 版本

1. 前往 [Releases](https://github.com/PEPETII/danmuai/releases/latest) 下载最新版本。
2. 需要安装体验时下载 `Setup.exe`；需要解压到任意目录时下载 `Portable.zip`。
3. 启动后，在 Web 控制台中填写模型平台、API Key 和模型信息。
4. 选择截图显示器、弹幕显示器、识别间隔、每批弹幕数量、人格和样式，然后开始运行。

> 安装包和 Portable 包的限制、更新说明以对应版本的 Release Notes 为准。API Key 请只填写在应用配置中，不要提交到仓库或公开截图中。

### 方式二：从源码运行

#### 环境要求

- Windows
- Python 3.12（推荐）
- 可用的视觉模型服务及对应密钥
- WebView2 运行环境（使用默认桌面壳时需要）

```powershell
pip install -r requirements.txt
python main.py
```

默认启动路径是 Web 控制台 + pywebview 桌面壳 + Qt 弹幕浮层 + 系统托盘。如果希望使用系统浏览器访问控制台：

```powershell
python main.py --web-browser
```

## ⚙️ 常用配置

<details>
<summary>配置视觉模型与自定义模型</summary>

在控制台的模型设置中填写模型平台、API Key、端点和模型名。项目已适配的平台与模型能力以当前版本的配置界面为准；自定义模型请确认其接口兼容项目支持的请求格式。

</details>

<details>
<summary>配置 AI 读弹幕</summary>

在 AI 读弹幕页面选择 provider、音色、朗读间隔和风格。凭据按 provider 加密保存，音色目录支持缓存与刷新；试听时也可以使用当前表单中的未保存值。

</details>

<details>
<summary>配置弹幕浮层与 CSS</summary>

可以调整弹幕从下到上的入场、顶推和退出动画，选择内置样式，或在受管目录中管理 CSS 主题。预览、Web 浮动面板和 Qt 备用渲染路径共享同一套动画语义。

</details>

<details>
<summary>启用麦克风、桌宠、烂梗弹幕和知识库</summary>

这些能力属于可选模块。是否显示对应页面、是否需要额外的模型或音频服务，取决于当前版本和本地配置；遇到问题时请附上脱敏后的操作步骤与日志摘要。

</details>

## 🔄 运行链路

```text
定时截图
  → 内存压缩
  → 视觉模型请求
  → 回复解析与校验
  → 回复队列
  → Qt 透明弹幕浮层
```

默认本地 Web 服务只监听 `127.0.0.1:18765`。Web 控制台通过应用内会话机制访问本地接口，配置和密钥不会因为启动本地服务而自动暴露到公网。

## 🧱 项目结构

| 目录 / 文件 | 职责 |
| --- | --- |
| `main.py` | 应用入口、生命周期和主运行态 |
| `app/web_api/` | Web API 路由、输入校验和鉴权边界 |
| `app/providers/` | 模型平台、端点和能力适配 |
| `app/tts/` | AI 读弹幕的 provider registry、音色目录和适配层 |
| `app/overlay.py`、`app/danmu_engine/` | 透明弹幕浮层与渲染引擎 |
| `web/static/` | Web 控制台页面、模块和样式 |
| `tests/` | 单元测试、集成测试和边界检查 |

## 🔐 隐私与安全

- 配置、模型信息和凭据保存在本机 `%APPDATA%/DanmuAI/` 目录中。
- 截图默认在发送前于内存中压缩，不默认写入磁盘。
- 模型请求是否离开本机、以及第三方平台如何处理数据，取决于你选择的 provider；请同时阅读对应平台的隐私政策。
- 提交 Issue、截图或日志前，请移除 API Key、`Authorization`、长 base64 图片和本地数据库内容。
- 安全问题请按照 [SECURITY.md](SECURITY.md) 的方式私下反馈，不要公开粘贴敏感信息。

## 🧑‍💻 开发与验证

```powershell
pip install -r requirements-dev.txt
ruff check app main.py tests scripts
python -m pytest tests/test_web_console.py tests/test_web_persona_api.py tests/test_web_custom_models.py tests/test_ui_mode.py -q -x
```

修改 `web/static/` 中的 HTML/CSS/JS 后，需要重新生成入口 HTML：

```powershell
python web/static/build_index_html.py
```

更完整的协作边界、架构说明和分批测试策略见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [AGENTS.md](AGENTS.md)。

## 🤝 交流与反馈

- 使用交流：加入 [Discord 社区](https://discord.gg/xQyx24ttK)。
- 问题反馈：前往 [GitHub Issues](https://github.com/PEPETII/danmuai/issues)。
- 提交反馈时，请尽量附上系统版本、启动方式、复现步骤和脱敏日志；不要公开 API Key 或包含隐私的截图。

如果 DanmuAI 对你有帮助，欢迎点一个 [Star](https://github.com/PEPETII/danmuai)。这会帮助项目获得更多反馈并持续维护。

## 📄 许可证

DanmuAI 采用 [GPL-3.0-or-later](LICENSE) 许可证。AI 生成内容、第三方模型服务和素材的使用责任由使用者自行承担，请遵守当地法律以及所使用服务的条款。
