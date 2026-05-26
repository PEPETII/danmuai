# macOS App 打包指南（PyInstaller + pywebview Cocoa）

本文档记录 DanmuAI 在 macOS 上源码运行和打包为 `.app` 的流程。默认使用 pywebview Cocoa/WebKit 内嵌窗口；WebView helper 进程会以 accessory 模式运行，避免在 Dock 里显示第二个 DanmuAI 图标。Qt 仍负责弹幕 Overlay 与托盘。

## 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | macOS 13+ 建议；需在目标架构机器上构建 |
| Python | 3.12+ |
| 桌面壳 | pywebview + PyObjC Cocoa/WebKit |
| 打包工具 | PyInstaller（见 `requirements-dev.txt`） |

## 源码运行

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

macOS 默认会打开 pywebview Cocoa 内嵌窗口。若需要强制确认该启动模式：

```bash
DANMU_WEB_LAUNCH=webview .venv/bin/python main.py
```

## macOS 权限

首次实际生成弹幕前，请在 macOS 中确认权限：

- 屏幕录制：系统设置 > 隐私与安全性 > 屏幕录制，允许 DanmuAI.app；源码运行时通常需要允许当前终端或 Python。
- 麦克风：仅开启麦克风模式时需要；`.app` 内已带 `NSMicrophoneUsageDescription`。

权限变更后通常需要重启应用。若截图失败，日志会提示检查屏幕录制权限。

## 本地数据路径

macOS 默认数据目录：

```text
~/Library/Application Support/DanmuAI/
```

其中包含：

- `config.db`：配置库
- `.key`：Fernet 加密密钥
- `startup.log`：打包态启动诊断

可用 `DANMUAI_CONFIG_DIR=/path/to/dir` 覆盖数据目录，便于本地验证。

## 构建 `.app`

```bash
./scripts/build_macos.sh
```

产物：

```text
dist/DanmuAI.app
```

本地未签名构建可直接用于开发机验证。对外分发前仍需按 Apple 要求执行 codesign/notarization；本仓库当前只提供可构建的 `.app` 结构，不包含开发者证书配置。

## 验证清单

- `dist/DanmuAI.app` 能启动本地 Web 控制台并打开 pywebview Cocoa 窗口。
- `http://127.0.0.1:18765/api/session` 返回 token。
- Web「助手设置」可保存 API Endpoint、API Key、Model 与 `api_mode=doubao`。
- 点击开始后，如未授权屏幕录制，日志出现 macOS 权限提示；授权并重启后可截图。
- 退出后无 `python main.py`、`DanmuAI`、`uvicorn`、`pyinstaller`、`multiprocessing.spawn` 遗留进程。

## 已知限制

- macOS 全局快捷键默认禁用；使用托盘或 Web 控制台启停。
- 未签名 `.app` 在其他机器上可能被 Gatekeeper 阻止，需要用户手动允许或完成签名/公证。
- 屏幕录制权限由 macOS TCC 控制，权限状态无法由应用静默修改。
