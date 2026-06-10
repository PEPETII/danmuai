# 已知问题记录

## 问题 ID

ISSUE-036

## 发现时间

2026-06-01

## 发现来源

W-ERROR-REPORT-AUDIT-001（Supabase `error_reports` 只读审计）

## 所属模块

`web/static/app.js`（`pickErrorLogExcerpt`、`collectErrorReportContext`）

## 问题描述

用户确认提交的自动错误报告中，当 `summary` 为退避文案「连续 5 次请求失败，已暂停截图。最近错误：…」时，`logs_excerpt` 常**不含** `[ERROR]` 级别行，且不含摘要中的 HTTP 状态码字面量（如 `405`）。

审计样本（指纹 `a6d2fbc0…`，报告 id `1b33c49b-7359-415c-807c-7ebb570b3799`、`7f19ce65-7a40-4595-8185-9cb56b8b8005`）：`has_error_level=false`，`logs_excerpt` 以大量 `[DEBUG] [WebConsole] _broadcast_status` 为主。根因：`pickErrorLogExcerpt` 用 `error_message` 前 80 字在日志中匹配 ERROR 行；退避 summary 与原始 AI 错误日志文案不一致，锚点匹配失败后仅保留时间窗内的 DEBUG 行。

## 影响范围

- 运维/负责人在 Supabase Dashboard 查看 `error_reports` 时难以从 `logs_excerpt` 还原真实失败栈
- 用户侧弹窗与提交功能正常

## 严重程度

高

## 是否阻塞当前工单

否

## 状态

**已修复**（W-ERROR-REPORT-003，2026-06-01）

## 临时处理方式

结合同报告的 `summary`、`diagnostics_json` 与 `--- status ---` 块；必要时让用户复现并查本机 `startup.log` / Web 日志环。

## 建议后续工单

W-ERROR-REPORT-003：改进摘录策略（优先最近 ERROR/WARNING、或按 `status.error_message` 子串二次匹配、退避文案时附带最近一条 AI 错误日志）

## 备注

- 相关函数：`web/static/app.js` `pickErrorLogExcerpt`、`ERROR_REPORT_LOG_WINDOW_SEC`（90s）、`ERROR_REPORT_LOG_LINE_RADIUS`（40 行）
- 审计 SQL 见 [W-ERROR-REPORT-AUDIT-001-完成报告.md](../Codex完成报告/W-ERROR-REPORT-AUDIT-001-完成报告.md) §4
