# ISSUE-011

## 问题 ID

ISSUE-011

## 发现时间

2026-05-29

## 发现来源

启动链路代码审查 / 用户反馈「双击 exe 后没有界面、托盘还在」/ W-009～W-012 验收后残留

## 所属模块

`app/webview_shell.py`（`_webview_worker`、`WebViewShell.start` / `_wait_for_handshake`）、`main.py`（`attach_webview_shell` 延迟调用）

## 问题描述

**用户可见现象**：`python main.py` 或双击打包 exe 后，系统托盘几乎必定出现，本地 Web 服务（`127.0.0.1:18765`）可能正常，但 **没有 pywebview 桌面窗口**；用户感知为「软件没打开」。托盘菜单「设置」在部分情况下也无反应（若同时叠加 ISSUE-009 跨进程 `open()` 问题，已由 W-010 修复）。

**技术根因**（W-014 修复前）：

1. 子进程在 `webview.start()` **之前**执行 `ready_queue.put(True)`，向父进程表示「已就绪」。
2. 父进程 `WebViewShell.start()` 对 `ready_queue` **只 `get()` 一次**；收到 `True` 即设 `_started = True`，认为 pywebview 启动成功。
3. 若随后 `webview.start()` 因 WebView2、edgechromium、系统环境、冻结包依赖等失败，子进程在 `except` 中再 `put(str(exc))`，但父进程已不再读取 → **不触发** `_fallback_to_system_browser()`。
4. 窗口为 `hidden=True`，仅在 `on_loaded` 时 `show()`；若页面永不触发 `loaded`，窗口永不可见，而父进程仍可能已判定成功。

**相关测试**：`tests/test_webview_shell.py::test_webview_worker_start_error_puts_error` 曾断言队列序列为 `[True, "webview boom"]`，印证第二条失败信号被丢弃。

## 影响范围

用户可见（Windows 开发环境与打包 exe）

## 严重程度

高

## 是否阻塞当前工单

否（由 W-014 单独修复）

## 临时处理方式

- `python main.py --web-browser` 或 `DanmuAI.exe --web-browser`
- 安装 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
- 浏览器访问 `http://127.0.0.1:18765`
- 查看 `%APPDATA%\DanmuAI\startup.log`（修复前无 `fallback to system browser` 时亦可手动打开上述地址）

## 建议后续工单

W-014（pywebview 二阶段握手：`created` → `loaded`；`start()` 失败 / 子进程退出 / loaded 超时 → 浏览器回退）

## 备注

- 与 [ISSUE-009](ISSUE-009-有托盘无Web控制台.md) 第 3 点同源；W-009～W-012 已修 `nav_queue`、单实例、服务未就绪提示等，**本项为握手语义遗留**
- **禁止**在 `webview.start()` 前 `window.show()`（见 [ISSUE-010](ISSUE-010-W009-pywebview启动回归.md)）；不可将唯一成功信号改为「仅 `loaded` 首包」而不发 `created`
- **已修复**（2026-05-29，W-014）：
  - 子进程：`put("created")` → `webview.start()` → `on_loaded` 内 `show()` + `put("loaded")`
  - 父进程：循环读队列，仅 `loaded` 后 `_started=True`；失败/超时/子进程提前退出 → `_fallback_to_system_browser()`
  - 代码锚点：`app/webview_shell.py`；完成报告 [W-014-完成报告.md](../Codex完成报告/W-014-完成报告.md)
