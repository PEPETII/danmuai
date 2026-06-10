# ISSUE-010

## 问题 ID

ISSUE-010

## 发现时间

2026-05-29

## 发现来源

W-009～W-012 交付后用户手动验收；`python main.py` 报错 `timeout waiting for pywebview window`

## 所属模块

`app/webview_shell.py`（`_webview_worker`）

## 问题描述

W-009 初版为实现「窗口立即可见」与「仅 `loaded` 后发 ready」，在子进程中做了两类改动：

1. `hidden=False` 且在 `webview.start()` **之前**调用 `window.show()`
2. 将 `ready_queue.put(True)` 延后到 `on_loaded`，或 10s 未 loaded 时向父进程发送 `load timeout` 失败

在 Windows + pywebview（edgechromium）下，**(1) 会导致子进程主线程在 `show()` 处阻塞**，永远走不到 `put(True)`；父进程 20s 后判定 `timeout waiting for pywebview window` 并 `terminate` 子进程。用户侧表现为：修改前可正常打开桌面控制台，修改后出现 DanmuAI 错误弹窗并回退浏览器。

**(2)** 单独亦会导致父进程在 SPA/`#settings` 路由下长期收不到 ready（若未先修复 (1)）。

## 影响范围

用户可见（开发环境 `python main.py` 与打包 exe 均受影响）

## 严重程度

高（阻塞默认桌面壳启动）

## 是否阻塞当前工单

是（W-009～W-012 验收失败，需同日热修）

## 临时处理方式

- `python main.py --web-browser`
- 或回退 `app/webview_shell.py` 至 W-009 前握手顺序

## 建议后续工单

无（已在 W-009～W-012 热修中闭环）

## 备注

- **热修最终约定**（与 W-009 前一致 + 保留 W-010 nav_queue）：
  - `hidden=True`；**禁止**在 `webview.start()` 前调用 `window.show()`
  - `ready_queue.put(True)` 紧挨在 `webview.start()` 之前（不等 `loaded`）
  - `on_loaded` 内 `window.show()`
  - 加载超时仅写 `startup.log`，不向父进程发失败信号
  - pywebview 启动失败时仅日志 + 浏览器回退，**不**再弹 `QMessageBox`（避免误报）
- 见 [W-009-012-托盘无控制台-完成报告.md](../Codex完成报告/W-009-012-托盘无控制台-完成报告.md) §11
