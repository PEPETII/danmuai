# ISSUE-017 — 未处理异常无 Web 错误反馈

## 问题 ID

ISSUE-017

## 发现时间

2026-05-29

## 发现来源

W-ERROR-REPORT-001 / W-ERROR-REPORT-002 完成报告

## 所属模块

`main.py`（`global_exception_hook`）、Web 控制台

## 问题描述

`is_error=true` 时 Web 控制台会弹出「是否要将该问题反馈」并提交 `error_reports`。未捕获的 Python 异常仍仅通过 Qt `QMessageBox.critical` 提示后 `sys.exit(1)`，不经过 Web 状态与自动反馈弹窗。

## 影响范围

用户可见（进程即将退出时的致命错误）

## 严重程度

低

## 是否阻塞当前工单

否

## 临时处理方式

用户可在退出前使用侧栏「问题反馈」手动描述；或查看本机日志 / 弹幕日记。

## 建议后续工单

W-ERROR-REPORT-003（需单独授权 `main.py`：致命异常前经 bridge 通知 Web 或合并进反馈流）

## 备注

与 ISSUE-007（Supabase 外网不可用）独立。
