# DanmuAI

DanmuAI 是一个基于 PyQt6 的 Windows 桌面弹幕工具。它会截取你配置的屏幕区域，调用视觉模型生成 5 条弹幕，并以透明置顶浮层的形式滚动展示。

**项目定位**：为直播主播提供一个轻量、隐私友好的 AI 弹幕助手。通过截取指定屏幕区域并调用视觉模型，自动生成与当前画面相关的弹幕内容，以透明置顶浮层形式展示，不影响直播软件运行。

<img width="2487" height="1375" alt="屏幕截图 2026-05-17 195301" src="https://github.com/user-attachments/assets/7a366c6c-1729-4852-b8df-c5755388fe60" />
<img width="2541" height="1408" alt="屏幕截图 2026-05-17 195727" src="https://github.com/user-attachments/assets/655b778a-26c8-4c3b-8fd3-45eef7aac4a9" />
<img width="2526" height="1391" alt="屏幕截图 2026-05-17 195659" src="https://github.com/user-attachments/assets/ab2aff3c-c1d0-44bc-b507-7a42921dbb48" />


## 项目状态

早期活跃开发中，API 和配置格式可能变动。

## 技术栈

| 组件 | 用途 |
|------|------|
| **Python** ≥ 3.12 | 主语言 |
| **PyQt6** | GUI 框架（主窗口 + 透明置顶弹幕层） |
| **httpx** | HTTP/2 客户端，AI API 请求 |
| **Pillow** | 图像压缩（JPEG + Base64） |
| **SQLite** | 配置存储（WAL 模式） |
| **cryptography** | API Key 加密（Fernet） |
| **keyboard** | 全局快捷键 |
| **python-Levenshtein** | 弹幕去重相似度计算 |

## 功能特性

- 固定返回 5 条弹幕：前 2 条强相关当前画面，后 3 条为泛用直播间弹幕
- 主线程截图，线程池压缩和 AI 请求，避免 UI 阻塞
- 过期 `screenshot_id` / 场景代际回复自动丢弃，旧画面不会覆盖新画面
- 连续失败退避、超时控制、日志脱敏
- 默认只截取配置区域，不做全屏截图
- 默认不保存截图，只保存弹幕文本历史

## 环境要求

- **Python** ≥ 3.12
- **平台**：Windows（仅主屏幕）
- 依赖见 [requirements.txt](requirements.txt)

## 安装方式

```bash
pip install -r requirements.txt
```

如需运行测试，额外安装：

```bash
pip install pytest pytest-qt Pillow
```

## 运行方式

```bash
python main.py
```

首次启动如果本地配置不存在，程序会自动创建配置库，并提示你先检查 API Key 和截图区域。

> **限制**：当前版本只支持主屏幕截图和主屏幕 Overlay，不支持多屏或非 100% 缩放。

## 如何配置 API Key

1. 启动程序后打开"设置"页。
2. 在 `API Endpoint`、`API Key`、`Model` 中填入你的服务配置。
3. 在"截图与隐私"区域确认截图设置。
4. 保存配置后再启动弹幕。

项目提供了一个示例文件 [`.env.example`](.env.example)。**注意**：当前桌面应用默认通过设置页写入 `%APPDATA%/DanmuAI/config.db`，不会自动加载 `.env`；该文件仅作为本地记录或脚本化启动时的参考模板。

## 隐私提醒

- 本工具会截取你配置的区域，并把截图发送给你选择的 AI 服务商。
- 默认不会保存截图，也不会把截图内容写入日志。
- 请不要选择包含密码、聊天记录、支付信息、内部文档等敏感内容的区域。
- API Key 存储在 `%APPDATA%/DanmuAI/config.db`，优先使用 `cryptography` + Fernet 加密；若本地缺少加密依赖，会退化为 base64 编码并给出明确警告。

更多说明见 [docs/PRIVACY.md](docs/PRIVACY.md)。

## 常见问题

### 为什么启动后没有弹幕？

- 通常是 API Key 未配置、截图区域无效，或请求连续失败进入退避状态。
- 先检查设置页中的 API 参数，再查看日志页中的错误提示。

### 为什么旧画面的弹幕没显示出来？

- 当前版本会丢弃过期 `screenshot_id`、超出新鲜度阈值的回复，以及场景切换前缓存的旧回复。这是有意设计，用来避免旧内容覆盖新画面。

### 程序会保存截图吗？

- 默认不会。当前实现只保存弹幕文本历史，不落盘截图。

## 已知限制

- 当前版本只支持主屏幕截图和主屏幕 Overlay。
- 正在进行中的网络请求无法强制中断，只能在超时后自然释放；退出流程会先标记停止并等待线程池短暂收尾。

## 贡献方式

- 提交 Issue 之前，先阅读 [SECURITY.md](SECURITY.md) 和 [docs/OPEN_SOURCE_AUDIT.md](docs/OPEN_SOURCE_AUDIT.md)。
- 提交代码前请运行最小测试集。
- 贡献说明见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 目录结构

```text
.
├─ app/               核心逻辑
├─ ui/                Qt UI
├─ tests/             pytest 测试
├─ docs/              文档（架构、隐私、许可证、路线图、变更日志）
├─ prototype/         HTML 原型
├─ .github/           Issue/PR 模板
└─ main.py            程序入口
```

## License

本项目基于 [GNU General Public License v3.0 或更新版本](LICENSE) 开源。

本项目依赖的第三方组件各自保留其原始许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [docs/OPEN_SOURCE_AUDIT.md](docs/OPEN_SOURCE_AUDIT.md)。
