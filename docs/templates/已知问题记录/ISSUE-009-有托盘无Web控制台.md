# ISSUE-009

## 问题 ID

ISSUE-009

## 发现时间

2026-05-29

## 发现来源

用户反馈 / 启动链路代码审查（有托盘无 Web 控制台）

## 所属模块

`app/webview_shell.py`、`main.py`、`app/web_console.py`、打包 exe

## 问题描述

双击 exe 或 `python main.py` 后系统托盘几乎必定出现，但 Web 控制台（pywebview 或浏览器）可能不出现，用户感知为「程序没开」。常见叠加原因：

1. 本地 Web 服务 `127.0.0.1:18765` 未监听（端口占用、uvicorn 线程崩溃、打包 stderr 问题等）→ `startup_ok=False`，仅写日志
2. pywebview 子进程 `hidden=True` 且仅在 `loaded` 时 `show()` → 页面加载失败则窗口永不可见
3. `ready_queue.put(True)` 早于 `webview.start()` → `start()` 抛错时父进程已认为成功，不走浏览器回退（**W-014 / ISSUE-011 已修**）
4. `WebViewShell.open()` 在主进程访问 `webview.windows`（窗口在子进程）→ 托盘「设置」/ 双击无反应
5. 无单实例锁，多开加剧端口占用

弹幕 Overlay 在未点「开始」前不显示，属产品设计，易被误认为未启动。

## 影响范围

用户可见（尤其是 Windows 打包 exe）

## 严重程度

高

## 是否阻塞当前工单

否（已通过 W-009～W-012 修复）

## 临时处理方式

- 查看 `%APPDATA%\DanmuAI\startup.log`
- 使用 `DanmuAI.exe --web-browser` 或安装 WebView2 Runtime
- 确认分发整个 `dist\DanmuAI\` 目录；`netstat` 检查 18765 端口
- 浏览器访问 `http://127.0.0.1:18765`

## 建议后续工单

W-009～W-012（pywebview 可靠性、open 跨进程、失败提示、单实例）

## 备注

- 打包 uvicorn stderr 根因见 [PACKAGING_WINDOWS.md](../../PACKAGING_WINDOWS.md) 问题 6
- **已修复**（2026-05-29）：`nav_queue` 跨进程导航、单实例、`notify_web_console_failure`（`startup_ok=False` / 服务未就绪）；pywebview 握手：`created` → `webview.start()` → `loaded` 时 `show()`（W-014 二阶段确认；见 ISSUE-010、ISSUE-011）
- W-009 初版曾引入启动回归（`show()` 早于 `start()`），见 [ISSUE-010-W009-pywebview启动回归.md](ISSUE-010-W009-pywebview启动回归.md)
