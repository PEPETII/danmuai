# 已知问题记录

## 问题 ID

ISSUE-021

## 发现时间

2026-05-30

## 发现来源

W-STARTUP-002 手动验收 / 用户反馈

## 所属模块

`main.py`、`app/web_console.py`、`app/webview_shell.py`、`app/startup_trace.py`

## 问题描述

W-STARTUP-002 将 `attach_web_console` 的 `wait_ready` 缩至 frozen 5s，且仅在 `web_server.startup_ok` 为 True 时调度 `attach_webview_shell`。uvicorn 稍慢或 `startup_ok` 仍为 False 时，桌面 pywebview 不会启动；握手超时又触发 `_fallback_to_system_browser`，表现为**任务栏无 DanmuAI 窗口、仅系统浏览器**打开控制台。

## 影响范围

用户可见；默认 `python main.py` / 打包 exe 的 Web 控制台入口

## 严重程度

高

## 是否阻塞当前工单

否（已在同日热修）

## 临时处理方式

使用 `--web-browser` 或托盘打开（热修前可能仍 fallback 浏览器）；热修后重启应用。

## 建议后续工单

无（热修已合并）；持续用 `startup.log` 观察 `webview.handshake.*` 阶段耗时。

## 备注

**已修复**（2026-05-30 热修）：

- `web_console_ready_timeout`：frozen 10s / dev 12s
- `_schedule_webview_attach`：HTTP 就绪后轮询 attach，不依赖初始 `startup_ok`
- `_ensure_server_ready`：`startup_ok` 时增加 HTTP 探测，避免 stale 标志
- 握手**超时**不再自动打开浏览器（硬错误仍 fallback）

相关工单：W-STARTUP-001、W-STARTUP-002；完成报告 [W-STARTUP-001-002-完成报告.md](../Codex完成报告/W-STARTUP-001-002-完成报告.md)

## 状态

**已修复**
