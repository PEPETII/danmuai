# 已知问题记录

## 问题 ID

ISSUE-022

## 发现时间

2026-05-30

## 发现来源

用户启动报错 / 终端 `NameError`

## 所属模块

`main.py`（`DanmuApp._schedule_webview_attach`）

## 问题描述

`log_startup` 仅在 `DanmuApp.__init__` 内 `from app.startup_trace import log_startup`，`_schedule_webview_attach` 直接调用 `log_startup(...)` 导致：

```text
NameError: name 'log_startup' is not defined
```

应用在进入 `app.exec()` 前崩溃，全局异常对话框提示「程序遇到未处理的异常」。

## 影响范围

用户可见；阻塞一切启动路径（含 pywebview 与托盘）

## 严重程度

阻塞

## 是否阻塞当前工单

否（已热修）

## 临时处理方式

无（必须修代码后重启）

## 建议后续工单

可选：将 `log_startup` / `mark_app_start` 提升到 `main.py` 模块级单次导入，避免方法内漏导入。

## 备注

**已修复**（2026-05-30）：在 `_schedule_webview_attach` 的 `attempt == 0` 分支内补充 `from app.startup_trace import log_startup`。

## 状态

**已修复**
