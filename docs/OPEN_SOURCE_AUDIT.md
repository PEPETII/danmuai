# Open Source Audit

## 许可证结论

- 根目录使用 [GNU General Public License v3.0 或更新版本](../LICENSE)
- 项目选择 GPL-3.0+ 是因为核心依赖 PyQt6 (GPL-3.0) 和 python-Levenshtein (GPL-2.0+) 均为强 copyleft 许可证，MIT 与之不兼容
- 仓库内未保留"非商用限制"、"禁止商业使用"、"Source-available"或 CC NC 条款

## 第三方依赖许可证

| 依赖 | 许可证 | copyleft | 备注 |
|------|--------|----------|------|
| PyQt6 | GPL-3.0 | ✅ | 核心 UI 框架，决定项目必须 GPL |
| python-Levenshtein | GPL-2.0+ | ✅ | 可选依赖，代码中有 ImportError fallback |
| httpx | BSD-3-Clause | ❌ | |
| keyboard | MIT | ❌ | |
| cryptography | Apache-2.0 OR BSD-3-Clause | ❌ | |
| volcengine-python-sdk | Apache-2.0 | ❌ | |
| Pillow | HPND | ❌ | MIT-like 宽松许可证 |
| fastapi | MIT | ❌ | Web 控制台 HTTP API |
| python-multipart | Apache-2.0 | ❌ | FastAPI 上传压缩预览 multipart 解析 |
| uvicorn | BSD-3-Clause | ❌ | ASGI 服务器 |
| pywebview | BSD-3-Clause | ❌ | 桌面 Web 壳（Windows WebView2 / macOS Cocoa WebKit） |
| pyobjc-core | MIT | ❌ | macOS Objective-C bridge |
| pyobjc-framework-Cocoa | MIT | ❌ | macOS pywebview Cocoa 后端 |
| pyobjc-framework-WebKit | MIT | ❌ | macOS pywebview WebKit 后端 |
| sounddevice | MIT | ❌ | 麦克风采集 |
| numpy | BSD-3-Clause | ❌ | 音频缓冲数值计算 |
| websockets | BSD-3-Clause | ❌ | uvicorn WebSocket 实现 |

## 敏感文件审计

以下内容属于本地调试或隐私数据，不应进入公开仓库，已通过 [`.gitignore`](../.gitignore) 忽略：

- `log/`、`ph/` — 日志和截图
- `.coverage`、`.pytest_cache/`、`__pycache__/`、`.npmcache/` — 缓存和覆盖率
- `*.db`、`*.sqlite`、`*.sqlite3`、`*.key` — 本地数据库和密钥
- `.agents/`、`.trae/` — 本地工具目录
- `scratchpad.md`、`skills-lock.json`、`test_icon.png` — 草稿和临时文件

## 隐私边界

- 截图默认不落盘，截图压缩在内存中完成
- 日志会脱敏 API Key、Bearer Token 和长 base64 数据
- 当前版本默认按 `screen_index` 截取所选显示器全屏；`region_*` 宽高大于 0 时会按所选屏幕相对坐标裁剪
- 旧截图对应的 AI 回复会按 `screenshot_id` / `scene_generation` 丢弃

## 公开发布前仍需人工确认

- 确认工作目录中没有手工遗留的测试数据库或 Windows `%APPDATA%/DanmuAI/`、macOS `~/Library/Application Support/DanmuAI/` 导出副本
- 确认截图样例、直播内容样例和本地日志不随发布包分发
- 确认最终压缩包或 GitHub 发布资产中不包含调试缓存目录
